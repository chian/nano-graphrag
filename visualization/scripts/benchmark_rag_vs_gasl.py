#!/usr/bin/env python3
"""
Benchmark RAG vs GASL over graph-derived question sets.

The benchmark generates deterministic questions from each graph's topology,
runs both pipelines with the same model/key, and scores the answers against
graph-derived reference entities. This is intended to find real cases where
GASL's global traversal beats top-k retrieval instead of relying on cherry picks.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import multiprocessing as mp
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from visualization.graph_loader import GraphLoader
from visualization.query_engine import RagQueryEngine
from gasl import GASLExecutor
from gasl.adapters import NetworkXAdapter
from gasl.llm.argo_bridge import ArgoBridgeLLM


DEFAULT_GRAPHS = [
    "haiqu_graphs/v1/haiqu_engineering_controls/haiqu_engineering_controls_graph.graphml",
    "haiqu_graphs/v1/haiqu_hospital_environment/haiqu_hospital_environment_graph.graphml",
    "haiqu_graphs/v1/haiqu_biosensor_detection/haiqu_biosensor_detection_graph.graphml",
    "haiqu_graphs/v1/haiqu_aerosol_exposure/haiqu_aerosol_exposure_graph.graphml",
]

BENCHMARK_SUFFIX = " Return the top three item names as a comma-separated list with no explanation."

RELATION_PROMPT_STYLES = [
    "Across the {graph_name} evidence base, which {dst_type_h} are most frequently linked with {src_type_h} findings through {rel_h}?{suffix}",
    "For indoor-health monitoring and intervention planning, which {dst_type_h} come up most often in connection with {src_type_h} in the {graph_name} literature?{suffix}",
    "Looking across the {graph_name} graph, what {dst_type_h} have the strongest overall evidence footprint linked from {src_type_h}?{suffix}",
]

BREADTH_PROMPT_STYLES = [
    "Which {mid_type_h} span the broadest range of evidence across both {src_type_h} and {dst_type_h} in the {graph_name} graph?{suffix}",
    "For deployment planning, which {mid_type_h} are supported across the widest range of {src_type_h} and {dst_type_h} evidence in the {graph_name} literature?{suffix}",
    "Looking across the {graph_name} evidence base, what {mid_type_h} appear most consistently across both {src_type_h} and {dst_type_h}?{suffix}",
]


@dataclass
class QuestionSpec:
    graph_path: str
    graph_name: str
    family: str
    question: str
    expected: List[str]
    metadata: Dict[str, Any]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def score_answer(answer: str, expected: Iterable[str]) -> int:
    answer_parts = [norm(part) for part in re.split(r"[\n,;|]+", answer or "") if norm(part)]
    score = 0
    for item in expected:
        needle = norm(item)
        if any(part == needle or needle in part or part in needle for part in answer_parts):
            score += 1
    return score


def humanize(token: str) -> str:
    return token.replace("_", " ").lower()


def top_relation_triples(graph: nx.Graph, limit: int, min_edges: int = 8) -> List[QuestionSpec]:
    triple_rows: Dict[tuple[str, str, str], List[tuple[str, str]]] = {}
    for src, dst, data in graph.edges(data=True):
        src_type = graph.nodes[src].get("entity_type", "ENTITY")
        dst_type = graph.nodes[dst].get("entity_type", "ENTITY")
        rel = data.get("relation_type", "RELATED")
        key = (str(src_type), str(rel), str(dst_type))
        triple_rows.setdefault(key, []).append((src, dst))

    ranked = sorted(
        [(k, v) for k, v in triple_rows.items() if len(v) >= min_edges],
        key=lambda kv: (-len(kv[1]), kv[0]),
    )[:limit]

    questions: List[QuestionSpec] = []
    for (src_type, rel, dst_type), edges in ranked:
        counts: Dict[str, int] = {}
        for _src, dst in edges:
            counts[dst] = counts.get(dst, 0) + 1
        expected = [name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
        graph_name = Path(graph.graph.get("graphml_path", "graph")).stem.replace("_graph", "")
        for style_idx, style in enumerate(RELATION_PROMPT_STYLES):
            questions.append(
                QuestionSpec(
                    graph_path=str(graph.graph.get("graphml_path", "")),
                    graph_name=graph_name,
                    family=f"relation_frequency/style_{style_idx+1}",
                    question=style.format(
                        graph_name=graph_name.replace("_", " "),
                        dst_type_h=humanize(dst_type),
                        src_type_h=humanize(src_type),
                        rel_h=humanize(rel),
                        suffix=BENCHMARK_SUFFIX,
                    ),
                    expected=expected,
                    metadata={
                        "src_type": src_type,
                        "rel": rel,
                        "dst_type": dst_type,
                        "edge_count": len(edges),
                    },
                )
            )
    return questions


def breadth_questions(graph: nx.Graph, limit: int, min_nodes: int = 6) -> List[QuestionSpec]:
    questions: List[QuestionSpec] = []
    entity_types = {}
    for node, data in graph.nodes(data=True):
        entity_types.setdefault(data.get("entity_type", "ENTITY"), []).append(node)

    for mid_type, nodes in entity_types.items():
        if len(nodes) < min_nodes:
            continue
        by_pattern: Dict[tuple[str, str, str, str], List[tuple[str, int]]] = {}
        for node in nodes:
            incoming: Dict[tuple[str, str], set[str]] = {}
            outgoing: Dict[tuple[str, str], set[str]] = {}
            for src, _dst, data in graph.in_edges(node, data=True):
                key = (graph.nodes[src].get("entity_type", "ENTITY"), data.get("relation_type", "RELATED"))
                incoming.setdefault(key, set()).add(src)
            for _src, dst, data in graph.out_edges(node, data=True):
                key = (data.get("relation_type", "RELATED"), graph.nodes[dst].get("entity_type", "ENTITY"))
                outgoing.setdefault(key, set()).add(dst)

            for (src_type, rel_in), sources in incoming.items():
                for (rel_out, dst_type), targets in outgoing.items():
                    if len(sources) < 2 or len(targets) < 2:
                        continue
                    pattern = (mid_type, src_type, rel_in, dst_type, rel_out)
                    score = len(sources) * len(targets)
                    by_pattern.setdefault(pattern, []).append((node, score))

        for pattern, rows in sorted(by_pattern.items(), key=lambda kv: -max(v for _, v in kv[1]))[:limit]:
            mid_type, src_type, rel_in, dst_type, rel_out = pattern
            top_nodes = [n for n, _ in sorted(rows, key=lambda kv: (-kv[1], kv[0]))[:3]]
            graph_name = Path(graph.graph.get("graphml_path", "graph")).stem.replace("_graph", "")
            for style_idx, style in enumerate(BREADTH_PROMPT_STYLES):
                questions.append(
                    QuestionSpec(
                        graph_path=str(graph.graph.get("graphml_path", "")),
                        graph_name=graph_name,
                        family=f"two_axis_breadth/style_{style_idx+1}",
                        question=style.format(
                            graph_name=graph_name.replace("_", " "),
                            mid_type_h=humanize(mid_type),
                            src_type_h=humanize(src_type),
                            dst_type_h=humanize(dst_type),
                            suffix=BENCHMARK_SUFFIX,
                        ),
                        expected=top_nodes,
                        metadata={
                            "mid_type": mid_type,
                            "src_type": src_type,
                            "dst_type": dst_type,
                            "rel_in": rel_in,
                            "rel_out": rel_out,
                        },
                    )
                )
    return questions[:limit]


def generate_questions(graph_path: str, per_graph: int) -> List[QuestionSpec]:
    loader = GraphLoader(graph_path)
    graph = loader.graph
    assert graph is not None
    graph.graph["graphml_path"] = str(Path(graph_path))
    third = max(1, per_graph // 2)
    questions = top_relation_triples(graph, limit=third)
    questions.extend(breadth_questions(graph, limit=max(1, per_graph - len(questions))))
    for q in questions:
        q.graph_path = graph_path
        q.graph_name = Path(graph_path).parent.name
    return questions[:per_graph]


def run_rag(loader: GraphLoader, question: str, api_key: str, model: str) -> Dict[str, Any]:
    engine = RagQueryEngine(loader)
    start = time.perf_counter()
    result = engine.query(question)
    answer = engine.generate_answer(question, result["context"], api_key=api_key, model=model)
    return {
        "latency_s": round(time.perf_counter() - start, 3),
        "nodes": result["nodes"],
        "edges": result["edges"],
        "answer": answer["text"],
        "usage": answer["usage"],
    }


def _run_gasl_worker(graph_path: str, question: str, api_key: str, model: str) -> Dict[str, Any]:
    loader = GraphLoader(graph_path)
    adapter = NetworkXAdapter(loader.graph)
    llm = ArgoBridgeLLM(model=model, api_key=api_key)
    executor = GASLExecutor(adapter, llm, job_id=f"bench-{int(time.time()*1000)}")
    start = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = executor.run_hypothesis_driven_traversal(question, max_iterations=8)
    return {
        "latency_s": round(time.perf_counter() - start, 3),
        "answer": result.get("final_answer", ""),
        "iterations": result.get("iterations", 0),
        "query_answered": result.get("query_answered", False),
        "usage": dict(llm.usage),
    }


def _run_gasl_queue_worker(graph_path: str, question: str, api_key: str, model: str, queue: Any) -> None:
    try:
        queue.put(_run_gasl_worker(graph_path, question, api_key, model))
    except Exception as exc:
        queue.put({
            "latency_s": 0.0,
            "answer": "",
            "iterations": 0,
            "query_answered": False,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0},
            "error": str(exc),
        })


def run_gasl(graph_path: str, question: str, api_key: str, model: str, timeout_s: int) -> Dict[str, Any]:
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(
        target=_run_gasl_queue_worker,
        args=(graph_path, question, api_key, model, queue),
    )
    proc.start()
    proc.join(timeout_s)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        return {
            "latency_s": float(timeout_s),
            "answer": "",
            "iterations": 0,
            "query_answered": False,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0},
            "timeout": True,
        }
    if not queue.empty():
        return queue.get()
    return {
        "latency_s": 0.0,
        "answer": "",
        "iterations": 0,
        "query_answered": False,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0},
        "error": "No result returned from GASL worker",
    }


def _append_bug_log(path: Optional[Path], row: Dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def benchmark(
    graph_paths: List[str],
    api_key: str,
    model: str,
    per_graph: int,
    gasl_timeout_s: int,
    bug_log_path: Optional[Path] = None,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    total_questions = 0
    for graph_path in graph_paths:
        total_questions += len(generate_questions(graph_path, per_graph=per_graph))
    completed = 0
    for graph_path in graph_paths:
        loader = GraphLoader(graph_path)
        questions = generate_questions(graph_path, per_graph=per_graph)
        for spec in questions:
            completed += 1
            print(
                f"[{completed}/{total_questions}] {spec.graph_name} | {spec.family} | {spec.question}",
                flush=True,
            )
            rag = run_rag(loader, spec.question, api_key, model)
            gasl = run_gasl(graph_path, spec.question, api_key, model, gasl_timeout_s)
            rag_score = score_answer(rag["answer"], spec.expected)
            gasl_score = score_answer(gasl["answer"], spec.expected)
            row = {
                "graph": spec.graph_name,
                "graph_path": graph_path,
                "family": spec.family,
                "question": spec.question,
                "expected": spec.expected,
                "rag": rag,
                "gasl": gasl,
                "rag_score": rag_score,
                "gasl_score": gasl_score,
                "delta": gasl_score - rag_score,
                "metadata": spec.metadata,
            }
            rows.append(row)
            print(
                f"    rag={rag_score} gasl={gasl_score} delta={row['delta']} "
                f"rag_s={rag['latency_s']} gasl_s={gasl['latency_s']}"
                + (" TIMEOUT" if gasl.get("timeout") else "")
                + (f" GASL_ERR={gasl.get('error')}" if gasl.get("error") else ""),
                flush=True,
            )
            if gasl.get("timeout") or gasl.get("error"):
                _append_bug_log(
                    bug_log_path,
                    {
                        "question": spec.question,
                        "graph": spec.graph_name,
                        "family": spec.family,
                        "type": "gasl_timeout" if gasl.get("timeout") else "gasl_error",
                        "payload": gasl,
                    },
                )

    wins = [row for row in rows if row["delta"] > 0]
    wins.sort(key=lambda row: (-row["delta"], row["gasl"]["latency_s"], row["question"]))
    summary = {
        "total_questions": len(rows),
        "gasl_better": len([r for r in rows if r["delta"] > 0]),
        "rag_better": len([r for r in rows if r["delta"] < 0]),
        "ties": len([r for r in rows if r["delta"] == 0]),
        "top_gasl_wins": wins[:15],
        "rows": rows,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", action="append", dest="graphs", default=[])
    parser.add_argument("--per-graph", type=int, default=10)
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--gasl-timeout", type=int, default=90)
    parser.add_argument("--output", default="")
    parser.add_argument("--bug-log", default="")
    args = parser.parse_args()

    load_env_file(REPO_ROOT / ".viz.local.env")
    api_key = os.environ.get("VIZ_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise SystemExit("No API key found. Set VIZ_API_KEY or OPENAI_API_KEY.")

    graphs = [str((REPO_ROOT / g).resolve()) for g in (args.graphs or DEFAULT_GRAPHS)]
    summary = benchmark(
        graphs,
        api_key=api_key,
        model=args.model,
        per_graph=args.per_graph,
        gasl_timeout_s=args.gasl_timeout,
        bug_log_path=Path(args.bug_log) if args.bug_log else None,
    )

    print(json.dumps({
        "total_questions": summary["total_questions"],
        "gasl_better": summary["gasl_better"],
        "rag_better": summary["rag_better"],
        "ties": summary["ties"],
        "top_gasl_wins": [
            {
                "graph": row["graph"],
                "family": row["family"],
                "delta": row["delta"],
                "question": row["question"],
                "expected": row["expected"],
                "rag_score": row["rag_score"],
                "gasl_score": row["gasl_score"],
            }
            for row in summary["top_gasl_wins"]
        ],
    }, indent=2))

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
