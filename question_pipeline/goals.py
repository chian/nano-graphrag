"""Question-level fill goals for iterative table aggregation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence


_MISSING_STRINGS = {
    "",
    "n/a",
    "na",
    "none",
    "not applicable",
    "not specified",
    "not specified in current evidence",
    "null",
    "unknown",
}


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
    round: int | str
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
    all_seen_slot_keys: set[str] = field(default_factory=set)
    new_slot_history: list[dict[str, Any]] = field(default_factory=list)

    def prompt_context(
        self,
        table_rows: Mapping[str, list[dict[str, Any]]],
        gaps: Iterable[str],
        universe_estimate: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        slots = _observed_slots(table_rows, self.table_schemas)
        open_slots = [slot for slot in slots if slot.status != "covered"]
        return {
            "target_table_names": sorted(
                str(name)
                for name in table_rows
                if str(name).strip()
            ),
            "tables": [
                _table_profile(name, rows, self.table_schemas.get(name, ()))
                for name, rows in table_rows.items()
            ],
            "observed_slot_count": len(slots),
            "open_observed_slot_count": len(open_slots),
            "observed_slot_counts": _slot_counts(slots),
            "open_observed_slot_counts": _slot_counts(open_slots),
            "sample_open_slots": [
                slot.to_dict() for slot in open_slots[:40]
            ],
            "sample_gaps": list(gaps)[:40],
            "current_universe_estimate": _compact_estimate(
                universe_estimate,
                table_rows=table_rows,
            ),
        }

    def evaluate(
        self,
        *,
        round_idx: int | str,
        table_rows: Mapping[str, list[dict[str, Any]]],
        universe_estimate: Mapping[str, Any] | None,
        search_frontier: Mapping[str, Any],
        search_outcomes: list[dict[str, Any]],
        paper_count: int,
        max_papers: int,
        paper_budget_available: bool,
        gap_search_tasks: list[dict[str, Any]],
        goal_search_tasks: list[dict[str, Any]],
        update_history: bool = True,
    ) -> FillGoalState:
        slots = _observed_slots(table_rows, self.table_schemas)
        slot_keys = {slot.key for slot in slots}
        open_slots = [slot for slot in slots if slot.status != "covered"]
        estimate = normalize_universe_estimate(
            universe_estimate,
            table_rows=table_rows,
        )

        if (
            not update_history
            and self.new_slot_history
            and self.new_slot_history[-1].get("round") == round_idx
        ):
            new_slots = set(self.new_slot_history[-1].get("new_slots") or [])
        else:
            previous_slots = set(self.all_seen_slot_keys)
            new_slots = slot_keys - previous_slots
            self.all_seen_slot_keys.update(slot_keys)
            self.new_slot_history.append(
                {
                    "round": round_idx,
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
                "name": "answer universe estimated",
                "satisfied": estimate.get("status") == "estimated",
                "detail": (
                    f"status={estimate.get('status')}; "
                    f"{len(estimate.get('supporting_source_ids') or [])} "
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
                    "source-supported lower bounds"
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
            round=round_idx,
            mode="table_fill",
            fulfilled=fulfilled,
            stop_rule=(
                "Stop only after Firecrawl-backed discovery evidence yields a "
                "question-specific answer-universe estimate, every final row "
                "family has a source-supported lower-bound count, every estimated "
                "count target is covered by the exported answer tables, and the "
                "search frontier has no queued work."
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
    targets: list[dict[str, Any]] = []
    unestimated_targets: list[dict[str, Any]] = []
    out_of_scope_targets: list[dict[str, Any]] = []
    for raw_index, item in enumerate(_as_list(raw.get("count_targets") or raw.get("targets"))):
        if not isinstance(item, Mapping):
            continue
        target, expected_minimum = _coerce_count_target(
            item,
            raw,
            fallback_index=raw_index + 1,
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

    for raw_index, item in enumerate(_as_list(raw.get("unestimated_count_targets"))):
        if not isinstance(item, Mapping):
            continue
        target, _ = _coerce_count_target(
            item,
            raw,
            fallback_index=len(targets) + len(unestimated_targets) + raw_index + 1,
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

    for raw_index, item in enumerate(_as_list(raw.get("out_of_scope_count_targets"))):
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
        status = "estimated" if targets else "insufficient_evidence"
    if targets and not unestimated_targets:
        status = "estimated"
    elif status == "estimated":
        status = "insufficient_evidence"

    return {
        "status": status,
        "scope_summary": _clean_display(raw.get("scope_summary")),
        "count_targets": targets,
        "unestimated_count_targets": unestimated_targets,
        "out_of_scope_count_targets": out_of_scope_targets,
        "supporting_source_ids": _unique(raw.get("supporting_source_ids")),
        "supporting_queries": _unique(raw.get("supporting_queries")),
        "unresolved_questions": _unique(raw.get("unresolved_questions")),
        "suggested_queries": _unique(raw.get("suggested_queries")),
        "raw": dict(raw),
    }


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
        merged["status"] = "estimated"
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
    if table:
        return table

    columns = tuple(
        sorted(_clean_key(column) for column in _as_list(target.get("key_columns")))
    )
    columns = tuple(column for column in columns if column)
    payload = {
        "name": _clean_key(target.get("name")),
        "key_columns": columns,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _coerce_count_target(
    item: Mapping[str, Any],
    raw: Mapping[str, Any],
    *,
    fallback_index: int,
) -> tuple[dict[str, Any], int]:
    expected_minimum = _as_int(
        item.get("expected_minimum_count")
        or item.get("minimum_expected_count")
        or item.get("min_count")
        or item.get("lower_bound")
    )
    target = {
        "name": _clean_display(item.get("name")) or f"target_{fallback_index}",
        "description": _clean_display(item.get("description")),
        "target_table": str(item.get("target_table") or "").strip(),
        "key_columns": [
            str(column).strip()
            for column in _as_list(item.get("key_columns"))
            if str(column).strip()
        ],
        "expected_minimum_count": expected_minimum if expected_minimum > 0 else None,
        "expected_maximum_count": _optional_int(
            item.get("expected_maximum_count")
            or item.get("maximum_expected_count")
            or item.get("max_count")
            or item.get("upper_bound")
        ),
        "basis": _clean_display(item.get("basis") or item.get("rationale")),
        "supporting_source_ids": _unique(
            item.get("supporting_source_ids")
            or item.get("source_ids")
            or raw.get("supporting_source_ids")
        ),
        "known_missing_examples": _unique(
            item.get("known_missing_examples") or item.get("missing_examples")
        ),
    }
    target["id"] = _target_id(target)
    return target, expected_minimum


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

    basis = _clean_key(target.get("basis"))
    circular_patterns = (
        r"\bcurrent(?:-[a-z0-9]+){0,4}-table\b",
        r"\bcurrent-table\b",
        r"\bcurrent-row",
        r"\balready-contains-\d+",
        r"\bexisting-\d+-rows\b",
        r"\bcurrent-\d+-rows\b",
    )
    if any(re.search(pattern, basis) for pattern in circular_patterns):
        errors.append("expected count appears to rely on current exported rows")
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
    target["observed_count"] = covered
    target["observed_total_count"] = observed
    target["deficit_count"] = max(
        0,
        _as_int(target.get("expected_minimum_count")) - covered,
    )
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
    max_row_gaps_per_table: int = 4,
    max_total: int = 32,
) -> list[FillDeficit]:
    """Build concrete, generic search deficits for the next fill round."""
    estimate = normalize_universe_estimate(
        universe_estimate,
        table_rows=table_rows,
    )
    deficits: dict[str, FillDeficit] = {}

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
    catalog: dict[str, Any],
    coverage: dict[str, Any],
    search_state: dict[str, Any],
) -> list[dict[str, Any]]:
    count_targets = estimate.get("count_targets") or []
    unestimated_targets = estimate.get("unestimated_count_targets") or []
    rows = [
        {
            "scope": "in_scope",
            "outcome": f"answer-universe estimate status is {estimate.get('status')}",
            "what_it_means": (
                "the stop rule needs searched discovery evidence before it can "
                "judge how large the final answer should be"
            ),
            "interpretation": criteria[0]["detail"],
        },
        {
            "scope": "in_scope",
            "outcome": f"{len(count_targets)} count targets estimated",
            "what_it_means": (
                "each count target is a question-specific lower bound that the "
                "exported answer tables must meet"
            ),
            "interpretation": criteria[1]["detail"],
        },
        {
            "scope": "in_scope",
            "outcome": f"{len(unestimated_targets)} target families still unquantified",
            "what_it_means": (
                "every final row family needs a searched lower bound before "
                "the run can know what complete means"
            ),
            "interpretation": criteria[2]["detail"],
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
            "interpretation": criteria[3]["detail"],
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
            "interpretation": criteria[4]["detail"],
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


def _table_profile(
    name: str,
    rows: list[dict[str, Any]],
    schema_columns: Sequence[str],
) -> dict[str, Any]:
    columns: list[str] = list(schema_columns)
    for row in rows[:50]:
        for key in row:
            if key not in columns:
                columns.append(key)
    return {
        "name": name,
        "rows": len(rows),
        "columns": columns,
        "sample_rows": [_sample_row_values(row) for row in rows[:5]],
    }


def _compact_estimate(
    estimate: Mapping[str, Any] | None,
    *,
    table_rows: Mapping[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    normalized = normalize_universe_estimate(estimate, table_rows=table_rows)
    return {
        "status": normalized.get("status"),
        "scope_summary": normalized.get("scope_summary"),
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
    expected = _as_int(target.get("expected_minimum_count"))
    observed = _as_int(target.get("observed_count"))
    deficit_count = _as_int(target.get("deficit_count"))
    shortfall_ratio = deficit_count / max(expected, 1)
    key_columns = tuple(_unique(target.get("key_columns")))
    missing_fields = tuple(_top_missing_columns(rows, key_columns, limit=6))
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
        expected_minimum_count=expected,
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
    missing_fields = tuple(
        _top_missing_columns([row for _, row in gapped], columns, limit=8)
    )
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
        row_missing_fields = tuple(_missing_columns(row, columns)[:8])
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
    columns: list[str] = []
    for row in rows[:200]:
        for column in row:
            if column.startswith("_") or column in _FILL_COLUMN_SKIP:
                continue
            if column not in columns:
                columns.append(column)
    return columns


def _top_missing_columns(
    rows: list[dict[str, Any]],
    columns: Sequence[str],
    *,
    limit: int,
) -> list[str]:
    if not rows or not columns:
        return []

    counts = [
        (
            column,
            sum(1 for row in rows if _missing(row.get(column))),
        )
        for column in columns
    ]
    return [
        column
        for column, count in sorted(counts, key=lambda item: (-item[1], item[0]))
        if count > 0
    ][:limit]


def _missing_columns(row: Mapping[str, Any], columns: Sequence[str]) -> list[str]:
    return [column for column in columns if _missing(row.get(column))]


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
        value = row.get(column)
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


def _stable_row_key(row: Mapping[str, Any], index: int) -> str:
    payload = json.dumps(
        _sample_row_values(dict(row)),
        ensure_ascii=True,
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{index}-{digest}"


def _sample_row_values(row: Mapping[str, Any], *, max_fields: int = 16) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if len(out) >= max_fields:
            break
        if _missing(value):
            continue
        out[str(key)] = _compact_value(value)
    return out


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
        current = current.get(part)
    return current


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


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_STRINGS
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


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
