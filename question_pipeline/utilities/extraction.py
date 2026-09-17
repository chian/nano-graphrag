"""Graph, table, and chunk extraction plus source-text ranking."""

from __future__ import annotations


# ============================================================================
# extraction.py
# ============================================================================

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import networkx as nx

EXTRACTION_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(EXTRACTION_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACTION_REPO_ROOT))

from graph_enrichment.graph_merger import (
    add_entities_to_graph,
    add_relationships_to_graph,
)
from nano_graphrag.graph_slots import get_salience_score, set_salience_score


@dataclass(frozen=True)
class TextChunk:
    """One deterministic source slice with exact character offsets."""

    index: int
    start_offset: int
    end_offset: int
    text: str


def chunk_spans(
    text: str, chunk_size: int = 2000, overlap: int = 200
) -> List[TextChunk]:
    """Split text while retaining exact source-version offsets."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    chunks: List[TextChunk] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(TextChunk(len(chunks), start, end, text[start:end]))
        if end >= len(text) or len(text) - end <= overlap:
            break
        start = end - overlap
    return chunks


def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> List[str]:
    """Split text into overlapping character chunks."""
    return [chunk.text for chunk in chunk_spans(text, chunk_size, overlap)]


#: Signature of :func:`extract_from_text`'s per-chunk observer:
#: ``(chunk_index, chunk_id, entities, relationships, failure)``. ``failure`` is
#: ``""`` when the chunk's extraction returned, and a class label
#: (``"timeout"`` or the exception's type name) when it did not.
ChunkObserver = Callable[[int, str, list, list, str], None]


async def extract_from_text(
    extractor,
    text: str,
    source_id: str,
    *,
    chunk_size: int = 2000,
    overlap: int = 200,
    concurrency: int = 1,
    timeout: Optional[float] = None,
    on_chunk: Optional[ChunkObserver] = None,
) -> Tuple[Dict[str, dict], List[dict]]:
    """Run the typed extractor over chunked text.

    Returns (entities_by_name, relationships). Entities are merged across
    chunks by name, keeping the highest salience and accumulating source
    chunk ids; relationships are collected with their source chunk.

    ``on_chunk`` observes each chunk's own output **before** the merge, in
    deterministic chunk order, and after the gather -- so the concurrency above
    is untouched and what the observer sees is that chunk's extraction rather
    than the merged residue. It is handed the chunk's failure class as well as
    its output, because this function converts a per-chunk timeout or exception
    into an empty result: without the flag a failed chunk is indistinguishable
    from a barren one, and a consumer counting barren chunks would count
    instrument failures as evidence. Defaults to ``None``, so every existing
    caller is byte-identical.
    """
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")

    entities: Dict[str, dict] = {}
    relationships: List[dict] = []
    semaphore = asyncio.Semaphore(concurrency)

    async def extract_chunk(idx: int, chunk: str):
        chunk_id = f"{source_id}_chunk_{idx}"
        try:
            async with semaphore:
                extraction = extractor.forward(chunk)
                if timeout is not None and timeout > 0:
                    prediction = await asyncio.wait_for(
                        extraction,
                        timeout=timeout,
                    )
                else:
                    prediction = await extraction
        except asyncio.TimeoutError:
            print(f"    [extract] chunk {idx} timed out after {timeout}s")
            return idx, chunk_id, [], [], "timeout"
        except Exception as exc:  # noqa: BLE001 - one bad chunk shouldn't abort
            print(f"    [extract] chunk {idx} failed: {exc}")
            return idx, chunk_id, [], [], type(exc).__name__

        return idx, chunk_id, prediction.entities, prediction.relationships, ""

    chunk_results = await asyncio.gather(
        *(
            extract_chunk(idx, chunk)
            for idx, chunk in enumerate(chunk_text(text, chunk_size, overlap))
        )
    )

    for index, chunk_id, chunk_entities, chunk_relationships, failure in sorted(
        chunk_results,
        key=lambda item: item[0],
    ):
        if on_chunk is not None:
            on_chunk(index, chunk_id, chunk_entities, chunk_relationships, failure)
        for entity in chunk_entities:
            ent = entity.to_dict()
            name = ent.get("entity_name")
            if not name:
                continue
            if name not in entities:
                ent["source_chunks"] = [chunk_id]
                entities[name] = ent
            else:
                existing = entities[name]
                if get_salience_score(ent, 0.0) > get_salience_score(existing, 0.0):
                    set_salience_score(existing, get_salience_score(ent, 0.0))
                if chunk_id not in existing["source_chunks"]:
                    existing["source_chunks"].append(chunk_id)

        for rel in chunk_relationships:
            rel_dict = rel.to_dict()
            rel_dict["source_chunk"] = chunk_id
            relationships.append(rel_dict)

    return entities, relationships


def enrich_graph(
    graph: nx.DiGraph,
    entities: Dict[str, dict],
    relationships: List[dict],
    source_id: str,
    *,
    similarity_threshold: float = 0.85,
    auto_merge: bool = True,
) -> nx.DiGraph:
    """Merge extracted entities/relationships into the graph in place-ish.

    Returns the updated graph (the mergers may return a new object).
    """
    graph, name_mapping = add_entities_to_graph(
        graph,
        entities,
        source_id,
        similarity_threshold=similarity_threshold,
        auto_merge=auto_merge,
    )
    graph = add_relationships_to_graph(graph, relationships, name_mapping, source_id)
    return graph


def schema_type_coverage(
    schema_entity_types: List[str],
    entities: Dict[str, dict],
) -> Dict[str, Any]:
    """Compute how well a set of extractions fit a schema's entity types."""
    allowed = set(schema_entity_types)
    used: Dict[str, int] = {}
    off_schema = 0
    for ent in entities.values():
        etype = ent.get("entity_type", "UNKNOWN")
        used[etype] = used.get(etype, 0) + 1
        if etype not in allowed:
            off_schema += 1
    total = max(1, len(entities))
    return {
        "n_entities": len(entities),
        "types_used": used,
        "off_schema_entities": off_schema,
        "off_schema_rate": round(off_schema / total, 3),
        "schema_types_hit": sorted(set(used) & allowed),
        "schema_types_unused": sorted(allowed - set(used)),
    }


# ============================================================================
# schema_synthesis.py
# ============================================================================

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(SCHEMA_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(SCHEMA_REPO_ROOT))

import yaml

from domain_schemas.schema_loader import DomainSchema, EntityType, RelationshipType
from nano_graphrag.entity_extraction.typed_module import (
    create_domain_extractor_from_schema,
)

from question_pipeline.utilities.model import ModelTier, ask_json, register_call_site_tier

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


# ============================================================================
# episode_bindings/shared/chunk_ranking.py
# ============================================================================

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from question_pipeline.utilities.model import ModelTier, ask_json, register_call_site_tier
from question_pipeline.utilities.tables import TableSpec


_LEXICAL_PROBE_TIER = register_call_site_tier(
    "page-lexical-probe",
    ModelTier.REASONING,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_CONTEXT_RADII = (0, 1, 4)
_CONTEXT_WEIGHTS = (3.0, 1.0, 1.0)
_RANK_FUSION_OFFSET = 60.0

_CHUNK_RANKING_SYSTEM_PROMPT = """You propose one lexical retrieval query for a document.
Return one valid JSON object and no prose. Choose words and phrases that are
likely to occur verbatim in an unprocessed chunk and that could reveal values
for the declared table contract. Prefer the surface forms likely to appear in
data-bearing rows: abbreviations, units, codes, field labels, and compact value
formats. Do not rely only on conceptual names from the table contract when the
document is likely to express them differently. You select a string only. You
never decide whether retrieval should continue or stop."""


@dataclass(frozen=True)
class LexicalProbe:
    """One model-proposed lexical query, never a batch of alternatives."""

    query: str
    rationale: str = ""

    def __post_init__(self) -> None:
        query = " ".join(str(self.query).split())
        if not query:
            raise ValueError("a lexical probe query must be non-empty")
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "rationale", str(self.rationale).strip())

    def to_dict(self) -> dict[str, str]:
        return {"query": self.query, "rationale": self.rationale}


def page_outline(text: str, title: str = "") -> dict[str, Any]:
    """Return local, non-model page cues for the probe proposer."""

    headings = [" ".join(value.split()) for value in _HEADING_RE.findall(text)]
    return {
        "title": " ".join(str(title).split()),
        "headings": list(dict.fromkeys(headings)),
    }


async def propose_lexical_probe(
    llm: Any,
    *,
    question: str,
    table_spec: TableSpec,
    outline: Mapping[str, Any],
    previous_probes: Sequence[Mapping[str, Any]],
) -> LexicalProbe:
    """Ask for exactly one query using the outcomes of earlier probes."""

    prompt = f"""QUESTION:
{question}

TABLE CONTRACT:
{json.dumps(table_spec.prompt_context(), ensure_ascii=False, sort_keys=True)}

DOCUMENT OUTLINE:
{json.dumps(dict(outline), ensure_ascii=False, sort_keys=True)}

PREVIOUS PROBES ON THIS DOCUMENT:
{json.dumps([dict(item) for item in previous_probes], ensure_ascii=False, sort_keys=True)}

Propose exactly one lexical query for ranking the document's remaining chunks.
Use the previous probe outcomes to avoid repeating an unproductive vocabulary
and to refine vocabulary that found accepted table values. Choose literal
surface forms likely to occur inside the values or rows themselves, including
document-native abbreviations, units, codes, labels, and formatting tokens.
The query may contain several mutually supporting terms or one exact phrase,
but it is one retrieval probe, not a list of alternatives.

Return exactly:
{{"query": "one lexical query", "rationale": "why this query follows from the contract and prior outcomes"}}"""
    payload = await ask_json(
        llm,
        prompt,
        system_prompt=_CHUNK_RANKING_SYSTEM_PROMPT,
        tier=_LEXICAL_PROBE_TIER,
        call_site="page-lexical-probe",
    )
    if not isinstance(payload, Mapping):
        raise ValueError("lexical probe generation must return a JSON object")
    return LexicalProbe(
        query=str(payload.get("query") or ""),
        rationale=str(payload.get("rationale") or ""),
    )


def rank_chunks(
    chunks: Sequence[Any],
    query: str,
) -> list[Any]:
    """Order chunks by fused direct and local-context BM25 ranks.

    Direct matches receive the strongest vote. Immediate and wider context
    let a matching header or explanation lift adjacent data-bearing chunks.
    Ranking never removes a chunk and uses no score threshold. The numerical
    nested Episode alone decides when processing the ranked sequence ends.
    """

    if not chunks:
        return []
    query_terms = _tokens(query)
    if not query_terms:
        return list(chunks)

    chunk_tokens = [_tokens(str(chunk.text)) for chunk in chunks]
    scale_scores = [
        _bm25_scores(
            _context_documents(chunk_tokens, radius=radius),
            query_terms,
        )
        for radius in _CONTEXT_RADII
    ]
    positive_ranks = [_positive_ranks(scores) for scores in scale_scores]

    def fused_score(index: int) -> float:
        return sum(
            weight / (_RANK_FUSION_OFFSET + ranks[index])
            for weight, ranks in zip(_CONTEXT_WEIGHTS, positive_ranks)
            if index in ranks
        )

    ranked = sorted(
        enumerate(chunks),
        key=lambda item: (
            -fused_score(item[0]),
            -scale_scores[0][item[0]],
            item[0],
        ),
    )
    return [chunk for _, chunk in ranked]


def _context_documents(
    chunk_tokens: Sequence[tuple[str, ...]],
    *,
    radius: int,
) -> list[tuple[str, ...]]:
    """Represent each chunk at one local context scale."""

    documents: list[tuple[str, ...]] = []
    for index in range(len(chunk_tokens)):
        first = max(0, index - radius)
        last = min(len(chunk_tokens), index + radius + 1)
        documents.append(
            tuple(
                token
                for neighboring_chunk in chunk_tokens[first:last]
                for token in neighboring_chunk
            )
        )
    return documents


def _bm25_scores(
    documents: Sequence[tuple[str, ...]],
    query_terms: Sequence[str],
) -> list[float]:
    """Return a BM25 score for each document at one context scale."""

    average_length = sum(len(document) for document in documents) / len(documents)
    if average_length <= 0:
        return [0.0 for _ in documents]

    frequencies = [Counter(document) for document in documents]
    document_frequency = Counter(
        term for document in documents for term in set(document)
    )
    count = len(documents)

    def score(index: int) -> float:
        length = len(documents[index])
        total = 0.0
        for term in query_terms:
            frequency = frequencies[index].get(term, 0)
            if frequency == 0:
                continue
            inverse_document_frequency = math.log(
                1.0 + (count - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            # Standard BM25 ranking constants. They affect order only; neither
            # is a threshold and neither can stop an Episode.
            saturation = 1.5
            length_normalization = 0.75
            denominator = frequency + saturation * (
                1.0 - length_normalization
                + length_normalization * length / average_length
            )
            total += inverse_document_frequency * (
                frequency * (saturation + 1.0) / denominator
            )
        return total

    return [score(index) for index in range(len(documents))]


def _positive_ranks(scores: Sequence[float]) -> dict[int, int]:
    """Rank actual matches while leaving zero-match chunks unvoted."""

    ordered = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    return {
        index: rank
        for rank, index in enumerate(ordered, start=1)
        if scores[index] > 0.0
    }


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(str(text).lower()))


# ============================================================================
# episode_bindings/shared/table_extraction.py
# ============================================================================

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from question_pipeline.utilities.model import ModelTier, ask_json, register_call_site_tier
from question_pipeline.utilities.tables import ColumnEvidenceRole, TableSpec


# The V15 run is the reasoning-tier baseline for this high-volume call site.
# The fresh continuation experiment moves this one call site to the configured
# fast model while holding the table contract and all acquisition rules fixed.
_TABLE_PAGE_EXTRACTION_TIER = register_call_site_tier(
    "table-page-extraction",
    ModelTier.FAST,
)

_TABLE_EXTRACTION_SYSTEM_PROMPT = """You extract source-reported values into a declared table
contract. Return one valid JSON object and no prose. Never infer, estimate,
normalize, reconcile, or fill a value that the supplied source chunk does not
state. Preserve the source wording of text, dates, ranges, bounds, and
comparisons. Numeric JSON values may differ only in harmless numeric formatting
such as commas. Omit missing fields."""


@dataclass(frozen=True)
class TableChunkExtraction:
    """Validated source-local rows returned for one exact chunk."""

    rows: tuple[dict[str, Any], ...]


class TableSpecExtractor:
    """Model-backed mapper from one source chunk to a frozen ``TableSpec``."""

    def __init__(self, llm: Any, table_spec: TableSpec) -> None:
        diagnostic = table_spec.column_yield_diagnostic()
        if not diagnostic["usable_schema"]:
            raise ValueError(
                "table extraction requires a usable table contract: "
                f"{diagnostic}"
            )
        self._llm = llm
        self._table_spec = table_spec
        self._tables = {
            name: table
            for name, table in table_spec.tables.items()
            if table.deliverable
        }

    async def forward(self, text: str) -> TableChunkExtraction:
        contract = self._extraction_contract()
        prompt = f"""TABLE CONTRACT:
{json.dumps(contract, ensure_ascii=False, sort_keys=True)}

SOURCE CHUNK:
{text}

Extract every distinct source-local subject described in this chunk that
belongs in a declared table.

Rules:
- Return only declared table and column names.
- Return only columns whose role is reported. Best-guess columns are handled
  by a separate evidence-anchored reasoning step.
- One row represents one subject at the table's declared grain.
- Partial rows are allowed, but include every subject-key column that the
  chunk explicitly states. Do not invent a missing identity field.
- Every string value must be an exact substring of SOURCE CHUNK.
- Do not combine facts from different subjects.
- If the chunk contains no qualifying row, return an empty rows list.

Return exactly:
{{
  "rows": [
    {{
      "table": "declared_table_name",
      "values": {{"declared_reported_column": "exact source value"}}
    }}
  ]
}}"""
        payload = await ask_json(
            self._llm,
            prompt,
            system_prompt=_TABLE_EXTRACTION_SYSTEM_PROMPT,
            tier=_TABLE_PAGE_EXTRACTION_TIER,
            call_site="table-page-extraction",
        )
        if not isinstance(payload, Mapping):
            raise ValueError("table extraction must return a JSON object")
        return TableChunkExtraction(rows=self._validated_rows(payload.get("rows")))

    def _extraction_contract(self) -> dict[str, Any]:
        tables: dict[str, Any] = {}
        for name, table in self._tables.items():
            reported = {
                column.name: column.to_dict()
                for column in table.all_columns()
                if column.role is ColumnEvidenceRole.REPORTED
            }
            tables[name] = {
                "description": table.description,
                "grain": table.grain,
                "subject_key_columns": list(table.subject_key_columns),
                "reported_columns": reported,
            }
        return {"tables": tables}

    def _validated_rows(self, raw_rows: Any) -> tuple[dict[str, Any], ...]:
        if raw_rows is None:
            return ()
        if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
            raise ValueError("table extraction rows must be a list")
        rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                continue
            table_name = str(raw.get("table") or "")
            table = self._tables.get(table_name)
            values = raw.get("values")
            if table is None or not isinstance(values, Mapping):
                continue
            reported_names = {
                column.name
                for column in table.all_columns()
                if column.role is ColumnEvidenceRole.REPORTED
            }
            admitted = {
                str(name): value
                for name, value in values.items()
                if str(name) in reported_names
                and value is not None
                and not isinstance(value, (Mapping, list, tuple, set, bool))
                and str(value).strip()
            }
            if admitted:
                rows.append({"table": table_name, "values": admitted})
        return tuple(rows)


async def extract_table_rows_from_text(
    extractor: TableSpecExtractor,
    text: str,
    source_id: str,
    *,
    chunk_size: int = 2000,
    overlap: int = 200,
    concurrency: int = 1,
    timeout: Optional[float] = None,
    on_chunk: Optional[Callable[[int, str, list, list, str], None]] = None,
) -> list[dict[str, Any]]:
    """Apply the table extractor chunkwise while preserving source anchors."""

    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    spans = chunk_spans(text, chunk_size, overlap)
    semaphore = asyncio.Semaphore(concurrency)

    async def extract_chunk(index: int, chunk_text: str):
        chunk_id = f"{source_id}_chunk_{index}"
        try:
            async with semaphore:
                call = extractor.forward(chunk_text)
                result = (
                    await asyncio.wait_for(call, timeout=timeout)
                    if timeout is not None and timeout > 0
                    else await call
                )
        except asyncio.TimeoutError:
            return index, chunk_id, (), "timeout"
        except Exception as exc:  # noqa: BLE001 - one chunk cannot abort a page
            return index, chunk_id, (), type(exc).__name__
        return index, chunk_id, result.rows, ""

    results = await asyncio.gather(
        *(extract_chunk(chunk.index, chunk.text) for chunk in spans)
    )
    records: list[dict[str, Any]] = []
    for index, chunk_id, rows, failure in sorted(results, key=lambda item: item[0]):
        if on_chunk is not None:
            on_chunk(index, chunk_id, list(rows), [], failure)
        for row in rows:
            records.append(
                {
                    "table": row["table"],
                    "index": len(records),
                    "values": dict(row["values"]),
                    "source_chunks": [chunk_id],
                }
            )
    return records
