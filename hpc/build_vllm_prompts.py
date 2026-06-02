from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from domain_schemas.schema_loader import load_domain_schema
from hpc.common import read_json_records, write_json, write_jsonl
from nano_graphrag.entity_extraction.typed_module import create_domain_extractor_from_schema


def _build_extraction_prompt(extractor, chunk_text: str) -> str:
    """
    Reuse the typed extraction prompt contract so the vLLM prompt rows stay
    aligned with the extractor used by the shard runner.
    """
    return extractor._build_extraction_prompt(chunk_text)


def build_vllm_prompts(
    *,
    shard_path: Path,
    out_path: Path,
    schema_name: str,
    model: str,
    request_format: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
) -> dict[str, Any]:
    rows = read_json_records(shard_path)
    prompt_rows: list[dict[str, Any]] = []
    schema = load_domain_schema(schema_name)
    extractor = create_domain_extractor_from_schema(
        schema,
        llm_func=lambda prompt: "",
        num_refine_turns=1,
        self_refine=False,
    )

    for row in rows:
        prompt = _build_extraction_prompt(extractor, row["chunk_text"])
        if request_format == "openai-chat":
            prompt_rows.append(
                {
                    "custom_id": row["chunk_id"],
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "top_p": top_p,
                        "max_tokens": max_tokens,
                    },
                }
            )
        elif request_format == "prompt-jsonl":
            prompt_rows.append(
                {
                    "custom_id": row["chunk_id"],
                    "paper_id": row.get("paper_id", ""),
                    "prompt": prompt,
                    "model": model,
                    "temperature": temperature,
                    "top_p": top_p,
                    "max_tokens": max_tokens,
                }
            )
        else:
            raise ValueError(f"Unsupported request format: {request_format}")

    write_jsonl(out_path, prompt_rows)
    summary = {
        "shard_path": str(shard_path),
        "out_path": str(out_path),
        "schema": schema_name,
        "model": model,
        "format": request_format,
        "rows": len(prompt_rows),
    }
    write_json(out_path.with_suffix(".summary.json"), summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build vLLM-ready prompt JSONL from a deterministic shard manifest."
    )
    parser.add_argument("shard_path", type=Path)
    parser.add_argument("out_path", type=Path)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument(
        "--format",
        choices=["openai-chat", "prompt-jsonl"],
        default="openai-chat",
    )
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    args = parser.parse_args()
    build_vllm_prompts(
        shard_path=args.shard_path,
        out_path=args.out_path,
        schema_name=args.schema,
        model=args.model,
        request_format=args.format,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
    )


if __name__ == "__main__":
    main()
