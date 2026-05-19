#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from visualization.scripts.run_trace_corpus import summarize_gasl_behavior, summarize_gasl_trace


def _iter_run_dirs(root: Path, pattern: str) -> List[Path]:
    return sorted([p for p in root.glob(pattern) if p.is_dir()])


def _load_question(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize post-tuning failure patterns across run dirs.")
    parser.add_argument("--run-root", default="benchmark_results")
    parser.add_argument("--pattern", default="corpus_20260518_posttune*")
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-text", required=True)
    args = parser.parse_args()

    run_root = Path(args.run_root)
    run_dirs = _iter_run_dirs(run_root, args.pattern)
    total = 0
    clean = 0
    command_errors = 0
    error_categories = Counter()
    per_run: List[Dict[str, Any]] = []
    examples: Dict[str, List[Dict[str, Any]]] = {}

    for run_dir in run_dirs:
        for qdir in sorted([p for p in run_dir.glob("q*") if p.is_dir()]):
            gasl_json = qdir / "gasl.json"
            if not gasl_json.exists():
                continue
            total += 1
            gasl_payload = json.loads(gasl_json.read_text(encoding="utf-8"))
            trace_file = qdir / "gasl_artifacts" / "traces" / f"{qdir.name}.jsonl"
            trace_summary = summarize_gasl_trace(trace_file)
            state_file = qdir / "gasl_state.json"
            behavior = summarize_gasl_behavior(state_file, gasl_payload["gasl"]["result"], trace_summary)
            if (
                behavior["query_answered"]
                and behavior["command_error_count"] == 0
                and behavior["command_empty_count"] == 0
            ):
                clean += 1
            command_errors += behavior["command_error_count"]
            for cat, count in behavior["error_categories"].items():
                error_categories[cat] += count
                if count and len(examples.setdefault(cat, [])) < 3:
                    question = _load_question(qdir / "question.json")
                    examples[cat].append(
                        {
                            "run_id": run_dir.name,
                            "query_id": qdir.name,
                            "question": question.get("question", ""),
                            "trace_file": str(trace_file),
                            "state_file": str(state_file),
                        }
                    )
            per_run.append(
                {
                    "run_id": run_dir.name,
                    "query_id": qdir.name,
                    "query_answered": behavior["query_answered"],
                    "command_error_count": behavior["command_error_count"],
                    "command_empty_count": behavior["command_empty_count"],
                    "error_categories": behavior["error_categories"],
                }
            )

    top_failures = error_categories.most_common()
    summary = {
        "pattern": args.pattern,
        "run_dirs": [str(p) for p in run_dirs],
        "completed_queries": total,
        "fully_clean_queries": clean,
        "clean_rate": (clean / total) if total else 0.0,
        "command_errors": command_errors,
        "top_failures": top_failures,
        "examples": examples,
        "per_run": per_run,
    }
    Path(args.out_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        f"Completed queries: {total}",
        f"Fully clean queries: {clean}",
        f"Clean rate: {summary['clean_rate']:.2%}",
        f"Command errors: {command_errors}",
        "",
        "Top failure families:",
    ]
    for cat, count in top_failures[:10]:
        lines.append(f"- {cat}: {count}")
        for example in examples.get(cat, [])[:2]:
            lines.append(f"  - {example['run_id']}/{example['query_id']}: {example['question']}")
    next_steps = []
    if top_failures:
        lead = top_failures[0][0]
        if lead == "aggregate_field_resolution":
            next_steps.append("Run aggregate-repair prompt optimization on fresh prompt observations from these runs.")
        elif lead == "path_semantics_validator":
            next_steps.append("Tighten GRAPHWALK path-semantics prompt/evaluator and rerun.")
        elif lead == "llm_judge_validation":
            next_steps.append("Harden validator criteria and inspect row-grain preservation before aggregate.")
        else:
            next_steps.append("Inspect variable-flow persistence and produced_artifact handoff before changing prompts.")
    lines.extend(["", "Suggested next actions:"] + [f"- {step}" for step in next_steps])
    Path(args.out_text).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"WROTE {args.out_json}")
    print(f"WROTE {args.out_text}")


if __name__ == "__main__":
    main()
