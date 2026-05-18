#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.prompt_lab.common import iter_jsonl, run_verifier_command, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify repaired prompt candidates with an external verifier command.")
    parser.add_argument("--cases", required=True, help="Input standardized prompt cases JSONL")
    parser.add_argument("--candidates", required=True, help="Input repair candidates JSONL")
    parser.add_argument("--verifier-cmd", required=True, help="Shell command template using {case_path} and {candidate_path}")
    parser.add_argument("--out", required=True, help="Output JSONL of verification results")
    args = parser.parse_args()

    cases = {row["case_id"]: row for row in iter_jsonl(Path(args.cases))}
    results = []
    for candidate in iter_jsonl(Path(args.candidates)):
        case = cases.get(candidate["case_id"])
        if not case:
            continue
        verdict = run_verifier_command(args.verifier_cmd, case=case, candidate=candidate)
        results.append(
            {
                "candidate_id": candidate["candidate_id"],
                "case_id": candidate["case_id"],
                "pass": bool(verdict.get("pass", False)),
                "score": float(verdict.get("score", 0.0) or 0.0),
                "labels": verdict.get("labels", {}) or {},
                "notes": verdict.get("notes", "") or "",
            }
        )
    write_jsonl(Path(args.out), results)
    print(f"WROTE {args.out} ({len(results)} verifications)")


if __name__ == "__main__":
    main()
