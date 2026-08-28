"""Question-driven search strategy: query generation and answer assessment.

These are the LLM agents that decide what to search for next and whether the
graph can yet answer the question. They replace the domain-hardcoded template
generator in iterative_search/ with a generic, question-aware approach.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .llm_utils import ModelTier, ask_json, register_call_site_tier
from .windowing import measured_size, window_items, window_stamps

#: 0M-strategy-arms: `gpt-5.4-mini` agreed on 0.600 of planned queries against a
#: registered 0.95 threshold, with both sensitivity controls discriminating
#: cleanly (weak 0.000, truncated 0.154) and the comparator perfectly symmetric
#: and consistent. Arm generation stays on the reasoning model.
_TARGET_DEFICIT_QUERIES_TIER = register_call_site_tier("strategy-arms", ModelTier.REASONING)

#: The acquisition composition's run-grain source (phase 4E-c). 0M never tested
#: it, and 0M's own rule for a call site it did not measure is that the site
#: stays on `REASONING`.
_STRATEGY_PROPOSER_TIER = register_call_site_tier(
    "strategy-proposer", ModelTier.REASONING
)

#: 0M-best-guess: `gpt-5.4-mini` agreed on 0.175 of candidates — the lowest of
#: any tested site. The models disagree about *whether* to guess at all, not
#: only about the value. Stays on the reasoning model.
_BEST_GUESS_TIER = register_call_site_tier("best-guess", ModelTier.REASONING)


_SEARCH_SYSTEM_PROMPT = """You are a scientific search strategist.
Generate concise web-search queries that retrieve source material needed to
answer the user's research question. Infer the domain and target categories
from the question and current run state. Return only valid JSON in the shape
requested by the user."""

_ASSESSMENT_SYSTEM_PROMPT = """You are a rigorous evidence-coverage reviewer.
Judge whether a graph-derived answer is supported by enough retrieved evidence
to answer the user's research question. Return only valid JSON in the shape
requested by the user."""

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

CURRENT BEST ANSWER FROM THE GRAPH (complete and unabridged):
{current_answer}

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


#: Serialized-character budget for ONE planner call's slice of the deficit
#: catalog. It bounds a call, not the catalog: a catalog larger than this
#: becomes more calls, never a shortened one. A single deficit that exceeds it
#: gets a window to itself, uncut.
#:
#: Sized so the recorded catalogs need one or two windows rather than a dozen
#: -- the largest is 35,694 characters over 6 deficits, largest single deficit
#: 2,875 -- while still splitting a catalog that grows past that. There is no
#: cost cliff here to tune against: the observed ceiling on this client is
#: 658,611 tokens, so this is a guard against pathological growth and a lever
#: on how much context one call reasons over, not a budget in the money sense.
_DEFICIT_WINDOW_BUDGET = 40000

async def target_deficit_queries(
    llm,
    question: str,
    *,
    goal_context: Dict[str, Any],
    deficits: List[Dict[str, Any]],
    n: int = 4,
    arms_per_target: int = 1,
    queries_per_arm: int = 1,
    seed_queries: Sequence[str] = (),
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Generate focused prompt-arm experiments for table-fill deficits.

    The catalog is split across as many calls as its measured size needs, and
    the returned queries are the union over those calls. Returns the queries
    and a window report describing the split, which the caller persists: a
    reader should be able to see three windows over sixteen deficits yielding
    N tasks without inferring any of it.

    Windows are unioned *within* the round rather than spread across rounds. A
    deficit in the second window of a three-round run would otherwise wait a
    third of the run to be planned at all, which is positional starvation with
    a longer period -- the same defect as ranking deficits and keeping a
    prefix, which is what this replaced.

    ``seed_queries`` are phrasings a proposed strategy suggested (phase 4E-c
    §11). They are forwarded to **every** window call as declared prompt
    context, empty by default so every existing call renders a byte-identical
    prompt. They are context and nothing else: no predicate reads them, and what
    reaches a predicate is ``control.stable_id`` over the normalized seed set,
    which is content-addressing rather than text-steering. They are a declared
    parameter with a declared render site rather than something smuggled through
    ``goal_context``, and they are shared across every arm of the call, so they
    cannot differentially bias one sibling against another and the contrast
    between siblings stays meaningful.

    **They must reach a prompt if they are hashed into a key.** If a caller
    hashes seeds into a strategy's content key while they reach no prompt, the
    untried test discriminates on content the run never used, two proposals
    differing only in seeds instantiate byte-identical arms, and the proposer's
    novelty is fictional.
    """

    seeds = [str(seed).strip() for seed in seed_queries if str(seed).strip()]
    if n <= 0 or not deficits:
        return [], {
            "window_count": 0,
            "deficit_count": 0,
            "windows": [],
            "union_size": 0,
            "goal_context_chars": measured_size(goal_context),
            "goal_context_windowed": False,
            "seed_query_count": len(seeds),
            "seed_query_chars": measured_size(seeds),
        }

    arms_per_target = max(1, arms_per_target)
    queries_per_arm = max(1, queries_per_arm)

    windows = window_items(deficits, budget=_DEFICIT_WINDOW_BUDGET)
    queries: List[Dict[str, Any]] = []
    seen: set[str] = set()
    window_records: List[Dict[str, Any]] = []

    for index, window in enumerate(windows):
        planned = await _plan_deficit_window(
            llm,
            question,
            goal_context=goal_context,
            window=window,
            stamps=window_stamps(index, len(windows)),
            n=n,
            arms_per_target=arms_per_target,
            queries_per_arm=queries_per_arm,
            seed_queries=seeds,
        )
        accepted = 0
        for item in planned:
            query = str(item.get("query") or "").strip()
            key = query.lower()
            if len(query) < 4 or key in seen:
                continue
            seen.add(key)
            queries.append(item | {"query": query})
            accepted += 1
        window_records.append(
            {
                **window_stamps(index, len(windows)),
                "deficit_count": len(window),
                "deficit_ids": [
                    str(deficit.get("id") or "")
                    for deficit in window
                    if isinstance(deficit, Mapping)
                ],
                "chars": sum(measured_size(deficit) for deficit in window),
                "planned_queries": len(planned),
                "accepted_queries": accepted,
            }
        )

    report = {
        "window_count": len(windows),
        "deficit_count": len(deficits),
        "window_budget_chars": _DEFICIT_WINDOW_BUDGET,
        "union_size": len(queries),
        # Sent whole in every window call rather than clipped. Declared so a
        # reader can see what the per-call payload actually was, and so growth
        # here is visible in emitted data instead of being absorbed silently.
        "goal_context_chars": measured_size(goal_context),
        "goal_context_windowed": False,
        # What each call carried of the proposed-seed block, so a reader can see
        # whether a proposal's seeds reached the arms it claims novelty over.
        "seed_query_count": len(seeds),
        "seed_query_chars": measured_size(seeds),
        "windows": window_records,
    }
    return queries, report


async def _plan_deficit_window(
    llm,
    question: str,
    *,
    goal_context: Dict[str, Any],
    window: List[Dict[str, Any]],
    stamps: Dict[str, int],
    n: int,
    arms_per_target: int,
    queries_per_arm: int,
    seed_queries: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """One planner call over one window of the deficit catalog.

    The deficit catalog is the windowed axis. `goal_context` is not windowed
    and is not clipped: it is a mapping whose members describe one coverage
    state, and a planner shown half of it would plan against a coverage picture
    that never existed. It is therefore treated as one oversized item and sent
    whole, which is the rule `windowing.py` already states for an item larger
    than its budget. Its measured size is reported by the caller so a reader
    can see what each call carried.

    ``seed_queries`` renders as its own declared block, before the instructions,
    and is omitted entirely when empty so an unseeded call is byte-identical to
    the pre-4E-c prompt.
    """

    seed_block = ""
    if seed_queries:
        seed_block = f"""
PROPOSED SEED QUERIES JSON (complete and unabridged):
{json.dumps(list(seed_queries), indent=2, default=str)}

These are seed phrasings proposed for this strategy. Treat them as starting
vocabulary for the arms below. Do not return any of them unchanged, and do not
treat them as a constraint on which deficit an arm attacks.
"""

    prompt = f"""QUESTION:
{question}

CURRENT COVERAGE STATE JSON (complete and unabridged):
{json.dumps(goal_context, indent=2, default=str)}

UNMET FILL DEFICITS JSON (window {stamps["window_index"] + 1} of {stamps["window_count"]}, {len(window)} deficits, complete and unabridged):
{json.dumps(window, indent=2, default=str)}
{seed_block}
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
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_SEARCH_SYSTEM_PROMPT,
        tier=_TARGET_DEFICIT_QUERIES_TIER,
    )
    # `n` bounds each window's plan. Deduplication and the run's own task
    # budget bound the union, which is the caller's business: capping here
    # would let an early window spend the whole allowance and starve a later
    # one, which is the positional defect windowing exists to remove.
    return list(
        _iter_target_query_items(
            parsed,
            arms_per_target=arms_per_target,
            queries_per_arm=queries_per_arm,
        )
    )[: max(1, n)]


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


#: The prose fields a proposer's payload may carry as CONTEXT and that no
#: predicate may read. Declared by name here so the boundary is checkable
#: rather than assumed: these are one module's model-emitted prose aggregated by
#: another (`search_memory`'s cue counters, the page gate's need lists), and the
#: charter licenses them as "the run's view ... rendered as text" while banning
#: them from any branch. The accept rule reads `(content key, distance)` and
#: nothing else, so no predicate can reach them by construction.
PROPOSER_CONTEXT_PROSE_FIELDS = (
    "avoid_cues",
    "better_search_cues",
    "matched_needs",
    "missing_needs",
    "offtopic_axes",
)


async def propose_distant_strategy(
    llm,
    question: str,
    *,
    run_view: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
    tried: Sequence[Mapping[str, Any]],
    n: int = 3,
) -> List[Dict[str, Any]]:
    """Sample candidate strategies for the acquisition run grain's switch edge.

    THE MODEL'S WHOLE JOB HERE IS STRING WORK AND ONE NUMBER. It samples
    candidate ``(operator, targets, seed phrasings)`` combinations and reports,
    per candidate, how far it judges that combination to sit from the ones
    already tried -- because semantic distance is a property of two strings.

    It does **not** decide whether to propose: that is the run grain's own
    verdict, read by the loop after every unit. It does **not** decide whether a
    candidate is distant enough: `control.select_first_clearing` compares the
    reported number against a written floor. It emits no count, no estimate and
    no verdict that a branch consumes, and the prompt names no floor, no
    threshold and no consequence of the number -- a model told what the floor is
    has been handed the rule back.

    Three returned fields reach a predicate and they are named here so the
    boundary is checkable: ``operator`` (a set-membership test against the
    injected ``catalog``, applied by the caller -- `acquisition.StrategyProposer`
    drops a non-member before selection and records it with
    ``rejection_class: operator_not_in_catalog``; a non-member is rejected,
    never renamed onto the nearest member),
    ``target_ids`` (intersected with the run's declared target ids), and
    ``distance`` (a float against a written floor). ``query_seeds`` are
    normalized and hashed into a code-minted content key and otherwise forwarded
    to the arm planner as context. ``label`` and ``rationale`` reach no
    predicate at all.

    ``catalog`` is injected rather than imported so this function assumes no
    particular operator vocabulary, and ``run_view`` is built by the caller from
    the run's own view -- finished strategy records, the declared contract, the
    criteria snapshot, the observed deficits, accepted-source terms. Nothing
    question-specific is written here.
    """

    if n <= 0 or not catalog:
        return []

    prompt = f"""QUESTION:
{question}

RUN VIEW JSON (complete and unabridged):
{json.dumps(dict(run_view), indent=2, default=str)}

STRATEGIES ALREADY OPENED IN THIS RUN JSON (complete and unabridged):
{json.dumps(list(tried), indent=2, default=str)}

AVAILABLE OPERATOR CATALOG JSON (complete and unabridged):
{json.dumps(dict(catalog), indent=2, default=str)}

Propose up to {n} further search strategies for this run. A strategy is one
operator from the catalog above, applied to one or more of the target ids the
run has declared, with a few seed phrasings that show how its searches would be
worded.

Use an `operator` value that appears as a key of the catalog. Use `target_ids`
that appear in the run view. Order your proposals by how different you judge
them to be from the strategies already opened, most different first.

For each proposal report `distance` on a 0.0-1.0 scale: how far this
combination of operator, targets and seed phrasing sits from the nearest
strategy already opened, where 0.0 is the same strategy reworded and 1.0 is a
combination sharing nothing with any of them.

Return JSON:
{{
  "proposals": [
    {{
      "operator": "one key of the catalog",
      "target_ids": ["declared target ids this strategy attacks"],
      "query_seeds": ["seed phrasing", "seed phrasing"],
      "distance": 0.0,
      "label": "short generic name",
      "rationale": "why this combination differs from the opened ones"
    }}
  ]
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_SEARCH_SYSTEM_PROMPT,
        tier=_STRATEGY_PROPOSER_TIER,
    )
    if isinstance(parsed, Mapping):
        parsed = parsed.get("proposals") or parsed.get("strategies")
    if not isinstance(parsed, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in parsed[: max(1, n)]:
        if not isinstance(item, Mapping):
            continue
        out.append(
            {
                "operator": str(item.get("operator") or "").strip(),
                "target_ids": [
                    str(value).strip()
                    for value in (item.get("target_ids") or [])
                    if str(value).strip()
                ],
                "query_seeds": [
                    str(value).strip()
                    for value in (item.get("query_seeds") or [])
                    if str(value).strip()
                ],
                "distance": item.get("distance"),
                "label": str(item.get("label") or "").strip(),
                "rationale": str(item.get("rationale") or "").strip(),
            }
        )
    return out


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
{json.dumps(tasks, indent=2, default=str)}

LOCAL EVIDENCE JSON:
{json.dumps(evidence, indent=2, default=str)}

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
        tier=_BEST_GUESS_TIER,
    )
    if isinstance(parsed, dict):
        parsed = parsed.get("candidates")
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


async def assess_answer(
    llm,
    question: str,
    *,
    answer: str,
    graph_summary: str,
) -> Dict[str, Any]:
    """Judge whether the current answer sufficiently answers the question.

    The answer is sent whole. It is not windowed and not clipped: sufficiency
    and completeness are properties of the whole answer, so a judgment made
    from a window is not a partial version of the real judgment -- it is a
    judgment of a different object. The clip this replaced showed the judge the
    first 2,500 characters of an answer measured at 8,165 characters on the
    live run, which meant "insufficient, gaps remain" was partly a report about
    the scissors.
    """
    prompt = f"""QUESTION:
{question}

CANDIDATE ANSWER (produced by graph traversal, complete and unabridged):
{answer}

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
