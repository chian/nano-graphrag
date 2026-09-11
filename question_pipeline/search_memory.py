"""Compact search-strategy memory for iterative table aggregation.

Phase 2C adds a second, typed memory beside the free-text one: **where the
chain broke** for each accepted source, per target criterion family.  A pass
that learns "no criteria delta" knows nothing actionable; a pass that learns
*which* of five stages the source stopped at knows what to change next --
broader source families, more direct terminology, narrower subject anchors, or
provenance repair.

Everything in the path-outcome half of this module joins by **stable ID**:
criterion, snapshot, decision, action, task, and source.  Nothing is inferred
from record counts, from timing, or from text matching.  Two evidence bundles
with identical cardinalities in every set and different criterion transitions
classify differently, and that is asserted rather than assumed --
:func:`classify_path_outcome` branches only on set membership and emptiness.

The classification is recording only.  Routing on it is a later phase's.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .control import stable_id
from .reward import CostVector, aggregate_cost


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
        # ``sequence`` is the outcome's position in the stream this memory was
        # built from -- arrival order, which is chronology because outcomes are
        # appended as searches complete. It is an ORDERING KEY for recency
        # comparisons inside this build only: never a continuation offset,
        # never an artifact identity, and never emitted as a global counter.
        for sequence, outcome in enumerate(outcomes):
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
            _merge_outcome(record, outcome, sequence=sequence)

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
                scored.append((score, _latest_sequence(record), record))
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
        "skipped_by_reason": Counter(),
        "strategy_families": Counter(),
        "strategy_operators": Counter(),
        "successful_query_terms": Counter(),
        "failed_query_terms": Counter(),
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


def _merge_outcome(
    record: dict[str, Any],
    outcome: Mapping[str, Any],
    *,
    sequence: int = 0,
) -> None:
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

    record["attempt_count"] += 1
    record["accepted_source_ids"].extend(accepted_source_ids)
    record["accepted_urls"].extend(accepted_urls)
    record["skipped_by_reason"].update(skipped)
    record["attempts"].append(
        {
            "sequence": int(sequence),
            "episode_id": str(outcome.get("episode_id") or ""),
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
            "accepted_source_ids": accepted_source_ids,
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
            "post_episode_observed_delta": metadata.get("post_episode_observed_delta"),
            "post_episode_graph_node_delta": metadata.get(
                "post_episode_graph_node_delta",
            ),
            "post_episode_graph_edge_delta": metadata.get(
                "post_episode_graph_edge_delta",
            ),
            "post_episode_deficit_count": metadata.get("post_episode_deficit_count"),
            "post_episode_table_row_hits": metadata.get("post_episode_table_row_hits"),
            "post_episode_best_guess_hits": metadata.get("post_episode_best_guess_hits"),
            # Real semantic yield, joined by ID from 3A's own instrument
            # (`reward.score_criterion_yield`) once the strategy Episode that
            # ran this query has materialized and been scored -- never a row,
            # source, or graph-delta count.  Absent (``None``) until that join
            # has happened; ``[]`` once it has and found nothing.  See
            # ``pipeline.py:_annotate_recent_target_outcomes``, which is the
            # only writer of these two keys.
            "post_episode_credited_criterion_ids": metadata.get(
                "post_episode_credited_criterion_ids"
            ),
            "post_episode_credited_datapoint_kinds": metadata.get(
                "post_episode_credited_datapoint_kinds"
            ),
            "post_episode_cost_records": metadata.get("post_episode_cost_records") or [],
            "error": str(outcome.get("error") or "")[:500],
        }
    )


def _finalize_record(record: dict[str, Any]) -> dict[str, Any]:
    attempts = sorted(
        record["attempts"],
        key=lambda attempt: (
            _as_int(attempt.get("sequence")),
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
        "skipped_by_reason": dict(record["skipped_by_reason"]),
        "strategy_families": dict(record["strategy_families"]),
        "strategy_operators": dict(record["strategy_operators"]),
        "successful_query_terms": _top_counter(record["successful_query_terms"], 12),
        "failed_query_terms": _top_counter(record["failed_query_terms"], 12),
        # Unclipped, for the same reason as `strategy_history` in
        # `pipeline._deficits_with_strategy_history`: this is the memory the
        # next planner call uses to avoid reissuing a query, and a tail bounds
        # how far back "avoid repeating" can reach. Clipping here would also
        # have made the fix one layer up ineffective -- the pipeline's own
        # limit of 8 was reading from a list this had already cut to 12.
        # LATENT on every recorded run: largest observed is 2 attempts.
        "strategy_attempts": strategy_attempts,
        "attempts": attempts,
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
                "sequence": attempt.get("sequence"),
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
                "search_results": [],
                "accepted_urls": [],
                "prompt_arms": OrderedDict(),
                # Real semantic yield for the whole strategy attempt.
                # `None` means no query in this attempt has had its yield
                # measured yet -- distinct from `[]`, which means measured
                # and found zero. Routing reads this
                # (`strategy_state._credited_yield_productive`), so
                # collapsing the two would make "not known" indistinguishable
                # from "known to be nothing".
                "post_episode_credited_criterion_ids": None,
                "post_episode_credited_datapoint_kinds": None,
                "outcome_count": 0,
                "error_count": 0,
                "errors": [],
            },
        )
        query = str(attempt.get("query") or "")
        if query:
            strategy_attempt["queries"].append(query)
            strategy_attempt["query"] = query
        strategy_attempt["sequence"] = attempt.get("sequence")
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
            "post_episode_observed_delta",
            "post_episode_graph_node_delta",
            "post_episode_graph_edge_delta",
            "post_episode_deficit_count",
            "post_episode_table_row_hits",
            "post_episode_best_guess_hits",
        ):
            value = attempt.get(field_name)
            if value is not None:
                strategy_attempt[field_name] = value

        # The credited fields are **list-valued**, unlike the six scalars
        # above, and are merged by **union over criterion ID** rather than
        # last-write-wins. A strategy attempt spans several concrete
        # queries; a criterion credited by any one of them was credited by
        # the attempt, and the last query is not more authoritative than the
        # first. Union, never a count -- a criterion credited twice is one
        # criterion, and turning this into a tally would put volume back on
        # the routing path that cycles 1 and 2 removed it from.
        credited_ids = attempt.get("post_episode_credited_criterion_ids")
        if credited_ids is not None:
            merged_ids = strategy_attempt["post_episode_credited_criterion_ids"] or []
            strategy_attempt["post_episode_credited_criterion_ids"] = _unique(
                [*merged_ids, *credited_ids]
            )
        credited_kinds = attempt.get("post_episode_credited_datapoint_kinds")
        if credited_kinds is not None:
            merged_kinds = strategy_attempt["post_episode_credited_datapoint_kinds"] or []
            # Distinct kinds observed, not one entry per datapoint: the
            # membership is diagnostic, the multiplicity would be volume.
            strategy_attempt["post_episode_credited_datapoint_kinds"] = sorted(
                set(merged_kinds) | set(credited_kinds)
            )
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
            # WHERE THIS ARM CAME FROM, carried rather than derived. The
            # deterministic fallback arm carries a declared constant delta
            # ("deterministic fallback") and no sibling, so a strategy attempt
            # consisting only of fallback arms produces a contrast of identical
            # declared deltas that LOOKS like contrast and carries none. The
            # field is already on the task and on the control action, so this is
            # a field to forward, not a fact to reconstruct -- and nothing
            # reconstructs arm provenance from wording.
            "strategy_origin": str(attempt.get("strategy_origin") or ""),
            "prompt_delta": str(attempt.get("prompt_delta") or ""),
            "prompt_hypothesis": str(attempt.get("prompt_hypothesis") or ""),
            "expected_source_shape": str(
                attempt.get("expected_source_shape") or ""
            ),
            "queries": [],
            "firecrawl_hits": 0,
            "search_result_count": 0,
            "accepted_source_count": 0,
            "accepted_source_ids": [],
            "duplicate_url_count": 0,
            # Operational volume. Recorded for diagnostics, never scored --
            # see `_prompt_arm_score`.
            "table_row_hits": 0,
            "best_guess_hits": 0,
            # Real semantic yield, joined from 3A's reward once the round is
            # scored. `_yield_known` distinguishes "not measured yet" from
            # "measured, zero" -- the same distinction `RewardReport.score`
            # makes for cost.
            "_yield_known": False,
            "credited_criterion_ids": set(),
            "credited_datapoint_kinds": Counter(),
            "cost_records": [],
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
    arm["accepted_source_ids"].extend(attempt.get("accepted_source_ids") or [])
    arm["duplicate_url_count"] += _as_int(attempt.get("duplicate_url_count"))
    arm["table_row_hits"] += _as_int(attempt.get("post_episode_table_row_hits"))
    arm["best_guess_hits"] += _as_int(attempt.get("post_episode_best_guess_hits"))
    if attempt.get("post_episode_credited_criterion_ids") is not None:
        arm["_yield_known"] = True
        arm["credited_criterion_ids"].update(
            attempt.get("post_episode_credited_criterion_ids") or []
        )
        arm["credited_datapoint_kinds"].update(
            attempt.get("post_episode_credited_datapoint_kinds") or []
        )
    arm["cost_records"].extend(attempt.get("post_episode_cost_records") or [])
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
    raw_arms = list((wave.get("prompt_arms") or {}).values())
    # Every other arm's accepted sources, per arm -- the set an arm's own
    # accepted sources are checked against for "contributed no independent
    # evidence".  Computed before any arm is finalized so each arm sees its
    # siblings' full accepted set, not a partial one built up during a single
    # pass.
    accepted_by_identity = {id(arm): set(arm.get("accepted_source_ids") or []) for arm in raw_arms}
    prompt_arms = []
    for arm in raw_arms:
        own_identity = id(arm)
        sibling_union: set[str] = set()
        for other_identity, other_ids in accepted_by_identity.items():
            if other_identity != own_identity:
                sibling_union |= other_ids
        prompt_arms.append(
            _finalize_prompt_arm(arm, sibling_accepted_source_ids=frozenset(sibling_union))
        )
    return {
        "strategy_attempt_id": wave.get("strategy_attempt_id", ""),
        "sequence": wave.get("sequence"),
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
        "search_results": list(wave.get("search_results") or [])[:12],
        "post_episode_observed_delta": wave.get("post_episode_observed_delta"),
        "post_episode_graph_node_delta": wave.get("post_episode_graph_node_delta"),
        "post_episode_graph_edge_delta": wave.get("post_episode_graph_edge_delta"),
        "post_episode_deficit_count": wave.get("post_episode_deficit_count"),
        "post_episode_table_row_hits": wave.get("post_episode_table_row_hits"),
        "post_episode_best_guess_hits": wave.get("post_episode_best_guess_hits"),
        # Carried onto the finalized attempt because this is the shape
        # `pipeline._deficits_with_strategy_history` puts into
        # `strategy_history`, which is what `strategy_state._target_attempts`
        # hands to the routing exhaustion guard. Dropping it here starved
        # `_credited_yield_productive` of the only input it reads, so every
        # attempt read unmeasured and routing collapsed onto
        # `_default_target_order`.
        "post_episode_credited_criterion_ids": wave.get(
            "post_episode_credited_criterion_ids"
        ),
        "post_episode_credited_datapoint_kinds": wave.get(
            "post_episode_credited_datapoint_kinds"
        ),
        "prompt_arms": prompt_arms,
        "arm_contrast": _arm_contrast(prompt_arms),
        "error": error,
    }


def _finalize_prompt_arm(
    arm: Mapping[str, Any],
    *,
    sibling_accepted_source_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    query_count = len(arm.get("queries") or [])
    own_accepted_ids = _unique(arm.get("accepted_source_ids") or [])
    duplicate_with_sibling_ids = sorted(
        set(own_accepted_ids) & set(sibling_accepted_source_ids)
    )
    yield_known = bool(arm.get("_yield_known"))
    credited_criterion_ids = (
        sorted(arm.get("credited_criterion_ids") or set()) if yield_known else None
    )
    cost_vector = aggregate_cost(arm.get("cost_records") or [])
    outcome = _prompt_arm_outcome(
        arm,
        duplicate_with_sibling_count=len(duplicate_with_sibling_ids),
        credited_criterion_ids=credited_criterion_ids,
    )
    return {
        "prompt_arm_id": arm.get("prompt_arm_id", ""),
        "prompt_arm_name": arm.get("prompt_arm_name", ""),
        "prompt_arm_index": arm.get("prompt_arm_index"),
        "strategy_origin": arm.get("strategy_origin", ""),
        "prompt_delta": arm.get("prompt_delta", ""),
        "prompt_hypothesis": arm.get("prompt_hypothesis", ""),
        "expected_source_shape": arm.get("expected_source_shape", ""),
        "query_count": query_count,
        "queries": _unique(arm.get("queries") or []),
        "firecrawl_hits": _as_int(arm.get("firecrawl_hits")),
        "search_result_count": _as_int(arm.get("search_result_count")),
        "accepted_source_count": _as_int(arm.get("accepted_source_count")),
        "accepted_source_ids": own_accepted_ids[:20],
        "duplicate_url_count": _as_int(arm.get("duplicate_url_count")),
        # The duplicate penalty, individually observable: sources this arm
        # accepted that a sibling arm in the same evolution step also
        # accepted -- non-overlapping evidence contributed nothing new.
        "duplicate_with_sibling_source_ids": duplicate_with_sibling_ids,
        "duplicate_with_sibling_count": len(duplicate_with_sibling_ids),
        # Operational volume. Recorded for diagnostics, never scored -- see
        # `_prompt_arm_score`. Rows materialized and best-guess candidates
        # are not goodness; an arm that produced a hundred of either and
        # zero credited criteria scores as zero yield, not as volume.
        "table_row_hits": _as_int(arm.get("table_row_hits")),
        "best_guess_hits": _as_int(arm.get("best_guess_hits")),
        "skipped_by_reason": dict(arm.get("skipped_by_reason") or {}),
        "candidate_fates": dict(arm.get("candidate_fates") or {}),
        "accepted_urls": _unique(arm.get("accepted_urls") or [])[:10],
        "search_results": list(arm.get("search_results") or [])[:12],
        # The yield term: real datapoints from 3A's own instrument
        # (`reward.score_criterion_yield`), joined here by ID
        # (`crediting_source_ids` intersected against this arm's own
        # `accepted_source_ids`) -- not a source-local hit count, not an
        # accepted-source count, not a row materialized.
        "yield_known": yield_known,
        "credited_criterion_ids": credited_criterion_ids,
        "credited_criterion_count": (
            len(credited_criterion_ids) if credited_criterion_ids is not None else None
        ),
        "credited_datapoint_kinds": dict(arm.get("credited_datapoint_kinds") or {}),
        # The cost penalty, individually observable: 1B's own per-action
        # records, joined by `observation_id`/`nested_in` against this arm's
        # search task IDs -- never estimated or re-derived.
        "cost": cost_vector.to_dict(),
        # Whether the cost axis is meaningful for this arm at all. An
        # uninstrumented arm is charged no cost penalty, which would read as
        # "free" rather than "unknown" if a consumer could not tell them
        # apart -- so it is stated rather than inferred.
        "cost_known": cost_vector.available,
        "score": _prompt_arm_score(
            credited_criterion_ids=credited_criterion_ids,
            duplicate_with_sibling_count=len(duplicate_with_sibling_ids),
            cost_vector=cost_vector,
        ),
        "outcome": outcome,
        "error": "; ".join(arm.get("errors") or [])[:500],
    }


def _strategy_attempt_key(attempt: Mapping[str, Any]) -> str:
    attempt_id = str(attempt.get("strategy_attempt_id") or "")
    if attempt_id:
        return attempt_id
    payload = {
        "episode_id": attempt.get("episode_id"),
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
    """Nested per-arm contrast: each penalty axis stays a separate column.

    Routing reads this list, never an aggregate over it -- see
    `strategy_state.route_next_family`. Sorted so a known score always
    outranks an unmeasured one (`None`), and higher known scores come first;
    among unmeasured arms the order is the input order.
    """
    rows = [
        {
            "prompt_arm_id": arm.get("prompt_arm_id", ""),
            "prompt_arm_name": arm.get("prompt_arm_name", ""),
            # So a contrast row can distinguish a planner arm from the
            # deterministic fallback. Without it, an attempt made entirely of
            # fallback arms produces rows with identical declared deltas that
            # read as contrast and carry none. Carried as a field; no consumer
            # infers it from the arm's wording.
            "strategy_origin": arm.get("strategy_origin", ""),
            "expected_source_shape": arm.get("expected_source_shape", ""),
            "score": arm.get("score"),
            "yield_known": arm.get("yield_known", False),
            "credited_criterion_count": arm.get("credited_criterion_count"),
            "duplicate_with_sibling_count": arm.get("duplicate_with_sibling_count", 0),
            "cost": arm.get("cost", {}),
            "cost_known": arm.get("cost_known", False),
            "accepted_source_count": arm.get("accepted_source_count", 0),
            "outcome": arm.get("outcome", ""),
        }
        for arm in prompt_arms
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.get("score") is not None,
            float(row.get("score") or 0.0),
        ),
        reverse=True,
    )


#: Relative importances *within* the penalty term, never against yield.
#:
#: These are ratios, not magnitudes: the summed penalty is squashed into
#: ``[0, 1)`` by :func:`_penalty` before it reaches the score, so no
#: combination of them can ever cross an integer credited-criterion
#: boundary.  Changing one changes which arm wins a tie; none of them can
#: change whether a crediting arm outranks a non-crediting one.
_DUPLICATE_PENALTY_WEIGHT = 1.0
_COST_PENALTY_WEIGHT = 0.01


def _penalty(
    *,
    duplicate_with_sibling_count: int,
    cost_vector: CostVector,
) -> float:
    """Duplicate and cost penalties, squashed below one credited datapoint.

    ``raw / (1 + raw)`` maps ``[0, inf)`` onto ``[0, 1)``: strictly
    increasing, so ordering among arms that tied on yield is preserved
    exactly, and bounded, so the penalty is always worth less than one
    credited criterion.

    **This is the fix for a volume-scoring defect.**  The predecessor added
    the raw sum directly, with ``_DUPLICATE_PENALTY_WEIGHT = 1.0`` putting a
    *count of accepted sources* -- operational volume -- at parity with a
    real datapoint.  An arm crediting one criterion on a source a sibling
    also accepted scored 0.0, tying an arm that credited nothing; with two
    shared sources it scored -1.0 and ranked *below* it.  Since
    :func:`_arm_contrast` sorts by score and ``_route_from_contrast`` reads
    ``contrast[0]``, that arm's family would stop being exploited because a
    sibling happened to see the same paper.  A credited criterion is real
    data added whether or not a sibling also saw the source it came from.

    The module docstring's invariant is now enforced here rather than
    asserted: *a penalty axis can only reorder arms that already tied on
    real yield, and can never outrank one that credited more.*
    """

    raw = _DUPLICATE_PENALTY_WEIGHT * max(0, duplicate_with_sibling_count)
    if cost_vector.available:
        raw += _COST_PENALTY_WEIGHT * max(0, cost_vector.billable_calls)
    return raw / (1.0 + raw)


def _prompt_arm_score(
    *,
    credited_criterion_ids: list[str] | None,
    duplicate_with_sibling_count: int,
    cost_vector: CostVector,
) -> float | None:
    """Real yield, with duplicate and cost as strict tie-breaks.

    ``None`` -- not zero -- until the round this arm's queries ran in has
    been scored by `reward.score_criterion_yield` and joined back by ID.
    Comparing an unmeasured arm's score to a measured zero would silently
    treat "not yet known" as "measured and found wanting".

    The penalty is bounded strictly below 1 (see :func:`_penalty`), so for
    integer credited counts the ranking is lexicographic: credited count
    first, penalties only within a tie.

    **Cost caveat.** When an arm's cost is unknown (`cost_vector.available`
    false -- nothing instrumented it) no cost penalty is charged, so an
    uninstrumented arm reads as cheaper than an instrumented one rather than
    as unknown.  The arm carries ``cost_known`` so a consumer can see this
    rather than infer it; contrast rows within one evolution step come from
    one run and are normally all-known or all-unknown together.

    **Rounding caveat.** The result is rounded to 6 decimals, so a crediting
    arm whose raw penalty exceeds roughly ``2e6`` rounds to exactly the
    barren arm's ``0.0`` and ties it.  ``sorted`` is stable, so on a tie the
    earlier arm keeps ``contrast[0]`` and a crediting arm could lose the
    exploitation slot to input order.  It ties, never inverts -- the squash
    keeps the true value strictly above -- and the counts required
    (millions of shared sources or billable calls in one evolution step) are
    unreachable in practice.  Recorded rather than guarded, because a guard
    here would cost a branch on every scoring call to fix an arithmetic
    boundary no real run can reach.
    """
    if credited_criterion_ids is None:
        return None
    return round(
        len(credited_criterion_ids)
        - _penalty(
            duplicate_with_sibling_count=duplicate_with_sibling_count,
            cost_vector=cost_vector,
        ),
        6,
    )


def _prompt_arm_outcome(
    arm: Mapping[str, Any],
    *,
    duplicate_with_sibling_count: int,
    credited_criterion_ids: list[str] | None,
) -> str:
    """One of the pseudo-gradient's named classes.

    Matches `docs/TABLE_FILL_PROMPT_MUTATION_EXPERIMENTS.md`'s definition of
    the pseudo-gradient directly: which arms found non-overlapping useful
    evidence (`credited_yield`), which returned only duplicates
    (`all_duplicates` / `sibling_duplicate`), and which found promising
    sources that failed to support the target criteria (`accepted_no_yield`).
    """
    if credited_criterion_ids:
        return "credited_yield"
    if _as_int(arm.get("search_result_count")) <= 0:
        return "no_hits"
    skipped = _mapping(arm.get("skipped_by_reason"))
    if _as_int(skipped.get("duplicate_url")) >= _as_int(
        arm.get("search_result_count")
    ):
        return "all_duplicates"
    if duplicate_with_sibling_count > 0 and duplicate_with_sibling_count >= _as_int(
        arm.get("accepted_source_count")
    ):
        return "sibling_duplicate"
    if _as_int(arm.get("accepted_source_count")) > 0 and credited_criterion_ids is None:
        return "accepted_pending_yield"
    if _as_int(arm.get("accepted_source_count")) > 0:
        return "accepted_no_yield"
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


def _top_counter(counter: Counter, limit: int) -> list[str]:
    return [value for value, _ in counter.most_common(limit) if value]


def _latest_sequence(record: Mapping[str, Any]) -> int:
    """Recency of a record's newest attempt within THIS memory build.

    An ordering key over the build's own outcome stream and nothing more --
    see :meth:`SearchMemory.from_outcomes`.
    """

    attempts = record.get("attempts")
    if not isinstance(attempts, list):
        return -1
    return max(
        (_as_int(attempt.get("sequence")) for attempt in attempts),
        default=-1,
    )


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
    """Content words of one query, for the term-frequency memory. NOT an identity.

    Every surviving term, not the first twelve. These feed the
    `successful_query_terms` / `failed_query_terms` Counters, which the planner
    prompt reads to steer the next query's vocabulary, so a `[:12]` dropped the
    thirteenth-onward content word of a long query out of that memory purely
    for standing late in the string -- and a term that never enters the counter
    can never be learned from, in this round or any later one. The emitted
    payload is bounded downstream by `_top_counter(..., 12)`, which ranks by
    observed frequency; that is a bound on what is *reported*, and it was
    already doing the job this slice appeared to be doing.

    Explicitly not an identity tokenizer, and nothing here uses it as one: its
    only consumers are the two `Counter.update` calls above. A key built from a
    fixed-length token prefix would collide for two different long queries
    sharing their first twelve terms, which is why this must not acquire such a
    use without becoming single-owner and versioned first.
    """

    return [
        word
        for word in _WORD_RE.findall(_clean(query))
        if len(word) > 2 and word not in _STOPWORDS
    ]


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


# ---------------------------------------------------------------------------
# Path outcomes (phase 2C)
# ---------------------------------------------------------------------------
#
# One accepted source, one target criterion family, exactly one of five
# outcomes.  The five are the stages of a single chain -- graph evidence, a
# route worth walking, a candidate value for the target criterion, and finally
# a criterion transition -- and the recorded outcome names the furthest stage
# the source actually reached for that family.
#
# Why the furthest stage rather than the first break: the stages are nested by
# construction, so "candidate evidence exists" already implies a route reached
# the table.  Naming the first break would let one weakly scored route mask a
# transition that did happen, and the whole point of this record is to say what
# the next round should change.


#: Bumped when a change would move an existing (source, family) pair to a
#: different outcome.  Carried on every record so a consumer comparing outcomes
#: across versions sees a mismatch rather than a difference in yield.
PATH_OUTCOME_VERSION = "path_outcome_v1"


class PathOutcome(str, Enum):
    """Where the chain broke for one accepted source and one target family.

    Closed, ordered, and deliberately not prose.  A downstream stage groups by
    the identifier; nothing anywhere branches on a sentence.
    """

    #: The source contributed nothing to the traversal at all: no node, edge,
    #: or candidate row in the round's traversal state cites it.
    NO_GRAPH_EVIDENCE = "no_graph_evidence"

    #: Traversal rows cite the source, but no route to the family's table
    #: scored at or above the caller's selection threshold.
    ROUTES_ALL_LOW_SCORE = "routes_all_low_score"

    #: At least one route scored high, and still no row carries a value for
    #: this family's field on the strength of this source.
    NO_CANDIDATE_EVIDENCE = "no_candidate_evidence"

    #: A criterion in this family is supported citing this source, and no
    #: criterion newly gained support attributable to it.  Re-traversal of a
    #: source the graph already held lands here, which is the point.
    CANDIDATE_WITHOUT_TRANSITION = "candidate_without_transition"

    #: A criterion newly gained support, attributable to this source by ID.
    SUPPORT_GAINED_ATTRIBUTED = "support_gained_attributed"


#: Stage number of each outcome, weakest first.  A consumer that wants "how far
#: did this get" compares through this map rather than re-deriving an order,
#: and :class:`PathOutcomeMemory` uses it to keep the furthest stage a
#: (source, family) pair ever reached across rounds.
PATH_OUTCOME_STAGE: Mapping[PathOutcome, int] = {
    PathOutcome.NO_GRAPH_EVIDENCE: 1,
    PathOutcome.ROUTES_ALL_LOW_SCORE: 2,
    PathOutcome.NO_CANDIDATE_EVIDENCE: 3,
    PathOutcome.CANDIDATE_WITHOUT_TRANSITION: 4,
    PathOutcome.SUPPORT_GAINED_ATTRIBUTED: 5,
}


@dataclass(frozen=True)
class CriterionFamilyRef:
    """One target family: a table and a field, identified rather than described.

    This is 1D's criterion grouping with the subject coordinate projected out.
    A criterion is *(table, subject, field)*; a family is every criterion that
    asks the same question of a different subject, which is the grain a deficit
    search actually attacks and the grain a next-action decision is made at.

    The version-4 table-spec contract's ``required_criterion_families`` do not
    exist at baseline and are **not** what this is.
    """

    id: str
    table: str
    field: str

    @classmethod
    def create(cls, *, table: str, field: str) -> "CriterionFamilyRef":
        table = str(table or "").strip()
        field = str(field or "").strip()
        return cls(
            id=stable_id(
                {
                    "version": PATH_OUTCOME_VERSION,
                    "table": table,
                    "field": field,
                }
            ),
            table=table,
            field=field,
        )

    @classmethod
    def of_criterion(cls, ref: Any) -> "CriterionFamilyRef":
        """The family a criterion belongs to.

        Accepts a :class:`~question_pipeline.criteria.CriterionRef`, its
        ``to_dict()`` payload, or anything else exposing ``table`` and
        ``field`` -- so a caller reading a serialized snapshot does not have to
        rebuild the ref first.
        """

        if isinstance(ref, Mapping):
            table = ref.get("table", "")
            name = ref.get("field", "")
        else:
            table = getattr(ref, "table", "")
            name = getattr(ref, "field", "")
        return cls.create(table=table, field=name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_family_id": self.id,
            "table": self.table,
            "field": self.field,
        }


@dataclass(frozen=True)
class SemanticClaimPair:
    """One attributable semantic-claim / canonical-source pair.

    The pair outcome 5 is defined by: a criterion that newly gained support,
    and the source that gain is attributable to.  Both are IDs, and the
    transition and snapshot IDs travel with them so the pair can be traced back
    to the exact projection pair it was computed from.

    ``subject_bound`` is recorded, never gated on.  An unbound subject's ID is
    a content hash that moves as soon as a field fills, so a pair carrying
    ``False`` is a weaker claim about identity; that is reported rather than
    silently dropped or silently counted.
    """

    criterion_id: str
    source_id: str
    transition_id: str
    before_snapshot_id: str = ""
    after_snapshot_id: str = ""
    after_basis: str = ""
    subject_id: str = ""
    subject_bound: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "source_id": self.source_id,
            "criteria_transition_id": self.transition_id,
            "before_criteria_snapshot_id": self.before_snapshot_id,
            "after_criteria_snapshot_id": self.after_snapshot_id,
            "after_evidence_basis": self.after_basis,
            "subject_id": self.subject_id,
            "subject_bound": self.subject_bound,
        }


@dataclass(frozen=True)
class PathOutcomeEvidence:
    """What one accepted source produced for one target family in one scoring pass.

    Every field is an ID or a set of IDs.  There is no count anywhere, and no
    text: the classifier reads emptiness and membership, so a busy round and a
    productive one are distinguishable rather than the same number twice.

    ``graph_row_ids`` is every traversal row citing the source; ``route_ids``
    is the subset that carries route slots and reached this family's table;
    ``high_score_route_ids`` is the subset of those the caller's path-selection
    threshold admitted.  The threshold is the caller's policy -- scoring is
    2A's and gating is 2B's -- so it is applied before this record is built and
    is not re-decided here.
    """

    source_id: str
    family: CriterionFamilyRef
    graph_row_ids: tuple[str, ...] = ()
    route_ids: tuple[str, ...] = ()
    high_score_route_ids: tuple[str, ...] = ()
    supporting_criterion_ids: tuple[str, ...] = ()
    claim_pairs: tuple[SemanticClaimPair, ...] = ()
    before_snapshot_id: str = ""
    after_snapshot_id: str = ""
    #: The strategy Episode whose scoring pass produced this evidence bundle.
    #: Attribution of the source's own acquisition lives on the source record
    #: (``search_episode_id``), joined by ``source_id``.
    episode_id: str = ""
    decision_id: str = ""
    action_id: str = ""
    task_id: str = ""

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("a path outcome is recorded against a source ID")
        routes = set(self.route_ids)
        if not set(self.high_score_route_ids) <= routes:
            raise ValueError("every high-scoring route must also be a route")
        if not routes <= set(self.graph_row_ids):
            raise ValueError("every route must also be graph evidence")
        for pair in self.claim_pairs:
            if pair.source_id != self.source_id:
                raise ValueError(
                    "a claim pair on this record must be attributable to this "
                    "source; a pair naming another source belongs to that "
                    "source's record"
                )


def classify_path_outcome(evidence: PathOutcomeEvidence) -> PathOutcome:
    """Which of the five outcomes this evidence is, deterministically.

    Reads set emptiness only.  It never reads a cardinality, a timestamp, a
    round distance, or a string, so:

    * one high-scoring route and five hundred of them classify alike -- volume
      does not buy progress; and
    * two bundles with identical cardinalities everywhere and different
      criterion transitions do not classify alike.

    Outcome 5 requires the criterion transition.  Accepted sources, graph
    deltas, and source-local hits are outcome 4 at best, by construction: they
    reach ``supporting_criterion_ids`` and stop there.
    """

    if evidence.claim_pairs:
        return PathOutcome.SUPPORT_GAINED_ATTRIBUTED
    if evidence.supporting_criterion_ids:
        return PathOutcome.CANDIDATE_WITHOUT_TRANSITION
    if evidence.high_score_route_ids:
        return PathOutcome.NO_CANDIDATE_EVIDENCE
    if evidence.graph_row_ids:
        return PathOutcome.ROUTES_ALL_LOW_SCORE
    return PathOutcome.NO_GRAPH_EVIDENCE


def attributable_claim_pairs(
    transitions: Iterable[Any],
    *,
    source_id: str,
    family: CriterionFamilyRef,
    new_source_ids: Iterable[str],
    snapshot: Any = None,
) -> tuple[SemanticClaimPair, ...]:
    """The pairs that license outcome 5, and nothing weaker.

    Three conditions, all joins by ID:

    1. the transition is ``SUPPORT_GAINED``.  ``BASIS_CHANGED`` is a source
       being accepted under a criterion that was already supported, and
       ``EVIDENCE_CHANGED`` is an extractor rewording a value; neither is new
       support and neither may be credited as one;
    2. the criterion belongs to this family;
    3. ``source_id`` is in the transition's ``gained_source_ids`` **and** in
       ``new_source_ids``.

    ``snapshot`` is optional and is read only to record whether the criterion's
    subject was bound.  It may be a :class:`~question_pipeline.criteria.CriteriaSnapshot`
    or the ``by_criterion()`` index of one; a caller classifying many
    (source, family) pairs against one snapshot should build that index once
    and pass it, because rebuilding it per call is linear in the number of
    criteria and there can be hundreds of thousands of those.

    The third condition is the load-bearing one.  ``gained_source_ids`` means
    new *to the criterion*, not new to the run, and a freshly minted criterion
    has no "before", so its gained set is every source it cites however
    old.  Classifying outcome 5 on a non-empty gained set would therefore
    report re-traversal of an already-held graph as discovery -- which is what
    this corpus mostly does.  Intersecting with the sources newly accepted in
    the pass being classified is what separates the two, and it is an ID join,
    so it survives the gap when credit arrives passes after the ingest that
    earned it.
    """

    new_ids = {str(value) for value in new_source_ids if value}
    pairs: list[SemanticClaimPair] = []
    states = _states_by_criterion(snapshot)
    for transition in transitions or ():
        payload = _transition_payload(transition)
        if payload.get("kind") != "support_gained":
            continue
        if str(payload.get("table") or "") != family.table:
            continue
        if str(payload.get("field") or "") != family.field:
            continue
        gained = {str(value) for value in payload.get("gained_source_ids") or ()}
        if source_id not in gained or source_id not in new_ids:
            continue
        criterion_id = str(payload.get("criterion_id") or "")
        state = states.get(criterion_id)
        pairs.append(
            SemanticClaimPair(
                criterion_id=criterion_id,
                source_id=source_id,
                transition_id=str(payload.get("id") or ""),
                before_snapshot_id=str(payload.get("before_snapshot_id") or ""),
                after_snapshot_id=str(payload.get("after_snapshot_id") or ""),
                after_basis=str(payload.get("after_basis") or ""),
                subject_id=str(payload.get("subject_id") or ""),
                subject_bound=bool(getattr(getattr(state, "ref", None), "subject_bound", False)),
            )
        )
    return tuple(sorted(pairs, key=lambda pair: (pair.criterion_id, pair.transition_id)))


@dataclass(frozen=True)
class PathOutcomeRecord:
    """One (source, family) outcome, with the IDs it was joined on.

    ``id`` is content-addressed over the source, the family, and the snapshot
    pair -- not over the outcome -- so re-deriving the same round's evidence
    lands on the same record and a changed classification is visible as a
    changed field rather than as a new row.
    """

    id: str
    version: str
    source_id: str
    family: CriterionFamilyRef
    outcome: PathOutcome
    evidence: PathOutcomeEvidence

    @classmethod
    def create(cls, evidence: PathOutcomeEvidence) -> "PathOutcomeRecord":
        return cls(
            id=stable_id(
                {
                    "version": PATH_OUTCOME_VERSION,
                    "source_id": evidence.source_id,
                    "criterion_family_id": evidence.family.id,
                    "before_snapshot_id": evidence.before_snapshot_id,
                    "after_snapshot_id": evidence.after_snapshot_id,
                }
            ),
            version=PATH_OUTCOME_VERSION,
            source_id=evidence.source_id,
            family=evidence.family,
            outcome=classify_path_outcome(evidence),
            evidence=evidence,
        )

    @property
    def stage(self) -> int:
        return PATH_OUTCOME_STAGE[self.outcome]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_outcome_id": self.id,
            "path_outcome_version": self.version,
            "path_outcome": self.outcome.value,
            "path_outcome_stage": self.stage,
            "source_id": self.source_id,
            **self.family.to_dict(),
            "episode_id": self.evidence.episode_id,
            "before_criteria_snapshot_id": self.evidence.before_snapshot_id,
            "after_criteria_snapshot_id": self.evidence.after_snapshot_id,
            "control_decision_id": self.evidence.decision_id,
            "control_action_id": self.evidence.action_id,
            "search_task_id": self.evidence.task_id,
            "graph_row_ids": list(self.evidence.graph_row_ids),
            "route_ids": list(self.evidence.route_ids),
            "high_score_route_ids": list(self.evidence.high_score_route_ids),
            "supporting_criterion_ids": list(self.evidence.supporting_criterion_ids),
            "semantic_claim_pairs": [pair.to_dict() for pair in self.evidence.claim_pairs],
        }


class PathOutcomeMemory:
    """Path outcomes across scoring passes, keyed by (source, family).

    The key is two IDs, so the record survives the gap between a source being
    accepted and a criterion it supports passes later.  What is kept per
    key is the **furthest stage** that pair ever reached, and the union of its
    attributable claim pairs; a later pass that reaches no further does not
    erase what an earlier one established, and no pass's contribution is a
    count.
    """

    def __init__(self) -> None:
        self._records: "OrderedDict[tuple[str, str], PathOutcomeRecord]" = OrderedDict()
        self._pairs: dict[tuple[str, str], dict[tuple[str, str], SemanticClaimPair]] = {}

    def observe(self, record: PathOutcomeRecord) -> PathOutcomeRecord:
        """Fold one pass's record in, and return what is now held for its key."""

        key = (record.source_id, record.family.id)
        seen = self._pairs.setdefault(key, {})
        for pair in record.evidence.claim_pairs:
            seen[(pair.criterion_id, pair.transition_id)] = pair
        held = self._records.get(key)
        if held is None or record.stage > held.stage:
            self._records[key] = record
        return self._records[key]

    def observe_evidence(self, evidence: PathOutcomeEvidence) -> PathOutcomeRecord:
        return self.observe(PathOutcomeRecord.create(evidence))

    @property
    def records(self) -> tuple[PathOutcomeRecord, ...]:
        return tuple(self._records.values())

    def claim_pairs(self, source_id: str, family_id: str) -> tuple[SemanticClaimPair, ...]:
        held = self._pairs.get((str(source_id), str(family_id)), {})
        return tuple(sorted(held.values(), key=lambda pair: (pair.criterion_id, pair.transition_id)))

    def for_family(self, family_id: str) -> tuple[PathOutcomeRecord, ...]:
        return tuple(
            record for record in self._records.values() if record.family.id == str(family_id)
        )

    def for_source(self, source_id: str) -> tuple[PathOutcomeRecord, ...]:
        return tuple(
            record for record in self._records.values() if record.source_id == str(source_id)
        )

    def outcome_counts(self) -> dict[str, int]:
        """How many (source, family) pairs sit at each outcome.

        A report, never an input: nothing in this module branches on it, and a
        larger number here is a bigger run rather than a better one.
        """

        counts = {outcome.value: 0 for outcome in PathOutcome}
        for record in self._records.values():
            counts[record.outcome.value] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_outcome_version": PATH_OUTCOME_VERSION,
            "record_count": len(self._records),
            "outcome_counts": self.outcome_counts(),
            "records": [record.to_dict() for record in self._records.values()],
        }


def _transition_payload(transition: Any) -> dict[str, Any]:
    """Read a criterion transition from the object or its serialized form."""

    if isinstance(transition, Mapping):
        kind = transition.get("kind")
        return {
            "id": transition.get("criteria_transition_id") or transition.get("id"),
            "kind": getattr(kind, "value", kind),
            "criterion_id": transition.get("criterion_id"),
            "table": transition.get("table"),
            "field": transition.get("field"),
            "subject_id": transition.get("subject_id"),
            "before_snapshot_id": transition.get("before_criteria_snapshot_id")
            or transition.get("before_snapshot_id"),
            "after_snapshot_id": transition.get("after_criteria_snapshot_id")
            or transition.get("after_snapshot_id"),
            "after_basis": transition.get("after_evidence_basis")
            or transition.get("after_basis"),
            "gained_source_ids": transition.get("gained_source_ids") or (),
        }
    kind = getattr(transition, "kind", None)
    return {
        "id": getattr(transition, "id", ""),
        "kind": getattr(kind, "value", kind),
        "criterion_id": getattr(transition, "criterion_id", ""),
        "table": getattr(transition, "table", ""),
        "field": getattr(transition, "field", ""),
        "subject_id": getattr(transition, "subject_id", ""),
        "before_snapshot_id": getattr(transition, "before_snapshot_id", ""),
        "after_snapshot_id": getattr(transition, "after_snapshot_id", ""),
        "after_basis": getattr(transition, "after_basis", ""),
        "gained_source_ids": getattr(transition, "gained_source_ids", ()) or (),
    }


def _states_by_criterion(snapshot: Any) -> Mapping[str, Any]:
    if snapshot is None:
        return {}
    if isinstance(snapshot, Mapping):
        return snapshot
    by_criterion = getattr(snapshot, "by_criterion", None)
    if callable(by_criterion):
        return dict(by_criterion())
    return {}
