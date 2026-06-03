from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from domain_schemas.schema_loader import DomainSchema, SchemaLoader, load_domain_schema
from hpc.common import read_json_records, write_json, write_jsonl


def _schema_prompt_components(schema_name: str) -> tuple[DomainSchema, str, str]:
    """Load and format the schema once per shard run."""
    loader = SchemaLoader()
    schema = load_domain_schema(schema_name)
    entity_type_descriptions = loader.format_entity_types_for_prompt(schema)
    relationship_type_descriptions = loader.format_relationship_types_for_prompt(schema)
    return schema, entity_type_descriptions, relationship_type_descriptions


def _build_extraction_prompt(
    chunk_text: str,
    entity_type_descriptions: str,
    relationship_type_descriptions: str,
) -> str:
    """Build the typed-extraction prompt contract using preformatted schema text."""
    return f"""Extract entities and relationships from the following text using domain-specific types.

Given a text document and domain-specific entity and relationship types, identify all entities and relationships that match the domain schema.

ENTITY TYPES (use exactly these):
{entity_type_descriptions}

RELATIONSHIP TYPES (use exactly these):
{relationship_type_descriptions}

Entity Guidelines:
1. Each entity must match one of the provided entity_types exactly.
2. Extract only entities relevant to the domain.
3. Entity names should be atomic words/phrases from the input text.
4. Avoid duplicates and generic terms.
5. Provide comprehensive descriptions covering:
   a). Entity's role in the domain context
   b). Key domain-relevant attributes
   c). Relationships to other entities
   d). Functional significance

Relationship Guidelines:
1. Each relationship MUST use a relation_type from the provided relationship_types list.
2. Choose the most specific and accurate relationship type.
3. Include comprehensive descriptions covering:
   a). The nature of the interaction (mechanism, effect, dependency)
   b). The biological/scientific significance
   c). Conditions under which the relationship holds
   d). Evidence or basis for the relationship
4. Include direct relationships (order 1) and higher-order relationships (order 2-3).
5. The "src_id" and "tgt_id" must exactly match entity names from the extracted entities.
6. IMPORTANT: Only use relationship types from the provided 'relationship_types' list.

Examples:
- If relation_type is "INHIBITS": Drug X INHIBITS Enzyme Y by competitive binding
- If relation_type is "CAUSES": Mutation A CAUSES Loss of function in Protein B
- If relation_type is "PART_OF": Protein C PART_OF Pathway D as a rate-limiting enzyme

TEXT:
{chunk_text}

Extract all entities and relationships. Return JSON:
{{
  "entities": [
    {{"entity_name": "...", "entity_type": "...", "description": "...", "importance_score": 0.0-1.0}}
  ],
  "relationships": [
    {{"src_id": "...", "tgt_id": "...", "relation_type": "...", "description": "...", "weight": 0.0-1.0, "order": 1-3}}
  ]
}}"""


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
    _, entity_type_descriptions, relationship_type_descriptions = _schema_prompt_components(
        schema_name
    )

    for row in rows:
        prompt = _build_extraction_prompt(
            row["chunk_text"],
            entity_type_descriptions,
            relationship_type_descriptions,
        )
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
