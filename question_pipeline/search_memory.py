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
            "accepted_source_count": len(accepted_source_ids),
            "accepted_urls": accepted_urls[:5],
            "duplicate_url_count": len(duplicate_urls),
            "skipped_by_reason": dict(skipped),
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
            "error": str(outcome.get("error") or "")[:500],
        }
    )


def _finalize_record(record: dict[str, Any]) -> dict[str, Any]:
    attempts = sorted(
        record["attempts"],
        key=lambda attempt: (
            _round_sort_value(attempt.get("round")),
            str(attempt.get("query") or ""),
        ),
    )
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
        "attempts": record.get("attempts", [])[-6:],
    }


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
