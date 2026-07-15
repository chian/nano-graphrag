"""Stateful generic operators for iterative table-fill search."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping


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
            "Use accepted-source or relevance-gate wording when it describes the missing need.",
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
    "target_context_grain": {
        "phase": "target",
        "source_family": "stratified table",
        "max_attempts": 2,
        "description": (
            "Search the same row family at a different reported contextual "
            "grain, such as a narrower or broader place, site, subgroup, or "
            "scenario."
        ),
        "query_terms": [
            "regional",
            "site",
            "stratified",
        ],
        "constraints": [
            "Vary the context grain instead of assuming one aggregation level.",
            (
                "Prefer sources that report estimates split by place, site, "
                "subgroup, or scenario."
            ),
        ],
    },
    "target_temporal_window": {
        "phase": "target",
        "source_family": "time stratified study",
        "max_attempts": 2,
        "description": (
            "Search the same row family with an explicit observation window, "
            "phase, season, or before/after context."
        ),
        "query_terms": [
            "longitudinal",
            "seasonal",
            "time",
            "series",
        ],
        "constraints": [
            "Vary the observation window when rows are distinguished by time.",
            (
                "Prefer sources that report estimates by period, phase, "
                "season, or before/after context."
            ),
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
_CONTEXT_GRAIN_MARKERS = {
    "area",
    "city",
    "cohort",
    "context",
    "country",
    "facility",
    "geographic",
    "geography",
    "group",
    "jurisdiction",
    "local",
    "location",
    "national",
    "place",
    "population",
    "province",
    "regional",
    "region",
    "setting",
    "site",
    "spatial",
    "state",
    "stratum",
    "subgroup",
    "subnational",
    "territory",
}
_TEMPORAL_WINDOW_MARKERS = {
    "after",
    "baseline",
    "before",
    "date",
    "duration",
    "followup",
    "interval",
    "month",
    "observation",
    "period",
    "phase",
    "post",
    "pre",
    "season",
    "temporal",
    "time",
    "wave",
    "week",
    "window",
    "year",
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
    "not_relevant": (
        "target_terminology_swap",
        "target_exact_anchor",
        "target_source_shift",
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

    candidates = [
        [*anchors, *examples[:1], *source_terms[:2], *memory_terms[:2]],
        [*examples[:2], *source_terms[:3], *memory_terms[:3]],
        [*memory_terms[:4], *source_terms[:2]],
        [*anchors, *memory_terms[:3], *source_terms[:2]],
    ]
    attempted = {
        str(attempt.get("query") or "").strip().lower()
        for attempt in target.get("strategy_history") or []
        if isinstance(attempt, Mapping)
    }
    for parts in candidates:
        if not any(part in parts for part in (*anchors, *examples, *memory_terms)):
            continue
        query = _dedupe_words(parts)
        if query and query.lower() not in attempted:
            return query
    return ""


def classify_attempt_failure(attempt: Mapping[str, Any]) -> str:
    """Classify one attempt using search yield and post-round table delta."""
    if not attempt:
        return "new_target"
    table_delta = _as_int(attempt.get("post_round_observed_delta"))
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
        graph_delta = _as_int(attempt.get("post_round_graph_node_delta"))
        graph_delta += _as_int(attempt.get("post_round_graph_edge_delta"))
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
    if _as_int(skipped.get("not_relevant")) > 0:
        return "not_relevant"
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
) -> str:
    for operator in order:
        if operator in QUERY_OPERATORS and not _operator_exhausted(
            operator,
            attempts,
            productive_failures=productive_failures,
        ):
            return operator
    return ""


def _operator_exhausted(
    operator: str,
    attempts: list[dict[str, Any]],
    *,
    productive_failures: tuple[str, ...],
) -> bool:
    spec = QUERY_OPERATORS[operator]
    max_attempts = int(spec.get("max_attempts") or 1)
    matching = [
        attempt
        for attempt in attempts
        if _operator_name(attempt) == operator
    ]
    if len(matching) < max_attempts:
        return False
    latest = matching[-1] if matching else {}
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
) -> dict[str, Any]:
    spec = dict(QUERY_OPERATORS.get(operator) or {})
    counts = Counter(
        _operator_name(attempt) or str(attempt.get("strategy_family") or "")
        for attempt in attempts
    )
    counts.pop("", None)
    exhausted = [
        name
        for name in operators
        if _operator_exhausted(
            name,
            attempts,
            productive_failures=productive_failures,
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
    order: list[str] = []
    if "context_grain" in tags:
        order.append("target_context_grain")
    if "temporal_window" in tags:
        order.append("target_temporal_window")
    return tuple(order)


def _target_context_tags(target: Mapping[str, Any]) -> tuple[str, ...]:
    text_parts = [
        target.get("target_table"),
        target.get("target_name"),
        target.get("description"),
        target.get("evidence_gap"),
        target.get("key_columns"),
        target.get("missing_fields"),
        target.get("known_missing_examples"),
    ]
    anchors = _mapping(target.get("anchor_values"))
    text_parts.extend(anchors.keys())
    text_parts.extend(anchors.values())

    tokens = set(re.findall(r"[a-z]+", _search_text(text_parts).lower()))
    tags: list[str] = []
    if _has_any_token(tokens, _CONTEXT_GRAIN_MARKERS):
        tags.append("context_grain")
    if _has_any_token(tokens, _TEMPORAL_WINDOW_MARKERS):
        tags.append("temporal_window")
    return tuple(tags)


def _has_any_token(tokens: set[str], markers: set[str]) -> bool:
    return any(token in markers for token in tokens)


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
                "round": attempt.get("round"),
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
    aggregate["round"] = attempt.get("round")
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
            _as_int(attempt.get("round")),
            str(attempt.get("query") or ""),
        ),
    )


def _attempt_from_outcome(outcome: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping(outcome.get("metadata"))
    return {
        "round": outcome.get("round_index"),
        "query": outcome.get("query"),
        "strategy_operator": metadata.get("strategy_operator", ""),
        "strategy_family": metadata.get("strategy_family", ""),
        "source_family": metadata.get("source_family", ""),
        "operator_attempt": metadata.get("operator_attempt"),
        "firecrawl_hits": outcome.get("firecrawl_hits"),
        "accepted_source_count": len(outcome.get("accepted_source_ids") or []),
        "duplicate_url_count": len(outcome.get("duplicate_urls") or []),
        "skipped_by_reason": dict(outcome.get("skipped_by_reason") or {}),
        "post_round_observed_delta": metadata.get("post_round_observed_delta"),
        "post_round_graph_node_delta": metadata.get("post_round_graph_node_delta"),
        "post_round_graph_edge_delta": metadata.get("post_round_graph_edge_delta"),
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
        for field_name in (
            "matched_needs",
            "missing_needs",
            "successful_query_terms",
        ):
            for value in memory.get(field_name) or []:
                text = _search_text(value)
                if text:
                    terms.append(text)
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
