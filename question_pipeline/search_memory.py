"""Compact search-strategy memory for iterative table aggregation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.+-]*")
_STOPWORDS = {
    "about",
    "after",
    "against",
    "and",
    "are",
    "between",
    "from",
    "into",
    "not",
    "of",
    "or",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "with",
}


@dataclass
class SearchMemory:
    """Durable, generic memory of search attempts for table-fill deficits."""

    records: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_outcomes(cls, outcomes: Iterable[Mapping[str, Any]]) -> "SearchMemory":
        records: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        for outcome in outcomes:
            if outcome.get("topic") != "target_deficit":
                continue
            metadata = outcome.get("metadata")
            if not isinstance(metadata, Mapping):
                metadata = {}
            key = memory_key(metadata)
            if not key:
                continue
            record = records.setdefault(key, _new_record(key, metadata))
            _merge_target(record, metadata)
            _merge_outcome(record, outcome)

        return cls(records=[_finalize_record(record) for record in records.values()])

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_count": len(self.records),
            "records": self.records,
        }

    def to_deficit_context(
        self,
        target: Mapping[str, Any],
        *,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """Return the most relevant memory records for a newly built deficit."""
        scored = []
        for record in self.records:
            score = _match_score(target, record)
            if score > 0:
                scored.append((score, _latest_round(record), record))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            _compact_record(record, score=score)
            for score, _, record in scored[:limit]
        ]


def memory_key(metadata: Mapping[str, Any]) -> str:
    """Build a stable key from generic target metadata, not a transient task id."""
    table = _clean(metadata.get("target_table"))
    deficit_type = _clean(metadata.get("fill_deficit_type"))
    identity = (
        _clean(metadata.get("target_id"))
        or _clean(metadata.get("target_name"))
        or _anchor_signature(metadata.get("anchor_values"))
    )
    if not table or not identity:
        return ""

    payload = {
        "table": table,
        "deficit_type": deficit_type,
        "identity": identity,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _new_record(key: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "key": key,
        "target": {
            "target_table": str(metadata.get("target_table") or ""),
            "target_id": str(metadata.get("target_id") or ""),
            "target_name": str(metadata.get("target_name") or ""),
            "deficit_type": str(metadata.get("fill_deficit_type") or ""),
            "key_columns": list(metadata.get("key_columns") or []),
            "missing_fields": list(metadata.get("missing_fields") or []),
            "anchor_values": (
                dict(metadata.get("anchor_values"))
                if isinstance(metadata.get("anchor_values"), Mapping)
                else {}
            ),
        },
        "attempt_count": 0,
        "accepted_source_ids": [],
        "accepted_urls": [],
        "rejected_urls": [],
        "skipped_by_reason": Counter(),
        "strategy_families": Counter(),
        "strategy_operators": Counter(),
        "successful_query_terms": Counter(),
        "failed_query_terms": Counter(),
        "matched_needs": Counter(),
        "missing_needs": Counter(),
        "offtopic_axes": Counter(),
        "failure_modes": Counter(),
        "better_search_cues": Counter(),
        "avoid_cues": Counter(),
        "attempts": [],
    }


def _merge_target(record: dict[str, Any], metadata: Mapping[str, Any]) -> None:
    target = record["target"]
    for field_name in ("target_table", "target_id", "target_name", "deficit_type"):
        metadata_name = (
            "fill_deficit_type" if field_name == "deficit_type" else field_name
        )
        value = str(metadata.get(metadata_name) or "")
        if value:
            target[field_name] = value
    for field_name in ("key_columns", "missing_fields"):
        target[field_name] = _unique(
            [*target.get(field_name, []), *list(metadata.get(field_name) or [])],
        )
    anchor_values = metadata.get("anchor_values")
    if isinstance(anchor_values, Mapping):
        target.setdefault("anchor_values", {}).update(
            {str(key): value for key, value in anchor_values.items() if value}
        )


def _merge_outcome(record: dict[str, Any], outcome: Mapping[str, Any]) -> None:
    metadata = outcome.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}

    accepted_source_ids = [
        str(value) for value in outcome.get("accepted_source_ids") or [] if value
    ]
    accepted_urls = [
        str(value) for value in outcome.get("accepted_urls") or [] if value
    ]
    duplicate_urls = [
        str(value) for value in outcome.get("duplicate_urls") or [] if value
    ]
    relevance = [
        decision
        for decision in outcome.get("relevance_decisions") or []
        if isinstance(decision, Mapping)
    ]
    rejected_urls = [
        str(decision.get("url") or "")
        for decision in relevance
        if not decision.get("accept") and decision.get("url")
    ]
    skipped = Counter(
        {
            str(key): int(value or 0)
            for key, value in dict(outcome.get("skipped_by_reason") or {}).items()
        }
    )

    strategy_family = str(metadata.get("strategy_family") or "")
    if strategy_family:
        record["strategy_families"][strategy_family] += 1
    strategy_operator = str(metadata.get("strategy_operator") or strategy_family)
    if strategy_operator:
        record["strategy_operators"][strategy_operator] += 1

    query = str(outcome.get("query") or "")
    terms = _query_terms(query)
    if accepted_source_ids:
        record["successful_query_terms"].update(terms)
    elif not outcome.get("error"):
        record["failed_query_terms"].update(terms)

    for decision in relevance:
        record["matched_needs"].update(_decision_values(decision, "matched_needs"))
        record["missing_needs"].update(_decision_values(decision, "missing_needs"))
        record["offtopic_axes"].update(_decision_values(decision, "offtopic_axes"))
        record["failure_modes"].update(_decision_values(decision, "failure_modes"))
        record["better_search_cues"].update(
            _decision_values(decision, "better_search_cues")
        )
        record["avoid_cues"].update(_decision_values(decision, "avoid_cues"))

    record["attempt_count"] += 1
    record["accepted_source_ids"].extend(accepted_source_ids)
    record["accepted_urls"].extend(accepted_urls)
    record["rejected_urls"].extend(rejected_urls)
    record["skipped_by_reason"].update(skipped)
    record["attempts"].append(
        {
            "round": outcome.get("round_index"),
            "query": query,
            "strategy_attempt_id": (
                metadata.get("strategy_attempt_id")
                or metadata.get("strategy_wave_id")
                or ""
            ),
            "evolution_index": _first_present(
                metadata,
                "evolution_index",
                "strategy_evolution_index",
            ),
            "prompt_arm_id": metadata.get("prompt_arm_id", ""),
            "prompt_arm_name": metadata.get("prompt_arm_name", ""),
            "prompt_arm_index": metadata.get("prompt_arm_index"),
            "prompt_delta": metadata.get("prompt_delta", ""),
            "prompt_hypothesis": metadata.get("prompt_hypothesis", ""),
            "expected_source_shape": metadata.get("expected_source_shape", ""),
            "query_index": _first_present(
                metadata,
                "query_index",
                "strategy_query_index",
            ),
            "strategy_family": strategy_family,
            "strategy_operator": strategy_operator,
            "source_family": metadata.get("source_family", ""),
            "strategy_origin": metadata.get("strategy_origin", ""),
            "operator_attempt": metadata.get("operator_attempt"),
            "operator_last_failure_class": metadata.get(
                "operator_last_failure_class",
                "",
            ),
            "rationale": metadata.get("rationale", ""),
            "firecrawl_hits": int(outcome.get("firecrawl_hits") or 0),
            "search_result_count": len(
                outcome.get("search_result_observations") or []
            ),
            "accepted_source_count": len(accepted_source_ids),
            "accepted_urls": accepted_urls[:5],
            "duplicate_url_count": len(duplicate_urls),
            "skipped_by_reason": dict(skipped),
            "candidate_fates": dict(
                Counter(
                    str(candidate.get("fate") or "")
                    for candidate in outcome.get("candidate_source_outcomes") or []
                    if isinstance(candidate, Mapping)
                    and str(candidate.get("fate") or "")
                )
            ),
            "search_results": [
                dict(observation)
                for observation in (
                    outcome.get("search_result_observations") or []
                )[:5]
                if isinstance(observation, Mapping)
            ],
            "matched_needs": _top_counter(
                _counter_from_decisions(relevance, "matched_needs"),
                8,
            ),
            "missing_needs": _top_counter(
                _counter_from_decisions(relevance, "missing_needs"),
                8,
            ),
            "offtopic_axes": _top_counter(
                _counter_from_decisions(relevance, "offtopic_axes"),
                8,
            ),
            "failure_modes": _top_counter(
                _counter_from_decisions(relevance, "failure_modes"),
                8,
            ),
            "better_search_cues": _top_counter(
                _counter_from_decisions(relevance, "better_search_cues"),
                8,
            ),
            "avoid_cues": _top_counter(
                _counter_from_decisions(relevance, "avoid_cues"),
                8,
            ),
            "post_round_observed_delta": metadata.get("post_round_observed_delta"),
            "post_round_graph_node_delta": metadata.get(
                "post_round_graph_node_delta",
            ),
            "post_round_graph_edge_delta": metadata.get(
                "post_round_graph_edge_delta",
            ),
            "post_round_deficit_count": metadata.get("post_round_deficit_count"),
            "post_round_table_row_hits": metadata.get("post_round_table_row_hits"),
            "post_round_best_guess_hits": metadata.get("post_round_best_guess_hits"),
            "error": str(outcome.get("error") or "")[:500],
        }
    )


def _finalize_record(record: dict[str, Any]) -> dict[str, Any]:
    attempts = sorted(
        record["attempts"],
        key=lambda attempt: (
            _round_sort_value(attempt.get("round")),
            _as_int(attempt.get("evolution_index")),
            _as_int(attempt.get("prompt_arm_index")),
            _as_int(attempt.get("query_index")),
            str(attempt.get("query") or ""),
        ),
    )
    strategy_attempts = _summarize_strategy_attempts(attempts)
    return {
        "key": record["key"],
        "target": record["target"],
        "attempt_count": record["attempt_count"],
        "accepted_source_count": len(set(record["accepted_source_ids"])),
        "accepted_source_ids": _unique(record["accepted_source_ids"])[:20],
        "accepted_urls": _unique(record["accepted_urls"])[:20],
        "rejected_urls": _unique(record["rejected_urls"])[:20],
        "skipped_by_reason": dict(record["skipped_by_reason"]),
        "strategy_families": dict(record["strategy_families"]),
        "strategy_operators": dict(record["strategy_operators"]),
        "successful_query_terms": _top_counter(record["successful_query_terms"], 12),
        "failed_query_terms": _top_counter(record["failed_query_terms"], 12),
        "matched_needs": _top_counter(record["matched_needs"], 12),
        "missing_needs": _top_counter(record["missing_needs"], 12),
        "offtopic_axes": _top_counter(record["offtopic_axes"], 12),
        "failure_modes": _top_counter(record["failure_modes"], 12),
        "better_search_cues": _top_counter(record["better_search_cues"], 12),
        "avoid_cues": _top_counter(record["avoid_cues"], 12),
        "strategy_attempts": strategy_attempts[-12:],
        "attempts": attempts[-12:],
    }


def _compact_record(record: Mapping[str, Any], *, score: int) -> dict[str, Any]:
    return {
        "match_score": score,
        "target": record.get("target", {}),
        "attempt_count": record.get("attempt_count", 0),
        "accepted_source_count": record.get("accepted_source_count", 0),
        "skipped_by_reason": record.get("skipped_by_reason", {}),
        "strategy_families": record.get("strategy_families", {}),
        "strategy_operators": record.get("strategy_operators", {}),
        "successful_query_terms": record.get("successful_query_terms", []),
        "failed_query_terms": record.get("failed_query_terms", []),
        "matched_needs": record.get("matched_needs", []),
        "missing_needs": record.get("missing_needs", []),
        "offtopic_axes": record.get("offtopic_axes", []),
        "failure_modes": record.get("failure_modes", []),
        "better_search_cues": record.get("better_search_cues", []),
        "avoid_cues": record.get("avoid_cues", []),
        "attempts": (
            record.get("strategy_attempts")
            or record.get("search_waves")
            or record.get("attempts", [])
        )[-6:],
        "query_attempts": record.get("attempts", [])[-6:],
    }


def _summarize_strategy_attempts(
    attempts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for attempt in attempts:
        key = _strategy_attempt_key(attempt)
        strategy_attempt = groups.setdefault(
            key,
            {
                "strategy_attempt_id": str(
                    attempt.get("strategy_attempt_id") or key
                ),
                "round": attempt.get("round"),
                "evolution_index": attempt.get("evolution_index"),
                "strategy_family": attempt.get("strategy_family", ""),
                "strategy_operator": attempt.get("strategy_operator", ""),
                "source_family": attempt.get("source_family", ""),
                "operator_attempt": attempt.get("operator_attempt"),
                "operator_last_failure_class": attempt.get(
                    "operator_last_failure_class",
                    "",
                ),
                "queries": [],
                "firecrawl_hits": 0,
                "search_result_count": 0,
                "accepted_source_count": 0,
                "duplicate_url_count": 0,
                "skipped_by_reason": Counter(),
                "candidate_fates": Counter(),
                "matched_needs": Counter(),
                "missing_needs": Counter(),
                "offtopic_axes": Counter(),
                "failure_modes": Counter(),
                "better_search_cues": Counter(),
                "avoid_cues": Counter(),
                "search_results": [],
                "accepted_urls": [],
                "prompt_arms": OrderedDict(),
                "outcome_count": 0,
                "error_count": 0,
                "errors": [],
            },
        )
        query = str(attempt.get("query") or "")
        if query:
            strategy_attempt["queries"].append(query)
            strategy_attempt["query"] = query
        strategy_attempt["round"] = attempt.get("round")
        strategy_attempt["firecrawl_hits"] += _as_int(attempt.get("firecrawl_hits"))
        strategy_attempt["search_result_count"] += _as_int(
            attempt.get("search_result_count")
        )
        strategy_attempt["accepted_source_count"] += _as_int(
            attempt.get("accepted_source_count")
        )
        strategy_attempt["duplicate_url_count"] += _as_int(
            attempt.get("duplicate_url_count")
        )
        strategy_attempt["skipped_by_reason"].update(
            _mapping(attempt.get("skipped_by_reason"))
        )
        strategy_attempt["candidate_fates"].update(
            _mapping(attempt.get("candidate_fates"))
        )
        strategy_attempt["matched_needs"].update(attempt.get("matched_needs") or [])
        strategy_attempt["missing_needs"].update(attempt.get("missing_needs") or [])
        strategy_attempt["offtopic_axes"].update(attempt.get("offtopic_axes") or [])
        strategy_attempt["failure_modes"].update(attempt.get("failure_modes") or [])
        strategy_attempt["better_search_cues"].update(
            attempt.get("better_search_cues") or []
        )
        strategy_attempt["avoid_cues"].update(attempt.get("avoid_cues") or [])
        strategy_attempt["accepted_urls"].extend(attempt.get("accepted_urls") or [])
        if len(strategy_attempt["search_results"]) < 12:
            strategy_attempt["search_results"].extend(
                (attempt.get("search_results") or [])[
                    : max(0, 12 - len(strategy_attempt["search_results"]))
                ]
            )
        _merge_prompt_arm(strategy_attempt, attempt)
        strategy_attempt["outcome_count"] += 1
        for field_name in (
            "post_round_observed_delta",
            "post_round_graph_node_delta",
            "post_round_graph_edge_delta",
            "post_round_deficit_count",
            "post_round_table_row_hits",
            "post_round_best_guess_hits",
        ):
            value = attempt.get(field_name)
            if value is not None:
                strategy_attempt[field_name] = value
        error = str(attempt.get("error") or "")
        if error:
            strategy_attempt["error_count"] += 1
            strategy_attempt["errors"].append(error)

    return [
        _finalize_strategy_attempt(strategy_attempt)
        for strategy_attempt in groups.values()
    ]


def _merge_prompt_arm(
    strategy_attempt: dict[str, Any],
    attempt: Mapping[str, Any],
) -> None:
    arm_key = _prompt_arm_key(attempt)
    arms: OrderedDict[str, dict[str, Any]] = strategy_attempt["prompt_arms"]
    arm = arms.setdefault(
        arm_key,
        {
            "prompt_arm_id": str(attempt.get("prompt_arm_id") or arm_key),
            "prompt_arm_name": str(attempt.get("prompt_arm_name") or ""),
            "prompt_arm_index": attempt.get("prompt_arm_index"),
            "prompt_delta": str(attempt.get("prompt_delta") or ""),
            "prompt_hypothesis": str(attempt.get("prompt_hypothesis") or ""),
            "expected_source_shape": str(
                attempt.get("expected_source_shape") or ""
            ),
            "queries": [],
            "firecrawl_hits": 0,
            "search_result_count": 0,
            "accepted_source_count": 0,
            "duplicate_url_count": 0,
            "table_row_hits": 0,
            "best_guess_hits": 0,
            "skipped_by_reason": Counter(),
            "candidate_fates": Counter(),
            "search_results": [],
            "accepted_urls": [],
            "error_count": 0,
            "errors": [],
        },
    )

    query = str(attempt.get("query") or "")
    if query:
        arm["queries"].append(query)
    arm["firecrawl_hits"] += _as_int(attempt.get("firecrawl_hits"))
    arm["search_result_count"] += _as_int(attempt.get("search_result_count"))
    arm["accepted_source_count"] += _as_int(attempt.get("accepted_source_count"))
    arm["duplicate_url_count"] += _as_int(attempt.get("duplicate_url_count"))
    arm["table_row_hits"] += _as_int(attempt.get("post_round_table_row_hits"))
    arm["best_guess_hits"] += _as_int(attempt.get("post_round_best_guess_hits"))
    arm["skipped_by_reason"].update(_mapping(attempt.get("skipped_by_reason")))
    arm["candidate_fates"].update(_mapping(attempt.get("candidate_fates")))
    arm["accepted_urls"].extend(attempt.get("accepted_urls") or [])
    if len(arm["search_results"]) < 12:
        arm["search_results"].extend(
            (attempt.get("search_results") or [])[
                : max(0, 12 - len(arm["search_results"]))
            ]
        )
    error = str(attempt.get("error") or "")
    if error:
        arm["error_count"] += 1
        arm["errors"].append(error)


def _finalize_strategy_attempt(wave: Mapping[str, Any]) -> dict[str, Any]:
    query_count = len(wave.get("queries") or [])
    outcome_count = _as_int(wave.get("outcome_count"))
    error_count = _as_int(wave.get("error_count"))
    error = ""
    if outcome_count > 0 and error_count >= outcome_count:
        error = "; ".join(wave.get("errors") or [])[:500]
    prompt_arms = [
        _finalize_prompt_arm(arm)
        for arm in (wave.get("prompt_arms") or {}).values()
    ]
    return {
        "strategy_attempt_id": wave.get("strategy_attempt_id", ""),
        "round": wave.get("round"),
        "evolution_index": wave.get("evolution_index"),
        "strategy_family": wave.get("strategy_family", ""),
        "strategy_operator": wave.get("strategy_operator", ""),
        "source_family": wave.get("source_family", ""),
        "operator_attempt": wave.get("operator_attempt"),
        "operator_last_failure_class": wave.get("operator_last_failure_class", ""),
        "query_count": query_count,
        "queries": _unique(wave.get("queries") or []),
        "query": str(wave.get("query") or ""),
        "firecrawl_hits": _as_int(wave.get("firecrawl_hits")),
        "search_result_count": _as_int(wave.get("search_result_count")),
        "accepted_source_count": _as_int(wave.get("accepted_source_count")),
        "accepted_urls": _unique(wave.get("accepted_urls") or [])[:10],
        "duplicate_url_count": _as_int(wave.get("duplicate_url_count")),
        "skipped_by_reason": dict(wave.get("skipped_by_reason") or {}),
        "candidate_fates": dict(wave.get("candidate_fates") or {}),
        "matched_needs": _top_counter(wave.get("matched_needs") or Counter(), 8),
        "missing_needs": _top_counter(wave.get("missing_needs") or Counter(), 8),
        "offtopic_axes": _top_counter(wave.get("offtopic_axes") or Counter(), 8),
        "failure_modes": _top_counter(wave.get("failure_modes") or Counter(), 8),
        "better_search_cues": _top_counter(
            wave.get("better_search_cues") or Counter(),
            8,
        ),
        "avoid_cues": _top_counter(wave.get("avoid_cues") or Counter(), 8),
        "search_results": list(wave.get("search_results") or [])[:12],
        "post_round_observed_delta": wave.get("post_round_observed_delta"),
        "post_round_graph_node_delta": wave.get("post_round_graph_node_delta"),
        "post_round_graph_edge_delta": wave.get("post_round_graph_edge_delta"),
        "post_round_deficit_count": wave.get("post_round_deficit_count"),
        "post_round_table_row_hits": wave.get("post_round_table_row_hits"),
        "post_round_best_guess_hits": wave.get("post_round_best_guess_hits"),
        "prompt_arms": prompt_arms,
        "arm_contrast": _arm_contrast(prompt_arms),
        "error": error,
    }


def _finalize_prompt_arm(arm: Mapping[str, Any]) -> dict[str, Any]:
    query_count = len(arm.get("queries") or [])
    outcome = _prompt_arm_outcome(arm)
    return {
        "prompt_arm_id": arm.get("prompt_arm_id", ""),
        "prompt_arm_name": arm.get("prompt_arm_name", ""),
        "prompt_arm_index": arm.get("prompt_arm_index"),
        "prompt_delta": arm.get("prompt_delta", ""),
        "prompt_hypothesis": arm.get("prompt_hypothesis", ""),
        "expected_source_shape": arm.get("expected_source_shape", ""),
        "query_count": query_count,
        "queries": _unique(arm.get("queries") or []),
        "firecrawl_hits": _as_int(arm.get("firecrawl_hits")),
        "search_result_count": _as_int(arm.get("search_result_count")),
        "accepted_source_count": _as_int(arm.get("accepted_source_count")),
        "duplicate_url_count": _as_int(arm.get("duplicate_url_count")),
        "table_row_hits": _as_int(arm.get("table_row_hits")),
        "best_guess_hits": _as_int(arm.get("best_guess_hits")),
        "skipped_by_reason": dict(arm.get("skipped_by_reason") or {}),
        "candidate_fates": dict(arm.get("candidate_fates") or {}),
        "accepted_urls": _unique(arm.get("accepted_urls") or [])[:10],
        "search_results": list(arm.get("search_results") or [])[:12],
        "score": _prompt_arm_score(arm),
        "outcome": outcome,
        "error": "; ".join(arm.get("errors") or [])[:500],
    }


def _strategy_attempt_key(attempt: Mapping[str, Any]) -> str:
    attempt_id = str(attempt.get("strategy_attempt_id") or "")
    if attempt_id:
        return attempt_id
    payload = {
        "round": attempt.get("round"),
        "evolution_index": attempt.get("evolution_index"),
        "operator": _operator_name(attempt),
        "operator_attempt": attempt.get("operator_attempt"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _prompt_arm_key(attempt: Mapping[str, Any]) -> str:
    return str(
        attempt.get("prompt_arm_id")
        or attempt.get("strategy_attempt_id")
        or _strategy_attempt_key(attempt)
    )


def _arm_contrast(prompt_arms: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "prompt_arm_id": arm.get("prompt_arm_id", ""),
            "prompt_arm_name": arm.get("prompt_arm_name", ""),
            "score": arm.get("score", 0),
            "accepted_source_count": arm.get("accepted_source_count", 0),
            "table_row_hits": arm.get("table_row_hits", 0),
            "best_guess_hits": arm.get("best_guess_hits", 0),
            "outcome": arm.get("outcome", ""),
        }
        for arm in prompt_arms
    ]
    return sorted(
        rows,
        key=lambda row: float(row.get("score") or 0.0),
        reverse=True,
    )


def _prompt_arm_score(arm: Mapping[str, Any]) -> float:
    skipped = _mapping(arm.get("skipped_by_reason"))
    return round(
        5.0 * _as_int(arm.get("table_row_hits"))
        + 3.0 * _as_int(arm.get("best_guess_hits"))
        + 1.0 * _as_int(arm.get("accepted_source_count"))
        - 0.5 * _as_int(arm.get("duplicate_url_count"))
        - 1.0 * _as_int(skipped.get("not_relevant")),
        6,
    )


def _prompt_arm_outcome(arm: Mapping[str, Any]) -> str:
    if _as_int(arm.get("table_row_hits")) > 0:
        return "materialized_rows"
    if _as_int(arm.get("best_guess_hits")) > 0:
        return "best_guess_rows"
    if _as_int(arm.get("accepted_source_count")) > 0:
        return "accepted_sources"
    if _as_int(arm.get("search_result_count")) <= 0:
        return "no_hits"
    skipped = _mapping(arm.get("skipped_by_reason"))
    if _as_int(skipped.get("duplicate_url")) >= _as_int(
        arm.get("search_result_count")
    ):
        return "all_duplicates"
    if _as_int(skipped.get("not_relevant")) > 0:
        return "off_axis"
    return "no_accepted_sources"


def _match_score(target: Mapping[str, Any], record: Mapping[str, Any]) -> int:
    previous = record.get("target")
    if not isinstance(previous, Mapping):
        return 0

    score = 0
    if _clean(target.get("target_table")) == _clean(previous.get("target_table")):
        score += 20
    else:
        return 0

    if _clean(target.get("target_id")) and _clean(target.get("target_id")) == _clean(
        previous.get("target_id")
    ):
        score += 40
    if _clean(target.get("target_name")) and _clean(
        target.get("target_name")
    ) == _clean(previous.get("target_name")):
        score += 30
    target_deficit_type = _clean(
        target.get("deficit_type") or target.get("fill_deficit_type")
    )
    if target_deficit_type == _clean(previous.get("deficit_type")):
        score += 10

    score += 4 * len(
        set(_clean_list(target.get("key_columns")))
        & set(_clean_list(previous.get("key_columns")))
    )
    score += 3 * len(
        set(_clean_list(target.get("missing_fields")))
        & set(_clean_list(previous.get("missing_fields")))
    )
    score += 8 * len(
        set(_clean_list(dict(target.get("anchor_values") or {}).values()))
        & set(_clean_list(dict(previous.get("anchor_values") or {}).values()))
    )
    return score


def _counter_from_decisions(
    decisions: Sequence[Mapping[str, Any]],
    field_name: str,
) -> Counter:
    values: Counter = Counter()
    for decision in decisions:
        values.update(_decision_values(decision, field_name))
    return values


def _decision_values(decision: Mapping[str, Any], field_name: str) -> list[str]:
    values = _clean_list(decision.get(field_name))
    metadata = decision.get("metadata")
    if isinstance(metadata, Mapping):
        values.extend(_clean_list(metadata.get(field_name)))
        progress = metadata.get("progress_judgment")
        if isinstance(progress, Mapping):
            values.extend(_clean_list(progress.get(field_name)))
    return _unique(values)


def _top_counter(counter: Counter, limit: int) -> list[str]:
    return [value for value, _ in counter.most_common(limit) if value]


def _latest_round(record: Mapping[str, Any]) -> int:
    attempts = record.get("attempts")
    if not isinstance(attempts, list):
        return -1
    return max(
        (_round_sort_value(attempt.get("round")) for attempt in attempts),
        default=-1,
    )


def _round_sort_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _operator_name(attempt: Mapping[str, Any]) -> str:
    return str(
        attempt.get("strategy_operator")
        or attempt.get("operator")
        or attempt.get("strategy_family")
        or ""
    )


def _anchor_signature(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    return "|".join(_clean_list(value.values())[:6])


def _query_terms(query: str) -> list[str]:
    return [
        word
        for word in _WORD_RE.findall(_clean(query))
        if len(word) > 2 and word not in _STOPWORDS
    ][:12]


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes, Mapping)):
        values = [values]
    return _unique(_clean(value) for value in values if value)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).strip().lower()


def _unique(values: Iterable[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for value in values:
        if value is None or value == "":
            continue
        key = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out
