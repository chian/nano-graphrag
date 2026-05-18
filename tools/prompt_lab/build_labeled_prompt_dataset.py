#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.prompt_lab.common import iter_jsonl, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a reusable labeled prompt dataset from cases + verified repair candidates.")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--verifications", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    cases = {row["case_id"]: row for row in iter_jsonl(Path(args.cases))}
    candidates = {}
    for row in iter_jsonl(Path(args.candidates)):
        candidates[row["candidate_id"]] = row
    verifications = list(iter_jsonl(Path(args.verifications)))

    accepted_by_case: Dict[str, List[Dict[str, Any]]] = {}
    for verdict in verifications:
        cand = candidates.get(verdict["candidate_id"])
        if not cand:
            continue
        accepted_by_case.setdefault(verdict["case_id"], []).append({**cand, "verdict": verdict})

    rows: List[Dict[str, Any]] = []
    for case_id, case in cases.items():
        verified = sorted(
            accepted_by_case.get(case_id, []),
            key=lambda item: item["verdict"]["score"],
            reverse=True,
        )
        best = next((item for item in verified if item["verdict"]["pass"]), None)
        rows.append(
            {
                "case_id": case_id,
                "prompt_name": case["prompt_name"],
                "input_case": case,
                "label": "positive" if best else "negative",
                "best_candidate": best,
                "all_candidates": verified,
            }
        )

    rng = random.Random(args.seed)
    rng.shuffle(rows)
    split = int(len(rows) * args.train_ratio)
    dataset = {"train": rows[:split], "val": rows[split:]}
    Path(args.out).write_text(json.dumps(dataset, indent=2, default=str), encoding="utf-8")
    print(f"WROTE {args.out} (train={len(dataset['train'])}, val={len(dataset['val'])})")


if __name__ == "__main__":
    main()
