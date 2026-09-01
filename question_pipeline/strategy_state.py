"""Stateful generic operators for iterative table-fill search."""

from __future__ import annotations
from collections import Counter
from typing import Any, Mapping, Sequence

from .search_memory import PathOutcome


QUERY_OPERATORS: dict[str, dict[str, Any]] = {
    "catalog_broad_review": {
        "phase": "catalog",
        "source_family": "review table",
        "max_attempts": 3,
        "description": (
            "Find broad sources that enumerate the answer universe or expose "
            "large row families."
        ),
        "constraints": [
            "Prefer review, comparison, benchmark, table, and database wording.",
            "Avoid one narrow anchor unless it can reveal a broader row family.",
        ],
    },
    "catalog_source_shift": {
        "phase": "catalog",
        "source_family": "dataset appendix",
        "max_attempts": 2,
        "description": (
            "Switch discovery away from broad review wording toward other "
            "published source shapes."
        ),
        "constraints": [
            "Try appendix, supplement, dataset, registry, benchmark, or table wording.",
            "Avoid repeating source-title terms that only produced duplicates.",
        ],
    },
    "catalog_terminology_swap": {
        "phase": "catalog",
        "source_family": "terminology_probe",
        "max_attempts": 2,
        "description": (
            "Change the external vocabulary used to find universe-estimating "
            "sources."
        ),
        "constraints": [
            "Use synonyms or neighboring source terminology from accepted sources.",
            "Keep the query broad enough to surface multi-row sources.",
        ],
    },
    "target_batch_family": {
        "phase": "target",
        "source_family": "review table",
        "max_attempts": 3,
        "description": (
            "Find a source likely to fill many sibling rows in the same target "
            "family."
        ),
        "constraints": [
            "Prefer table, review, comparison, supplement, or database wording.",
            "Do not overfit to a single partial row when the deficit is a count shortfall.",
        ],
    },
    "target_exact_anchor": {
        "phase": "target",
        "source_family": "primary_specific",
        "max_attempts": 2,
        "anchor_limit": 3,
        "description": "Use concrete anchors from one partial row to fill its missing fields.",
        "constraints": [
            "Use the strongest external subject/context anchors.",
            "Keep internal column names and workflow phrases out of the query.",
        ],
    },
    "target_anchor_drop": {
        "phase": "target",
        "source_family": "broadened_anchor",
        "max_attempts": 2,
        "anchor_limit": 1,
        "description": (
            "Broaden an over-specific target search by dropping most row anchors."
        ),
        "constraints": [
            "Use at most one row anchor.",
            "Prefer a broader source-family term over a long exact row description.",
        ],
    },
    "target_terminology_swap": {
        "phase": "target",
        "source_family": "terminology_probe",
        "max_attempts": 2,
        "description": (
            "Search the same missing piece with terms learned from failed and "
            "successful attempts."
        ),
        "constraints": [
            "Avoid repeating failed query terms when a substitute is available.",
            "Use terms learned from accepted evidence and prior query outcomes.",
        ],
    },
    "target_source_shift": {
        "phase": "target",
        "source_family": "dataset appendix",
        "max_attempts": 2,
        "description": (
            "Keep the same missing piece but change the expected source shape."
        ),
        "constraints": [
            "Try supplement, appendix, dataset, table, benchmark, or report wording.",
            "Avoid source neighborhoods that only produced duplicates.",
        ],
    },
    "target_context_pivot": {
        "phase": "target",
        "source_family": "stratified table",
        "max_attempts": 2,
        "description": (
            "Search the same row family using alternate source terms for "
            "the target's row qualifiers and key columns."
        ),
        "query_terms": [
            "stratified",
            "table",
        ],
        "constraints": [
            "Vary terms for the row qualifiers instead of assuming one wording.",
            "Prefer sources that split estimates by the target key columns.",
        ],
    },
}

_CATALOG_DEFAULT_ORDER = (
    "catalog_broad_review",
    "catalog_source_shift",
    "catalog_terminology_swap",
)
_CATALOG_PRODUCTIVE_FAILURES = (
    "useful_catalog_delta",
    "useful_table_delta",
)
_TARGET_PRODUCTIVE_FAILURES = ("useful_table_delta",)
_TARGET_COUNT_ORDER = (
    "target_batch_family",
    "target_source_shift",
    "target_terminology_swap",
    "target_anchor_drop",
    "target_exact_anchor",
)
_TARGET_ROW_ORDER = (
    "target_exact_anchor",
    "target_anchor_drop",
    "target_terminology_swap",
    "target_source_shift",
    "target_batch_family",
)
_CONTEXT_RECOVERY_FAILURES = {
    "accepted_no_graph_delta",
    "all_duplicates",
    "graph_delta_no_table_delta",
    "no_accepted_source",
    "no_hits",
    "source_unusable",
}
_FAILURE_ROUTES = {
    "useful_table_delta": (
        "same",
        "target_batch_family",
        "target_exact_anchor",
        "target_source_shift",
    ),
    "accepted_no_graph_delta": (
        "target_source_shift",
        "target_terminology_swap",
        "target_anchor_drop",
    ),
    "graph_delta_no_table_delta": (
        "target_batch_family",
        "target_anchor_drop",
        "target_source_shift",
    ),
    "all_duplicates": (
        "target_source_shift",
        "target_terminology_swap",
        "target_batch_family",
    ),
    "source_unusable": (
        "target_source_shift",
        "target_terminology_swap",
        "target_anchor_drop",
    ),
    "no_hits": (
        "target_anchor_drop",
        "target_terminology_swap",
        "target_batch_family",
    ),
    "search_error": (
        "same",
        "target_terminology_swap",
        "target_source_shift",
    ),
    "no_accepted_source": (
        "target_terminology_swap",
        "target_source_shift",
        "target_anchor_drop",
    ),
}
_CATALOG_FAILURE_ROUTES = {
    "useful_catalog_delta": ("same", "catalog_source_shift", "catalog_terminology_swap"),
    "useful_table_delta": ("same", "catalog_source_shift", "catalog_terminology_swap"),
    "accepted_no_catalog_delta": ("catalog_source_shift", "catalog_terminology_swap"),
    "accepted_no_graph_delta": (
        "catalog_source_shift",
        "catalog_terminology_swap",
    ),
    "graph_delta_no_table_delta": (
        "catalog_source_shift",
        "catalog_terminology_swap",
    ),
    "all_duplicates": ("catalog_source_shift", "catalog_terminology_swap"),
    "no_hits": ("catalog_terminology_swap", "catalog_source_shift"),
    "source_unusable": ("catalog_source_shift", "catalog_terminology_swap"),
    "search_error": ("same", "catalog_terminology_swap"),
    "no_accepted_source": ("catalog_terminology_swap", "catalog_source_shift"),
}


#: Which operators a path outcome argues for next, per
#: ``docs/TABLE_FILL_PATH_SELECTION.md`` §4.  Each outcome names a *different*
#: deficiency -- the source family was wrong, the terminology was too indirect,
#: the subject anchor was too broad, or the evidence arrived and its provenance
#: did not -- and that is the whole reason the five are worth distinguishing.
#:
#: **Nothing branches on this in phase 2C.**  Path outcomes are recorded, not
#: routed; routing them into the operator plan is a later phase's decision and
#: needs its own experiment.  The mapping lives here, beside the operators it
#: names, so that phase inherits a typed table rather than re-deriving one from
#: the prose of a document.  Every value is a key of :data:`QUERY_OPERATORS`.
PATH_OUTCOME_NEXT_OPERATORS: Mapping[PathOutcome, tuple[str, ...]] = {
    # Nothing in the graph cites the source: look in other source families.
    PathOutcome.NO_GRAPH_EVIDENCE: (
        "target_source_shift",
        "target_batch_family",
    ),
    # The graph has it and no route carried it: ask more directly.
    PathOutcome.ROUTES_ALL_LOW_SCORE: (
        "target_terminology_swap",
        "target_source_shift",
    ),
    # Routes arrived and the field stayed empty: narrow the subject anchor.
    PathOutcome.NO_CANDIDATE_EVIDENCE: (
        "target_exact_anchor",
        "target_context_pivot",
    ),
    # A value is there and nothing became supported: the gap is provenance or
    # normalisation, so keep the source context rather than searching wider.
    PathOutcome.CANDIDATE_WITHOUT_TRANSITION: (
        "target_context_pivot",
        "target_exact_anchor",
    ),
    # It worked.  Keep doing it.
    PathOutcome.SUPPORT_GAINED_ATTRIBUTED: (
        "target_batch_family",
        "target_exact_anchor",
    ),
}


def next_operators_for_path_outcome(outcome: PathOutcome) -> tuple[str, ...]:
    """The operators a recorded path outcome argues for, as identifiers.

    A lookup, not a decision: it selects nothing and changes no plan.  See
    :data:`PATH_OUTCOME_NEXT_OPERATORS`.
    """

    return PATH_OUTCOME_NEXT_OPERATORS[PathOutcome(outcome)]


# ---------------------------------------------------------------------------
# Phase 3B -- routing the next mutation family from nested arm contrast
# ---------------------------------------------------------------------------
#
# `plan_target_operator` above routes on `classify_attempt_failure`, which
# reads post-Episode row/best-guess *counts* -- operational volume.  The
# functions below route the same decision (which named family the next
# evolution step should instantiate) from real per-arm semantic yield
# instead: `search_memory._finalize_prompt_arm`'s `arm_contrast`, itself
# joined by ID from 3A's `reward.score_criterion_yield`.  Everything here is a
# pure function over that typed contrast -- no query string is assumed to
# exist, and nothing is inferred from prose.  Surface-agnostic by
# construction: the same shape (named arms, a score, a duplicate/cost
# breakdown, an outcome class) would serve a catalog probe or a schema-
# synthesis arm exactly as it serves search.


#: Version of the **routing** exhaustion rule.
#:
#: ``arm_routing_v1`` keyed "was this family productive?" on
#: :data:`_TARGET_PRODUCTIVE_FAILURES`, i.e. on
#: ``classify_attempt_failure``'s ``useful_table_delta`` -- which fires on
#: ``post_episode_table_row_hits``, ``post_episode_best_guess_hits``, or
#: ``post_episode_observed_delta``.  All three are operational volume; none is
#: a credited criterion transition.  The consequence was that a family which
#: credited real criteria but materialized no rows was classed
#: non-productive, counted toward exhaustion, and routed away from, while a
#: family that materialized rows and credited nothing was kept alive and
#: exploited -- volume deciding the deliverable's own exploitation decision
#: through a path other than the criteria transition.
#:
#: ``arm_routing_v2`` keys it on credited yield instead
#: (:func:`_credited_yield_productive`).  ``classify_attempt_failure`` is
#: deliberately **not** changed: it is baseline behaviour used elsewhere, and
#: ``useful_table_delta`` remains exactly what it was for diagnostics.  Only
#: what *routing* treats as productive moved.
ARM_ROUTING_RULE_VERSION = "arm_routing_v2"


def _credited_yield_productive(attempt: Mapping[str, Any]) -> bool:
    """Whether an attempt was productive **for routing purposes**.

    Real semantic yield only: did this attempt's sources credit a criterion
    transition, per 3A's ``reward.score_criterion_yield`` joined back by ID
    (``post_episode_credited_criterion_ids``).  Rows materialized, best-guess
    hits, and observed-count deltas are operational volume and are ignored
    here however large they are.

    ``None`` -- yield not yet measured -- is **not** productivity.  An
    unmeasured attempt cannot be evidence that a family is working, so it
    does not keep that family alive past its attempt budget.  This resolves
    conservatively toward abandoning a family rather than pinning routing to
    one whose value is unknown.
    """

    credited = attempt.get("post_episode_credited_criterion_ids")
    if credited is None:
        return False
    return len(credited) > 0


def route_next_family(
    target: Mapping[str, Any],
    *,
    catalog: Mapping[str, Mapping[str, Any]] = QUERY_OPERATORS,
) -> dict[str, Any]:
    """Choose the next mutation family for one target deficit.

    ``target`` is an enriched deficit carrying ``strategy_memory`` (compact
    per-target memory records, each with ``attempts`` -- finalized strategy
    attempts, each carrying ``arm_contrast`` and ``strategy_operator``; see
    ``search_memory._finalize_strategy_attempt``).

    Returns the same shape :func:`plan_target_operator` does (``operator``,
    ``phase``, ``source_family``, ``description``, ``constraints``, attempt
    bookkeeping) plus ``routing_reason`` and the
    ``arm_contrast`` the decision was read from, so a reader can verify the
    decision without re-deriving it.
    """
    attempts = _target_attempts(target)
    # The default order is a *preference over the catalog*, not a source of
    # operator names. Its built-in entries are the shipped QUERY_OPERATORS
    # keys, so an injected catalog (another surface's operators) shares none
    # of them; filtering here is what stops the injection being discarded at
    # every later step that consults the order. With the default catalog this
    # is an identity -- every built-in order entry is a QUERY_OPERATORS key.
    default_order = tuple(
        name for name in _default_target_order(target) if name in catalog
    ) or tuple(catalog)
    latest_attempt = _latest_strategy_attempt(target)
    contrast = list((latest_attempt or {}).get("arm_contrast") or [])
    previous_operator = str((latest_attempt or {}).get("strategy_operator") or "")

    chosen, reason = _route_from_contrast(
        contrast,
        default_order,
        previous_operator=previous_operator,
        catalog=catalog,
    )

    if chosen not in catalog or _operator_exhausted(
        chosen,
        attempts,
        productive_failures=_TARGET_PRODUCTIVE_FAILURES,
        catalog=catalog,
        productive_predicate=_credited_yield_productive,
    ):
        chosen = (
            _first_available(
                default_order,
                attempts,
                productive_failures=_TARGET_PRODUCTIVE_FAILURES,
                catalog=catalog,
                productive_predicate=_credited_yield_productive,
            )
            or chosen
        )

    plan = _operator_plan(
        chosen,
        attempts,
        reason,
        phase="target",
        operators=default_order,
        productive_failures=_TARGET_PRODUCTIVE_FAILURES,
        context_tags=_target_context_tags(target),
        catalog=catalog,
        productive_predicate=_credited_yield_productive,
    )
    plan["arm_routing_rule_version"] = ARM_ROUTING_RULE_VERSION
    plan["routing_reason"] = reason
    plan["arm_contrast"] = contrast
    return plan


def _route_from_contrast(
    contrast: Sequence[Mapping[str, Any]],
    default_order: tuple[str, ...],
    *,
    previous_operator: str,
    catalog: Mapping[str, Mapping[str, Any]] = QUERY_OPERATORS,
) -> tuple[str, str]:
    """The deterministic decision made from nested arm contrast.

    Reads the nested per-arm rows directly -- never an aggregate over them.
    Each branch below corresponds to one of the pseudo-gradient's named
    classes (`search_memory._prompt_arm_outcome`): a real winner is exploited
    by repeating its family; duplicate-dominant contrast routes away from the
    family that produced it; sources found but nothing
    supported routes to a narrower, provenance-preserving family rather than
    a broader one; unmeasured contrast (mid-round, yield not landed yet)
    holds the current family rather than switching blind.
    """

    if not contrast:
        return (
            default_order[0] if default_order else "target_batch_family"
        ), "new_target"

    best = contrast[0]
    outcomes: Counter = Counter(str(row.get("outcome") or "") for row in contrast)
    n = len(contrast)

    if best.get("score") is not None and _as_int(best.get("credited_criterion_count")) > 0:
        family = (
            previous_operator
            if previous_operator in catalog
            else (default_order[0] if default_order else "target_batch_family")
        )
        return family, "credited_yield"

    if outcomes.get("sibling_duplicate", 0) + outcomes.get("all_duplicates", 0) > n / 2:
        return (
            _named_family("target_source_shift", default_order, catalog),
            "duplicate_dominant",
        )

    if outcomes.get("no_hits", 0) > n / 2:
        return (
            _named_family("target_anchor_drop", default_order, catalog),
            "no_hits_dominant",
        )

    if outcomes.get("accepted_no_yield", 0) > 0:
        return (
            _named_family("target_context_pivot", default_order, catalog),
            "accepted_no_yield",
        )

    if previous_operator in catalog:
        return previous_operator, "pending_yield"
    return (default_order[0] if default_order else "target_batch_family"), "pending_yield"


def _named_family(
    named: str,
    order: tuple[str, ...],
    catalog: Mapping[str, Mapping[str, Any]],
) -> str:
    """The family this contrast class actually argues for.

    **This is the routing decision.**  Each branch of
    :func:`_route_from_contrast` names one destination -- broaden the source
    shape when siblings duplicated, drop anchors when nothing was found, pivot
    context when sources
    landed but supported nothing -- and that named family is what gets
    returned whenever the catalog has it.

    The predecessor of this function took the named family as a *last-resort*
    third argument, after a loop over ``order`` that always returned early on
    any non-degenerate order.  The named family was therefore unreachable and
    all contrast classes collapsed onto one operator, which made contrast
    condition ``routing_reason`` and nothing else.  Found by review after the
    run; see ``experiments/log/3B.md`` -- Route 1's original result is void.

    Falling back to ``order`` happens only when the named family is not in the
    catalog at all.  The *exhausted* case is handled by
    :func:`route_next_family`'s own guard, which runs after this returns and
    re-selects from ``order`` when the named family has spent its attempts --
    so a family that keeps failing is still abandoned, without this function
    having to know about attempt history.

    Reads only closed-vocabulary operator identifiers.  No LLM prose --
    ``expected_source_shape``, ``prompt_delta``, ``prompt_hypothesis`` -- ever
    reaches a routing predicate.
    """

    if named in catalog:
        return named
    for name in order:
        if name in catalog:
            return name
    return named


def _latest_strategy_attempt(target: Mapping[str, Any]) -> Mapping[str, Any] | None:
    attempts: list[Mapping[str, Any]] = []
    for record in target.get("strategy_memory") or []:
        if not isinstance(record, Mapping):
            continue
        for attempt in record.get("attempts") or []:
            if isinstance(attempt, Mapping) and attempt.get("prompt_arms"):
                attempts.append(attempt)
    if not attempts:
        return None
    # ``sequence`` is the memory build's own arrival order; ``evolution_index``
    # is monotone per target. Between them the newest attempt is identified
    # without any global round number, and the enumerate index keeps the max
    # stable when both are absent on legacy records.
    return max(
        enumerate(attempts),
        key=lambda item: (
            _as_int(item[1].get("sequence")),
            _as_int(item[1].get("evolution_index")),
            item[0],
        ),
    )[1]


def plan_catalog_operator(outcomes: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Choose the next catalog-search operator from prior catalog outcomes."""
    attempts = _catalog_attempts_from_outcomes(outcomes)
    latest = attempts[-1] if attempts else {}
    failure = classify_attempt_failure(latest) if latest else "new_target"
    order = _catalog_order(failure, latest)
    operator = _first_available(
        order,
        attempts,
        productive_failures=_CATALOG_PRODUCTIVE_FAILURES,
    )
    return _operator_plan(
        operator,
        attempts,
        failure,
        phase="catalog",
        operators=_CATALOG_DEFAULT_ORDER,
        productive_failures=_CATALOG_PRODUCTIVE_FAILURES,
    )


def plan_target_operator(target: Mapping[str, Any]) -> dict[str, Any]:
    """Choose the next concrete search operator for one fill deficit."""
    attempts = _target_attempts(target)
    latest = attempts[-1] if attempts else {}
    failure = classify_attempt_failure(latest) if latest else "new_target"
    order = _target_order(target, failure, latest)
    default_order = _default_target_order(target)
    operator = _first_available(
        order,
        attempts,
        productive_failures=_TARGET_PRODUCTIVE_FAILURES,
    )
    context_tags = _target_context_tags(target)
    return _operator_plan(
        operator,
        attempts,
        failure,
        phase="target",
        operators=default_order,
        productive_failures=_TARGET_PRODUCTIVE_FAILURES,
        context_tags=context_tags,
    )


def fallback_query_for_operator(target: Mapping[str, Any]) -> str:
    """Build a deterministic generic fallback query for the selected operator."""
    plan = _mapping(target.get("operator_plan"))
    operator = str(plan.get("operator") or "target_batch_family")
    spec = QUERY_OPERATORS.get(operator, QUERY_OPERATORS["target_batch_family"])
    source_terms = [
        *str(spec.get("source_family") or "").replace("_", " ").split(),
        *[
            _search_text(term)
            for term in spec.get("query_terms") or []
            if _search_text(term)
        ],
    ]

    examples = [
        _search_text(example)
        for example in list(target.get("known_missing_examples") or [])[:3]
        if _search_text(example)
    ]
    anchor_limit = int(spec.get("anchor_limit") or 0)
    anchors = [
        _search_text(value)
        for value in _mapping(target.get("anchor_values")).values()
        if _search_text(value)
    ][:anchor_limit]
    memory_terms = _memory_terms(target)
    field_terms = _field_terms(target, limit=4)

    cold_start = str(target.get("deficit_type") or "") == "schema_cold_start"
    candidates = [
        # A cold-start anchor identifies whose rows to acquire; it does not say
        # which missing value the source must carry.  Keep one declared field
        # beside the anchor so `Haiti` becomes `Haiti GDP per capita ...`
        # rather than a broad search for the key alone.  Other deficit types
        # retain their established fallback shape.
        [
            *anchors,
            *(field_terms[:1] if cold_start else []),
            *examples[:1],
            *source_terms[:2],
            *memory_terms[:2],
        ],
        [*examples[:2], *source_terms[:3], *memory_terms[:3]],
        [*memory_terms[:4], *source_terms[:2]],
        [*anchors, *memory_terms[:3], *source_terms[:2]],
        # Field-name candidates come last so a deficit that already had
        # anchors, examples or memory keeps producing exactly the query it
        # produced before. They are reached only by a deficit whose entire
        # payload is the list of empty columns -- which previously fell off
        # the end of this loop and returned "".
        [*field_terms[:1], *source_terms[:3]],
        [*field_terms[:3], *source_terms[:2]],
    ]
    attempted = {
        str(attempt.get("query") or "").strip().lower()
        for attempt in target.get("strategy_history") or []
        if isinstance(attempt, Mapping)
    }
    for parts in candidates:
        if not any(
            part in parts
            for part in (*anchors, *examples, *memory_terms, *field_terms)
        ):
            continue
        query = _dedupe_words(parts)
        if query and query.lower() not in attempted:
            return query
    return ""


def classify_attempt_failure(attempt: Mapping[str, Any]) -> str:
    """Classify one attempt using search yield and post-Episode table delta."""
    if not attempt:
        return "new_target"
    if (
        _as_int(attempt.get("post_episode_table_row_hits")) > 0
        or _as_int(attempt.get("post_episode_best_guess_hits")) > 0
    ):
        return "useful_table_delta"
    table_delta = _as_int(attempt.get("post_episode_observed_delta"))
    if table_delta > 0:
        return "useful_table_delta"

    if str(attempt.get("error") or "").strip():
        return "search_error"

    accepted = _as_int(attempt.get("accepted_source_count"))
    catalog_delta = attempt.get("post_catalog_progress_delta")
    if catalog_delta is not None:
        if _as_int(catalog_delta) > 0:
            return "useful_catalog_delta"
        if accepted > 0:
            return "accepted_no_catalog_delta"

    if accepted > 0:
        graph_delta = _as_int(attempt.get("post_episode_graph_node_delta"))
        graph_delta += _as_int(attempt.get("post_episode_graph_edge_delta"))
        if graph_delta <= 0:
            return "accepted_no_graph_delta"
        return "graph_delta_no_table_delta"

    firecrawl_hits = _as_int(attempt.get("firecrawl_hits"))
    if firecrawl_hits <= 0:
        return "no_hits"

    skipped = _mapping(attempt.get("skipped_by_reason"))
    duplicate_count = _as_int(attempt.get("duplicate_url_count")) + _as_int(
        skipped.get("duplicate_url")
    )
    if duplicate_count >= firecrawl_hits:
        return "all_duplicates"
    if any(
        _as_int(skipped.get(reason)) > 0
        for reason in (
            "blocked_page",
            "blocked_scrape",
            "scrape_failed",
            "too_large",
            "too_short",
        )
    ):
        return "source_unusable"
    return "no_accepted_source"


def _catalog_order(failure: str, latest: Mapping[str, Any]) -> tuple[str, ...]:
    routed = _CATALOG_FAILURE_ROUTES.get(failure, ())
    previous = str(latest.get("strategy_operator") or "")
    return _expand_same(routed, previous) + _CATALOG_DEFAULT_ORDER


def _target_order(
    target: Mapping[str, Any],
    failure: str,
    latest: Mapping[str, Any],
) -> tuple[str, ...]:
    routed = _FAILURE_ROUTES.get(failure, ())
    previous = str(
        latest.get("strategy_operator")
        or latest.get("strategy_family")
        or ""
    )
    if failure in _CONTEXT_RECOVERY_FAILURES:
        routed = (*_target_context_order(target), *routed)
    return _dedupe_order(_expand_same(routed, previous) + _default_target_order(target))


def _default_target_order(target: Mapping[str, Any]) -> tuple[str, ...]:
    context_order = _target_context_order(target)
    if str(target.get("deficit_type") or "") in {
        "count_shortfall",
        "table_gap_saturation",
    }:
        return _dedupe_order(
            (_TARGET_COUNT_ORDER[0], *context_order, *_TARGET_COUNT_ORDER[1:]),
        )
    return _dedupe_order(
        (*_TARGET_ROW_ORDER[:2], *context_order, *_TARGET_ROW_ORDER[2:]),
    )


def _expand_same(order: tuple[str, ...], previous: str) -> tuple[str, ...]:
    if not previous:
        return tuple(value for value in order if value != "same")
    return tuple(previous if value == "same" else value for value in order)


def _first_available(
    order: tuple[str, ...],
    attempts: list[dict[str, Any]],
    *,
    productive_failures: tuple[str, ...],
    catalog: Mapping[str, Mapping[str, Any]] = QUERY_OPERATORS,
    productive_predicate: Any = None,
) -> str:
    for operator in order:
        if operator in catalog and not _operator_exhausted(
            operator,
            attempts,
            productive_failures=productive_failures,
            catalog=catalog,
            productive_predicate=productive_predicate,
        ):
            return operator
    return ""


def _operator_exhausted(
    operator: str,
    attempts: list[dict[str, Any]],
    *,
    productive_failures: tuple[str, ...],
    catalog: Mapping[str, Mapping[str, Any]] = QUERY_OPERATORS,
    productive_predicate: Any = None,
) -> bool:
    """Whether ``operator`` has spent its attempts without being productive.

    ``productive_predicate`` decides what "productive" means.  Routing passes
    :func:`_credited_yield_productive` (real credited yield); legacy callers
    pass nothing and keep ``classify_attempt_failure`` against
    ``productive_failures``, which is volume-based and deliberately
    unchanged for them.  See :data:`ARM_ROUTING_RULE_VERSION`.
    """

    spec = catalog[operator]
    max_attempts = int(spec.get("max_attempts") or 1)
    matching = [
        attempt
        for attempt in attempts
        if _operator_name(attempt) == operator
    ]
    if len(matching) < max_attempts:
        return False
    latest = matching[-1] if matching else {}
    if productive_predicate is not None:
        return not productive_predicate(latest)
    return classify_attempt_failure(latest) not in set(productive_failures)


def _operator_plan(
    operator: str,
    attempts: list[dict[str, Any]],
    failure: str,
    *,
    phase: str,
    operators: tuple[str, ...],
    productive_failures: tuple[str, ...],
    context_tags: tuple[str, ...] = (),
    catalog: Mapping[str, Mapping[str, Any]] = QUERY_OPERATORS,
    productive_predicate: Any = None,
) -> dict[str, Any]:
    spec = dict(catalog.get(operator) or {})
    counts = Counter(
        _operator_name(attempt) or str(attempt.get("strategy_family") or "")
        for attempt in attempts
    )
    counts.pop("", None)
    # `operators` is the default order, whose names need not all exist in an
    # injected catalog -- `_operator_exhausted` indexes the catalog directly,
    # so unknown names are filtered out rather than raising.
    exhausted = [
        name
        for name in operators
        if name in catalog
        and _operator_exhausted(
            name,
            attempts,
            productive_failures=productive_failures,
            catalog=catalog,
            productive_predicate=productive_predicate,
        )
    ]
    return {
        "operator": operator,
        "phase": spec.get("phase", phase),
        "source_family": spec.get("source_family", ""),
        "description": spec.get("description", ""),
        "constraints": list(spec.get("constraints") or []),
        "last_failure_class": failure,
        "attempt_index": counts.get(operator, 0) + 1 if operator else 0,
        "attempted_operator_counts": dict(counts),
        "context_tags": list(context_tags),
        "exhausted": not bool(operator),
        "exhausted_operators": exhausted,
    }


def _target_context_order(target: Mapping[str, Any]) -> tuple[str, ...]:
    tags = set(_target_context_tags(target))
    if "context_pivot" in tags:
        return ("target_context_pivot",)
    return ()


def _target_context_tags(target: Mapping[str, Any]) -> tuple[str, ...]:
    if (
        target.get("key_columns")
        or target.get("missing_fields")
        or _mapping(target.get("anchor_values"))
    ):
        return ("context_pivot",)
    return ()


def _dedupe_order(order: tuple[str, ...]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in order:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _catalog_attempts_from_outcomes(
    outcomes: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    current_key: tuple[str, Any] | None = None

    for outcome in outcomes:
        if outcome.get("topic") != "goal_catalog":
            continue
        attempt = _attempt_from_outcome(outcome)
        operator = _operator_name(attempt)
        if not operator:
            continue

        operator_attempt = attempt.get("operator_attempt")
        if operator_attempt:
            key: tuple[str, Any] = (operator, operator_attempt)
        elif current_key and current_key[0] == operator:
            key = current_key
        else:
            key = (operator, len(attempts) + 1)

        if key != current_key:
            if current:
                attempts.append(_finalize_catalog_attempt(current))
            current = {
                "strategy_operator": operator,
                "strategy_family": attempt.get("strategy_family", ""),
                "source_family": attempt.get("source_family", ""),
                "operator_attempt": operator_attempt,
                "queries": [],
                "firecrawl_hits": 0,
                "accepted_source_count": 0,
                "duplicate_url_count": 0,
                "skipped_by_reason": Counter(),
                "outcome_count": 0,
                "error_count": 0,
                "errors": [],
            }
            current_key = key

        _merge_catalog_attempt(current, attempt)

    if current:
        attempts.append(_finalize_catalog_attempt(current))
    return attempts


def _merge_catalog_attempt(
    aggregate: dict[str, Any],
    attempt: Mapping[str, Any],
) -> None:
    query = str(attempt.get("query") or "")
    if query:
        aggregate["queries"].append(query)
        aggregate["query"] = query
    aggregate["firecrawl_hits"] += _as_int(attempt.get("firecrawl_hits"))
    aggregate["accepted_source_count"] += _as_int(
        attempt.get("accepted_source_count")
    )
    aggregate["duplicate_url_count"] += _as_int(attempt.get("duplicate_url_count"))
    aggregate["skipped_by_reason"].update(_mapping(attempt.get("skipped_by_reason")))
    aggregate["outcome_count"] += 1
    for field_name in (
        "baseline_catalog_status",
        "baseline_catalog_count_target_count",
        "baseline_catalog_unestimated_count",
        "baseline_catalog_target_family_count",
        "post_catalog_status",
        "post_catalog_count_target_count",
        "post_catalog_unestimated_count",
        "post_catalog_target_family_count",
        "post_catalog_status_delta",
        "post_catalog_count_target_delta",
        "post_catalog_unestimated_delta",
        "post_catalog_target_family_delta",
        "post_catalog_progress_delta",
    ):
        value = attempt.get(field_name)
        if value is not None:
            aggregate[field_name] = value
    error = str(attempt.get("error") or "")
    if error:
        aggregate["error_count"] += 1
        aggregate["errors"].append(error)


def _finalize_catalog_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    skipped = Counter(attempt.get("skipped_by_reason") or {})
    finalized = {
        **attempt,
        "query_count": len(attempt.get("queries") or []),
        "skipped_by_reason": dict(skipped),
        "duplicate_url_count": _as_int(attempt.get("duplicate_url_count")),
    }
    if _as_int(attempt.get("error_count")) < _as_int(attempt.get("outcome_count")):
        finalized["error"] = ""
    else:
        finalized["error"] = "; ".join(attempt.get("errors") or [])[:500]
    return finalized


def _target_attempts(target: Mapping[str, Any]) -> list[dict[str, Any]]:
    attempts = [
        dict(attempt)
        for attempt in target.get("strategy_history") or []
        if isinstance(attempt, Mapping)
    ]
    return sorted(
        attempts,
        key=lambda attempt: (
            _as_int(attempt.get("sequence")),
            _as_int(attempt.get("evolution_index")),
            _as_int(attempt.get("prompt_arm_index")),
            _as_int(attempt.get("operator_attempt")),
            str(attempt.get("strategy_attempt_id") or attempt.get("query") or ""),
        ),
    )


def _attempt_from_outcome(outcome: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(outcome.get("metadata"))
    return {
        "episode_id": outcome.get("episode_id"),
        "query": outcome.get("query"),
        "strategy_operator": metadata.get("strategy_operator", ""),
        "strategy_family": metadata.get("strategy_family", ""),
        "source_family": metadata.get("source_family", ""),
        "operator_attempt": metadata.get("operator_attempt"),
        "firecrawl_hits": outcome.get("firecrawl_hits"),
        "accepted_source_count": len(outcome.get("accepted_source_ids") or []),
        "duplicate_url_count": len(outcome.get("duplicate_urls") or []),
        "skipped_by_reason": dict(outcome.get("skipped_by_reason") or {}),
        "post_episode_observed_delta": metadata.get("post_episode_observed_delta"),
        "post_episode_graph_node_delta": metadata.get("post_episode_graph_node_delta"),
        "post_episode_graph_edge_delta": metadata.get("post_episode_graph_edge_delta"),
        "post_episode_table_row_hits": metadata.get("post_episode_table_row_hits"),
        "post_episode_best_guess_hits": metadata.get("post_episode_best_guess_hits"),
        "baseline_catalog_status": metadata.get("baseline_catalog_status"),
        "baseline_catalog_count_target_count": metadata.get(
            "baseline_catalog_count_target_count",
        ),
        "baseline_catalog_unestimated_count": metadata.get(
            "baseline_catalog_unestimated_count",
        ),
        "baseline_catalog_target_family_count": metadata.get(
            "baseline_catalog_target_family_count",
        ),
        "post_catalog_status": metadata.get("post_catalog_status"),
        "post_catalog_count_target_count": metadata.get(
            "post_catalog_count_target_count",
        ),
        "post_catalog_unestimated_count": metadata.get(
            "post_catalog_unestimated_count",
        ),
        "post_catalog_target_family_count": metadata.get(
            "post_catalog_target_family_count",
        ),
        "post_catalog_status_delta": metadata.get("post_catalog_status_delta"),
        "post_catalog_count_target_delta": metadata.get(
            "post_catalog_count_target_delta",
        ),
        "post_catalog_unestimated_delta": metadata.get(
            "post_catalog_unestimated_delta",
        ),
        "post_catalog_target_family_delta": metadata.get(
            "post_catalog_target_family_delta",
        ),
        "post_catalog_progress_delta": metadata.get("post_catalog_progress_delta"),
        "error": outcome.get("error", ""),
    }


def _operator_name(attempt: Mapping[str, Any]) -> str:
    return str(
        attempt.get("strategy_operator")
        or attempt.get("operator")
        or attempt.get("strategy_family")
        or ""
    )


def _memory_terms(target: Mapping[str, Any]) -> list[str]:
    terms: list[str] = []
    for memory in target.get("strategy_memory") or []:
        if not isinstance(memory, Mapping):
            continue
        for field_name in ("successful_query_terms",):
            for value in memory.get(field_name) or []:
                text = _search_text(value)
                if text:
                    terms.append(text)
    return terms


#: Longest suffix, in tokens, that still reads as a structural tag on a base
#: column name rather than as a distinct column of its own.
_SIDECAR_SUFFIX_TOKENS = 2


def _field_terms(target: Mapping[str, Any], *, limit: int) -> list[str]:
    """Search terms taken from the field names a deficit reports as empty.

    For a deficit whose subject is a table's empty columns, these names are the
    entire payload: it carries no anchor values, no known examples and no
    search memory, because nothing has been retrieved for it yet. Without them
    the deterministic fallback has nothing target-specific to say and returns
    the empty string, so the one deficit type that names missing columns could
    never express a query at all -- the columns stayed empty because nothing
    ever searched for them.

    Derived variants are dropped in favour of the name they extend. Rows carry
    sidecar columns built by suffixing a base column name, and a suffix like
    that is run plumbing rather than anything an external source calls its
    data. The test is purely structural -- one normalized name extending
    another present in the same set by no more than a couple of tokens -- so it
    assumes no vocabulary and stays correct for any question or domain.

    The token limit is what keeps the rule from eating real columns. A sidecar
    appends a short structural tag; a genuinely different column appends a
    qualifying phrase. Without the limit, a table carrying both a bare measure
    and the same measure qualified by a year would lose the qualified one --
    silently discarding the more specific column of the pair.
    """

    fields = [
        text
        for text in (str(field or "").strip() for field in target.get("missing_fields") or [])
        if text
    ]
    normalized = {field: _search_text(field).lower().replace(" ", "-") for field in fields}
    bases = set(normalized.values())

    terms: list[str] = []
    for field in fields:
        key = normalized[field]
        if not key:
            continue
        if any(
            key.startswith(f"{other}-")
            and len(key[len(other) + 1 :].split("-")) <= _SIDECAR_SUFFIX_TOKENS
            for other in bases
            if other != key
        ):
            continue
        text = _search_text(field)
        if text and text not in terms:
            terms.append(text)
        if len(terms) >= limit:
            break
    return terms


def _dedupe_words(parts: list[str], *, limit: int = 10) -> str:
    seen: set[str] = set()
    words: list[str] = []
    for part in parts:
        for word in str(part or "").split():
            normalized = word.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            words.append(word)
            if len(words) >= limit:
                return " ".join(words)
    return " ".join(words)


def _search_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        value = " ".join(str(inner) for inner in value.values() if inner is not None)
    elif isinstance(value, (list, tuple, set)):
        value = " ".join(str(inner) for inner in value if inner is not None)
    return " ".join(str(value).replace("_", " ").replace("-", " ").split())


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
