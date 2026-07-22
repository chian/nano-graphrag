"""Question-driven search strategy: query generation and answer assessment.

These are the LLM agents that decide what to search for next and whether the
graph can yet answer the question. They replace the domain-hardcoded template
generator in iterative_search/ with a generic, question-aware approach.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping

from .llm_utils import ask_json
from .progress_judge import judge_progress


_SEARCH_SYSTEM_PROMPT = """You are a scientific search strategist.
Generate concise web-search queries that retrieve source material needed to
answer the user's research question. Infer the domain and target categories
from the question and current run state. Return only valid JSON in the shape
requested by the user."""

_ASSESSMENT_SYSTEM_PROMPT = """You are a rigorous evidence-coverage reviewer.
Judge whether a graph-derived answer is supported by enough retrieved evidence
to answer the user's research question. Return only valid JSON in the shape
requested by the user."""

_UNIVERSE_ESTIMATE_SYSTEM_PROMPT = """You estimate the answer universe for an
iterative table-aggregation run. Use retrieved discovery sources, current table
schemas, current row samples, and current gaps to infer the question-specific
families of rows that a complete answer would need. Estimate conservative
lower-bound counts for those row families. Do not reuse stale estimates when
the sources imply a larger universe. Return only valid JSON in the shape
requested by the user."""

_COMPLETION_PROBE_SYSTEM_PROMPT = """You plan search-space breadth probes for an
iterative table-aggregation run. Use the question, declared deliverables,
current completion state, and recent search outcomes to choose cheap external
queries that reveal how large and diverse the answer space is likely to be.
Prefer probes that test a missing axis, a suspiciously small count estimate, or
a search branch that has not yet been sampled. Return only valid JSON in the
shape requested by the user."""

_COMPLETION_CRITIQUE_SYSTEM_PROMPT = """You are a skeptical completion-scope
critic for an iterative table-aggregation run. Compare the current answer
universe estimate against the declared deliverables and search-space probes.
Accept the estimate only when its expected axes and lower-bound counts are
consistent with the breadth and diversity of retrieved search results. Return
only valid JSON in the shape requested by the user."""

_BEST_GUESS_SYSTEM_PROMPT = """You derive missing sidecar values for an
iterative table-aggregation run. Use only the provided row state and local
evidence. Return null when the evidence does not support a value. Keep hard
reported fields separate from inferred sidecar values. Return only valid JSON
in the shape requested by the user."""


def _coerce_query_list(parsed: Any, limit: int) -> List[str]:
    """Pull a clean list of query strings out of assorted JSON shapes."""
    if limit <= 0:
        return []
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


def _coerce_probe_list(parsed: Any, limit: int) -> List[Dict[str, Any]]:
    """Pull clean completion-probe records out of assorted JSON shapes."""
    if limit <= 0:
        return []
    if isinstance(parsed, dict):
        parsed = parsed.get("probes") or parsed.get("queries") or []

    probes: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in parsed or []:
        if isinstance(item, str):
            item = {"query": item}
        if not isinstance(item, Mapping):
            continue

        query = str(item.get("query") or "").strip()
        key = query.lower()
        if len(query) < 4 or key in seen:
            continue
        seen.add(key)

        axis_bindings = item.get("axis_bindings")
        probes.append(
            {
                "query": query,
                "purpose": str(item.get("purpose") or "").strip(),
                "axis_bindings": (
                    dict(axis_bindings)
                    if isinstance(axis_bindings, Mapping)
                    else {}
                ),
                "rationale": str(item.get("rationale") or "").strip(),
            }
        )
        if len(probes) >= limit:
            break
    return probes


async def initial_queries(
    llm,
    question: str,
    *,
    n: int = 6,
    schema_hint: str = "",
) -> List[str]:
    """Derive the first batch of web-search queries straight from the question."""
    prompt = f"""QUESTION:
{question}
{("DOMAIN FOCUS: " + schema_hint if schema_hint else "")}

Produce {n} diverse search queries that, run against scientific sources (PubMed,
bioRxiv, journals), would surface the evidence needed to answer the question.
Cover the core mechanism, key quantitative outcomes, and important sub-aspects.
Keep each query concise (3-9 words), no boolean operators.

Return JSON: {{"queries": ["...", "..."]}}"""
    parsed = await ask_json(llm, prompt, system_prompt=_SEARCH_SYSTEM_PROMPT)
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
    prompt = f"""QUESTION:
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
    parsed = await ask_json(llm, prompt, system_prompt=_SEARCH_SYSTEM_PROMPT)
    return _coerce_query_list(parsed, n)


async def catalog_queries(
    llm,
    question: str,
    *,
    goal_context: Dict[str, Any],
    completion_state: Dict[str, Any] | None = None,
    operator_plan: Dict[str, Any] | None = None,
    universe_estimate: Dict[str, Any] | None = None,
    search_outcomes: List[Dict[str, Any]] | None = None,
    n: int = 4,
) -> List[str]:
    """Generate broad searches that estimate the answer universe."""
    if n <= 0:
        return []
    prompt = f"""QUESTION:
{question}

CURRENT COVERAGE STATE JSON:
{json.dumps(goal_context, indent=2, default=str)[:3500]}

CURRENT ANSWER-UNIVERSE ESTIMATE JSON:
{json.dumps(universe_estimate or {}, indent=2, default=str)[:2500]}

COMPLETION SCOPE STATE JSON:
{json.dumps(completion_state or {}, indent=2, default=str)[:2500]}

SELECTED SEARCH OPERATOR JSON:
{json.dumps(operator_plan or {}, indent=2, default=str)[:1800]}

RECENT CATALOG SEARCH OUTCOMES JSON:
{json.dumps(search_outcomes or [], indent=2, default=str)[:2500]}

Produce {n} NEW broad search queries that help estimate or expand the row
families needed for the final answer. Prefer reviews, comparative papers, large
curated tables, and multi-subject or multi-context sources that can reveal
missing target categories and counts. Avoid a single known gap unless the query
would also reveal a broader list, table, review, or benchmark.

Use SELECTED SEARCH OPERATOR JSON as the concrete search move for this batch.
Honor its source_family and constraints while keeping every query grounded in
terms that could appear in external source titles, abstracts, tables,
appendices, or dataset descriptions.

Keep each query concise (3-10 words), no boolean operators.

Return JSON: {{"queries": ["...", "..."]}}"""
    parsed = await ask_json(llm, prompt, system_prompt=_SEARCH_SYSTEM_PROMPT)
    return _coerce_query_list(parsed, n)


async def completion_probe_queries(
    llm,
    question: str,
    *,
    goal_context: Dict[str, Any],
    completion_state: Dict[str, Any] | None = None,
    universe_estimate: Dict[str, Any] | None = None,
    search_outcomes: List[Dict[str, Any]] | None = None,
    n: int = 4,
) -> List[Dict[str, Any]]:
    """Generate breadth probes for sizing the answer universe."""
    if n <= 0:
        return []

    prompt = f"""QUESTION:
{question}

CURRENT COVERAGE STATE JSON:
{json.dumps(goal_context, indent=2, default=str)[:4500]}

COMPLETION SCOPE STATE JSON:
{json.dumps(completion_state or {}, indent=2, default=str)[:4500]}

CURRENT ANSWER-UNIVERSE ESTIMATE JSON:
{json.dumps(universe_estimate or {}, indent=2, default=str)[:3000]}

RECENT SEARCH OUTCOMES JSON:
{json.dumps(search_outcomes or [], indent=2, default=str)[:3000]}

Produce up to {n} cheap breadth probes that will help decide whether the
current answer-universe estimate is complete enough to drive a stop rule.

Each probe should reveal one of:
- the size or diversity of a row family needed by the declared final tables
- a missing qualifier axis that would split broad rows into more exact rows
- external terminology that may expose results missed by prior queries
- whether a currently underexplored bin is narrow, broad, or out of scope

Avoid repeating prior probe queries and recent searches unless the current
completion state says the wording was useful. Keep each query concise
(3-10 words), no boolean operators.

Return JSON:
{{
  "probes": [
    {{
      "query": "search text",
      "purpose": "what this search-space probe should clarify",
      "axis_bindings": {{"axis or table": "optional missing region"}},
      "rationale": "why this probe should sharpen the completion estimate"
    }}
  ]
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_COMPLETION_PROBE_SYSTEM_PROMPT,
    )
    return _coerce_probe_list(parsed, n)


async def target_deficit_queries(
    llm,
    question: str,
    *,
    goal_context: Dict[str, Any],
    deficits: List[Dict[str, Any]],
    n: int = 4,
    arms_per_target: int = 1,
    queries_per_arm: int = 1,
) -> List[Dict[str, Any]]:
    """Generate focused prompt-arm experiments for table-fill deficits."""
    if n <= 0 or not deficits:
        return []

    arms_per_target = max(1, arms_per_target)
    queries_per_arm = max(1, queries_per_arm)
    prompt = f"""QUESTION:
{question}

CURRENT COVERAGE STATE JSON:
{json.dumps(goal_context, indent=2, default=str)[:4500]}

UNMET FILL DEFICITS JSON:
{json.dumps(deficits, indent=2, default=str)[:6000]}

Produce up to {n} concrete focused searches organized as prompt-mutation
experiments. Each experiment attacks exactly one fill-deficit id. Each
experiment may contain up to {arms_per_target} prompt arms, and each arm may
contain up to {queries_per_arm} concrete external-search queries.

Prefer high-priority deficits, but diversify across target tables and deficit
types when several deficits have similar priority. Each query must map to one
fill-deficit id through its parent experiment.

A prompt arm is one explicit delta in how to phrase searches for the same
deficit. Mutate one thing per arm: the expected source shape, the external
terminology, the anchoring breadth, or the context qualifier emphasis. Use
previous arm contrast, accepted-source terms, matched needs, missing needs,
search-result samples, rejection reasons, failed query terms, and exhausted
operators to choose arms whose results will be informative relative to prior
arms.

Each deficit has an operator_plan selected by deterministic code. Instantiate
that operator only; do not invent a different strategy_family. Use each
deficit's strategy_history and strategy_memory to avoid stalled search
behavior. Treat accepted-source terms, matched needs, missing needs, rejection
reasons, failed query terms, and exhausted_operators as memory that must shape
the next query text.

Queries must use terms that could appear in external source titles, abstracts,
tables, appendices, or dataset descriptions. Do not repeat a previous query for
the same deficit. Do not include internal table names, column identifiers,
deficit descriptions, count strings, or workflow phrases unless they also occur
as real subject terms in known examples or accepted source context. Prefer
source queries that can fill multiple missing rows in the target table, and use
known missing examples only when they are present in the deficit.

When the selected operator asks for a context-pivot expansion, vary the
external vocabulary for the target's key columns, missing fields, or row
qualifiers. Preserve the specific qualifiers reported by source authors
instead of collapsing every row to one broad bucket.

Keep each query concise (3-10 words), no boolean operators.

Return JSON:
{{
  "experiments": [
    {{
      "target_id": "matching fill-deficit id",
      "target_name": "matching target or table name",
      "strategy_family": "exact_anchor | review_or_table | dataset_or_appendix | terminology_mutation | context_expansion",
      "arms": [
        {{
          "name": "short generic label",
          "prompt_delta": "what search-phrasing change this arm tests",
          "hypothesis": "why this arm should find non-overlapping useful evidence",
          "expected_source_shape": "kind of external source this arm should retrieve",
          "queries": [
            {{
              "query": "search text",
              "rationale": "why this can add missing rows"
            }}
          ]
        }}
      ]
    }}
  ]
}}"""
    parsed = await ask_json(llm, prompt, system_prompt=_SEARCH_SYSTEM_PROMPT)
    queries: List[Dict[str, Any]] = []
    seen = set()
    for item in _iter_target_query_items(
        parsed,
        arms_per_target=arms_per_target,
        queries_per_arm=queries_per_arm,
    ):
        query = str(item.get("query") or "").strip()
        key = query.lower()
        if len(query) < 4 or key in seen:
            continue
        seen.add(key)
        queries.append(item | {"query": query})
        if len(queries) >= n:
            break
    return queries


def _iter_target_query_items(
    parsed: Any,
    *,
    arms_per_target: int = 1,
    queries_per_arm: int = 1,
) -> Iterable[Dict[str, Any]]:
    arms_per_target = max(1, arms_per_target)
    queries_per_arm = max(1, queries_per_arm)
    if isinstance(parsed, dict) and isinstance(parsed.get("experiments"), list):
        experiments = parsed.get("experiments") or []
        arm_counts_by_target: dict[str, int] = {}
        for experiment in experiments:
            if not isinstance(experiment, Mapping):
                continue
            target_key = str(
                experiment.get("target_id")
                or experiment.get("target_name")
                or ""
            ).strip()
            if not target_key:
                target_key = "__unknown__"
            base = {
                "target_id": str(experiment.get("target_id") or "").strip(),
                "target_name": str(experiment.get("target_name") or "").strip(),
                "strategy_family": str(
                    experiment.get("strategy_family") or ""
                ).strip(),
            }
            for arm in experiment.get("arms") or []:
                arm_index = arm_counts_by_target.get(target_key, 0)
                if arm_index >= arms_per_target:
                    break
                if isinstance(arm, str):
                    arm = {"queries": [arm]}
                if not isinstance(arm, Mapping):
                    continue
                arm_counts_by_target[target_key] = arm_index + 1
                arm_base = {
                    **base,
                    "prompt_arm_name": str(arm.get("name") or "").strip(),
                    "prompt_arm_index": arm_index,
                    "prompt_delta": str(arm.get("prompt_delta") or "").strip(),
                    "prompt_hypothesis": str(arm.get("hypothesis") or "").strip(),
                    "expected_source_shape": str(
                        arm.get("expected_source_shape") or ""
                    ).strip(),
                }
                arm_queries = list(
                    arm.get("queries") or arm.get("search_queries") or []
                )[:queries_per_arm]
                for query_index, query_item in enumerate(arm_queries):
                    if isinstance(query_item, Mapping):
                        yield {
                            **arm_base,
                            "query": str(query_item.get("query") or ""),
                            "rationale": str(
                                query_item.get("rationale")
                                or arm.get("hypothesis")
                                or ""
                            ).strip(),
                            "query_index": query_index,
                        }
                    else:
                        yield {
                            **arm_base,
                            "query": str(query_item or ""),
                            "rationale": str(
                                arm.get("hypothesis") or ""
                            ).strip(),
                            "query_index": query_index,
                        }
        return

    items = parsed.get("queries") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return

    for query_index, item in enumerate(items):
        if not isinstance(item, Mapping):
            item = {"query": str(item or "")}
        yield {
            "query": str(item.get("query") or ""),
            "target_id": str(item.get("target_id") or "").strip(),
            "target_name": str(item.get("target_name") or "").strip(),
            "strategy_family": str(item.get("strategy_family") or "").strip(),
            "rationale": str(item.get("rationale") or "").strip(),
            "prompt_arm_name": str(
                item.get("prompt_arm_name")
                or item.get("strategy_family")
                or "default"
            ).strip(),
            "prompt_arm_index": _coerce_int(item.get("prompt_arm_index"), 0),
            "prompt_delta": str(item.get("prompt_delta") or "").strip(),
            "prompt_hypothesis": str(
                item.get("prompt_hypothesis")
                or item.get("rationale")
                or ""
            ).strip(),
            "expected_source_shape": str(
                item.get("expected_source_shape") or ""
            ).strip(),
            "query_index": _coerce_int(item.get("query_index"), query_index),
        }


async def assess_source_relevance(
    llm,
    question: str,
    *,
    task_state: Dict[str, Any] | None = None,
    task: Dict[str, Any],
    result: Dict[str, Any],
    text: str,
) -> Dict[str, Any]:
    """Gate a harvested source against the exact search task it would fill."""
    judgment = await judge_progress(
        llm,
        kind="source_candidate",
        question=question,
        task_state=task_state or {},
        operation={
            "phase": "source_gate",
            "search_task": task,
            "expected_use": "accepting this candidate writes it for extraction",
        },
        candidate={"search_result": result},
        evidence_text=text,
    )
    return {
        **judgment.to_dict(),
        "accept": judgment.accepted,
        "confidence": judgment.fruitfulness_score,
        "progress_judgment": judgment.to_dict(),
    }


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def infer_best_guess_candidates(
    llm,
    question: str,
    *,
    operator: str,
    tasks: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract best-guess sidecar candidates from existing local evidence."""
    prompt = f"""QUESTION:
{question}

BEST-GUESS OPERATOR:
{operator}

MISSING ROW-SLOT TASKS JSON:
{json.dumps(tasks, indent=2, default=str)[:6000]}

LOCAL EVIDENCE JSON:
{json.dumps(evidence, indent=2, default=str)[:18000]}

For each task, infer the requested sidecar value only if the local evidence
supports it. These are derived best guesses for grouping or plotting. They do
not overwrite hard reported table columns.

Rules:
- Use the task's canonical_column as the requested slot.
- Use only LOCAL EVIDENCE JSON and the row_values already attached to the task.
- Return no candidate when the provided evidence is ambiguous or irrelevant.
- Preserve the qualifier grain implied by the evidence.
- Explain the exact basis without citing outside knowledge.
- confidence should be 0.5-1.0 only when a value is supported.

Return JSON:
{{
  "candidates": [
    {{
      "task_id": "matching task id",
      "value": "inferred sidecar value or null",
      "confidence": 0.0,
      "basis": "short evidence-grounded reason",
      "source_ids": ["optional existing source ids"],
      "source_chunks": ["optional existing source chunks"]
    }}
  ]
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_BEST_GUESS_SYSTEM_PROMPT,
    )
    if isinstance(parsed, dict):
        parsed = parsed.get("candidates")
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


async def estimate_coverage_universe(
    llm,
    question: str,
    *,
    goal_context: Dict[str, Any],
    discovery_sources: List[Dict[str, Any]],
    completion_state: Dict[str, Any] | None = None,
    previous_estimate: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Estimate question-specific lower bounds from discovery source text."""
    prompt = f"""QUESTION:
{question}

CURRENT COVERAGE STATE JSON:
{json.dumps(goal_context, indent=2, default=str)[:6000]}

PREVIOUS ANSWER-UNIVERSE ESTIMATE JSON:
{json.dumps(previous_estimate or {}, indent=2, default=str)[:3000]}

COMPLETION SCOPE STATE JSON:
{json.dumps(completion_state or {}, indent=2, default=str)[:3500]}

DISCOVERY SOURCES JSON:
{json.dumps(discovery_sources, indent=2, default=str)[:24000]}

Infer the row families that define a complete tabular answer for this question.
For each row family, estimate a conservative lower bound from the discovery
sources, then map the target to the table whose name, columns, and row samples
directly represent that row family. Do not choose an adjacent table merely
because it shares some key columns.

count_targets are executable stop-rule targets. Include only row families that
the final answer tables should materialize. Prefer exact names from
CURRENT COVERAGE STATE JSON.target_table_names for target_table. Propose a new
snake_case table name ending in _table only when the question directly requires
a separate final table that is absent from the current target list. Use broad
catalog counts only to set lower bounds for final table rows; do not create
count_targets for auxiliary catalogs or search-space summaries that are not
themselves final answer rows.

Choose key_columns from fields that can count distinct rows for that family.
When the final rows vary by a qualifier that changes the meaning of a row,
retain that axis in key_columns instead of collapsing it to one broad row.
When multiple current final tables represent different required row families,
keep an executable count_target or an unestimated_count_target for each family
until retrieved discovery evidence supports a lower bound.

Use lower bounds that are explicitly defensible from searched source text. If
the sources do not support any useful lower bound yet, set status to
"insufficient_evidence" and propose broader queries in suggested_queries.
Use search-space probes to list expected_axes and underexplored_bins even when
there is not enough evidence to quantify every target family yet.

Return JSON:
{{
  "status": "estimated" | "insufficient_evidence",
  "scope_summary": "what a complete answer needs to enumerate",
  "expected_axes": [
    {{
      "name": "axis that changes the meaning or count of final rows",
      "description": "why this axis matters",
      "status": "open | resolved",
      "supporting_queries": ["queries or probes that exposed this axis"]
    }}
  ],
  "supporting_source_ids": ["source ids used for the estimate"],
  "supporting_queries": ["queries that found useful discovery sources"],
  "count_targets": [
    {{
      "name": "short row-family name",
      "description": "what should be counted",
      "target_table": "best matching current table or proposed *_table name",
      "key_columns": ["columns that uniquely identify this row family"],
      "expected_minimum_count": 12,
      "expected_maximum_count": 30,
      "basis": "why the searched sources support that count",
      "supporting_source_ids": ["source ids for this count"],
      "known_missing_examples": ["optional examples to search next"]
    }}
  ],
  "underexplored_bins": [
    {{
      "axis": "table, row family, or qualifier axis",
      "description": "what needs broader probing or counting",
      "status": "open | resolved | out_of_scope",
      "severity": "low | medium | high",
      "suggested_queries": ["specific next query"]
    }}
  ],
  "out_of_scope_count_targets": [
    {{
      "name": "target that should not be a final-row count",
      "description": "why this is auxiliary or outside the declared answer",
      "target_table": "proposed table name",
      "reason": "why it should not block the stop rule"
    }}
  ],
  "unresolved_questions": ["what still prevents a sharper estimate"],
  "suggested_queries": ["broad discovery query", "..."]
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_UNIVERSE_ESTIMATE_SYSTEM_PROMPT,
    )
    return parsed if isinstance(parsed, dict) else {}


async def critique_coverage_universe(
    llm,
    question: str,
    *,
    goal_context: Dict[str, Any],
    completion_state: Dict[str, Any],
    universe_estimate: Dict[str, Any],
) -> Dict[str, Any]:
    """Critique whether the universe estimate is complete enough to drive stop."""

    prompt = f"""QUESTION:
{question}

CURRENT COVERAGE STATE JSON:
{json.dumps(goal_context, indent=2, default=str)[:5000]}

COMPLETION SCOPE STATE JSON:
{json.dumps(completion_state, indent=2, default=str)[:6000]}

CURRENT ANSWER-UNIVERSE ESTIMATE JSON:
{json.dumps(universe_estimate, indent=2, default=str)[:5000]}

Decide whether the answer-universe estimate is consistent with the declared
tables, observed rows, and search-space probes.

Reject estimates that are too narrow, ignore an expected final-table axis, turn
an auxiliary catalog into a final-table count, or claim completeness while probe
titles and result diversity imply more row families than the estimate covers.

Return JSON:
{{
  "accepted": true,
  "issues": [
    {{
      "axis": "table, row family, or qualifier axis",
      "description": "why the estimate is not yet credible",
      "status": "open | resolved",
      "severity": "low | medium | high | critical",
      "suggested_queries": ["specific next query"]
    }}
  ],
  "underexplored_bins": [
    {{
      "axis": "table, row family, or qualifier axis",
      "description": "what must be sampled before completion is credible",
      "status": "open | resolved | out_of_scope",
      "severity": "low | medium | high",
      "suggested_queries": ["specific next query"]
    }}
  ],
  "unresolved_questions": ["what the next scoping or deficit search wave must answer"],
  "suggested_queries": ["broad or bin-specific query"],
  "rationale": "one concise explanation"
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_COMPLETION_CRITIQUE_SYSTEM_PROMPT,
    )
    return parsed if isinstance(parsed, dict) else {}


async def assess_answer(
    llm,
    question: str,
    *,
    answer: str,
    graph_summary: str,
) -> Dict[str, Any]:
    """Judge whether the current answer sufficiently answers the question."""
    prompt = f"""QUESTION:
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
    parsed = await ask_json(llm, prompt, system_prompt=_ASSESSMENT_SYSTEM_PROMPT)
    if not isinstance(parsed, dict):
        return {"sufficient": False, "confidence": 0.0, "gaps": [], "rationale": ""}
    parsed.setdefault("sufficient", False)
    parsed.setdefault("confidence", 0.0)
    parsed.setdefault("gaps", [])
    parsed.setdefault("rationale", "")
    if not isinstance(parsed["gaps"], list):
        parsed["gaps"] = [str(parsed["gaps"])]
    return parsed
