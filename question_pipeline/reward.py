"""Read-only reward reporting over the pipeline's one credit assignment.

Credit is assigned after accepted evidence is written into typed table state by
``TableCreditAssigner`` in :mod:`question_pipeline.acquisition`.  This module
does not decide what counts, project tables, or maintain a second credit
ledger.  It only aggregates those immutable assignment records with measured
costs for export.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .criteria import CRITERIA_PROJECTION_VERSION, EvidenceBasis


__all__ = [
    "REWARD_VERSION",
    "REWARD_COMPONENT_COLUMNS",
    "DatapointKind",
    "CreditedDatapoint",
    "CostVector",
    "RewardReport",
    "report_assigned_credit",
    "aggregate_cost",
    "load_seed_best_guess_rows",
    "merge_best_guess_rows",
]


#: Reporting semantics changed when credit assignment moved to the post-table
#: boundary. Historical reward versions are not directly comparable.
REWARD_VERSION = "single_credit_report_v1"

REWARD_COMPONENT_COLUMNS = [
    "component",
    "direction",
    "raw_value",
    "score",
    "interpretation",
]


class DatapointKind(str, Enum):
    """The accepted datapoint kind supported by this reward version."""

    #: A source states the value, joined at field scope.
    VERBATIM = "verbatim"
    BEST_GUESS = "best_guess"


@dataclass(frozen=True)
class CreditedDatapoint:
    """One real datapoint copied from its authoritative assignment record.

    Every field here is an identifier or a closed vocabulary member. Nothing is
    a count, a timestamp, or free text: credit joins by ID, so an attribution
    that survives a rename has to be built out of things that do not change
    when prose does.
    """

    assignment_id: str
    criterion_id: str
    kind: DatapointKind
    basis: EvidenceBasis
    table: str
    field: str
    subject_id: str
    #: The accepted source carried by the authoritative assignment.
    crediting_source_ids: tuple[str, ...]
    #: The Episode in which the assignment was made.
    realized_episode_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "credit_assignment_id": self.assignment_id,
            "criterion_id": self.criterion_id,
            "datapoint_kind": self.kind.value,
            "evidence_basis": self.basis.value,
            "table": self.table,
            "field": self.field,
            "subject_id": self.subject_id,
            "crediting_source_ids": list(self.crediting_source_ids),
            "realized_episode_id": self.realized_episode_id,
        }


@dataclass(frozen=True)
class CostVector:
    """What one scoring pass paid, summed from 1B's per-action records.

    A vector rather than a scalar because the units are different money and no
    exchange rate between them is measurable here. ``billable_calls`` is the one
    place two units are added, and the reason it is defensible is that both
    count discrete paid round trips: a search provider call and a model call are
    each one thing somebody bills for. Tokens and wall time are reported beside
    it so a later phase can adopt a different denominator without this module
    having quietly picked one for it.
    """

    records: int = 0
    provider_calls: int = 0
    llm_calls: int = 0
    provider_credits: float = 0.0
    provider_credits_available: bool = False
    returned_hits: int = 0
    fetched_bytes: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0
    wall_ms: float = 0.0
    errors: int = 0

    @property
    def billable_calls(self) -> int:
        return self.provider_calls + self.llm_calls

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def available(self) -> bool:
        """Whether any cost was recorded at all.

        A pass with records but zero calls really was free. A pass with no
        records at all has unknown cost, and the two must not compare equal.
        """

        return self.records > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_records": self.records,
            "provider_calls": self.provider_calls,
            "llm_calls": self.llm_calls,
            "billable_calls": self.billable_calls,
            "provider_credits": round(self.provider_credits, 6),
            "provider_credits_available": self.provider_credits_available,
            "returned_hits": self.returned_hits,
            "fetched_bytes": self.fetched_bytes,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "tokens": self.tokens,
            "retries": self.retries,
            "wall_ms": round(self.wall_ms, 3),
            "errors": self.errors,
            "cost_available": self.available,
        }


@dataclass(frozen=True)
class RewardReport:
    """One episode's already-assigned yield and measured cost."""

    reward_version: str
    criteria_projection_version: str
    #: The strategy Episode this scoring pass belongs to.
    episode_id: str
    before_table_state_id: str
    after_table_state_id: str
    datapoints: tuple[CreditedDatapoint, ...]
    cost: CostVector
    #: Assignment records that were recurrences rather than new table slots.
    uncredited: Mapping[str, int] = field(default_factory=dict)

    @property
    def datapoint_count(self) -> int:
        return len(self.datapoints)

    @property
    def cost_available(self) -> bool:
        return self.cost.available

    @property
    def score(self) -> float | None:
        """Datapoints per billable call, or ``None`` when cost is unknown.

        ``None`` rather than the datapoint count, because a yield that has not
        been divided by anything is not a yield-per-cost and must not be read as
        one by a consumer that forgot to check.
        """

        return self.yield_per("billable_calls")

    def yield_per(self, unit: str) -> float | None:
        if not self.cost.available:
            return None
        denominators = {
            "billable_calls": float(self.cost.billable_calls),
            "provider_calls": float(self.cost.provider_calls),
            "llm_calls": float(self.cost.llm_calls),
            "tokens": float(self.cost.tokens),
            "wall_ms": float(self.cost.wall_ms),
            "fetched_bytes": float(self.cost.fetched_bytes),
        }
        denominator = denominators.get(unit)
        if denominator is None or denominator <= 0:
            return None
        return round(self.datapoint_count / denominator, 9)

    def by_kind(self) -> dict[str, int]:
        counts = {kind.value: 0 for kind in DatapointKind}
        for datapoint in self.datapoints:
            counts[datapoint.kind.value] += 1
        return counts

    def components(self) -> list[dict[str, Any]]:
        """The report as rows, for the run's own artifact export."""

        rows = [
            {
                "component": "credited_datapoints",
                "direction": "maximize",
                "raw_value": self.datapoint_count,
                "score": self.datapoint_count,
                "interpretation": (
                    "New logical value slots assigned after accepted evidence "
                    "was materialized in typed table state."
                ),
            }
        ]
        for name, count in sorted(self.by_kind().items()):
            rows.append(
                {
                    "component": f"credited_{name}",
                    "direction": "maximize",
                    "raw_value": count,
                    "score": count,
                    "interpretation": f"Credited datapoints of kind {name}.",
                }
            )
        for name, count in sorted(self.uncredited.items()):
            rows.append(
                {
                    "component": f"uncredited_{name}",
                    "direction": "ignore",
                    "raw_value": count,
                    "score": 0,
                    "interpretation": (
                        "An authoritative assignment record that repeated a "
                        "logical slot already present in typed table state."
                    ),
                }
            )
        return rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "reward_version": self.reward_version,
            "criteria_projection_version": self.criteria_projection_version,
            "episode_id": self.episode_id,
            "before_table_state_id": self.before_table_state_id,
            "after_table_state_id": self.after_table_state_id,
            "score": self.score,
            "cost_available": self.cost_available,
            "credited_datapoints": self.datapoint_count,
            "credited_by_kind": self.by_kind(),
            "yield_per": {
                unit: self.yield_per(unit)
                for unit in (
                    "billable_calls",
                    "provider_calls",
                    "llm_calls",
                    "tokens",
                    "wall_ms",
                )
            },
            "cost": self.cost.to_dict(),
            "uncredited_volume": dict(sorted(self.uncredited.items())),
            "datapoints": [datapoint.to_dict() for datapoint in self.datapoints],
        }


def aggregate_cost(
    cost_records: Iterable[Mapping[str, Any]] | None,
) -> CostVector:
    """Sum 1B cost records. The caller decides which records are in scope.

    Selection is the caller's business and is done by ``episode_id`` on the
    records themselves -- never by a round window, which no record carries.

    1B's scopes do not nest their spend -- an inner meter takes the calls and
    records ``nested_in``; the outer does not also count them -- so a plain sum
    over records counts every provider call exactly once. Do not add a
    ``nested_in`` filter here: it would drop the inner records and undercount.
    """

    records = 0
    provider_calls = llm_calls = returned_hits = fetched_bytes = 0
    prompt_tokens = completion_tokens = retries = errors = 0
    credits = 0.0
    credits_available = False
    wall_ms = 0.0

    for record in cost_records or ():
        if not isinstance(record, Mapping):
            continue
        records += 1
        provider_calls += _int(record.get("provider_calls"))
        llm_calls += _int(record.get("llm_calls"))
        returned_hits += _int(record.get("returned_hits"))
        fetched_bytes += _int(record.get("fetched_bytes"))
        prompt_tokens += _int(record.get("prompt_tokens"))
        completion_tokens += _int(record.get("completion_tokens"))
        retries += _int(record.get("retries"))
        wall_ms += _float(record.get("wall_ms"))
        if record.get("provider_credits_available"):
            credits_available = True
            credits += _float(record.get("provider_credits"))
        if str(record.get("error_class") or ""):
            errors += 1

    return CostVector(
        records=records,
        provider_calls=provider_calls,
        llm_calls=llm_calls,
        provider_credits=credits,
        provider_credits_available=credits_available,
        returned_hits=returned_hits,
        fetched_bytes=fetched_bytes,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        retries=retries,
        wall_ms=wall_ms,
        errors=errors,
    )


def report_assigned_credit(
    assignments: Iterable[Mapping[str, Any]],
    *,
    episode_id: str,
    cost_records: Iterable[Mapping[str, Any]] | None = None,
) -> RewardReport:
    """Report the single table-bound credit assignments without reassigning.

    ``new_to_table`` is authored by the live credit assigner after typed table
    storage. This function may aggregate that decision for cost/yield output;
    it never projects tables, evaluates evidence, or decides what deserves
    credit.
    """

    rows = [dict(item) for item in assignments if isinstance(item, Mapping)]
    selected = [row for row in rows if bool(row.get("new_to_table"))]
    repeats = len(rows) - len(selected)

    datapoints: list[CreditedDatapoint] = []
    for row in selected:
        identity = str(row.get("identity") or "")
        source_id = str(row.get("source_id") or "")
        kind = (
            DatapointKind.BEST_GUESS
            if str(row.get("source_kind") or "") == DatapointKind.BEST_GUESS.value
            else DatapointKind.VERBATIM
        )
        datapoints.append(
            CreditedDatapoint(
                assignment_id=str(row.get("assignment_id") or identity),
                criterion_id=str(row.get("criterion_id") or identity),
                kind=kind,
                basis=EvidenceBasis.RESOLVED_ASSERTION_CHAIN,
                table=str(row.get("table") or ""),
                field=str(row.get("field") or ""),
                subject_id=str(row.get("subject_id") or ""),
                crediting_source_ids=(source_id,) if source_id else (),
                realized_episode_id=str(episode_id),
            )
        )

    return RewardReport(
        reward_version=REWARD_VERSION,
        criteria_projection_version=CRITERIA_PROJECTION_VERSION,
        episode_id=str(episode_id),
        before_table_state_id=(
            rows[0].get("before_table_state_id", "") if rows else ""
        ),
        after_table_state_id=(
            rows[-1].get("after_table_state_id", "") if rows else ""
        ),
        datapoints=tuple(datapoints),
        cost=aggregate_cost(cost_records),
        uncredited={
            "repeat_assignment": repeats,
        },
    )


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Best-guess artifact plumbing
# ---------------------------------------------------------------------------
#
# These predate this module's rewrite and are unchanged: they load and merge the
# run's own best-guess context exports. They carry no score. They exist because
# the accepted, judged best guesses are an *input* to the projection now rather
# than a component of a coverage count.


def load_seed_best_guess_rows(path: str | Path | None) -> list[dict[str, Any]]:
    """Load previous best-guess context rows adjacent to seeded table exports."""

    if not path:
        return []

    root = Path(path)
    candidates = []
    if root.name == "tables":
        candidates.append(root.parent / "derived")
    if root.name == "answers":
        candidates.append(root / "derived")
    candidates.extend(
        [
            root / "derived",
            root / "answers" / "derived",
        ]
    )

    seen_paths: set[Path] = set()
    rows: list[dict[str, Any]] = []
    for directory in candidates:
        if not directory.is_dir():
            continue
        # Any artifact stem: matches both this tree's Episode-labelled exports
        # and legacy round-numbered ones without inferring anything from the
        # number.
        for json_path in sorted(directory.glob("*_best_guess_context.json")):
            if json_path in seen_paths:
                continue
            seen_paths.add(json_path)
            rows.extend(_read_dict_rows(json_path))
    return rows


def merge_best_guess_rows(
    *groups: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge best-guess context rows by their stable row-slot keys."""

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for row in group:
            if not isinstance(row, Mapping):
                continue
            row_dict = dict(row)
            key = str(row_dict.get("row_slot_id") or "").strip() or _stable_json(row_dict)
            if key in seen:
                continue
            seen.add(key)
            merged.append(row_dict)
    return merged


def _read_dict_rows(path: Path) -> list[dict[str, Any]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
