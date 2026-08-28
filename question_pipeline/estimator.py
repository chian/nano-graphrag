"""Breadth probes over the search space for table-fill runs.

No count is estimated here. The richness estimator that produced count targets
is deleted; what remains plans external probes and records what they returned,
so the completion scope can be judged from observations rather than from an
extrapolation over them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from .completion import result_count_bucket
from .llm_utils import ask_json
from .search import compact_search_result, normalize_query

# `estimator-evidence` is gone with the count. That call asked a model whether
# a document was "count-bearing", which was only a question because a count was
# being produced. Nothing downstream asks it now, so the call site is retired
# rather than repurposed: a provider call with no stated question is a cost
# with no claim attached to it.

# `estimator-synthesis` is gone: no model produces the numeric universe
# estimate any more. 0M measured that call site at 0.322 agreement, which was
# read as "needs a reasoning model" when it should have been read as "this is
# not a job for a model at all."


SearchFn = Callable[[str, int], list[dict[str, Any]]]


#: The system prompt carries the role framing, so it has to say the same thing
#: the user prompt says. It previously read "design external searches that
#: measure how many final-table data points exist" and told the model to reason
#: from "prior estimate state" -- the retired question, surviving in the other
#: argument to the same provider call while the user prompt asked for breadth.
#: Two contradictory instructions in one call, and the sweep missed it because
#: `system_prompt` is a separate argument that a check over the prompt body
#: never sees.
_PLANNER_SYSTEM_PROMPT = """You are a search-space breadth planner for an
iterative table-aggregation run. Your job is to design external searches that
reach parts of the search space earlier probes did not reach, so the breadth of
the space can be observed. You do not estimate how many rows or data points
exist, and no count is derived from what you return. Reason from the user's
question, declared tables, current row samples, and previous search
observations. Return only valid JSON."""

# The synthesis and critique prompts that used to live here are deleted, not
# disabled. They asked a model to emit `expected_count` bands from prose.
# Chao1 replaced them with arithmetic, and Chao1 is now deleted too: no count
# is produced here by any route, asked or computed. Families are reported as
# unestimated with a reason. There is no prompt to fall back to and no
# estimator to fall back to either.


async def estimate_count_expectations(
    llm,
    question: str,
    *,
    goal_context: Mapping[str, Any],
    completion_state: Mapping[str, Any],
    previous_estimate: Mapping[str, Any],
    search_fn: SearchFn,
    max_iterations: int,
    queries_per_iteration: int,
    results_per_query: int,
) -> dict[str, Any]:
    """Work out executable count expectations through targeted search probes."""

    max_iterations = max(1, int(max_iterations or 1))
    queries_per_iteration = max(1, int(queries_per_iteration or 1))
    results_per_query = max(1, int(results_per_query or 1))

    current_estimate = dict(previous_estimate or {})
    families: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    critique: dict[str, Any] = {}

    for iteration in range(max_iterations):
        plan = await _plan_expectation_searches(
            llm,
            question,
            goal_context=goal_context,
            completion_state=completion_state,
            previous_estimate=current_estimate,
            iteration=iteration,
            n=queries_per_iteration,
        )
        families = _coerce_families(plan) or families
        queries = _coerce_queries(plan, limit=queries_per_iteration)
        if not queries:
            break

        attempts.extend(
            _run_search_attempts(
                queries,
                search_fn=search_fn,
                results_per_query=results_per_query,
                iteration=iteration,
            )
        )

    # There is no computed estimate any more, and therefore no saturation gate
    # to stop the loop early. Chao1 produced both, and it is deleted: every
    # family it would have sized is reported as unestimated with the reason,
    # which is what "we have not measured this" should have looked like all
    # along. The loop now runs its configured waves and stops.
    current_estimate = _fallback_unestimated_estimate(
        families,
        attempts=attempts,
    )

    return {
        "estimate": current_estimate,
        "critique": critique,
        "attempts": attempts,
        "search_space_probes": search_space_probes_from_attempts(attempts),
    }


def search_space_probes_from_attempts(
    attempts: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for attempt in attempts:
        results = [
            dict(result)
            for result in attempt.get("results") or []
            if isinstance(result, Mapping)
        ]
        urls = _unique_strings(result.get("url") for result in results)
        domains = _unique_strings(_domain(url) for url in urls)
        probes.append(
            {
                "id": str(attempt.get("id") or ""),
                "artifact_label": attempt.get("artifact_label"),
                "pipeline_round": attempt.get("pipeline_round"),
                "query": str(attempt.get("query") or ""),
                "purpose": str(attempt.get("purpose") or ""),
                "axis_bindings": {
                    "family": str(attempt.get("family_name") or ""),
                    "source_shape": str(attempt.get("expected_source_shape") or ""),
                },
                "result_count": len(results),
                "unique_url_count": len(urls),
                "unique_domain_count": len(domains),
                "result_count_bucket": result_count_bucket(len(results)),
                "domains": domains[:12],
                "titles": _unique_strings(result.get("title") for result in results)[
                    :12
                ],
                "results": results[:10],
            }
        )
    return probes


async def _plan_expectation_searches(
    llm,
    question: str,
    *,
    goal_context: Mapping[str, Any],
    completion_state: Mapping[str, Any],
    previous_estimate: Mapping[str, Any],
    iteration: int,
    n: int,
) -> dict[str, Any]:
    """Plan the next wave of BREADTH probes for the completion scope.

    This call survived the Chao1 deletion and it needs its own justification,
    because its old one went with the estimator: it no longer plans searches to
    measure how many rows exist. What it plans are breadth probes whose
    RESULTS -- urls, domains, result-count buckets -- become
    `search_space_probes` and feed the completion scope. That question survives
    the count's retirement: "how broad is the space this question ranges over"
    is answerable from what a probe returns, without extrapolating a richness
    estimate from it.

    The prompt below previously instructed the model to read
    `chao1_coverage_fraction`, `accumulation_curve` and
    `sample_size_rarefaction`, and serialized the whole rarefaction dict as a
    payload. All of those are deleted. Leaving the instruction would have told
    the model to read an absent field -- which it cannot report, it just plans
    differently and nothing records that it did.
    """

    prompt = f"""QUESTION:
{question}

CURRENT COVERAGE STATE JSON:
{json_for_prompt(goal_context, budget=8000)}

COMPLETION SCOPE STATE JSON:
{json_for_prompt(completion_state, budget=6000)}

PREVIOUS EXPECTATION ESTIMATE JSON:
{json_for_prompt(previous_estimate, budget=6000)}

Plan iteration {iteration}. Name the unresolved final-row families and propose
up to {n} searches that probe how BROAD the space is for those families -- how
many distinct sources and source shapes exist to be found, not how many rows
exist. Prefer probes that would surface parts of the space earlier probes did
not reach: different terminology, different source shapes, different
subdomains of the question. Reaching a region already covered is a weaker
probe than reaching one that is not.

Do not use internal column names as query text unless they are also natural
source terminology. Do not estimate or state a count, and do not treat any
number a source reports as the size of the space.

Return JSON:
{{
  "families": [
    {{
      "name": "required final-row family",
      "target_table": "declared final table for this family",
      "key_columns": ["columns that identify distinct final rows"],
      "reason": "why this row family is still unresolved"
    }}
  ],
  "queries": [
    {{
      "family_name": "matching family name",
      "query": "concise web search text",
      "purpose": "region of the search space this query should reach",
      "expected_source_shape": "review | appendix | dashboard | repository | dataset | paper | catalog",
      "mutation": "how this query differs from prior failed searches"
    }}
  ]
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_PLANNER_SYSTEM_PROMPT,
    )
    return parsed if isinstance(parsed, dict) else {}


def _run_search_attempts(
    queries: list[Mapping[str, Any]],
    *,
    search_fn: SearchFn,
    results_per_query: int,
    iteration: int,
) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for index, item in enumerate(queries):
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        error = ""
        try:
            raw_results = search_fn(query, results_per_query)
        except Exception as exc:  # noqa: BLE001 - failed probes are estimator evidence
            raw_results = []
            error = str(exc)

        results: list[dict[str, Any]] = []
        for rank, result in enumerate(raw_results, start=1):
            if not isinstance(result, Mapping):
                continue
            compact = compact_search_result(dict(result))
            url = str(result.get("url") or compact.get("url") or "")
            compact["result_id"] = _stable_id(
                {
                    "query": normalize_query(query),
                    "rank": rank,
                    "url": url,
                }
            )
            compact["rank"] = rank
            compact["url"] = url
            compact["title"] = str(result.get("title") or compact.get("title") or "")
            results.append(compact)

        urls = _unique_strings(result.get("url") for result in results)
        domains = _unique_strings(_domain(url) for url in urls)
        attempts.append(
            {
                "id": _stable_id(
                    {
                        "iteration": iteration,
                        "index": index,
                        "query": normalize_query(query),
                    }
                ),
                "iteration": iteration,
                "query_index": index,
                "family_name": str(item.get("family_name") or "").strip(),
                "target_table": str(item.get("target_table") or "").strip(),
                "query": query,
                "purpose": str(item.get("purpose") or item.get("rationale") or ""),
                "expected_source_shape": str(
                    item.get("expected_source_shape") or ""
                ).strip(),
                "mutation": str(item.get("mutation") or "").strip(),
                "result_count": len(results),
                "unique_url_count": len(urls),
                "unique_domain_count": len(domains),
                "result_count_bucket": result_count_bucket(len(results)),
                "domains": domains[:12],
                "error": error,
                "results": results,
            }
        )
    return attempts


# --------------------------------------------------------------------------- #
# Plan and result coercion.
#
# RESTORED AFTER A DELETION OVERREACH, not re-added as new behaviour. These three
# went out as collateral when the Chao1 machinery was cut: 915 lines were removed
# and these were inside the swept ranges while their call sites -- lines 92, 93
# and 540 -- were not. Every one is Chao1-free at `a9cfd8c` and reintroduces
# nothing the deletion mandate retired: no chao1, rarefaction, richness,
# expected_count, singleton or doubleton reference appears in any of them.
#
# The file still imported cleanly with them missing, because a NameError on a
# module-level function is only raised when the line executes. Nothing caught it
# until a live `--pipeline-mode table-fill` run reached
# `_estimate_task_goal_universe` and aborted before round 0.
# --------------------------------------------------------------------------- #


def _coerce_families(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    families = plan.get("families") or plan.get("row_families") or []
    out: list[dict[str, Any]] = []
    for item in families:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or item.get("family_name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "target_table": str(item.get("target_table") or "").strip(),
                "key_columns": _unique_strings(item.get("key_columns")),
                "reason": str(item.get("reason") or item.get("description") or ""),
            }
        )
    return out


def _coerce_queries(
    plan: Mapping[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    items = plan.get("queries") or plan.get("search_queries") or []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            item = {"query": item}
        if not isinstance(item, Mapping):
            continue
        query = str(item.get("query") or "").strip()
        key = normalize_query(query)
        if len(query) < 4 or not key or key in seen:
            continue
        seen.add(key)
        out.append({**dict(item), "query": query})
        if len(out) >= limit:
            break
    return out


def _attempt_results(attempt: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        result
        for result in attempt.get("results") or []
        if isinstance(result, Mapping)
    ]


def _fallback_unestimated_estimate(
    families: list[Mapping[str, Any]],
    *,
    attempts: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if not families:
        families = [
            {
                "name": "answer_universe",
                "target_table": "",
                "key_columns": [],
                "reason": "No final-row family has been resolved yet.",
            }
        ]

    return {
        "status": "insufficient_evidence",
        "scope_summary": (
            "No count is estimated. Breadth probes run and are reported; "
            "nothing extrapolates a universe size from them."
        ),
        "search_space_summary": f"Ran {len(attempts)} breadth probe(s).",
        "expected_axes": [],
        "count_targets": [],
        "unestimated_count_targets": [
            {
                "name": str(family.get("name") or f"family_{index + 1}"),
                "description": str(family.get("reason") or ""),
                "target_table": str(family.get("target_table") or ""),
                "key_columns": _unique_strings(family.get("key_columns")),
                "reason": (
                    "No count is estimated for this family. Only the observed "
                    "census is measured, counted from exported rows; nothing "
                    "extrapolates a universe size from it."
                ),
            }
            for index, family in enumerate(families)
        ],
        # NO MANUFACTURED BINS. This used to emit one open, high-severity
        # underexplored bin for EVERY family, unconditionally, because every
        # family is unestimated -- and after the Chao1 deletion every family is
        # always unestimated. A flag raised on every subject every time
        # distinguishes nothing; it is a constant wearing a finding's shape.
        #
        # It was also load-bearing in the wrong direction:
        # `completion_scope_actionable` refuses to proceed while any bin is
        # open, so a bin emitted unconditionally here held the pre-GASL gate
        # shut on every from-scratch run. An open bin should mean a scope
        # critic looked and objected, and those still arrive via
        # `completion_update_from_critique`.
        "underexplored_bins": [],
        "unresolved_questions": [
            "Which external sources provide numeric coverage for each final-row family?"
        ],
        "suggested_queries": [],
    }


def _preserve_unestimated_families(
    estimate: Mapping[str, Any],
    families: list[Mapping[str, Any]],
) -> dict[str, Any]:
    out = dict(estimate or {})
    if not families:
        return out

    covered = set()
    for key in (
        "count_targets",
        "unestimated_count_targets",
        "out_of_scope_count_targets",
    ):
        for target in out.get(key) or []:
            if not isinstance(target, Mapping):
                continue
            name = _family_key(target.get("name") or target.get("family_name"))
            if name:
                covered.add(name)

    missing = []
    for family in families:
        if not isinstance(family, Mapping):
            continue
        name = str(family.get("name") or family.get("family_name") or "").strip()
        key = _family_key(name)
        if not name or not key or key in covered:
            continue
        covered.add(key)
        missing.append(
            {
                "name": name,
                "description": str(
                    family.get("description") or family.get("reason") or ""
                ),
                "target_table": str(family.get("target_table") or "").strip(),
                "key_columns": _unique_strings(family.get("key_columns")),
                "reason": (
                    "The estimator planned searches for this required final-row "
                    "family, but the synthesis did not produce numeric count "
                    "evidence for it."
                ),
            }
        )

    if not missing:
        return out

    out["unestimated_count_targets"] = [
        *[
            target
            for target in out.get("unestimated_count_targets") or []
            if isinstance(target, Mapping)
        ],
        *missing,
    ]
    if out.get("status") == "estimated":
        out["status"] = "insufficient_evidence"
    unresolved = _unique_strings(out.get("unresolved_questions"))
    unresolved.append(
        "Which external sources provide numeric coverage for each omitted final-row family?"
    )
    out["unresolved_questions"] = _unique_strings(unresolved)
    return out


def _unique_strings(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clean(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _family_bucket(value: Any) -> str:
    """Join key for the probe-observation namespace: attempt and probe ids.

    Those three derive their key here and nowhere else. When the grouping side
    cleaned the family name and the lookup side did not, the URL signal was
    silently `None` for every family that had actually been probed -- a miss
    that reads as "unprobed" rather than as an error, so nothing downstream
    could notice it. One derivation removes that class within this namespace.

    It is not the module's only family key: `_family_key` normalizes the same
    field differently for a different join. See its docstring.
    """

    return _clean(value) or "unspecified"


def _family_key(value: Any) -> str:
    """Join key for the estimate namespace: planned families against targets.

    Deliberately not `_family_bucket`. This one collapses whitespace runs and
    keeps spaces, and it maps an empty name to `""` rather than to a real
    bucket -- `_preserve_unestimated_families` relies on that falsiness to skip
    unnamed entries instead of collapsing them together under one key. Both
    sides of this join call this function, so it is self-consistent; the two
    keys never meet, and unifying them would change that skip behaviour for no
    gain.
    """

    return " ".join(str(value or "").lower().split())


def _domain(url: Any) -> str:
    return urlparse(str(url or "")).netloc.lower().lstrip("www.")


def _stable_id(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


SUPPORTING_SOURCE_ID_KIND_PROBE_URL = "probe_url"


def _observed_source_ids_for_family(
    attempts: list[Mapping[str, Any]] | None,
    family_name: str,
) -> list[str]:
    """The URLs this run actually retrieved while probing one family.

    This is the sample the family's breadth probes drew from, joined on
    the same key and deduplicated the same way, so the count and the support
    cited for it can never describe different evidence: when the URL signal is
    primary, ``len()`` of this list *is* ``expected_minimum_count``.

    Nothing here is synthesized. A family whose probes returned no URL yields
    no ids, and a count with no observation behind it is not one this function
    is willing to claim support for.
    """

    bucket = _family_bucket(family_name)
    urls: list[str] = []
    seen: set[str] = set()
    for attempt in attempts or []:
        if not isinstance(attempt, Mapping):
            continue
        if _family_bucket(attempt.get("family_name")) != bucket:
            continue
        for result in _attempt_results(attempt):
            url = str(result.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def _iter_lists(value: Any, path: tuple = ()) -> list[tuple[tuple, list]]:
    found: list[tuple[tuple, list]] = []
    if isinstance(value, Mapping):
        for key, inner in value.items():
            found.extend(_iter_lists(inner, path + (key,)))
    elif isinstance(value, list):
        found.append((path, value))
        for index, inner in enumerate(value):
            found.extend(_iter_lists(inner, path + (index,)))
    return found


def _at_path(root: Any, path: tuple) -> Any:
    node = root
    for step in path:
        node = node[step]
    return node


def _rendered_payload(
    reduced: Any,
    dropped: Mapping[str, int],
    *,
    budget_note: Mapping[str, Any] | None = None,
) -> str:
    """Serialize a reduced payload with its disclosure attached, if any.

    A dict root carries `_reduction` as one more key. Any other root -- a list
    of records is the common case -- is wrapped as `{"items": ..., "_reduction":
    ...}`, because there is nowhere else to put the disclosure.

    Wrapping is preferred to appending a sentinel element to the list. These
    lists are arrays of homogeneous records, and one call site asks a model to
    return exactly one judgment per element; a meta-object sitting among the
    records invites a judgment about a record that does not exist. The wrapper
    keeps every real element homogeneous and puts the disclosure beside them,
    not among them.
    """

    disclosure: dict[str, Any] = {}
    if dropped:
        disclosure = {
            "note": (
                "Lists were shortened to fit the prompt budget. Counts "
                "below are elements omitted per path. No value was cut "
                "mid-structure."
            ),
            "omitted_elements_by_path": dict(dropped),
        }
    if budget_note:
        disclosure = {**disclosure, **budget_note}
    if not disclosure:
        return json.dumps(reduced, indent=2, default=str)
    if isinstance(reduced, dict):
        return json.dumps(
            {**reduced, "_reduction": disclosure},
            indent=2,
            default=str,
        )
    return json.dumps(
        {"items": reduced, "_reduction": disclosure},
        indent=2,
        default=str,
    )


def json_for_prompt(value: Any, *, budget: int) -> str:
    """Serialize within ``budget`` characters without ever cutting mid-structure.

    Returns valid JSON. When reduction was necessary the payload carries a
    ``_reduction`` key naming every path that lost elements and how many, so
    the omission is visible to the model and in the recorded prompt.

    That promise used to hold only for dict roots. A list root had its elements
    deleted and no disclosure attached at all -- so the largest call site here,
    which hands a model a list of search attempts, silently dropped half of
    them and returned a judgment nothing downstream could tell apart from one
    made on the whole input. The disclosure is the entire point of preferring
    structural reduction to a character slice, and it now covers every root.

    The loop measures the payload it will actually emit, disclosure included,
    rather than reserving a guessed number of characters for it.
    """

    text = json.dumps(value, indent=2, default=str)
    if len(text) <= budget:
        return text

    reduced = json.loads(json.dumps(value, default=str))
    dropped: dict[str, int] = {}

    def render() -> str:
        # `budget_met` rides along with the omission note rather than being
        # attached afterwards, so the string measured against the budget is
        # byte-for-byte the string returned. It is stated positively on
        # success because a missing flag cannot distinguish "fitted" from
        # "written before anything recorded whether it fitted".
        return _rendered_payload(
            reduced,
            dropped,
            budget_note={"budget_met": True, "budget": budget} if dropped else None,
        )

    for _ in range(200):
        text = render()
        if len(text) <= budget:
            return text
        lists = [(p, l) for p, l in _iter_lists(reduced) if len(l) > 1]
        if not lists:
            break
        path, longest = max(lists, key=lambda item: len(item[1]))
        keep = max(1, len(longest) // 2)
        label = ".".join(str(step) for step in path) or "(root)"
        dropped[label] = dropped.get(label, 0) + (len(longest) - keep)
        del _at_path(reduced, path)[keep:]

    text = render()
    if len(text) <= budget:
        return text

    # The irreducible structure -- scalar measurements plus one element per
    # list -- is itself larger than the budget. Overshooting is the right trade
    # against dropping measured values or emitting a fragment, but it is
    # declared rather than left for the reader to discover.
    return _rendered_payload(
        reduced,
        dropped,
        budget_note={
            "budget_met": False,
            "budget": budget,
            "actual_chars": len(text),
            "note_budget": (
                "Every list is already at one element; what remains is scalar "
                "measurement that cannot be dropped without losing data. "
                "actual_chars is the payload size before this note was added."
            ),
        },
    )
