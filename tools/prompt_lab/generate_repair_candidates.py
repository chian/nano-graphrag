#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gasl.llm.argo_bridge import ArgoBridgeLLM
from gasl.llm.runtime_config import resolve_runtime_llm_config
from tools.prompt_lab.common import iter_jsonl, render_template, write_jsonl, load_env_file


def _build_llm(model: str) -> ArgoBridgeLLM:
    os.environ.pop("NANOGRAPHRAG_LLM_TRANSPORT", None)
    explicit_key = os.getenv("VIZ_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    cfg = resolve_runtime_llm_config(explicit_api_key=explicit_key, explicit_model=model)
    return ArgoBridgeLLM(model=cfg.model or model, api_key=cfg.api_key, base_url=cfg.base_url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate generic repair candidates from standardized prompt cases.")
    parser.add_argument("--cases", required=True, help="Input standardized prompt cases JSONL")
    parser.add_argument("--template-file", required=True, help="Repair prompt template file using Python format placeholders")
    parser.add_argument("--out", required=True, help="Output JSONL for repair candidates")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--variants", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--env-file", default=".viz.local.env", help="Optional env file providing direct API keys")
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    template = Path(args.template_file).read_text(encoding="utf-8")
    llm = _build_llm(args.model)
    cases = list(iter_jsonl(Path(args.cases)))
    if args.limit:
        cases = cases[: args.limit]
    rows: List[Dict[str, Any]] = []
    for case in cases:
        for idx in range(args.variants):
            prompt_text = render_template(template, case)
            response = llm.call(prompt_text)
            parsed = {}
            try:
                parsed = json.loads(response)
            except Exception:
                parsed = {}
            rows.append(
                {
                    "candidate_id": str(uuid.uuid4()),
                    "case_id": case["case_id"],
                    "variant_index": idx,
                    "prompt_name": case["prompt_name"],
                    "repair_model": args.model,
                    "repair_prompt": prompt_text,
                    "response_text": response,
                    "parsed": parsed,
                }
            )
    write_jsonl(Path(args.out), rows)
    print(f"WROTE {args.out} ({len(rows)} candidates)")


if __name__ == "__main__":
    main()
