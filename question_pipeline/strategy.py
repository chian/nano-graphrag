"""Question-driven search strategy: query generation and answer assessment.

These are the LLM agents that decide what to search for next and whether the
graph can yet answer the question. They replace the domain-hardcoded template
generator in iterative_search/ with a generic, question-aware approach.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .llm_utils import ask_json


def _coerce_query_list(parsed: Any, limit: int) -> List[str]:
    """Pull a clean list of query strings out of assorted JSON shapes."""
    if isinstance(parsed, dict):
        parsed = parsed.get("queries") or parsed.get("search_queries") or []
    queries: List[str] = []
    seen = set()
    for item in parsed or []:
        text = item.get("query") if isinstance(item, dict) else item
        text = str(text or "").strip()
        key = text.lower()
        if len(text) >= 4 and key not in seen:
            seen.add(key)
            queries.append(text)
        if len(queries) >= limit:
            break
    return queries


async def initial_queries(
    llm,
    question: str,
    *,
    n: int = 6,
    schema_hint: str = "",
) -> List[str]:
    """Derive the first batch of web-search queries straight from the question."""
    prompt = f"""You are finding scientific literature on the web to answer a research question.

QUESTION:
{question}
{("DOMAIN FOCUS: " + schema_hint if schema_hint else "")}

Produce {n} diverse search queries that, run against scientific sources (PubMed,
bioRxiv, journals), would surface the evidence needed to answer the question.
Cover the core mechanism, key quantitative outcomes, and important sub-aspects.
Keep each query concise (3-9 words), no boolean operators.

Return JSON: {{"queries": ["...", "..."]}}"""
    parsed = await ask_json(llm, prompt)
    return _coerce_query_list(parsed, n)


async def followup_queries(
    llm,
    question: str,
    *,
    current_answer: str,
    gaps: List[str],
    top_entities: List[str],
    n: int = 6,
) -> List[str]:
    """Generate the next batch of queries aimed at the current answer's gaps."""
    gap_text = "\n".join(f"- {g}" for g in gaps) if gaps else "- (none identified)"
    entity_text = ", ".join(top_entities[:25]) if top_entities else "(graph is empty)"
    prompt = f"""You are iteratively building a knowledge graph to answer one question.
Decide what to search for NEXT to close the remaining gaps.

QUESTION:
{question}

CURRENT BEST ANSWER FROM THE GRAPH:
{current_answer[:1500]}

IDENTIFIED GAPS:
{gap_text}

ENTITIES ALREADY IN THE GRAPH (avoid redundant searches):
{entity_text}

Produce {n} NEW search queries targeting the gaps and unexplored but relevant
directions. Do not repeat what the graph already covers well. Concise queries
(3-9 words), no boolean operators.

Return JSON: {{"queries": ["...", "..."]}}"""
    parsed = await ask_json(llm, prompt)
    return _coerce_query_list(parsed, n)


async def assess_answer(
    llm,
    question: str,
    *,
    answer: str,
    graph_summary: str,
) -> Dict[str, Any]:
    """Judge whether the current answer sufficiently answers the question."""
    prompt = f"""You are judging whether a knowledge graph can now answer a question well.

QUESTION:
{question}

CANDIDATE ANSWER (produced by graph traversal):
{answer[:2500]}

GRAPH SUMMARY:
{graph_summary}

Decide whether the answer is well-supported and complete, or whether more
evidence is needed. Be strict: a vague or hedged answer is NOT sufficient.

Return JSON:
{{
  "sufficient": true | false,
  "confidence": 0.0-1.0,
  "gaps": ["what is still missing or weakly supported", "..."],
  "rationale": "one or two sentences"
}}"""
    parsed = await ask_json(llm, prompt)
    if not isinstance(parsed, dict):
        return {"sufficient": False, "confidence": 0.0, "gaps": [], "rationale": ""}
    parsed.setdefault("sufficient", False)
    parsed.setdefault("confidence", 0.0)
    parsed.setdefault("gaps", [])
    parsed.setdefault("rationale", "")
    if not isinstance(parsed["gaps"], list):
        parsed["gaps"] = [str(parsed["gaps"])]
    return parsed
