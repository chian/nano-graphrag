"""Question-level fill goals for iterative table aggregation."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
import re
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .completion import (
    normalize_completion_state,
    open_completion_bins,
    open_completion_issues,
    scope_probe_context,
)
from .criteria import is_missing_value
from .provenance import is_provenance_name

#: This module kept its own nine-token set until phase 4E-c. `criteria` now owns
#: what "nothing here" means for every consumer, and its set is the union of
#: what five producers meant by absence -- so this module gains nine tokens
#: (`-`, `--`, `<null>`, `[null]`, `not available`, `not found`, `not provided`,
#: `not reported`, `not stated`) and contributes the one no other set had,
#: `"not specified in current evidence"`.
#:
#: THE DIRECTION IS REGISTERED, NOT ASSUMED. This module decides which columns
#: are worth searching for, so more tokens reading as missing means more cells
#: counted missing, more columns judged fillable, more deficits planned and more
#: searches issued.


@dataclass(frozen=True)
class TargetSlot:
    key: str
    slot_type: str
    status: str
    table: str
    values: dict[str, Any] = field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "slot_type": self.slot_type,
            "status": self.status,
            "table": self.table,
            "values": dict(self.values),
            "missing_fields": list(self.missing_fields),
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True)
class FillDeficit:
    """One generic missing piece the table-fill scheduler can search for."""

    id: str
    deficit_type: str
    target_table: str
    priority: float
    description: str
    target_id: str = ""
    target_name: str = ""
    key_columns: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    anchor_values: dict[str, Any] = field(default_factory=dict)
    evidence_gap: str = ""
    expected_minimum_count: int = 0
    observed_count: int = 0
    deficit_count: int = 0
    gap_row_count: int = 0
    row_count: int = 0
    known_missing_examples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "deficit_type": self.deficit_type,
            "target_id": self.target_id,
            "target_name": self.target_name,
            "target_table": self.target_table,
            "priority": round(self.priority, 3),
            "description": self.description,
            "key_columns": list(self.key_columns),
            "missing_fields": list(self.missing_fields),
            "anchor_values": dict(self.anchor_values),
            "evidence_gap": self.evidence_gap,
            "expected_minimum_count": self.expected_minimum_count,
            "observed_count": self.observed_count,
            "deficit_count": self.deficit_count,
            "gap_row_count": self.gap_row_count,
            "row_count": self.row_count,
            "known_missing_examples": list(self.known_missing_examples),
        }


@dataclass
class FillGoalState:
    label: int | str
    round: int | None
    mode: str
    fulfilled: bool
    stop_rule: str
    unmet_criteria: list[str]
    criteria: list[dict[str, Any]]
    target_estimate: dict[str, Any]
    target_catalog: dict[str, Any]
    coverage: dict[str, Any]
    search_frontier: dict[str, Any]
    analysis: list[dict[str, Any]]
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TableFillGoalTracker:
    """Track whether exported answer tables fill a searched universe estimate."""

    table_schemas: Mapping[str, Sequence[str]] = field(default_factory=dict)
    table_columns: Mapping[str, Sequence[str]] = field(default_factory=dict)
    table_key_columns: Mapping[str, Sequence[str]] = field(default_factory=dict)
    cold_start_columns: Mapping[str, Sequence[str]] = field(default_factory=dict)
    cold_start_anchors: Mapping[
        str,
        Sequence[Mapping[str, str]],
    ] = field(default_factory=dict)
    best_guess_columns: Mapping[str, Sequence[str]] = field(default_factory=dict)
    all_seen_slot_keys: set[str] = field(default_factory=set)
    new_slot_history: list[dict[str, Any]] = field(default_factory=list)

    def prompt_context(
        self,
        table_rows: Mapping[str, list[dict[str, Any]]],
        gaps: Iterable[str],
        universe_estimate: Mapping[str, Any] | None = None,
        completion_state: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        slots = _observed_slots(table_rows, self.table_schemas)
        open_slots = [slot for slot in slots if slot.status != "covered"]
        # Materialized once: `gaps` is an Iterable, and reading it more than
        # once would silently yield an empty list on the second read.
        gap_list = list(gaps)
        return {
            "target_table_names": sorted(
                str(name)
                for name in table_rows
                if str(name).strip()
            ),
            "tables": [
                _table_profile(
                    name,
                    rows,
                    self.table_columns.get(
                        name,
                        self.table_schemas.get(name, ()),
                    ),
                )
                for name, rows in table_rows.items()
            ],
            "observed_slot_count": len(slots),
            "open_observed_slot_count": len(open_slots),
            "observed_slot_counts": _slot_counts(slots),
            "open_observed_slot_counts": _slot_counts(open_slots),
            # KNOWN TRUNCATION, DECLARED, AND STRUCTURALLY STARVING.
            #
            # These two are prompt payload, not a rule about the data, so by
            # the no-truncation principle they should be windows. They are not
            # converted here because the fix is not local: on the live
            # earthquake run's round-2 table there are 270 open slots measuring
            # 786,337 characters against the 103,919 that `[:40]` sends, and
            # this mapping is delivered WHOLE to every deficit-planner call.
            # Unbounding it without giving `strategy.target_deficit_queries` a
            # second windowed axis would put ~870,000 characters into each of
            # that call's windows.
            #
            # The selection is NOT arbitrary, which is worse than if it were.
            # `_observed_slots` sorts by `(slot_type, key)` and `key` is
            # `f"{table}::{index}-{sha1[:12]}"`, so the discriminator is the
            # STRINGIFIED ROW INDEX and the hash only breaks ties. The observed
            # first twelve are `0-, 1-, 10-, 100-, 101-, 102-, ...`:
            # lexicographic on the index string, hence deterministic and
            # identical every round. The same 40 of 270 slots are shown for the
            # life of the run and the other 230 are structurally unreachable --
            # the same self-sustaining starvation removed from the column path
            # in `_incomplete_columns` two hundred lines below, which a reader
            # should not have to rediscover here.
            "sample_open_slots": [
                slot.to_dict() for slot in open_slots[:40]
            ],
            "sample_open_slots_disclosure": {
                "sent": min(40, len(open_slots)),
                "total": len(open_slots),
                "omitted": max(0, len(open_slots) - 40),
                "selection": (
                    "first 40 by lexicographic stringified row index; "
                    "deterministic and STABLE across rounds, so the omitted "
                    "slots never rotate in and are unreachable for the life "
                    "of the run"
                ),
                "rotates_across_rounds": False,
                "reason": "prompt payload not yet windowed; see module note",
            },
            "sample_gaps": gap_list[:40],
            "sample_gaps_disclosure": {
                "sent": min(40, len(gap_list)),
                "total": len(gap_list),
                "omitted": max(0, len(gap_list) - 40),
                "selection": (
                    "first 40 in the caller's gap order; whether the omitted "
                    "gaps rotate depends entirely on the caller, and on the "
                    "table-gap path they do not"
                ),
                "rotates_across_rounds": False,
                "reason": "prompt payload not yet windowed; see module note",
            },
            "current_universe_estimate": compact_estimate_for_prompt(
                universe_estimate,
                table_rows=table_rows,
            ),
            "completion_scope": scope_probe_context(completion_state or {}),
        }

    def evaluate(
        self,
        *,
        artifact_label: int | str,
        table_rows: Mapping[str, list[dict[str, Any]]],
        universe_estimate: Mapping[str, Any] | None,
        search_frontier: Mapping[str, Any],
        search_outcomes: list[dict[str, Any]],
        paper_count: int,
        max_papers: int,
        paper_budget_available: bool,
        gap_search_tasks: list[dict[str, Any]],
        goal_search_tasks: list[dict[str, Any]],
        completion_state: Mapping[str, Any] | None = None,
        update_history: bool = True,
    ) -> FillGoalState:
        slots = _observed_slots(table_rows, self.table_schemas)
        slot_keys = {slot.key for slot in slots}
        open_slots = [slot for slot in slots if slot.status != "covered"]
        estimate = normalize_universe_estimate(
            universe_estimate,
            table_rows=table_rows,
        )
        completion = normalize_completion_state(completion_state)
        completion_issues = open_completion_issues(completion)
        completion_bins = open_completion_bins(completion)

        if (
            not update_history
            and self.new_slot_history
            and self.new_slot_history[-1].get("label") == artifact_label
        ):
            new_slots = set(self.new_slot_history[-1].get("new_slots") or [])
        else:
            previous_slots = set(self.all_seen_slot_keys)
            new_slots = slot_keys - previous_slots
            self.all_seen_slot_keys.update(slot_keys)
            self.new_slot_history.append(
                {
                    "label": artifact_label,
                    "round": (
                        artifact_label
                        if isinstance(artifact_label, int)
                        else None
                    ),
                    "new_count": len(new_slots),
                    "new_slots": sorted(new_slots),
                }
            )

        pending_tasks = int(search_frontier.get("pending_tasks") or 0)
        count_targets = estimate.get("count_targets") or []
        unestimated_targets = estimate.get("unestimated_count_targets") or []
        unmet_targets = [
            target
            for target in count_targets
            if _as_int(target.get("deficit_count")) > 0
        ]
        universe_outcomes = [
            outcome
            for outcome in search_outcomes
            if outcome.get("topic") == "goal_catalog"
        ]
        universe_sources = {
            source
            for outcome in universe_outcomes
            for source in outcome.get("accepted_source_ids", [])
            if source
        }

        criteria = [
            {
                "name": "search space probed",
                "satisfied": bool(completion.get("search_space_probes")),
                "detail": (
                    f"{len(completion.get('search_space_probes') or [])} "
                    "search-space probes recorded"
                ),
            },
            {
                "name": "completion estimate consistent",
                "satisfied": (
                    completion.get("scope_status") == "estimated"
                    and not completion_issues
                    and not completion_bins
                ),
                "detail": (
                    f"scope_status={completion.get('scope_status')}; "
                    f"{len(completion_issues)} blocking estimate issues; "
                    f"{len(completion_bins)} underexplored bins"
                ),
            },
            {
                "name": "answer universe estimated",
                "satisfied": estimate.get("status") == "estimated",
                "detail": (
                    f"status={estimate.get('status')}; "
                    f"{_cited_discovery_source_count(estimate)} "
                    "discovery sources cited by the estimate"
                ),
            },
            {
                "name": "count targets estimated",
                "satisfied": bool(count_targets),
                "detail": f"{len(count_targets)} answer-universe count targets",
            },
            {
                "name": "all target families quantified",
                "satisfied": not unestimated_targets,
                "detail": (
                    f"{len(unestimated_targets)} row families still lack "
                    "source-supported expected counts"
                ),
            },
            {
                "name": "all estimated count targets covered",
                "satisfied": bool(count_targets) and not unmet_targets,
                "detail": f"{len(unmet_targets)}/{len(count_targets)} count targets still short",
            },
            {
                "name": "search frontier drained",
                "satisfied": pending_tasks == 0,
                "detail": f"{pending_tasks} pending search tasks",
            },
        ]
        fulfilled = all(criterion["satisfied"] for criterion in criteria)
        unmet = [
            f"{criterion['name']}: {criterion['detail']}"
            for criterion in criteria
            if not criterion["satisfied"]
        ]

        catalog = {
            "slots": [slot.to_dict() for slot in slots],
            "open_slots": [slot.to_dict() for slot in open_slots],
            "slot_counts": _slot_counts(slots),
            "open_slot_counts": _slot_counts(open_slots),
            "unmet_count_targets": unmet_targets,
            "unestimated_count_targets": unestimated_targets,
            "fill_deficits": [
                deficit.to_dict()
                for deficit in build_fill_deficits(
                    table_rows,
                    estimate,
                    table_columns=self.table_columns,
                    cold_start_columns=self.cold_start_columns,
                    table_key_columns=self.table_key_columns,
                    cold_start_anchors=self.cold_start_anchors,
                )
            ],
        }
        coverage = {
            "table_rows": {
                name: len(rows)
                for name, rows in table_rows.items()
            },
            "open_observed_slots": len(open_slots),
            "new_observed_slot_count": len(new_slots),
            "new_observed_slots": sorted(new_slots),
            "goal_discovery_searches_completed": len(universe_outcomes),
            "goal_discovery_sources_accepted": len(universe_sources),
            "gap_search_tasks_enqueued": len(gap_search_tasks),
            "goal_search_tasks_enqueued": len(goal_search_tasks),
            "papers_fetched": paper_count,
            "max_papers": max_papers,
        }
        search_state = {
            **search_frontier,
            "paper_budget_available": paper_budget_available,
        }
        analysis = _analysis_rows(
            criteria=criteria,
            estimate=estimate,
            completion=completion,
            catalog=catalog,
            coverage=coverage,
            search_state=search_state,
        )
        if not paper_budget_available and not fulfilled:
            analysis.append(
                {
                    "scope": "out_of_scope",
                    "outcome": f"paper budget exhausted at {paper_count}/{max_papers}",
                    "what_it_means": (
                        "the runtime cannot search further without a larger paper budget"
                    ),
                    "interpretation": (
                        "budget exhaustion explains an incomplete run; it is not "
                        "evidence that the task-level stop rule was satisfied"
                    ),
                }
            )

        return FillGoalState(
            label=artifact_label,
            round=artifact_label if isinstance(artifact_label, int) else None,
            mode="table_fill",
            fulfilled=fulfilled,
            stop_rule=(
                "Stop only after search-space breadth probes and retrieved "
                "discovery evidence yield a consistent question-specific "
                "answer-universe estimate, every final record family has a "
                "source-supported realistic expected count, every estimated "
                "count target is covered by the exported answer tables, and "
                "the search frontier has no queued work."
            ),
            unmet_criteria=unmet,
            criteria=criteria,
            target_estimate=estimate,
            target_catalog=catalog,
            coverage=coverage,
            search_frontier=search_state,
            analysis=analysis,
            config={
                "table_schemas": {
                    name: list(columns)
                    for name, columns in self.table_schemas.items()
                },
                "table_columns": {
                    name: list(columns)
                    for name, columns in self.table_columns.items()
                },
                "table_key_columns": {
                    name: list(columns)
                    for name, columns in self.table_key_columns.items()
                },
                "cold_start_columns": {
                    name: list(columns)
                    for name, columns in self.cold_start_columns.items()
                },
                "cold_start_anchors": {
                    name: [dict(anchor) for anchor in anchors]
                    for name, anchors in self.cold_start_anchors.items()
                },
                "best_guess_columns": {
                    name: list(columns)
                    for name, columns in self.best_guess_columns.items()
                },
            },
        )


CoverageGoalState = FillGoalState
TableCoverageGoalTracker = TableFillGoalTracker


def normalize_universe_estimate(
    raw: Mapping[str, Any] | None,
    *,
    table_rows: Mapping[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Coerce an LLM estimate into count targets the stop rule can score."""
    if not isinstance(raw, Mapping):
        raw = {}

    deliverable_tables = {
        str(name).strip()
        for name in (table_rows or {})
        if str(name).strip()
    }
    fallback_target_table = _sole_deliverable_table(deliverable_tables)
    raw_count_targets = _first_raw_section(raw, "count_targets", "targets")
    raw_unestimated_targets = _first_raw_section(raw, "unestimated_count_targets")
    raw_out_of_scope_targets = _first_raw_section(raw, "out_of_scope_count_targets")

    targets: list[dict[str, Any]] = []
    unestimated_targets: list[dict[str, Any]] = []
    out_of_scope_targets: list[dict[str, Any]] = []
    for raw_index, item in enumerate(_as_list(raw_count_targets)):
        if not isinstance(item, Mapping):
            continue
        target, expected_minimum = _coerce_count_target(
            item,
            raw,
            fallback_index=raw_index + 1,
            fallback_target_table=fallback_target_table,
        )
        if not _target_table_is_deliverable(
            str(target.get("target_table") or ""),
            deliverable_tables,
        ):
            out_of_scope_targets.append(
                {
                    **target,
                    "reason": _target_table_rejection_reason(
                        str(target.get("target_table") or ""),
                        deliverable_tables,
                    ),
                }
            )
            continue
        target_errors = _target_validation_errors(target)
        if expected_minimum <= 0 or target_errors:
            reason = (
                "expected_minimum_count is missing"
                if expected_minimum <= 0
                else "; ".join(target_errors)
            )
            unestimated_targets.append({**target, "reason": reason})
            continue
        targets.append(_attach_observed_count(target, table_rows or {}))

    for raw_index, item in enumerate(_as_list(raw_unestimated_targets)):
        if not isinstance(item, Mapping):
            continue
        target, _ = _coerce_count_target(
            item,
            raw,
            fallback_index=len(targets) + len(unestimated_targets) + raw_index + 1,
            fallback_target_table=fallback_target_table,
        )
        if not _target_table_is_deliverable(
            str(target.get("target_table") or ""),
            deliverable_tables,
        ):
            out_of_scope_targets.append(
                {
                    **target,
                    "reason": _target_table_rejection_reason(
                        str(target.get("target_table") or ""),
                        deliverable_tables,
                    ),
                }
            )
            continue
        unestimated_targets.append(
            {
                **target,
                "reason": (
                    _clean_display(item.get("reason"))
                    or "expected_minimum_count is missing"
                ),
            }
        )

    for raw_index, item in enumerate(_as_list(raw_out_of_scope_targets)):
        if not isinstance(item, Mapping):
            continue
        target, _ = _coerce_count_target(
            item,
            raw,
            fallback_index=(
                len(targets)
                + len(unestimated_targets)
                + len(out_of_scope_targets)
                + raw_index
                + 1
            ),
        )
        out_of_scope_targets.append(
            {
                **target,
                "reason": (
                    _clean_display(item.get("reason"))
                    or _target_table_rejection_reason(
                        str(target.get("target_table") or ""),
                        deliverable_tables,
                    )
                ),
            }
        )

    status = _clean_display(raw.get("status")).lower() or "missing"
    if status not in {"missing", "insufficient_evidence", "estimated"}:
        status = "missing"
    if unestimated_targets:
        status = "insufficient_evidence"
    elif targets and status != "estimated":
        status = "insufficient_evidence"
    elif not targets and status == "estimated":
        status = "insufficient_evidence"

    return {
        "status": status,
        "scope_summary": _clean_display(raw.get("scope_summary")),
        "search_space_summary": _clean_display(raw.get("search_space_summary")),
        "expected_axes": _record_list(raw.get("expected_axes") or raw.get("axes")),
        "underexplored_bins": _record_list(raw.get("underexplored_bins")),
        "estimate_issues": _record_list(
            raw.get("estimate_issues") or raw.get("issues")
        ),
        "count_targets": targets,
        "unestimated_count_targets": unestimated_targets,
        "out_of_scope_count_targets": out_of_scope_targets,
        "supporting_source_ids": _unique(raw.get("supporting_source_ids")),
        "supporting_queries": _unique(raw.get("supporting_queries")),
        "unresolved_questions": _unique(raw.get("unresolved_questions")),
        "suggested_queries": _unique(raw.get("suggested_queries")),
        "raw": dict(raw),
    }


def _cited_discovery_source_count(estimate: Mapping[str, Any]) -> int:
    """Distinct discovery sources the estimate actually cites, at any level.

    Counting only the estimate-level `supporting_source_ids` reports zero
    forever: that list is deliberately never populated, because
    `_coerce_count_target` falls back to it and a union there would let an
    unprobed family inherit another family's sources and clear
    `_target_validation_errors` -- the guard defeated by data rather than by a
    visible change to the guard.

    This number is not decoration. It reaches an LLM prompt that gates whether
    fetched sources are accepted, so an estimate resting on real observations
    must not describe itself as resting on none.
    """

    seen: set[str] = set()
    for source_id in estimate.get("supporting_source_ids") or []:
        text = str(source_id or "").strip()
        if text:
            seen.add(text)
    for target in estimate.get("count_targets") or []:
        if not isinstance(target, Mapping):
            continue
        for source_id in target.get("supporting_source_ids") or []:
            text = str(source_id or "").strip()
            if text:
                seen.add(text)
    return len(seen)


def merge_universe_estimates(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    *,
    table_rows: Mapping[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Merge a fresh estimate without dropping previously discovered families."""
    base = normalize_universe_estimate(previous, table_rows=table_rows)
    fresh = normalize_universe_estimate(current, table_rows=table_rows)

    out_of_scope = _merge_targets(
        fresh.get("out_of_scope_count_targets") or [],
        base.get("out_of_scope_count_targets") or [],
    )
    out_of_scope_keys = _target_keys(out_of_scope)

    count_targets = _merge_targets(
        fresh.get("count_targets") or [],
        base.get("count_targets") or [],
        exclude_keys=out_of_scope_keys,
    )
    count_keys = _target_keys(count_targets)

    unestimated_targets = _merge_targets(
        fresh.get("unestimated_count_targets") or [],
        base.get("unestimated_count_targets") or [],
        exclude_keys=count_keys | out_of_scope_keys,
    )

    merged = {
        **fresh,
        "expected_axes": _merge_records(
            fresh.get("expected_axes") or [],
            base.get("expected_axes") or [],
        ),
        "underexplored_bins": (
            fresh.get("underexplored_bins") or []
            if isinstance(current, Mapping) and "underexplored_bins" in current
            else base.get("underexplored_bins") or []
        ),
        "estimate_issues": (
            fresh.get("estimate_issues") or []
            if (
                isinstance(current, Mapping)
                and ("estimate_issues" in current or "issues" in current)
            )
            else base.get("estimate_issues") or []
        ),
        "count_targets": [
            _attach_observed_count(target, table_rows or {})
            for target in count_targets
        ],
        "unestimated_count_targets": unestimated_targets,
        "out_of_scope_count_targets": out_of_scope,
        "supporting_source_ids": _unique(
            [
                *(base.get("supporting_source_ids") or []),
                *(fresh.get("supporting_source_ids") or []),
            ],
        ),
        "supporting_queries": _unique(
            [
                *(base.get("supporting_queries") or []),
                *(fresh.get("supporting_queries") or []),
            ],
        ),
        "unresolved_questions": _unique(
            [
                *(fresh.get("unresolved_questions") or []),
                *(base.get("unresolved_questions") or []),
            ],
        ),
        "suggested_queries": _unique(
            [
                *(fresh.get("suggested_queries") or []),
                *(base.get("suggested_queries") or []),
            ],
        ),
    }
    if merged["count_targets"] and not merged["unestimated_count_targets"]:
        if "estimated" in {base.get("status"), fresh.get("status")}:
            merged["status"] = "estimated"
        else:
            merged["status"] = "insufficient_evidence"
    elif not merged["count_targets"] and not merged["unestimated_count_targets"]:
        merged["status"] = "missing"
    else:
        merged["status"] = "insufficient_evidence"
    return merged


def _merge_targets(
    primary: Iterable[Mapping[str, Any]],
    secondary: Iterable[Mapping[str, Any]],
    *,
    exclude_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    exclude_keys = exclude_keys or set()
    merged: dict[str, dict[str, Any]] = {}
    for target in [*list(primary), *list(secondary)]:
        if not isinstance(target, Mapping):
            continue
        key = _target_family_key(target)
        if not key or key in exclude_keys or key in merged:
            continue
        merged[key] = dict(target)
    return list(merged.values())


def _merge_records(
    primary: Iterable[Mapping[str, Any]],
    secondary: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in [*list(primary), *list(secondary)]:
        if not isinstance(record, Mapping):
            continue
        payload = dict(record)
        key = (
            _clean_key(payload.get("id"))
            or _clean_key(payload.get("name"))
            or _clean_key(payload.get("axis"))
            or _clean_key(payload.get("description"))
        )
        if not key:
            raw = json.dumps(payload, sort_keys=True, default=str)
            key = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        if key not in merged:
            merged[key] = payload
    return list(merged.values())


def _record_list(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _as_list(value):
        if isinstance(item, Mapping):
            records.append(dict(item))
        elif item:
            records.append({"description": str(item)})
    return records


def _target_keys(targets: Iterable[Mapping[str, Any]]) -> set[str]:
    return {
        key
        for target in targets
        if isinstance(target, Mapping)
        for key in [_target_family_key(target)]
        if key
    }


def _target_family_key(target: Mapping[str, Any]) -> str:
    table = _clean_key(target.get("target_table"))
    name = _clean_key(target.get("name"))
    if table or name:
        payload = {
            "target_table": table,
            "name": name,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    columns = tuple(
        sorted(_clean_key(column) for column in _as_list(target.get("key_columns")))
    )
    columns = tuple(column for column in columns if column)
    payload = {
        "key_columns": columns,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _first_raw_section(raw: Mapping[str, Any], *keys: str) -> Any:
    """Return a normalized section, falling back to a preserved model payload."""
    for key in keys:
        value = raw.get(key)
        if value:
            return value

    raw_payload = raw.get("raw")
    if not isinstance(raw_payload, Mapping):
        return None

    for key in keys:
        value = raw_payload.get(key)
        if value:
            return value
    return None


def _coerce_count_target(
    item: Mapping[str, Any],
    raw: Mapping[str, Any],
    *,
    fallback_index: int,
    fallback_target_table: str = "",
) -> tuple[dict[str, Any], int]:
    expected_minimum = _as_int(
        item.get("expected_minimum_count")
        or item.get("minimum_expected_count")
        or item.get("min_count")
        or item.get("lower_bound")
    )
    # `expected_count`, `expected_maximum_count` and `expected_count_basis` are
    # gone with the Chao1 estimator that was their only producer. Only the
    # observed census survives: `expected_minimum_count` is a count of rows
    # actually seen, which was the one of the three that was ever a
    # measurement rather than an extrapolation.
    target_table = (
        item.get("target_table")
        or item.get("table_name")
        or item.get("table")
        or item.get("output_table")
        or fallback_target_table
    )
    target = {
        "name": _clean_display(item.get("name")) or f"target_{fallback_index}",
        "description": _clean_display(item.get("description")),
        "target_table": str(target_table or "").strip(),
        "key_columns": [
            str(column).strip()
            for column in _as_list(item.get("key_columns"))
            if str(column).strip()
        ],
        "expected_minimum_count": expected_minimum if expected_minimum > 0 else None,
        "basis": _clean_display(item.get("basis") or item.get("rationale")),
        "supporting_source_ids": _unique(
            item.get("supporting_source_ids")
            or item.get("source_ids")
            or raw.get("supporting_source_ids")
        ),
        # Which namespace those ids live in. Normalization rebuilds targets
        # from a fixed key list, so a kind not carried here is a kind that
        # never reaches a consumer -- and an unlabelled id is one a join has to
        # guess about. Empty means the producer did not say.
        "supporting_source_id_kind": _clean_display(
            item.get("supporting_source_id_kind")
        ),
        "known_missing_examples": _unique(
            item.get("known_missing_examples") or item.get("missing_examples")
        ),
    }
    target["id"] = _target_id(target)
    return target, expected_minimum


def _sole_deliverable_table(deliverable_tables: set[str]) -> str:
    if len(deliverable_tables) != 1:
        return ""
    return sorted(deliverable_tables)[0]


def _target_table_is_deliverable(
    target_table: str,
    deliverable_tables: set[str],
) -> bool:
    if not target_table:
        return False
    return not deliverable_tables or target_table in deliverable_tables


def _target_table_rejection_reason(
    target_table: str,
    deliverable_tables: set[str],
) -> str:
    if not target_table:
        return "target_table is missing"
    return (
        "target_table is outside the currently materialized final tables: "
        f"{', '.join(sorted(deliverable_tables))}"
    )


def _target_validation_errors(target: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not target.get("supporting_source_ids"):
        errors.append("no supporting discovery source ids")

    # The circularity regex that stood here matched prose generated by the
    # Chao1 estimator (`\bcurrent-table\b`, `\balready-contains-\d+`, four
    # more) against `expected_count_basis`. Both the estimator and that field
    # are deleted, so the patterns can no longer match anything -- and a
    # predicate that cannot match reads as "no circularity found", which is the
    # silent no-op this campaign exists to remove. It dies with the string it
    # was coupled to rather than being left as reassurance.
    return errors


def _attach_observed_count(
    target: dict[str, Any],
    table_rows: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    target_rows = table_rows.get(str(target.get("target_table") or ""), [])
    covered = _distinct_count(
        (row for row in target_rows if _row_status(row, ()) == "covered"),
        target.get("key_columns") or [],
    )
    observed = _distinct_count(
        target_rows,
        target.get("key_columns") or [],
    )
    target = dict(target)
    expected_minimum = _as_int(target.get("expected_minimum_count"))
    target["observed_count"] = covered
    target["observed_total_count"] = observed
    # ONE EXPRESSION, TWO NAMES -- STATED RATHER THAN LEFT TO BE NOTICED.
    #
    # `deficit_count` used to be `expected_count - covered`, an extrapolated
    # universe minus coverage, while `minimum_deficit_count` was the census
    # minus coverage. With `expected_count` deleted there is one measured
    # number left, so the two are now identical by construction and the second
    # is computed from the first rather than restated.
    #
    # This is a BEHAVIOUR change to the fill scheduler, not only a change in
    # what a number means: a family whose census equals its coverage now
    # reports zero deficit where it previously reported an extrapolated
    # shortfall. It is forced by the deletion -- there is no other number to
    # measure against -- but it is owed a before/after on a recorded run, and
    # that validation belongs to its own change rather than to this one.
    #
    # If the two should ever diverge again, that is a scheduler decision that
    # needs its own justification, not a silent re-widening of this line.
    minimum_deficit = max(0, expected_minimum - covered)
    target["minimum_deficit_count"] = minimum_deficit
    target["deficit_count"] = minimum_deficit
    target["status"] = "covered" if target["deficit_count"] == 0 else "open"
    return target


def _target_id(target: Mapping[str, Any]) -> str:
    payload = {
        "name": _clean_display(target.get("name")),
        "target_table": _clean_display(target.get("target_table")),
        "key_columns": _unique(target.get("key_columns")),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_fill_deficits(
    table_rows: Mapping[str, list[dict[str, Any]]],
    universe_estimate: Mapping[str, Any] | None,
    *,
    table_columns: Mapping[str, Sequence[str]] | None = None,
    cold_start_columns: Mapping[str, Sequence[str]] | None = None,
    table_key_columns: Mapping[str, Sequence[str]] | None = None,
    cold_start_anchors: Mapping[
        str,
        Sequence[Mapping[str, str]],
    ] | None = None,
    max_row_gaps_per_table: int = 4,
    max_total: int = 32,
) -> list[FillDeficit]:
    """Build concrete, generic search deficits for the next fill round."""
    estimate = normalize_universe_estimate(
        universe_estimate,
        table_rows=table_rows,
    )
    deficits: dict[str, FillDeficit] = {}

    for deficit in _cold_start_fill_deficits(
        table_rows,
        table_columns=cold_start_columns or table_columns or {},
        table_key_columns=table_key_columns or {},
        cold_start_anchors=cold_start_anchors or {},
    ):
        deficits[deficit.id] = deficit

    for target in estimate.get("count_targets") or []:
        if _as_int(target.get("deficit_count")) <= 0:
            continue
        deficit = _count_fill_deficit(target, table_rows)
        deficits[deficit.id] = deficit

    for table_name, rows in table_rows.items():
        table_deficits = _table_gap_fill_deficits(
            table_name,
            rows,
            max_row_gaps=max_row_gaps_per_table,
        )
        for deficit in table_deficits:
            deficits.setdefault(deficit.id, deficit)

    return sorted(
        deficits.values(),
        key=lambda deficit: (-deficit.priority, deficit.target_table, deficit.id),
    )[:max_total]


def _cold_start_fill_deficits(
    table_rows: Mapping[str, list[dict[str, Any]]],
    *,
    table_columns: Mapping[str, Sequence[str]],
    table_key_columns: Mapping[str, Sequence[str]],
    cold_start_anchors: Mapping[str, Sequence[Mapping[str, str]]],
) -> list[FillDeficit]:
    """Emit schema-derived demand for every substantively cold declared table.

    Existing deficit producers both depend on observed supply: a count target
    or a row carrying gap prose.  This producer reads only the declared table
    contract and values another declared table has already observed.  It is
    therefore able to ask for the first row without inventing a row or asking
    a model to infer table grain.

    Row count is not evidence that a table has started filling.  A compiler
    may legitimately materialize key-only partial rows before it finds any of
    the table's declared measures.  Such rows remain cold-start inputs: they
    can feed ordinary row-gap deficits, but must not disable schema-owned
    demand for the first substantive value.  A table leaves cold start only
    when at least one non-key, non-plumbing declared field has a value.

    Keys identify the row and never become search targets.  Provenance and
    engine plumbing are excluded for the same reason as `_fill_candidate_columns`.
    A declared cold-start anchor maps one target key to one source column; all
    other target keys remain deliberately unbound.  If no mapped value has
    been observed yet, one unanchored field-scoped deficit keeps the table from
    becoming permanently unreachable.
    """

    out: list[FillDeficit] = []
    for table_name, columns in table_columns.items():
        key_columns = tuple(
            str(column)
            for column in table_key_columns.get(table_name, ())
            if str(column).strip()
        )
        missing_fields = tuple(
            str(column)
            for column in columns
            if (
                str(column).strip()
                and str(column) not in set(key_columns)
                and not str(column).startswith("_")
                and str(column) not in _FILL_COLUMN_SKIP
                and not is_provenance_name(str(column))
            )
        )
        if not missing_fields:
            continue

        rows = table_rows.get(table_name, [])
        if any(
            not _missing(_get_nested(row, column))
            for row in rows
            for column in missing_fields
        ):
            continue

        anchor_sets = _cold_start_anchor_values(
            table_name,
            table_rows,
            cold_start_anchors.get(table_name, ()),
        ) or [{}]
        for anchor_values in anchor_sets:
            description = (
                f"Acquire the first substantive values for declared table "
                f"{table_name}"
            )
            if anchor_values:
                description += " using already observed key values"
            deficit_id = _fill_deficit_id(
                "schema_cold_start",
                table_name,
                table_name,
                missing_fields,
                anchor_values,
            )
            out.append(
                FillDeficit(
                    id=deficit_id,
                    deficit_type="schema_cold_start",
                    target_id=table_name,
                    target_name=table_name,
                    target_table=table_name,
                    # No substantive declared value is the maximum observable
                    # table-level deficit; 100 is the existing top of this
                    # scheduler's priority scale, not a fitted threshold.
                    priority=100.0,
                    description=description,
                    key_columns=key_columns,
                    missing_fields=missing_fields,
                    anchor_values=anchor_values,
                    observed_count=len(rows),
                    row_count=len(rows),
                )
            )
    return out


def _cold_start_anchor_values(
    target_table: str,
    table_rows: Mapping[str, list[dict[str, Any]]],
    anchors: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    """Distinct partial target keys, kept row-local within each source table."""

    by_source: "OrderedDict[str, list[Mapping[str, str]]]" = OrderedDict()
    for anchor in anchors:
        source_table = str(anchor.get("source_table") or "").strip()
        target_column = str(anchor.get("target_column") or "").strip()
        source_column = str(anchor.get("source_column") or "").strip()
        if (
            not source_table
            or not target_column
            or not source_column
            or source_table == target_table
        ):
            continue
        by_source.setdefault(source_table, []).append(anchor)

    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_table, source_anchors in by_source.items():
        for row in table_rows.get(source_table, []):
            mapped: dict[str, Any] = {}
            for anchor in source_anchors:
                value = _get_nested(row, str(anchor.get("source_column") or ""))
                if _missing(value):
                    continue
                mapped[str(anchor.get("target_column"))] = _compact_value(value)
            if not mapped:
                continue
            signature = json.dumps(mapped, sort_keys=True, default=str)
            if signature in seen:
                continue
            seen.add(signature)
            values.append(mapped)
    return values


def _observed_slots(
    table_rows: Mapping[str, list[dict[str, Any]]],
    table_schemas: Mapping[str, Sequence[str]],
) -> list[TargetSlot]:
    slots: dict[str, TargetSlot] = {}
    for table_name, rows in table_rows.items():
        required = tuple(table_schemas.get(table_name, ()))
        for index, row in enumerate(rows):
            values = {
                key: value
                for key, value in row.items()
                if not key.startswith("_") and not _missing(value)
            }
            missing_fields = tuple(
                column for column in required if _missing(row.get(column))
            )
            status = _row_status(row, missing_fields)
            key = f"{table_name}::{_stable_row_key(row, index)}"
            slots[key] = TargetSlot(
                key=key,
                slot_type=table_name,
                status=status,
                table=table_name,
                values=_sample_row_values(values),
                missing_fields=missing_fields,
                source_refs=tuple(_unique(row.get("source_refs"))),
            )
    return sorted(slots.values(), key=lambda slot: (slot.slot_type, slot.key))


def _analysis_rows(
    *,
    criteria: list[dict[str, Any]],
    estimate: dict[str, Any],
    completion: dict[str, Any],
    catalog: dict[str, Any],
    coverage: dict[str, Any],
    search_state: dict[str, Any],
) -> list[dict[str, Any]]:
    count_targets = estimate.get("count_targets") or []
    unestimated_targets = estimate.get("unestimated_count_targets") or []
    completion_issues = open_completion_issues(completion)
    completion_bins = open_completion_bins(completion)
    rows = [
        {
            "scope": "in_scope",
            "outcome": (
                f"{len(completion.get('search_space_probes') or [])} "
                "search-space probes recorded"
            ),
            "what_it_means": (
                "the completion estimate needs broad external samples before "
                "it can bound how much the final tables should cover"
            ),
            "interpretation": _criterion_detail(criteria, "search space probed"),
        },
        {
            "scope": "in_scope",
            "outcome": (
                f"completion scope status is {completion.get('scope_status')} "
                f"with {len(completion_issues)} blocking issue(s) and "
                f"{len(completion_bins)} underexplored bin(s)"
            ),
            "what_it_means": (
                "the scoping critic must clear suspicious estimates and "
                "underexplored regions before the stop rule can pass"
            ),
            "interpretation": _criterion_detail(
                criteria,
                "completion estimate consistent",
            ),
        },
        {
            "scope": "in_scope",
            "outcome": f"answer-universe estimate status is {estimate.get('status')}",
            "what_it_means": (
                "the stop rule needs searched discovery evidence before it can "
                "judge how large the final answer should be"
            ),
            "interpretation": _criterion_detail(criteria, "answer universe estimated"),
        },
        {
            "scope": "in_scope",
            "outcome": f"{len(count_targets)} count targets estimated",
            "what_it_means": (
                "each count target is a question-specific lower bound that the "
                "exported answer tables must meet"
            ),
            "interpretation": _criterion_detail(criteria, "count targets estimated"),
        },
        {
            "scope": "in_scope",
            "outcome": f"{len(unestimated_targets)} target families still unquantified",
            "what_it_means": (
                "every final row family needs a searched lower bound before "
                "the run can know what complete means"
            ),
            "interpretation": _criterion_detail(
                criteria,
                "all target families quantified",
            ),
        },
        {
            "scope": "in_scope",
            "outcome": (
                f"{len(catalog.get('unmet_count_targets') or [])} count targets "
                "below their searched lower bound"
            ),
            "what_it_means": (
                "a nonzero value means the run has found fewer distinct table "
                "slots than the discovery evidence says likely exist"
            ),
            "interpretation": _criterion_detail(
                criteria,
                "all estimated count targets covered",
            ),
        },
        {
            "scope": "in_scope",
            "outcome": (
                f"{len(catalog.get('fill_deficits') or [])} concrete fill "
                "deficits identified"
            ),
            "what_it_means": (
                "the fill scheduler has table-level, row-level, and count-level "
                "missing pieces to prioritize rather than only broad row counts"
            ),
            "interpretation": (
                "nonzero concrete deficits keep the next search batch focused on "
                "specific missing fields or row families"
            ),
        },
        {
            "scope": "in_scope",
            "outcome": f"{search_state.get('pending_tasks', 0)} pending search tasks",
            "what_it_means": (
                "queued Firecrawl tasks still have to run before search can be "
                "considered drained"
            ),
            "interpretation": _criterion_detail(criteria, "search frontier drained"),
        },
    ]
    for target in count_targets[:8]:
        rows.append(
            {
                "scope": "in_scope",
                "outcome": (
                    f"{target.get('observed_count', 0)}/"
                    f"{target.get('expected_minimum_count', 0)} covered "
                    f"({target.get('observed_total_count', 0)} total) for "
                    f"{target.get('name')}"
                ),
                "what_it_means": (
                    f"distinct covered rows are counted in {target.get('target_table')} "
                    f"using {target.get('key_columns') or ['row']} as the key; "
                    "partial rows with recorded evidence gaps remain searchable "
                    "but do not satisfy the target"
                ),
                "interpretation": target.get("basis") or "no basis recorded",
            }
        )
    return rows


def _criterion_detail(criteria: Sequence[Mapping[str, Any]], name: str) -> str:
    for criterion in criteria:
        if criterion.get("name") == name:
            return str(criterion.get("detail") or "")
    return ""


def _table_profile(
    name: str,
    rows: list[dict[str, Any]],
    schema_columns: Sequence[str],
) -> dict[str, Any]:
    # Every row is scanned for column names. `rows[:50]` hid any column whose
    # first non-missing appearance is past row 50, so the profile told the
    # planner the table had fewer columns than it has -- the same defect as the
    # `rows[:200]` in `_fill_candidate_columns`, on the same data. Collecting
    # names costs nothing; it is the `sample_rows` below that costs prompt.
    columns: list[str] = list(schema_columns)
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return {
        "name": name,
        "rows": len(rows),
        "columns": columns,
        "sample_rows": [_sample_row_values(row) for row in rows[:5]],
    }


def _final_row_signature(
    row: Mapping[str, Any],
    final_key_columns: Sequence[str],
    index: int,
) -> str:
    values = {
        column: _clean_key(_get_nested(row, column))
        for column in final_key_columns
        if not _missing(_get_nested(row, column))
    }
    if values:
        return _stable_signature(values)
    return _stable_row_key(row, index)


def _source_refs(row: Mapping[str, Any]) -> list[str]:
    for column in ("source_refs", "source_ids", "source_id"):
        value = row.get(column)
        if _missing(value):
            continue
        if isinstance(value, str):
            text = value.strip()
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
            return _unique(_as_list(parsed))
        return _unique(_as_list(value))
    return []


def _stable_signature(values: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(sorted(values.items())),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def compact_estimate_for_prompt(
    estimate: Mapping[str, Any] | None,
    *,
    table_rows: Mapping[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    normalized = normalize_universe_estimate(estimate, table_rows=table_rows)
    # `scope_summary` is deliberately NOT forwarded into the prompt. It is
    # producer prose describing how a count was derived, and on a seeded or
    # resumed run it is inherited verbatim from an artifact written by the
    # deleted Chao1 estimator -- "Counts are Chao1 richness estimates over the
    # observed sample...". That string round-tripped out of a stored estimate
    # and back into a live prompt, describing machinery that no longer exists
    # to a model that would plan against it.
    #
    # Dropped here rather than stripped during normalization on purpose:
    # rewriting a recorded artifact's prose would be backfilling history, and
    # deleting it by matching the word "chao1" would be the name-based
    # classification this campaign keeps removing. The stored artifact keeps
    # what it always said; the prompt simply stops carrying a description of
    # how a count was made, because no count is made.
    return {
        "status": normalized.get("status"),
        "count_targets": [
            {
                key: target.get(key)
                for key in (
                    "name",
                    "target_table",
                    "key_columns",
                    "expected_minimum_count",
                    "observed_count",
                    "observed_total_count",
                    "minimum_deficit_count",
                    "deficit_count",
                    "status",
                )
            }
            for target in normalized.get("count_targets", [])
        ],
        "out_of_scope_count_targets": [
            {
                key: target.get(key)
                for key in (
                    "name",
                    "target_table",
                    "expected_minimum_count",
                    "reason",
                )
            }
            for target in normalized.get("out_of_scope_count_targets", [])[:10]
        ],
        "unestimated_count_targets": [
            {
                key: target.get(key)
                for key in (
                    "name",
                    "target_table",
                    "expected_minimum_count",
                    "reason",
                )
            }
            for target in normalized.get("unestimated_count_targets", [])[:10]
        ],
        "expected_axes": [
            {
                key: axis.get(key)
                for key in (
                    "name",
                    "description",
                    "status",
                )
            }
            for axis in normalized.get("expected_axes", [])[:10]
        ],
        "underexplored_bins": normalized.get("underexplored_bins", [])[:10],
        "estimate_issues": normalized.get("estimate_issues", [])[:10],
        "unresolved_questions": normalized.get("unresolved_questions", [])[:10],
        "suggested_queries": normalized.get("suggested_queries", [])[:10],
    }


def _distinct_count(
    rows: Iterable[dict[str, Any]],
    key_columns: Sequence[str],
) -> int:
    if not key_columns:
        return len(list(rows))

    keys: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(_clean_key(_get_nested(row, column)) for column in key_columns)
        if any(key):
            keys.add(key)
    return len(keys)


def _count_fill_deficit(
    target: Mapping[str, Any],
    table_rows: Mapping[str, list[dict[str, Any]]],
) -> FillDeficit:
    table_name = _clean_display(target.get("target_table"))
    rows = table_rows.get(table_name, [])
    expected_minimum = _as_int(target.get("expected_minimum_count"))
    observed = _as_int(target.get("observed_count"))
    deficit_count = _as_int(target.get("deficit_count"))
    shortfall_ratio = deficit_count / max(expected_minimum, 1)
    key_columns = tuple(_unique(target.get("key_columns")))
    missing_fields = tuple(_incomplete_columns(rows, key_columns))
    description = (
        _clean_display(target.get("description"))
        or _clean_display(target.get("name"))
        or f"Fill missing rows for {table_name}"
    )
    target_id = _clean_display(target.get("id"))
    deficit_id = _fill_deficit_id(
        "count_shortfall",
        table_name,
        target_id,
        missing_fields,
    )
    return FillDeficit(
        id=deficit_id,
        deficit_type="count_shortfall",
        target_id=target_id,
        target_name=_clean_display(target.get("name")),
        target_table=table_name,
        priority=80 + min(20.0, shortfall_ratio * 20),
        description=description,
        key_columns=key_columns,
        missing_fields=missing_fields,
        expected_minimum_count=expected_minimum,
        observed_count=observed,
        deficit_count=deficit_count,
        row_count=len(rows),
        known_missing_examples=tuple(_unique(target.get("known_missing_examples"))),
    )


def _table_gap_fill_deficits(
    table_name: str,
    rows: list[dict[str, Any]],
    *,
    max_row_gaps: int,
) -> list[FillDeficit]:
    if not rows:
        return []

    columns = _fill_candidate_columns(rows)
    gapped = [
        (index, row)
        for index, row in enumerate(rows)
        if _row_evidence_gap(row)
    ]
    if not gapped:
        return []

    gap_ratio = len(gapped) / max(len(rows), 1)
    missing_fields = tuple(_incomplete_columns([row for _, row in gapped], columns))
    deficits = [
        FillDeficit(
            id=_fill_deficit_id(
                "table_gap_saturation",
                table_name,
                table_name,
                missing_fields,
            ),
            deficit_type="table_gap_saturation",
            target_table=table_name,
            priority=70 + min(25.0, gap_ratio * 25) + min(5, len(missing_fields)),
            description=(
                f"Fill recurring gaps in {table_name}: "
                f"{len(gapped)}/{len(rows)} rows record evidence gaps"
            ),
            missing_fields=missing_fields,
            gap_row_count=len(gapped),
            row_count=len(rows),
        )
    ]

    ranked_rows = sorted(
        gapped,
        key=lambda item: _row_gap_score(item[1], columns),
        reverse=True,
    )
    for index, row in ranked_rows[: max(0, max_row_gaps)]:
        row_missing_fields = tuple(_missing_columns(row, columns))
        anchor_values = _anchor_values(row, columns)
        evidence_gap = _row_evidence_gap(row)
        deficits.append(
            FillDeficit(
                id=_fill_deficit_id(
                    "row_gap",
                    table_name,
                    f"{index}:{evidence_gap}",
                    row_missing_fields,
                    anchor_values,
                ),
                deficit_type="row_gap",
                target_table=table_name,
                priority=(
                    50
                    + min(25, len(row_missing_fields) * 4)
                    + min(10, len(anchor_values))
                ),
                description=f"Fill one partial row in {table_name}",
                missing_fields=row_missing_fields,
                anchor_values=anchor_values,
                evidence_gap=evidence_gap,
                gap_row_count=1,
                row_count=len(rows),
            )
        )

    return deficits


_FILL_COLUMN_SKIP = {
    "deduplication_key",
    "description",
    "entity_name",
    "entity_type",
    "evidence_gap",
    "group_key",
    "group_name",
    "id",
    "occurrence_count",
    "path_depth",
    "relation_type",
    "row_id",
    "source_chunk",
    "source_chunks",
    "source_refs",
    "src_id",
    "supporting_path_count",
    "table_name",
    "tgt_id",
}


def _fill_candidate_columns(rows: list[dict[str, Any]]) -> list[str]:
    """Columns a round could plausibly fill by searching for something.

    Provenance columns are excluded by naming convention rather than by an
    enumerated list. `_FILL_COLUMN_SKIP` catches exact spellings only, so a
    per-field sidecar like `affected country_source_chunks` slipped past it and
    was counted as an empty column with a deficit against it -- and once column
    truncation was removed, every such sidecar surfaced and became a search
    target. Nothing external describes its data as a chunk id, so those
    searches cannot succeed by construction.

    The predicate is `provenance.is_provenance_name`, the same one `criteria`
    uses to refuse provenance as a datapoint. Sharing it is the intent: a
    column this module sends the run looking for should not be one that module
    would refuse to credit.

    That intent is only half realised, and the docstring used to claim it whole.
    The two agree in one direction -- nothing this function proposes is
    rejected by `criteria` as provenance -- but not in the other: the extra
    filters here (`_FILL_COLUMN_SKIP`, and the suffix rules the two consumers
    keep privately) exclude 13 columns that `criteria` will happily credit, so
    the run refuses to search for columns it would score. The disagreement is
    one-directional and it is 13 columns wide, not zero. Stating it as
    agreement is how the next reader stops checking.

    Every row is scanned. The `rows[:200]` that was here was the same defect
    this docstring already claims to have removed, one layer out: it bounded
    the row scan instead of the column list, so a column that first appears in
    row 200 or later is never proposed as a fill target and therefore never
    filled, in this round or any later one. Measured on the live earthquake
    run's round-2 table (303 rows, 206 filled columns): 90 columns were visible
    through `rows[:200]` and 116 were not -- 56% of the table, including
    `country`, `deaths_reported`, `damage`, `displaced_people`,
    `direct_economic_impact`, and three of the four infrastructure-indicator
    columns, among them the best-filled one in the run. This scan is O(rows x
    columns) over data already in memory; there was no cost being bought.
    """

    columns: list[str] = []
    for row in rows:
        for column in row:
            if (
                column.startswith("_")
                or column in _FILL_COLUMN_SKIP
                or is_provenance_name(column)
            ):
                continue
            if column not in columns:
                columns.append(column)
    return columns


def _incomplete_columns(
    rows: list[dict[str, Any]],
    columns: Sequence[str],
) -> list[str]:
    """Every column with at least one missing cell, worst first. No truncation.

    The truncation this replaced was self-sustaining rather than merely lossy.
    A caller keeping a prefix decides which columns are searchable by where
    they fall in the order; columns tied on missing count were ordered by name,
    so the prefix selected by spelling. A column below the cut is never
    searched, so it stays empty, so it stays tied, so it is below the cut again
    next round -- unreachable at any number of rounds. On one recorded run,
    capitalisation was the only reason any indicator column ever surfaced, and
    thirty-one columns tied at zero fill competed for eight places.

    No sort key fixes that, because the columns are tied on the very quantity
    any key would rank them by. Only returning all of them does. A fill-ratio
    tie-break in particular cannot help: every column here is measured over the
    same rows, so the ratio is the missing count over a shared denominator and
    ties on one exactly when it ties on the other.

    Ordering is therefore by severity with the name last purely for
    determinism, which is safe precisely because nothing is dropped. Callers
    that cannot afford the whole list should shrink values, not drop columns.
    """

    if not rows or not columns:
        return []

    measured = [
        (sum(1 for row in rows if _missing(_get_nested(row, column))), column)
        for column in columns
    ]
    return [
        column
        for missing, column in sorted(measured, key=lambda item: (-item[0], item[1]))
        if missing > 0
    ]


def _missing_columns(row: Mapping[str, Any], columns: Sequence[str]) -> list[str]:
    return [column for column in columns if _missing(_get_nested(row, column))]


def _anchor_values(
    row: Mapping[str, Any],
    columns: Sequence[str],
    *,
    limit: int = 8,
) -> dict[str, Any]:
    anchors: dict[str, Any] = {}
    for column in columns:
        if len(anchors) >= limit:
            break
        # Same display-vs-serialized spelling as the missing-column counts: a
        # raw lookup returns nothing, so a deficit carries no anchors at all
        # and query generation has only field names left to work from.
        value = _get_nested(row, column)
        if _missing(value):
            continue
        anchors[column] = _compact_value(value)
    return anchors


def _row_evidence_gap(row: Mapping[str, Any]) -> str:
    for column in ("evidence_gap", "gap", "caveats"):
        value = _clean_display(row.get(column))
        if value:
            return value
    return ""


def _row_gap_score(row: Mapping[str, Any], columns: Sequence[str]) -> int:
    return (
        len(_anchor_values(row, columns)) * 2
        + len(_missing_columns(row, columns))
    )


#: Bumped whenever the hashed payload below changes meaning, so a deficit id
#: minted under one definition can never be silently joined to one minted under
#: another. `search_memory` joins on these ids and persisted artifacts already
#: carry them, so a change in what they hash is a change in what a join means.
#:
#: v2: `_sample_row_values` stopped capping at sixteen fields, so `anchor_values`
#: now covers the whole row and every id changed. Without this marker that
#: reads downstream as every deficit being new, which is a trend rather than
#: the refused comparison it should be -- the same argument `reward.py` makes
#: for `REWARD_VERSION`, applied to the identifier that keys the join.
FILL_DEFICIT_ID_VERSION = "v2"


def _fill_deficit_id(
    deficit_type: str,
    table_name: str,
    anchor: str,
    missing_fields: Sequence[str],
    anchor_values: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "anchor": _clean_display(anchor),
        "anchor_values": _sample_row_values(anchor_values or {}),
        "deficit_type": deficit_type,
        "missing_fields": list(missing_fields),
        "table_name": table_name,
        "id_version": FILL_DEFICIT_ID_VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _row_status(row: Mapping[str, Any], missing_fields: Sequence[str]) -> str:
    completeness = _clean_display(row.get("completeness")).lower()
    if completeness == "complete":
        return "covered"
    if completeness:
        return "open"
    evidence_gap = _clean_display(row.get("evidence_gap")).lower()
    if evidence_gap and evidence_gap not in {"none", "no gap", "complete"}:
        return "open"
    return "open" if missing_fields else "covered"


def _identity_values(row: Mapping[str, Any]) -> dict[str, Any]:
    """Every non-missing field of a row, whole, for hashing into an identity.

    Identity has no prompt budget, so nothing here is shortened. The previous
    identity hashed `_sample_row_values`, which kept the first sixteen fields
    in dict-insertion order and compacted each value to 240 characters. Both
    parts were wrong for an identity and wrong in opposite directions.

    The field cap made identity a function of position. On the live earthquake
    run the sixteen fields it selected were `src_id`, `tgt_id`, `relation_type`,
    `description`, `attributes`, `source_refs`, `source_chunks`, `source_chunk`,
    `attribute_evidence`, `observation_quote`, `entity_name`, `entity_type`,
    `path_depth`, `id`, `row_id`, `deduplication_key` -- not one of them
    semantic. `atomic_fact_type`, `fact_value`, `country_or_location_qualifier`
    and `temporal_qualifier_or_nearest_year` all sort past position sixteen and
    were excluded. A key built from `row_id`, `src_id` and `source_refs` can
    only ever answer "every row is distinct", which is what it did.

    The 240-character value clip was the opposite failure: it merges two rows
    that differ only past character 237 into one identity. A cap that both
    over-splits on position and under-splits on length is not a bound on
    anything, so there is none here.

    This does NOT on its own make row recapture measurable: the fields it now
    includes still contain per-row provenance, so rows stay distinct. What it
    removes is a truncation masquerading as an identity rule. The recapture
    problem is a separate, measured finding about the counting unit.
    """

    return {
        str(key): value
        for key, value in row.items()
        if not _missing(value)
    }


def _stable_row_key(row: Mapping[str, Any], index: int) -> str:
    payload = json.dumps(
        _identity_values(row),
        ensure_ascii=True,
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{index}-{digest}"


def _sample_row_values(row: Mapping[str, Any]) -> dict[str, Any]:
    """Every non-missing field of a row, for display inside a prompt.

    No field cap. The cap that was here decided which of a row's columns a
    model was allowed to see by their position in the row's key order, and the
    positions that lose are the ones added most recently -- which in a
    table-fill run are exactly the columns the run just learned to want.

    `_compact_value` still shortens an individual oversized cell and marks it
    with an ellipsis. That is a remaining truncation, not a defended bound; it
    is visible in the emitted value rather than silent, and removing it needs
    rows delivered across windows rather than one shorter row.
    """

    return {
        str(key): _compact_value(value)
        for key, value in row.items()
        if not _missing(value)
    }


def _compact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _compact_value(inner)
            for key, inner in list(value.items())[:8]
            if not _missing(inner)
        }
    if isinstance(value, (list, tuple, set)):
        return [_compact_value(item) for item in list(value)[:8]]
    text = str(value)
    if len(text) > 240:
        return text[:237] + "..."
    return value


def _get_nested(row: Mapping[str, Any], column: str) -> Any:
    current: Any = row
    for part in str(column).split("."):
        if not isinstance(current, Mapping):
            return None
        if part in current:
            current = current[part]
            continue
        resolved = _resolve_column_key(current, part)
        if resolved is None:
            return None
        current = current[resolved]
    return current


def _resolve_column_key(row: Mapping[str, Any], column: str) -> str | None:
    """Match a column name to a row key differing only in presentation.

    Count targets carry display names -- "epicenter country" -- while exported
    rows key on the serialized form, "epicenter_country". Compared raw, every
    lookup misses, and a miss is indistinguishable from an empty cell: the join
    fails silently instead of erroring. Downstream that reads as a table with
    almost nothing in it, so `observed_count` stays near zero, the deficit
    never shrinks, and the target's priority stays pinned at its ceiling for
    the life of the run.

    Same defect class as the family-name join in `estimator`: one side of a
    join normalized, the other not. Resolution here is exact equality under
    `_clean_key` -- never a similarity guess -- a direct hit always wins, and
    when two row keys normalize alike the first in row order is taken.
    """

    wanted = _clean_key(column)
    if not wanted:
        return None
    for key in row:
        if _clean_key(key) == wanted:
            return key
    return None


def _as_list(values: Any) -> list[Any]:
    if values is None:
        return []
    if isinstance(values, list):
        return values
    if isinstance(values, (tuple, set)):
        return list(values)
    return [values]


def _as_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _optional_int(value: Any) -> int | None:
    coerced = _as_int(value)
    return coerced if coerced > 0 else None


def _clean_key(value: Any) -> str:
    value = _clean_display(value)
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _clean_display(value: Any) -> str:
    if _missing(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


#: One owner, one predicate. `criteria.is_missing_value` already collapses
#: whitespace as well as casefolding, so a cell reading `"not  specified"` is
#: absence here where it was a value before -- disclosed rather than slipped in.
_missing = is_missing_value


def _unique(values: Any) -> list[str]:
    if _missing(values):
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        values = [values]

    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if _missing(value):
            continue
        text = str(value).strip()
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _slot_counts(slots: Iterable[TargetSlot]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for slot in slots:
        counts[slot.slot_type] = counts.get(slot.slot_type, 0) + 1
    return counts
