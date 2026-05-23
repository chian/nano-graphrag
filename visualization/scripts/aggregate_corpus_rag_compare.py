#!/usr/bin/env python3
"""
Aggregate per-question RAG and GASL artifacts from a corpus run into
run-level comparison files that are easy to diff and archive.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[2]


def _safe_load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _iter_query_dirs(run_dir: Path):
    for path in sorted(run_dir.iterdir()):
        if path.is_dir() and path.name.startswith("q"):
            yield path


def _build_row(query_dir: Path) -> Dict[str, Any]:
    question = _safe_load(query_dir / "question.json")
    rag = _safe_load(query_dir / "rag.json")
    gasl = _safe_load(query_dir / "gasl.json")
    gasl_state = _safe_load(query_dir / "gasl_state.json")
    failure = _safe_load(query_dir / "failure.json")

    gasl_result = gasl.get("result") or {}
    gasl_behavior = gasl.get("behavior") or {}
    trace_summary = gasl.get("trace_summary") or {}
    retrieval = rag.get("retrieval") or {}
    visited_nodes = rag.get("visited_nodes") or []

    return {
        "query_id": query_dir.name,
        "graph": question.get("graph", ""),
        "family": question.get("family", ""),
        "question": question.get("question", ""),
        "target_view": ((question.get("metadata") or {}).get("target_view", "")),
        "theme": ((question.get("metadata") or {}).get("theme", "")),
        "rag_answer": rag.get("answer", ""),
        "rag_latency_s": rag.get("latency_s"),
        "rag_context_chars": len(retrieval.get("context", "") or ""),
        "rag_visited_nodes_count": len(visited_nodes),
        "gasl_answer": gasl_result.get("final_answer") or gasl_state.get("final_answer", ""),
        "gasl_latency_s": gasl.get("latency_s"),
        "gasl_query_answered": gasl_result.get("query_answered", gasl_state.get("query_answered")),
        "gasl_final_answer_mode": gasl_state.get("final_answer_mode", ""),
        "gasl_planner_iterations": gasl_behavior.get("planner_iterations"),
        "gasl_trace_events": trace_summary.get("events"),
        "gasl_trace_process_steps": trace_summary.get("process_steps"),
        "status": "failed" if failure else "completed",
        "failure_type": failure.get("type", ""),
        "failure_message": failure.get("message", ""),
    }


def aggregate_run(run_dir: Path) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for query_dir in _iter_query_dirs(run_dir):
        rows.append(_build_row(query_dir))

    completed = [r for r in rows if r["status"] == "completed"]
    answered = [r for r in completed if r.get("gasl_query_answered") is True]
    unanswered = [r for r in completed if r.get("gasl_query_answered") is False]
    failed = [r for r in rows if r["status"] == "failed"]

    summary = {
        "run_id": run_dir.name,
        "query_count": len(rows),
        "completed_queries": len(completed),
        "failed_queries": len(failed),
        "gasl_answered_queries": len(answered),
        "gasl_unanswered_queries": len(unanswered),
        "mean_rag_latency_s": round(
            sum((r.get("rag_latency_s") or 0.0) for r in completed) / len(completed), 3
        ) if completed else None,
        "mean_gasl_latency_s": round(
            sum((r.get("gasl_latency_s") or 0.0) for r in completed) / len(completed), 3
        ) if completed else None,
        "rows": rows,
    }
    return summary


def write_outputs(output_dir: Path, summary: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "rag_vs_gasl_summary.json"
    jsonl_path = output_dir / "rag_vs_gasl_rows.jsonl"
    csv_path = output_dir / "rag_vs_gasl_rows.csv"

    summary_path.write_text(json.dumps(summary, indent=2))

    rows = summary["rows"]
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    fieldnames = [
        "query_id",
        "graph",
        "family",
        "target_view",
        "theme",
        "question",
        "rag_answer",
        "rag_latency_s",
        "rag_context_chars",
        "rag_visited_nodes_count",
        "gasl_answer",
        "gasl_latency_s",
        "gasl_query_answered",
        "gasl_final_answer_mode",
        "gasl_planner_iterations",
        "gasl_trace_events",
        "gasl_trace_process_steps",
        "status",
        "failure_type",
        "failure_message",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True, help="Corpus run id under benchmark_results/")
    args = parser.parse_args()

    run_dir = REPO_ROOT / "benchmark_results" / args.run_id
    if not run_dir.exists():
        raise SystemExit(f"Run directory not found: {run_dir}")

    summary = aggregate_run(run_dir)
    write_outputs(run_dir, summary)
    print(json.dumps({
        "run_id": summary["run_id"],
        "query_count": summary["query_count"],
        "completed_queries": summary["completed_queries"],
        "failed_queries": summary["failed_queries"],
        "gasl_answered_queries": summary["gasl_answered_queries"],
        "gasl_unanswered_queries": summary["gasl_unanswered_queries"],
        "summary_path": str(run_dir / "rag_vs_gasl_summary.json"),
    }, indent=2))


if __name__ == "__main__":
    main()
