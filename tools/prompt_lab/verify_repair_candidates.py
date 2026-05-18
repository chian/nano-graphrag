#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.prompt_lab.common import iter_jsonl, run_verifier_command


def _base_candidate_from_case(case: Dict) -> Dict:
    return {
        "candidate_id": f"base-{case['case_id']}",
        "case_id": case["case_id"],
        "variant_index": 0,
        "prompt_name": case["prompt_name"],
        "repair_model": "original_case_output",
        "repair_prompt": case.get("prompt_text", ""),
        "response_text": case.get("response_text", ""),
        "parsed": case.get("parsed", {}) or {},
        "metadata": {"seeded": True, "source_file": case.get("source_file", "")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify repaired prompt candidates with an external verifier command.")
    parser.add_argument("--cases", required=True, help="Input standardized prompt cases JSONL")
    parser.add_argument("--candidates", required=True, help="Input repair candidates JSONL")
    parser.add_argument("--verifier-cmd", required=True, help="Shell command template using {case_path} and {candidate_path}")
    parser.add_argument("--out", required=True, help="Output JSONL of verification results")
    parser.add_argument(
        "--accepted-repairs-out",
        default="",
        help="Optional JSONL file for valuable repaired positives where original case output failed verification but candidate passed",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Print progress every N candidates",
    )
    args = parser.parse_args()

    cases = {row["case_id"]: row for row in iter_jsonl(Path(args.cases))}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    accepted_path = Path(args.accepted_repairs_out) if args.accepted_repairs_out else None
    if accepted_path:
        accepted_path.parent.mkdir(parents=True, exist_ok=True)

    base_verdict_cache: Dict[str, Dict] = {}
    total = 0
    with out_path.open("w", encoding="utf-8") as out_fh, (
        accepted_path.open("w", encoding="utf-8") if accepted_path else open("/dev/null", "w", encoding="utf-8")
    ) as accepted_fh:
        for candidate in iter_jsonl(Path(args.candidates)):
            total += 1
            case = cases.get(candidate["case_id"])
            if not case:
                continue
            verdict = run_verifier_command(args.verifier_cmd, case=case, candidate=candidate)
            row = {
                "candidate_id": candidate["candidate_id"],
                "case_id": candidate["case_id"],
                "pass": bool(verdict.get("pass", False)),
                "score": float(verdict.get("score", 0.0) or 0.0),
                "labels": verdict.get("labels", {}) or {},
                "notes": verdict.get("notes", "") or "",
            }
            out_fh.write(json.dumps(row, default=str) + "\n")
            out_fh.flush()

            if accepted_path:
                case_id = candidate["case_id"]
                base_verdict = base_verdict_cache.get(case_id)
                if base_verdict is None:
                    base_candidate = _base_candidate_from_case(case)
                    base_verdict = run_verifier_command(args.verifier_cmd, case=case, candidate=base_candidate)
                    base_verdict_cache[case_id] = base_verdict
                if (not bool(base_verdict.get("pass", False))) and bool(verdict.get("pass", False)):
                    accepted_fh.write(
                        json.dumps(
                            {
                                "case_id": case_id,
                                "candidate_id": candidate["candidate_id"],
                                "prompt_name": candidate.get("prompt_name", case.get("prompt_name", "")),
                                "base_verdict": base_verdict,
                                "repaired_verdict": verdict,
                                "case": case,
                                "candidate": candidate,
                            },
                            default=str,
                        )
                        + "\n"
                    )
                    accepted_fh.flush()

            if args.progress_every and total % args.progress_every == 0:
                print(f"PROGRESS {total}", file=sys.stderr, flush=True)
    print(f"WROTE {args.out} ({total} verifications)")
    if accepted_path:
        print(f"WROTE {accepted_path} (accepted repaired positives)", file=sys.stderr)


if __name__ == "__main__":
    main()
