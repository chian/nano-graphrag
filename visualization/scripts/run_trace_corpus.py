#!/usr/bin/env python3
"""
Run a large paired RAG/GASL corpus and archive every query's trace/output.

This is the iterative debugging/evaluation harness:
- generates many questions across HAIQU graphs
- runs RAG and GASL for each question
- stores schema snapshot, answers, node visits, and GASL trace path per query
- writes a run-level GASL behavior summary for later review before the next code-adjust cycle
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections import Counter
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
)
from gasl import GASLExecutor
from gasl.adapters import NetworkXAdapter
from gasl.llm.argo_bridge import ArgoBridgeLLM
from gasl.llm.runtime_config import resolve_runtime_llm_config


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
    runtime_cfg = resolve_runtime_llm_config(explicit_api_key=api_key, explicit_model=model)
    llm = ArgoBridgeLLM(model=runtime_cfg.model or model, api_key=runtime_cfg.api_key, base_url=runtime_cfg.base_url)
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


def _categorize_error(message: str) -> str:
    text = (message or "").lower()
    if "processed_items" in text and "processing_method" in text:
        return "process_output_shape_mismatch"
    if "no handler for command: show" in text:
        return "missing_handler_show"
    if "aggregate" in text and ("group_name" in text or "group_key" in text or "entity_name" in text):
        return "aggregate_field_resolution"
    if "graphwalk" in text or "relationship types" in text or "path" in text:
        return "path_semantics_validator"
    if "validation failed" in text:
        return "llm_judge_validation"
    return "other"


def summarize_gasl_behavior(state_file: Path, gasl_result: Dict[str, Any], trace_summary: Dict[str, Any]) -> Dict[str, Any]:
    if not state_file.exists():
        return {
            "planner_iterations": gasl_result.get("iterations", 0),
            "history_len": 0,
            "command_error_count": 0,
            "command_empty_count": 0,
            "process_status_counts": {},
            "error_categories": {},
            "validation_hint": None,
            "query_answered": gasl_result.get("query_answered"),
            "trace_events": trace_summary.get("events", 0),
            "trace_process_steps": trace_summary.get("process_steps", 0),
        }
    state = json.loads(state_file.read_text())
    history = state.get("history", [])
    process_status_counts = Counter()
    error_categories = Counter()
    command_empty_count = 0
    command_error_count = 0
    for entry in history:
        status = entry.get("status")
        command = entry.get("command", "")
        if status == "error":
            command_error_count += 1
            error_categories[_categorize_error(entry.get("error_message", ""))] += 1
        elif status == "empty":
            command_empty_count += 1
        if command.startswith("PROCESS "):
            process_status_counts[status] += 1

    return {
        "planner_iterations": gasl_result.get("iterations", 0),
        "history_len": len(history),
        "command_error_count": command_error_count,
        "command_empty_count": command_empty_count,
        "process_status_counts": dict(process_status_counts),
        "error_categories": dict(error_categories),
        "validation_hint": state.get("validation_hint"),
        "query_answered": gasl_result.get("query_answered"),
        "trace_events": trace_summary.get("events", 0),
        "trace_process_steps": trace_summary.get("process_steps", 0),
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
    if os.environ.get("NANOGRAPHRAG_LLM_TRANSPORT", "").strip().lower() == "shim":
        api_key = os.environ.get("NANOGRAPHRAG_SHIM_TOKEN") or os.environ.get("LLM_API_KEY") or ""
    else:
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
            gasl["behavior"] = summarize_gasl_behavior(Path(gasl["state_file"]), gasl["result"], trace_summary)
            (query_dir / "gasl.json").write_text(json.dumps(json_safe(gasl), indent=2))

            row = {
                "query_id": query_id,
                "graph": spec.graph_name,
                "family": spec.family,
                "question": spec.question,
                "rag_latency_s": rag["latency_s"],
                "gasl_latency_s": gasl["latency_s"],
                "gasl_behavior": gasl["behavior"],
                "gasl_trace_file": gasl["trace_file"],
            }
            rows.append(row)
            print(json.dumps(row, indent=2), flush=True)

    behavior_summary = {
        "run_id": run_id,
        "completed_at": datetime.now().isoformat(),
        "rows": rows,
        "aggregate": {
            "planner_iterations_total": sum(r["gasl_behavior"]["planner_iterations"] for r in rows),
            "history_len_total": sum(r["gasl_behavior"]["history_len"] for r in rows),
            "command_error_count_total": sum(r["gasl_behavior"]["command_error_count"] for r in rows),
            "command_empty_count_total": sum(r["gasl_behavior"]["command_empty_count"] for r in rows),
            "process_status_counts": dict(
                sum((Counter(r["gasl_behavior"]["process_status_counts"]) for r in rows), Counter())
            ),
            "error_categories": dict(
                sum((Counter(r["gasl_behavior"]["error_categories"]) for r in rows), Counter())
            ),
        },
    }
    (run_dir / "behavior_summary.json").write_text(json.dumps(behavior_summary, indent=2))
    print(f"WROTE {run_dir / 'behavior_summary.json'}")


if __name__ == "__main__":
    main()
