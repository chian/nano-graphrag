#!/usr/bin/env python3
"""
Run a large paired RAG/GASL corpus and archive every query's trace/output.

This is the iterative debugging/evaluation harness:
- generates many questions across HAIQU graphs
- runs RAG and GASL for each question
- stores schema snapshot, answers, node visits, and GASL trace path per query
- writes a run-level summary for later review before the next code-adjust cycle
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from visualization.graph_loader import GraphLoader
from visualization.query_engine import RagQueryEngine
from visualization.scripts.benchmark_rag_vs_gasl import (
    DEFAULT_GRAPHS,
    QuestionSpec,
    breadth_questions,
    generate_questions,
    load_env_file,
    run_gasl,
    score_answer,
)
from gasl import GASLExecutor
from gasl.adapters import NetworkXAdapter
from gasl.llm.argo_bridge import ArgoBridgeLLM


def run_rag_with_trace(loader: GraphLoader, question: str, api_key: str, model: str) -> Dict[str, Any]:
    engine = RagQueryEngine(loader)
    start = time.perf_counter()
    retrieval = engine.query(question)
    answer = engine.generate_answer(question, retrieval["context"], api_key=api_key, model=model)
    return {
        "latency_s": round(time.perf_counter() - start, 3),
        "retrieval": retrieval,
        "answer": answer,
        "visited_nodes": list(dict.fromkeys(retrieval["nodes"] + retrieval["neighbor_nodes"])),
    }


def run_gasl_with_artifacts(
    graph_path: str,
    question: str,
    api_key: str,
    model: str,
    heartbeat_s: int,
    query_dir: Path,
    query_id: str,
) -> Dict[str, Any]:
    loader = GraphLoader(graph_path)
    adapter = NetworkXAdapter(loader.graph)
    llm = ArgoBridgeLLM(model=model, api_key=api_key)
    state_file = query_dir / "gasl_state.json"
    executor = GASLExecutor(adapter, llm, state_file=str(state_file), job_id=query_id)
    start = time.perf_counter()
    result = executor.run_hypothesis_driven_traversal(question, max_iterations=8)
    trace_file = query_dir / "gasl_artifacts" / "traces" / f"{query_id}.jsonl"
    return {
        "latency_s": round(time.perf_counter() - start, 3),
        "result": result,
        "usage": dict(llm.usage),
        "trace_file": str(trace_file),
        "state_file": str(state_file),
    }


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if hasattr(value, "to_dict"):
        try:
            return json_safe(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return json_safe(vars(value))
    return str(value)


def summarize_gasl_trace(trace_file: Path) -> Dict[str, Any]:
    if not trace_file.exists():
        return {"events": 0, "process_steps": 0, "commands": [], "visited_nodes": []}
    commands = []
    visited_nodes = set()
    process_steps = 0
    events = 0
    for line in trace_file.read_text().splitlines():
        events += 1
        row = json.loads(line)
        if row["event"] == "command_start":
            commands.append(row["payload"]["command_type"])
        if row["event"] == "command_result":
            if row["payload"]["command_type"] == "PROCESS":
                process_steps += 1
            data = row["payload"].get("data")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "id" in item:
                        visited_nodes.add(item["id"])
            elif isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict) and "id" in item:
                                visited_nodes.add(item["id"])
    return {
        "events": events,
        "process_steps": process_steps,
        "commands": commands,
        "visited_nodes": sorted(visited_nodes),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", action="append", dest="graphs", default=[])
    parser.add_argument("--per-graph", type=int, default=10)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--heartbeat", type=int, default=1800)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--breadth-only", action="store_true")
    args = parser.parse_args()

    load_env_file(REPO_ROOT / ".viz.local.env")
    api_key = os.environ.get("VIZ_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise SystemExit("No API key found. Set VIZ_API_KEY or OPENAI_API_KEY.")

    run_id = args.run_id or datetime.now().strftime("corpus_%Y%m%dT%H%M%S")
    run_dir = REPO_ROOT / "benchmark_results" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    graphs = [str((REPO_ROOT / g).resolve()) for g in (args.graphs or DEFAULT_GRAPHS)]

    manifest = {
        "run_id": run_id,
        "started_at": datetime.now().isoformat(),
        "model": args.model,
        "graphs": graphs,
        "per_graph": args.per_graph,
        "breadth_only": args.breadth_only,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    rows: List[Dict[str, Any]] = []
    query_index = 0
    for graph_path in graphs:
        loader = GraphLoader(graph_path)
        graph = loader.graph
        graph.graph["graphml_path"] = str(graph_path)
        questions: List[QuestionSpec]
        if args.breadth_only:
            questions = breadth_questions(graph, limit=args.per_graph)
        else:
            questions = generate_questions(graph_path, per_graph=args.per_graph)
        schema = NetworkXAdapter(graph).get_schema()

        for spec in questions:
            query_index += 1
            query_id = f"q{query_index:03d}"
            query_dir = run_dir / query_id
            query_dir.mkdir(parents=True, exist_ok=True)
            print(f"[{query_id}] {spec.graph_name} | {spec.family} | {spec.question}", flush=True)

            (query_dir / "question.json").write_text(json.dumps({
                "graph": spec.graph_name,
                "graph_path": graph_path,
                "family": spec.family,
                "question": spec.question,
                "expected": spec.expected,
                "metadata": spec.metadata,
                "schema": schema,
            }, indent=2))

            rag = run_rag_with_trace(loader, spec.question, api_key, args.model)
            (query_dir / "rag.json").write_text(json.dumps(rag, indent=2))

            gasl = run_gasl_with_artifacts(
                graph_path, spec.question, api_key, args.model, args.heartbeat, query_dir, query_id
            )
            trace_summary = summarize_gasl_trace(Path(gasl["trace_file"]))
            gasl["trace_summary"] = trace_summary
            (query_dir / "gasl.json").write_text(json.dumps(json_safe(gasl), indent=2))

            row = {
                "query_id": query_id,
                "graph": spec.graph_name,
                "family": spec.family,
                "question": spec.question,
                "expected": spec.expected,
                "rag_score": score_answer(rag["answer"]["text"], spec.expected),
                "gasl_score": score_answer(gasl["result"]["final_answer"], spec.expected),
                "rag_latency_s": rag["latency_s"],
                "gasl_latency_s": gasl["latency_s"],
                "gasl_process_steps": trace_summary["process_steps"],
                "gasl_trace_file": gasl["trace_file"],
            }
            rows.append(row)
            print(json.dumps(row, indent=2), flush=True)

    summary = {
        "run_id": run_id,
        "completed_at": datetime.now().isoformat(),
        "rows": rows,
        "gasl_better": [r for r in rows if r["gasl_score"] > r["rag_score"]],
        "rag_better": [r for r in rows if r["gasl_score"] < r["rag_score"]],
        "ties": [r for r in rows if r["gasl_score"] == r["rag_score"]],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"WROTE {run_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
