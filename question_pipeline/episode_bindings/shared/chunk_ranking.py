"""One-at-a-time lexical retrieval inside one fetched page.

The model proposes one search string.  The lexical ranker orders the page's
remaining chunks.  Neither component decides whether another chunk or another
probe is attempted: those decisions belong to the nested numerical Episodes
that consume these outputs.

This module deliberately receives an LLM at the string-generation boundary
and otherwise consists of pure functions over page text and the frozen table
contract.  It performs no extraction, evidence acceptance, crediting,
persistence, or stopping.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ...llm_utils import ModelTier, ask_json, register_call_site_tier
from ...table_specs import TableSpec


_LEXICAL_PROBE_TIER = register_call_site_tier(
    "page-lexical-probe",
    ModelTier.REASONING,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_CONTEXT_RADII = (0, 1, 4)
_CONTEXT_WEIGHTS = (3.0, 1.0, 1.0)
_RANK_FUSION_OFFSET = 60.0

_SYSTEM_PROMPT = """You propose one lexical retrieval query for a document.
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
        system_prompt=_SYSTEM_PROMPT,
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
