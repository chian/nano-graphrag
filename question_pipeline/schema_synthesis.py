"""Synthesize a domain graph schema for a question.

Pipeline: an LLM proposes a candidate schema (entity + relationship types),
a judge LLM critiques it, the proposer revises, and finally the candidate is
stress-tested by running the real typed extractor over one or two fetched
documents. Test metrics (off-schema rate, type coverage) drive one more
revision so the finalized schema actually fits the source material.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml

from domain_schemas.schema_loader import DomainSchema, EntityType, RelationshipType
from nano_graphrag.entity_extraction.typed_module import (
    create_domain_extractor_from_schema,
)

from .extraction import extract_from_text, schema_type_coverage
from .llm_utils import ModelTier, ask_json, register_call_site_tier

#: 0M-schema-synthesis: `gpt-5.4-mini` agreed on 0.472 of entity and
#: relationship types against a registered 0.95 threshold. Stays on the
#: reasoning model. The other three calls in this module were not tested and
#: therefore also stay: `ask_json` defaults to `REASONING`.
_GENERATE_SCHEMA_TIER = register_call_site_tier("schema-synthesis", ModelTier.REASONING)


# --------------------------------------------------------------------------- #
# Conversion between LLM JSON, DomainSchema, and YAML
# --------------------------------------------------------------------------- #

def schema_dict_to_domain_schema(data: Dict[str, Any]) -> DomainSchema:
    """Build a DomainSchema dataclass from a plain dict (LLM output)."""
    entity_types: Dict[str, EntityType] = {}
    for item in data.get("entity_types", []):
        name = _norm_type_name(item.get("name", ""))
        if not name:
            continue
        entity_types[name] = EntityType(
            name=name,
            description=str(item.get("description", "")).strip(),
            examples=[str(x) for x in (item.get("examples") or [])][:8],
        )

    relationship_types: Dict[str, RelationshipType] = {}
    for item in data.get("relationship_types", []):
        name = _norm_type_name(item.get("name", ""))
        if not name:
            continue
        relationship_types[name] = RelationshipType(
            name=name,
            description=str(item.get("description", "")).strip(),
            inverse=item.get("inverse") or None,
            symmetric=bool(item.get("symmetric", False)),
            examples=[str(x) for x in (item.get("examples") or [])][:6],
        )

    return DomainSchema(
        domain_name=str(data.get("domain_name", "Synthesized Domain")).strip(),
        domain_description=str(data.get("domain_description", "")).strip(),
        entity_types=entity_types,
        relationship_types=relationship_types,
    )


def _norm_type_name(name: str) -> str:
    """Normalize a type name to the SCREAMING_SNAKE_CASE convention."""
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(name).strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned.upper()


def domain_schema_to_yaml(schema: DomainSchema) -> str:
    """Serialize a DomainSchema to YAML matching domain_schemas/*.yaml."""
    payload = {
        "domain_name": schema.domain_name,
        "domain_description": schema.domain_description,
        "entity_types": {
            name: {"description": et.description, "examples": et.examples}
            for name, et in schema.entity_types.items()
        },
        "relationship_types": {
            name: {
                "description": rt.description,
                "inverse": rt.inverse,
                "symmetric": rt.symmetric,
                "examples": rt.examples,
            }
            for name, rt in schema.relationship_types.items()
        },
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def write_schema_yaml(schema: DomainSchema, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(domain_schema_to_yaml(schema), encoding="utf-8")
    return path


def _schema_overview(schema: DomainSchema) -> str:
    """Compact text view of a schema for use inside prompts."""
    lines = [f"domain_name: {schema.domain_name}", f"domain_description: {schema.domain_description}", "entity_types:"]
    for name, et in schema.entity_types.items():
        lines.append(f"  - {name}: {et.description}")
    lines.append("relationship_types:")
    for name, rt in schema.relationship_types.items():
        lines.append(f"  - {name}: {rt.description}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# LLM agents
# --------------------------------------------------------------------------- #

_SCHEMA_JSON_SHAPE = """Return JSON with this exact shape:
{
  "domain_name": "Short Title Case name",
  "domain_description": "1-2 sentences on what this graph captures and why",
  "entity_types": [
    {"name": "SCREAMING_SNAKE_CASE", "description": "what this node is", "examples": ["...", "..."]}
  ],
  "relationship_types": [
    {"name": "SCREAMING_SNAKE_CASE", "description": "what this edge means",
     "inverse": "OPTIONAL_INVERSE_NAME_OR_NULL", "symmetric": false, "examples": ["A -> B"]}
  ]
}"""

_SCHEMA_SYSTEM_PROMPT = """You are a rigorous typed-graph schema designer.
Return only one complete valid JSON object in the exact shape requested by the
user. Do not include markdown fences, prose, comments, or partial drafts."""


async def generate_candidate_schema(
    llm,
    question: str,
    *,
    expectations: str = "",
    min_entity_types: int = 6,
    max_entity_types: int = 14,
) -> Dict[str, Any]:
    """Propose an initial schema tailored to the question."""
    prompt = f"""You are designing a knowledge-graph schema to answer ONE research question well.

QUESTION:
{question}

{("ANALYST EXPECTATIONS / SCOPE NOTES:\n" + expectations + "\n") if expectations else ""}
Design entity types and relationship types that would let a graph traversal
gather and compare the evidence needed to answer the question. Aim for
{min_entity_types}-{max_entity_types} entity types and a comparable number of
relationship types. Favor types that capture quantitative findings, causal or
mechanistic links, study/evidence provenance, and the key actors of the domain.
Do not include generic catch-all types like "CONCEPT" or "THING".

{_SCHEMA_JSON_SHAPE}"""
    return await ask_json(
        llm,
        prompt,
        system_prompt=_SCHEMA_SYSTEM_PROMPT,
        tier=_GENERATE_SCHEMA_TIER,
    )


async def critique_schema(
    llm,
    question: str,
    schema: DomainSchema,
) -> Dict[str, Any]:
    """Judge the schema against the question; return a structured critique."""
    prompt = f"""You are a rigorous reviewer of knowledge-graph schemas.

QUESTION the graph must answer:
{question}

CANDIDATE SCHEMA:
{_schema_overview(schema)}

Assess whether this schema is sufficient and well-formed to answer the question.
Check for: missing entity/relationship types needed by the question; redundant or
overlapping types; vague descriptions; generic catch-all types; and whether the
relationships actually connect the entity types into answerable paths.

Return JSON:
{{
  "verdict": "accept" | "revise",
  "score": 0.0-1.0,
  "issues": ["specific problem", "..."],
  "missing_entity_types": ["NAME: why"],
  "missing_relationship_types": ["NAME: why"],
  "redundant_types": ["NAME", "..."]
}}"""
    return await ask_json(llm, prompt, system_prompt=_SCHEMA_SYSTEM_PROMPT)


async def revise_schema(
    llm,
    question: str,
    schema: DomainSchema,
    feedback: Dict[str, Any],
) -> Dict[str, Any]:
    """Produce a revised schema dict that addresses feedback.

    The feedback is sent whole -- not clipped, and not windowed. It is not
    windowed because this call returns ONE full revised schema: splitting the
    feedback would produce several competing whole schemas and require a merge
    over schemas, which is a far worse contract than a longer prompt. It is not
    clipped because the previous 3,000-character clip decided which reviewer
    issues the reviser was allowed to see by their position in `critique_schema`'s
    JSON, and the last issues in that list are not the least important ones.
    The payload is bounded by the schema it critiques, so removing the clip does
    not open an unbounded prompt.
    """
    import json

    prompt = f"""Revise this knowledge-graph schema to address the reviewer feedback.

QUESTION:
{question}

CURRENT SCHEMA:
{_schema_overview(schema)}

REVIEWER FEEDBACK (JSON, complete and unabridged):
{json.dumps(feedback, indent=2, default=str)}

Apply the feedback: add missing types, drop or merge redundant ones, sharpen
vague descriptions. Keep what already works. Return the FULL revised schema.

{_SCHEMA_JSON_SHAPE}"""
    return await ask_json(llm, prompt, system_prompt=_SCHEMA_SYSTEM_PROMPT)


async def revise_schema_from_test(
    llm,
    question: str,
    schema: DomainSchema,
    test_reports: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Revise the schema given real extraction results on sample documents.

    The test reports are sent whole, for the same reason as `revise_schema`:
    this call returns ONE full revised schema, so windowing the reports would
    require merging schemas. The list is short by construction -- `synthesize_schema`
    tests at most two sample documents -- so the 3,500-character clip that was
    here bounded the *second* report's off-schema types out of the prompt while
    claiming to bound the prompt, which is how a schema learns from one document
    and is told it learned from two.
    """
    import json

    prompt = f"""You tested this schema by running a typed extractor over real source
documents. Use the results to improve the schema so it fits the material.

QUESTION:
{question}

CURRENT SCHEMA:
{_schema_overview(schema)}

EXTRACTION TEST RESULTS (JSON, complete and unabridged):
{json.dumps(test_reports, indent=2, default=str)}

Notes on reading the results:
- "off_schema_entities" / a high "off_schema_rate" means the extractor produced
  entity types that are not in the schema -> consider adding those types.
- "schema_types_unused" lists schema types that never matched anything -> consider
  removing them or sharpening their description if they should have matched.
- "sample_off_schema_types" shows concrete types the text wanted.

Return the FULL revised schema (add types the documents clearly need, prune dead ones).

{_SCHEMA_JSON_SHAPE}"""
    return await ask_json(llm, prompt, system_prompt=_SCHEMA_SYSTEM_PROMPT)


# --------------------------------------------------------------------------- #
# Schema testing on real text
# --------------------------------------------------------------------------- #

async def test_schema_on_text(
    schema: DomainSchema,
    text: str,
    llm,
    *,
    source_id: str,
    chunk_chars: int = 6000,
) -> Dict[str, Any]:
    """Run the real typed extractor with this schema over a whole document.

    `extract_from_text` already chunks and merges, so `chunk_chars` bounds one
    extractor call and never the document: a longer document becomes more
    chunks, not a shortened document. The `text[:sample_chars]` this replaced
    defeated that loop, and it defeated it in the one direction that matters
    for this function's purpose. The first 6,000 characters of a paper are its
    title, abstract and introduction; the results tables, units and qualifiers
    that a typed schema most needs to fit live further down. A schema tested
    only on front matter is tested on the part of the corpus it was already
    going to fit, and `off_schema_rate` measured that way is measuring the
    front matter.
    """
    extractor = create_domain_extractor_from_schema(
        schema, llm_func=llm.call_async, num_refine_turns=1, self_refine=False
    )
    entities, relationships = await extract_from_text(
        extractor,
        text,
        source_id,
        chunk_size=chunk_chars,
        overlap=0,
    )
    coverage = schema_type_coverage(list(schema.entity_types.keys()), entities)

    allowed_rel = set(schema.relationship_types.keys())
    off_schema_rels = sum(
        1 for r in relationships if r.get("relation_type", "UNKNOWN") not in allowed_rel
    )
    sample_off_types = sorted({
        e.get("entity_type", "UNKNOWN")
        for e in entities.values()
        if e.get("entity_type") not in schema.entity_types
    })
    coverage.update(
        {
            "source_id": source_id,
            "n_relationships": len(relationships),
            "off_schema_relationships": off_schema_rels,
            # Every off-schema type the extractor produced. The `[:12]` here
            # decided which types the reviser was allowed to add to the schema
            # by alphabetical position, which is not a ranking of anything.
            # `sample_off_schema_types` is retained as a deprecated alias with
            # identical contents -- the revision prompt names it -- rather than
            # shipping two keys that look like different measurements.
            "off_schema_types": sample_off_types,
            "sample_off_schema_types": sample_off_types,  # alias of the above
            "tested_chars": len(text),
            "chunk_chars": chunk_chars,
        }
    )
    return coverage


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

@dataclass
class SchemaSynthesisResult:
    schema: DomainSchema
    history: List[Dict[str, Any]] = field(default_factory=list)


async def synthesize_schema(
    llm,
    question: str,
    *,
    sample_texts: Optional[List[Dict[str, str]]] = None,
    expectations: str = "",
    max_review_passes: int = 2,
    run_extraction_test: bool = True,
) -> SchemaSynthesisResult:
    """Generate, judge, test, and finalize a schema for the question.

    sample_texts: optional list of {"id": ..., "text": ...} real documents used
    to stress-test the candidate schema before finalizing.
    """
    history: List[Dict[str, Any]] = []

    print("  [schema] generating candidate schema...")
    candidate = await generate_candidate_schema(llm, question, expectations=expectations)
    schema = schema_dict_to_domain_schema(candidate)
    history.append({"stage": "generate", "entity_types": list(schema.entity_types)})

    # Generate <-> judge refinement passes.
    for pass_idx in range(max_review_passes):
        critique = await critique_schema(llm, question, schema)
        history.append({"stage": "critique", "pass": pass_idx, "critique": critique})
        verdict = str(critique.get("verdict", "revise")).lower()
        print(
            f"  [schema] review {pass_idx + 1}: verdict={verdict} "
            f"score={critique.get('score')} "
            f"({len(schema.entity_types)} entity types)"
        )
        if verdict == "accept":
            break
        revised = await revise_schema(llm, question, schema, critique)
        schema = schema_dict_to_domain_schema(revised)
        history.append({"stage": "revise", "pass": pass_idx, "entity_types": list(schema.entity_types)})

    # Stress test on real documents, then one extraction-informed revision
    if run_extraction_test and sample_texts:
        reports = []
        for sample in sample_texts[:2]:
            print(f"  [schema] testing schema on sample '{sample.get('id')}'...")
            report = await test_schema_on_text(
                schema, sample.get("text", ""), llm, source_id=str(sample.get("id", "sample"))
            )
            reports.append(report)
            print(
                f"    -> {report['n_entities']} entities, "
                f"off-schema rate {report['off_schema_rate']}, "
                f"unused types {len(report['schema_types_unused'])}"
            )
        history.append({"stage": "test", "reports": reports})

        needs_fix = any(
            r["off_schema_rate"] > 0.2 or r["n_entities"] == 0 for r in reports
        )
        if needs_fix:
            print("  [schema] refining schema from extraction test results...")
            revised = await revise_schema_from_test(llm, question, schema, reports)
            schema = schema_dict_to_domain_schema(revised)
            history.append({"stage": "revise_from_test", "entity_types": list(schema.entity_types)})

    print(
        f"  [schema] finalized: {len(schema.entity_types)} entity types, "
        f"{len(schema.relationship_types)} relationship types"
    )
    return SchemaSynthesisResult(schema=schema, history=history)
