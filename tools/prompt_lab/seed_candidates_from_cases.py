#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.prompt_lab.common import iter_jsonl, write_jsonl


def _default_parsed(case: Dict[str, Any]) -> Dict[str, Any]:
    parsed = case.get("parsed")
    if isinstance(parsed, dict):
        return parsed
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed candidate rows directly from collected prompt cases.")
    parser.add_argument("--cases", required=True, help="Input standardized prompt cases JSONL")
    parser.add_argument("--out", required=True, help="Output JSONL of seeded candidates")
    parser.add_argument(
        "--only-positive",
        action="store_true",
        help="Only seed cases whose existing labels indicate success (parse_success or validator_yes or generated).",
    )
    args = parser.parse_args()

    rows: List[Dict[str, Any]] = []
    for case in iter_jsonl(Path(args.cases)):
        labels = case.get("labels", {}) or {}
        is_positive = bool(
            labels.get("parse_success")
            or labels.get("validator_yes")
            or labels.get("selector_valid")
            or labels.get("generated")
        )
        if args.only_positive and not is_positive:
            continue
        rows.append(
            {
                "candidate_id": str(uuid.uuid4()),
                "case_id": case["case_id"],
                "variant_index": 0,
                "prompt_name": case["prompt_name"],
                "repair_model": "seeded_from_case",
                "repair_prompt": case.get("prompt_text", ""),
                "response_text": case.get("response_text", ""),
                "parsed": _default_parsed(case),
                "metadata": {
                    "seeded": True,
                    "seed_positive": is_positive,
                    "source_file": case.get("source_file", ""),
                },
            }
        )

    write_jsonl(Path(args.out), rows)
    print(f"WROTE {args.out} ({len(rows)} candidates)")


if __name__ == "__main__":
    main()
