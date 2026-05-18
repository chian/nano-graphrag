#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.prompt_lab.common import load_cases_from_observation_files, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect prompt invocations/outcomes into generic cases.")
    parser.add_argument("--root", default="benchmark_results", help="Root to search for prompt_observations.jsonl")
    parser.add_argument("--prompt-name", action="append", default=[], help="Filter by prompt name (repeatable)")
    parser.add_argument("--out", required=True, help="Output JSONL file for standardized prompt cases")
    args = parser.parse_args()

    observation_files = sorted(Path(args.root).glob("**/prompt_observations.jsonl"))
    prompt_names = set(args.prompt_name) if args.prompt_name else None
    cases = load_cases_from_observation_files(observation_files, prompt_names=prompt_names)
    write_jsonl(Path(args.out), [case.to_dict() for case in cases])
    print(f"WROTE {args.out} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
