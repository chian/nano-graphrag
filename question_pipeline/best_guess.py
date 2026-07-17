"""Stateful local best-guess recovery for derived answer-table context."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

from .derived_context import source_ids_from_row


ExtractFn = Callable[
    [str, list[dict[str, Any]], list[dict[str, Any]]],
    Awaitable[list[dict[str, Any]]],
]


BEST_GUESS_CONTEXT_COLUMNS = [
    "row_slot_id",
    "target_table",
    "source_row_index",
    "source_row_key",
    "canonical_column",
    "best_guess_value",
    "confidence",
    "basis",
    "operators",
    "source_ids",
    "source_chunks",
]

BEST_GUESS_CANDIDATE_COLUMNS = [
    "candidate_id",
    "row_slot_id",
    "target_table",
    "source_row_index",
    "source_row_key",
    "canonical_column",
    "operator",
    "best_guess_value",
    "confidence",
    "basis",
    "source_ids",
    "source_chunks",
    "accepted",
    "rejection_reason",
]

_MISSING_STRINGS = {
    "",
    "n/a",
    "na",
    "none",
    "not applicable",
    "not available",
    "not reported",
    "not specified",
    "not stated",
    "null",
    "unknown",
}

_NON_DERIVED_SLOT_TOKENS = {
    "amount",
    "average",
    "bound",
    "confidence",
    "count",
    "estimate",
    "interval",
    "max",
    "mean",
    "median",
    "min",
    "number",
    "quantity",
    "range",
    "ratio",
    "score",
    "std",
    "threshold",
    "total",
    "uncertainty",
    "value",
    "variance",
}
_SLOT_SKIP_TOKENS = {
    "and",
    "basis",
    "chunk",
    "chunks",
    "completeness",
    "confidence",
    "dedup",
    "deduplication",
    "description",
    "evidence",
    "gap",
    "id",
    "index",
    "key",
    "note",
    "or",
    "path",
    "query",
    "ref",
    "refs",
    "source",
    "status",
    "summary",
    "task",
    "url",
}
_ROW_CONTEXT_SKIP_TOKENS = _SLOT_SKIP_TOKENS | {
    "basis",
    "confidence",
}
_UUID_CHUNK_RE = re.compile(r"^(?P<source_id>.+)_chunk_(?P<index>\d+)$")


@dataclass(frozen=True)
class BestGuessSlotPlan:
    """One canonical column that may receive an inferred sidecar value."""

    id: str
    target_table: str
    canonical_column: str
    best_guess_key: str
    field_hints: tuple[str, ...] = ()
    reason: str = ""
    row_count: int = 0
    missing_count: int = 0
    observed_count: int = 0
    key_column: bool = False
    allowed_operators: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_table": self.target_table,
            "canonical_column": self.canonical_column,
            "best_guess_key": self.best_guess_key,
            "field_hints": list(self.field_hints),
            "reason": self.reason,
            "row_count": self.row_count,
            "missing_count": self.missing_count,
            "observed_count": self.observed_count,
            "key_column": self.key_column,
            "allowed_operators": list(self.allowed_operators),
        }


@dataclass(frozen=True)
class BestGuessTask:
    """One missing derived row-slot to try to fill from local evidence."""

    id: str
    target_table: str
    row_index: int
    source_row_key: str
    canonical_column: str
    best_guess_key: str
    row_values: dict[str, Any] = field(default_factory=dict)
    source_ids: tuple[str, ...] = ()
    source_chunks: tuple[str, ...] = ()

    @property
    def row_slot_id(self) -> str:
        return (
            f"{self.target_table}:{self.source_row_key}:"
            f"{self.canonical_column}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "row_slot_id": self.row_slot_id,
            "target_table": self.target_table,
            "row_index": self.row_index,
            "source_row_key": self.source_row_key,
            "canonical_column": self.canonical_column,
            "best_guess_key": self.best_guess_key,
            "row_values": dict(self.row_values),
            "source_ids": list(self.source_ids),
            "source_chunks": list(self.source_chunks),
        }


@dataclass(frozen=True)
class BestGuessCandidate:
    """One proposed value for a best-guess row-slot."""

    id: str
    row_slot_id: str
    target_table: str
    source_row_index: int
    source_row_key: str
    canonical_column: str
    operator: str
    best_guess_value: str
    confidence: float
    basis: str
    source_ids: tuple[str, ...] = ()
    source_chunks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        accepted = _accepted(self)
        return {
            "candidate_id": self.id,
            "row_slot_id": self.row_slot_id,
            "target_table": self.target_table,
            "source_row_index": self.source_row_index,
            "source_row_key": self.source_row_key,
            "canonical_column": self.canonical_column,
            "operator": self.operator,
            "best_guess_value": self.best_guess_value,
            "confidence": round(self.confidence, 3),
            "basis": self.basis,
            "source_ids": list(self.source_ids),
            "source_chunks": list(self.source_chunks),
            "accepted": accepted,
            "rejection_reason": "" if accepted else _rejection_reason(self),
        }


def run_best_guess_recovery_local(
    rows_by_name: Mapping[str, list[dict[str, Any]]],
    *,
    count_targets: Iterable[Mapping[str, Any]] = (),
    slot_targets: Iterable[Mapping[str, Any]] = (),
    source_records: Mapping[str, Mapping[str, Any]] | None = None,
    graph_records: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    max_tasks: int = 160,
) -> dict[str, Any]:
    """Run deterministic, source-local operators and return strategy state."""

    return _BestGuessRunner(
        rows_by_name,
        count_targets=count_targets,
        slot_targets=slot_targets,
        source_records=source_records or {},
        source_texts={},
        graph_records=graph_records or {},
        max_tasks=max_tasks,
        evidence_chars=0,
        extract_fn=None,
        llm_batch_size=0,
    ).run_local()


async def run_best_guess_recovery(
    rows_by_name: Mapping[str, list[dict[str, Any]]],
    *,
    count_targets: Iterable[Mapping[str, Any]] = (),
    slot_targets: Iterable[Mapping[str, Any]] = (),
    source_records: Mapping[str, Mapping[str, Any]] | None = None,
    source_texts: Mapping[str, str] | None = None,
    graph_records: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    max_tasks: int = 160,
    evidence_chars: int = 5000,
    extract_fn: ExtractFn | None = None,
    llm_batch_size: int = 8,
) -> dict[str, Any]:
    """Run local deterministic and LLM operators over existing evidence only."""

    return await _BestGuessRunner(
        rows_by_name,
        count_targets=count_targets,
        slot_targets=slot_targets,
        source_records=source_records or {},
        source_texts=source_texts or {},
        graph_records=graph_records or {},
        max_tasks=max_tasks,
        evidence_chars=evidence_chars,
        extract_fn=extract_fn,
        llm_batch_size=llm_batch_size,
    ).run()


def best_guess_context_by_row_key(
    state: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Index resolved best guesses for numeric-candidate sidecar export."""

    out: dict[str, dict[str, Any]] = {}
    for resolution in state.get("resolutions") or []:
        if not isinstance(resolution, Mapping):
            continue
        row_key = str(
            resolution.get("source_row_lookup_key")
            or (
                f"{resolution.get('target_table')}::"
                f"{resolution.get('source_row_index')}"
            )
        )
        slot = str(resolution.get("canonical_column") or "")
        value = str(resolution.get("best_guess_value") or "").strip()
        if not row_key or not slot or not value:
            continue

        out.setdefault(row_key, {})[slot] = {
            "value": value,
            "field": f"best_guess.{slot}",
            "basis": resolution.get("basis", ""),
            "confidence": resolution.get("confidence", 0.0),
            "operator": ",".join(resolution.get("operators") or []),
            "source_ids": resolution.get("source_ids") or [],
            "source_chunks": resolution.get("source_chunks") or [],
        }
    return out


class _BestGuessRunner:
    def __init__(
        self,
        rows_by_name: Mapping[str, list[dict[str, Any]]],
        *,
        count_targets: Iterable[Mapping[str, Any]],
        slot_targets: Iterable[Mapping[str, Any]],
        source_records: Mapping[str, Mapping[str, Any]],
        source_texts: Mapping[str, str],
        graph_records: Mapping[str, Sequence[Mapping[str, Any]]],
        max_tasks: int,
        evidence_chars: int,
        extract_fn: ExtractFn | None,
        llm_batch_size: int,
    ):
        self.rows_by_name = rows_by_name
        self.count_targets = list(count_targets)
        self.slot_targets = list(slot_targets)
        self.source_records = source_records
        self.source_texts = source_texts
        self.graph_records = graph_records
        self.max_tasks = max(0, max_tasks)
        self.evidence_chars = max(500, evidence_chars)
        self.extract_fn = extract_fn
        self.llm_batch_size = max(1, llm_batch_size)
        self.plan = build_best_guess_plan(
            rows_by_name,
            count_targets=self.count_targets,
            slot_targets=self.slot_targets,
        )
        self.tasks = build_best_guess_tasks(
            rows_by_name,
            self.plan,
            max_tasks=self.max_tasks,
        )
        self.candidates: list[BestGuessCandidate] = []
        self.attempts: list[dict[str, Any]] = []

    async def run(self) -> dict[str, Any]:
        self.run_local()
        if self.extract_fn is not None:
            await self._run_llm_operator("source_metadata_extract")
            await self._run_llm_operator("source_chunk_extract")
            await self._run_llm_operator("kg_neighbor_extract")
        return self._state()

    def run_local(self) -> dict[str, Any]:
        self._run_operator(
            "same_row_scan",
            self._same_row_candidates(self._open_tasks()),
            attempted=len(self._open_tasks()),
        )
        self._run_operator(
            "sibling_row_scan",
            self._sibling_row_candidates(self._open_tasks()),
            attempted=len(self._open_tasks()),
        )
        return self._state()

    async def _run_llm_operator(self, operator: str) -> None:
        open_tasks = self._open_tasks()
        if not open_tasks:
            return

        evidence = [
            evidence_item
            for task in open_tasks
            for evidence_item in [self._evidence(operator, task)]
            if evidence_item
        ]
        tasks = [task for task in open_tasks if task.id in {item["task_id"] for item in evidence}]
        if not tasks:
            self._run_operator(operator, [], attempted=0)
            return

        candidates: list[BestGuessCandidate] = []
        evidence_by_task = {str(item["task_id"]): item for item in evidence}
        for batch in _batches(tasks, self.llm_batch_size):
            batch_evidence = [
                evidence_by_task[task.id]
                for task in batch
                if task.id in evidence_by_task
            ]
            parsed = await self.extract_fn(
                operator,
                [task.to_dict() for task in batch],
                batch_evidence,
            )
            candidates.extend(self._coerce_llm_candidates(operator, parsed))

        self._run_operator(operator, candidates, attempted=len(tasks))

    def _run_operator(
        self,
        operator: str,
        candidates: list[BestGuessCandidate],
        *,
        attempted: int,
    ) -> None:
        before = set(self._resolved().keys())
        self.candidates.extend(candidates)
        after = self._resolved()
        accepted = {
            candidate.row_slot_id
            for candidate in candidates
            if _accepted(candidate)
        }
        self.attempts.append(
            {
                "operator": operator,
                "attempted_row_slots": attempted,
                "candidate_count": len(candidates),
                "accepted_row_slots": len(accepted),
                "marginal_row_slots": len(set(after) - before),
                "duplicate_row_slots": len(accepted & before),
                "open_row_slots_after": max(0, len(self.tasks) - len(after)),
                "confidence": _candidate_stats(candidates),
            }
        )

    def _open_tasks(self) -> list[BestGuessTask]:
        resolved = set(self._resolved())
        return [task for task in self.tasks if task.row_slot_id not in resolved]

    def _resolved(self) -> dict[str, dict[str, Any]]:
        return resolve_candidates(self.candidates)

    def _state(self) -> dict[str, Any]:
        resolved = list(self._resolved().values())
        coverage = {
            "planned_slots": len(self.plan),
            "row_slots": len(self.tasks),
            "resolved_row_slots": len(resolved),
            "open_row_slots": max(0, len(self.tasks) - len(resolved)),
        }
        return {
            "plan": [slot.to_dict() for slot in self.plan],
            "tasks": [task.to_dict() for task in self.tasks],
            "attempts": list(self.attempts),
            "operator_summary": _operator_summary(self.candidates, self.tasks),
            "overlap": _operator_overlap(self.candidates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "resolutions": resolved,
            "coverage": coverage,
        }

    def _same_row_candidates(
        self,
        tasks: Sequence[BestGuessTask],
    ) -> list[BestGuessCandidate]:
        candidates: list[BestGuessCandidate] = []
        slot_by_key = {(slot.target_table, slot.canonical_column): slot for slot in self.plan}
        for task in tasks:
            slot = slot_by_key.get((task.target_table, task.canonical_column))
            if slot is None:
                continue
            hit = _best_mapping_hit(task.row_values, slot)
            if hit is None:
                continue
            candidates.append(
                _candidate(
                    task,
                    operator="same_row_scan",
                    value=hit["value"],
                    confidence=float(hit["confidence"]),
                    basis=f"same row field {hit['field']}",
                )
            )
        return candidates

    def _sibling_row_candidates(
        self,
        tasks: Sequence[BestGuessTask],
    ) -> list[BestGuessCandidate]:
        source_values: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
        for table, rows in self.rows_by_name.items():
            for row in rows:
                row_source_ids = source_ids_from_row(row)
                for slot in self.plan:
                    if slot.target_table != table:
                        continue
                    value = _clean_value(row.get(slot.canonical_column))
                    if not value:
                        continue
                    for source_id in row_source_ids:
                        source_values[(table, slot.canonical_column, source_id)][value] += 1

        candidates: list[BestGuessCandidate] = []
        for task in tasks:
            votes: Counter[str] = Counter()
            for source_id in task.source_ids:
                votes.update(
                    source_values.get(
                        (task.target_table, task.canonical_column, source_id),
                        {},
                    )
                )
            if not votes:
                continue
            value, count = votes.most_common(1)[0]
            confidence = min(0.78, 0.55 + count * 0.05)
            candidates.append(
                _candidate(
                    task,
                    operator="sibling_row_scan",
                    value=value,
                    confidence=confidence,
                    basis="other rows sharing existing source provenance",
                )
            )
        return candidates

    def _evidence(self, operator: str, task: BestGuessTask) -> dict[str, Any] | None:
        if operator == "source_metadata_extract":
            records = [
                _compact_mapping(self.source_records.get(source_id, {}))
                for source_id in task.source_ids
                if self.source_records.get(source_id)
            ]
            records = [record for record in records if record]
            if not records:
                return None
            return {
                "task_id": task.id,
                "evidence_kind": "source_metadata",
                "sources": records,
            }

        if operator == "source_chunk_extract":
            excerpts = [
                {
                    "source_id": source_id,
                    "text": excerpt,
                }
                for source_id in task.source_ids
                for excerpt in [
                    _source_excerpt(
                        self.source_texts.get(source_id, ""),
                        task,
                        max_chars=self.evidence_chars,
                    )
                ]
                if excerpt
            ]
            if not excerpts:
                return None
            return {
                "task_id": task.id,
                "evidence_kind": "source_text",
                "sources": excerpts,
            }

        if operator == "kg_neighbor_extract":
            records = [
                record
                for source_id in task.source_ids
                for record in self.graph_records.get(source_id, ())[:12]
            ][:20]
            if not records:
                return None
            return {
                "task_id": task.id,
                "evidence_kind": "kg_records",
                "records": records,
            }

        return None

    def _coerce_llm_candidates(
        self,
        operator: str,
        records: Iterable[Mapping[str, Any]],
    ) -> list[BestGuessCandidate]:
        tasks = {task.id: task for task in self.tasks}
        candidates: list[BestGuessCandidate] = []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            task = tasks.get(str(record.get("task_id") or ""))
            if task is None:
                continue
            value = _clean_value(record.get("value"))
            if not value:
                continue
            try:
                confidence = float(record.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            candidates.append(
                _candidate(
                    task,
                    operator=operator,
                    value=value,
                    confidence=max(0.0, min(1.0, confidence)),
                    basis=str(record.get("basis") or ""),
                    source_ids=record.get("source_ids") or task.source_ids,
                    source_chunks=record.get("source_chunks") or task.source_chunks,
                )
            )
        return candidates


def build_best_guess_plan(
    rows_by_name: Mapping[str, list[dict[str, Any]]],
    *,
    count_targets: Iterable[Mapping[str, Any]],
    slot_targets: Iterable[Mapping[str, Any]] = (),
) -> list[BestGuessSlotPlan]:
    targets_by_table: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    def add_slot(
        table: str,
        column: str,
        *,
        key_column: bool,
        reason: str,
        field_hints: Iterable[Any] = (),
    ) -> None:
        table = str(table or "").strip()
        column = str(column or "").strip()
        if not table or not column:
            return
        current = targets_by_table[table].setdefault(
            column,
            {
                "key_column": False,
                "reason": "",
                "field_hints": [],
            },
        )
        current["key_column"] = bool(current.get("key_column")) or key_column
        if reason and not current.get("reason"):
            current["reason"] = reason
        current["field_hints"] = _unique(
            [
                *list(current.get("field_hints") or []),
                column,
                *list(field_hints),
            ],
        )

    for target in count_targets:
        if not isinstance(target, Mapping):
            continue
        table = str(target.get("target_table") or "").strip()
        for column in _as_list(target.get("key_columns")):
            add_slot(
                table,
                str(column or ""),
                key_column=True,
                reason=(
                    "target key column is missing in canonical rows and may be "
                    "inferred for derived grouping"
                ),
            )

    for target in slot_targets:
        if not isinstance(target, Mapping):
            continue
        table = str(target.get("target_table") or "").strip()
        columns = (
            target.get("columns")
            or target.get("key_columns")
            or target.get("column")
            or []
        )
        for column in _as_list(columns):
            add_slot(
                table,
                str(column or ""),
                key_column=bool(target.get("key_column")),
                reason=str(target.get("reason") or ""),
                field_hints=target.get("field_hints") or (),
            )

    plans: list[BestGuessSlotPlan] = []
    for table, targets in sorted(targets_by_table.items()):
        rows = rows_by_name.get(table, [])
        columns = _observed_columns(rows)
        for column, target in sorted(targets.items()):
            field_hints = _unique(
                [
                    column,
                    *list(target.get("field_hints") or []),
                    *_field_hints(column, columns),
                ],
            )
            if not field_hints and not _slot_is_derivable(column):
                continue
            missing_count = sum(1 for row in rows if _missing(row.get(column)))
            if missing_count <= 0:
                continue
            observed_count = max(0, len(rows) - missing_count)
            plans.append(
                BestGuessSlotPlan(
                    id=_stable_id({"table": table, "column": column}),
                    target_table=table,
                    canonical_column=column,
                    best_guess_key=f"best_guess.{column}",
                    field_hints=tuple(field_hints),
                    reason=str(target.get("reason") or ""),
                    row_count=len(rows),
                    missing_count=missing_count,
                    observed_count=observed_count,
                    key_column=bool(target.get("key_column")),
                    allowed_operators=(
                        "same_row_scan",
                        "sibling_row_scan",
                        "source_metadata_extract",
                        "source_chunk_extract",
                        "kg_neighbor_extract",
                    ),
                )
            )
    return plans


def build_best_guess_tasks(
    rows_by_name: Mapping[str, list[dict[str, Any]]],
    plan: Sequence[BestGuessSlotPlan],
    *,
    max_tasks: int,
) -> list[BestGuessTask]:
    if max_tasks <= 0:
        return []

    tasks: list[BestGuessTask] = []
    by_table: dict[str, list[BestGuessSlotPlan]] = defaultdict(list)
    for slot in plan:
        by_table[slot.target_table].append(slot)

    for table, rows in sorted(rows_by_name.items()):
        for row_index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            source_row_key = _source_row_key(row, row_index)
            source_ids = tuple(source_ids_from_row(row))
            source_chunks = tuple(_source_chunks_from_row(row))
            row_values = _row_values(row)
            for slot in by_table.get(table, ()):
                if not _missing(row.get(slot.canonical_column)):
                    continue
                task_id = _stable_id(
                    {
                        "table": table,
                        "row": source_row_key,
                        "column": slot.canonical_column,
                    }
                )
                tasks.append(
                    BestGuessTask(
                        id=task_id,
                        target_table=table,
                        row_index=row_index,
                        source_row_key=source_row_key,
                        canonical_column=slot.canonical_column,
                        best_guess_key=slot.best_guess_key,
                        row_values=row_values,
                        source_ids=source_ids,
                        source_chunks=source_chunks,
                    )
                )
    return sorted(tasks, key=_task_priority)[:max_tasks]


def resolve_candidates(
    candidates: Iterable[BestGuessCandidate],
) -> dict[str, dict[str, Any]]:
    by_slot: dict[str, list[BestGuessCandidate]] = defaultdict(list)
    for candidate in candidates:
        if _accepted(candidate):
            by_slot[candidate.row_slot_id].append(candidate)

    resolved: dict[str, dict[str, Any]] = {}
    for row_slot_id, slot_candidates in by_slot.items():
        value_groups: dict[str, list[BestGuessCandidate]] = defaultdict(list)
        for candidate in slot_candidates:
            value_groups[_norm(candidate.best_guess_value)].append(candidate)
        best_group = max(
            value_groups.values(),
            key=lambda group: (
                len({candidate.operator for candidate in group}),
                max(candidate.confidence for candidate in group),
                len(group),
            ),
        )
        best = max(best_group, key=lambda candidate: candidate.confidence)
        operators = sorted({candidate.operator for candidate in best_group})
        confidence = min(
            0.99,
            max(candidate.confidence for candidate in best_group)
            + 0.04 * max(0, len(operators) - 1)
            + 0.02 * max(0, len(best_group) - 1),
        )
        source_ids = _unique(
            source_id
            for candidate in best_group
            for source_id in candidate.source_ids
        )
        source_chunks = _unique(
            chunk
            for candidate in best_group
            for chunk in candidate.source_chunks
        )
        resolved[row_slot_id] = {
            "row_slot_id": row_slot_id,
            "source_row_lookup_key": (
                f"{best.target_table}::{best.source_row_index}"
            ),
            "target_table": best.target_table,
            "source_row_index": best.source_row_index,
            "source_row_key": best.source_row_key,
            "canonical_column": best.canonical_column,
            "best_guess_value": best.best_guess_value,
            "confidence": round(confidence, 3),
            "basis": best.basis,
            "operators": operators,
            "source_ids": source_ids,
            "source_chunks": source_chunks,
            "candidate_count": len(slot_candidates),
            "conflict_count": max(0, len(value_groups) - 1),
        }
    return dict(sorted(resolved.items()))


def _operator_summary(
    candidates: Sequence[BestGuessCandidate],
    tasks: Sequence[BestGuessTask],
) -> list[dict[str, Any]]:
    resolved_before: set[str] = set()
    rows: list[dict[str, Any]] = []
    for operator in (
        "same_row_scan",
        "sibling_row_scan",
        "source_metadata_extract",
        "source_chunk_extract",
        "kg_neighbor_extract",
    ):
        accepted = [
            candidate
            for candidate in candidates
            if candidate.operator == operator and _accepted(candidate)
        ]
        accepted_slots = {candidate.row_slot_id for candidate in accepted}
        rows.append(
            {
                "operator": operator,
                "gross_row_slots": len(accepted_slots),
                "marginal_row_slots": len(accepted_slots - resolved_before),
                "overlap_row_slots": len(accepted_slots & resolved_before),
                "accepted_candidates": len(accepted),
            }
        )
        resolved_before.update(accepted_slots)

    attempted_slots = {task.row_slot_id for task in tasks}
    resolved_slots = set(resolve_candidates(candidates))
    rows.append(
        {
            "operator": "overall",
            "gross_row_slots": len(resolved_slots),
            "marginal_row_slots": len(resolved_slots),
            "overlap_row_slots": 0,
            "accepted_candidates": sum(1 for candidate in candidates if _accepted(candidate)),
            "unresolved_row_slots": len(attempted_slots - resolved_slots),
        }
    )
    return rows


def _operator_overlap(
    candidates: Sequence[BestGuessCandidate],
) -> list[dict[str, Any]]:
    by_operator: dict[str, dict[str, str]] = defaultdict(dict)
    for candidate in candidates:
        if not _accepted(candidate):
            continue
        by_operator[candidate.operator][candidate.row_slot_id] = _norm(
            candidate.best_guess_value
        )

    rows: list[dict[str, Any]] = []
    operators = sorted(by_operator)
    for left_index, left in enumerate(operators):
        for right in operators[left_index + 1 :]:
            left_slots = by_operator[left]
            right_slots = by_operator[right]
            shared = set(left_slots) & set(right_slots)
            conflicts = {
                row_slot_id
                for row_slot_id in shared
                if left_slots[row_slot_id] != right_slots[row_slot_id]
            }
            rows.append(
                {
                    "left": left,
                    "right": right,
                    "shared_row_slots": len(shared),
                    "conflicting_row_slots": len(conflicts),
                }
            )
    return rows


def _best_mapping_hit(
    row: Mapping[str, Any],
    slot: BestGuessSlotPlan,
) -> dict[str, Any] | None:
    field_hints = {
        _clean_field_name(hint)
        for hint in slot.field_hints
        if _clean_field_name(hint)
    }
    hits: list[dict[str, Any]] = []
    for field, value in _flatten(row):
        field_key = _clean_field_name(field)
        if field_key not in field_hints:
            continue
        text = _clean_value(value)
        if not text or not re.search(r"[A-Za-z]", text):
            continue
        hits.append(
            {
                "field": field,
                "value": text,
                "basis": "row field",
                "confidence": 0.95 if field_key == slot.canonical_column else 0.82,
            }
        )
    if not hits:
        return None
    return sorted(hits, key=lambda item: (-item["confidence"], item["field"]))[0]


def _candidate(
    task: BestGuessTask,
    *,
    operator: str,
    value: str,
    confidence: float,
    basis: str,
    source_ids: Iterable[Any] | None = None,
    source_chunks: Iterable[Any] | None = None,
) -> BestGuessCandidate:
    source_ids = tuple(str(item) for item in (source_ids or task.source_ids) if item)
    source_chunks = tuple(
        str(item) for item in (source_chunks or task.source_chunks) if item
    )
    payload = {
        "row_slot_id": task.row_slot_id,
        "operator": operator,
        "value": value,
        "basis": basis,
        "source_ids": source_ids,
        "source_chunks": source_chunks,
    }
    return BestGuessCandidate(
        id=_stable_id(payload),
        row_slot_id=task.row_slot_id,
        target_table=task.target_table,
        source_row_index=task.row_index,
        source_row_key=task.source_row_key,
        canonical_column=task.canonical_column,
        operator=operator,
        best_guess_value=_clean_value(value),
        confidence=max(0.0, min(1.0, confidence)),
        basis=basis[:500],
        source_ids=source_ids,
        source_chunks=source_chunks,
    )


def _source_excerpt(text: str, task: BestGuessTask, *, max_chars: int) -> str:
    text = str(text or "")
    if not text:
        return ""

    chunks = _chunk_text(text)
    selected: list[str] = []
    wanted = {
        int(match.group("index"))
        for value in task.source_chunks
        for match in [_UUID_CHUNK_RE.match(value)]
        if match is not None
    }
    for index in sorted(wanted):
        if 0 <= index < len(chunks):
            selected.append(chunks[index])

    if not selected:
        terms = _evidence_terms(task)
        ranked = sorted(
            enumerate(chunks),
            key=lambda item: (-_text_score(item[1], terms), item[0]),
        )
        selected = [chunk for _, chunk in ranked[:2]]

    return "\n\n".join(selected)[:max_chars].strip()


def _chunk_text(text: str, *, chunk_size: int = 2400, overlap: int = 240) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _evidence_terms(task: BestGuessTask) -> set[str]:
    text = " ".join(
        str(value)
        for value in [
            task.canonical_column,
            *task.row_values.keys(),
            *task.row_values.values(),
        ]
        if not isinstance(value, (list, tuple, set, dict))
    )
    return {
        token
        for token in re.findall(r"[A-Za-z0-9_]{3,}", text.lower())
        if token not in _SLOT_SKIP_TOKENS
    }


def _text_score(text: str, terms: set[str]) -> int:
    normalized = text.lower()
    return sum(normalized.count(term) * len(term) for term in terms)


def _field_hints(column: str, columns: Sequence[str]) -> list[str]:
    column_signature = _field_signature(column)
    hints = [column]
    for candidate in columns:
        if _field_signature(candidate) == column_signature:
            hints.append(candidate)
    return _unique(hints)


def _slot_is_derivable(column: str) -> bool:
    tokens = _field_tokens(column)
    return bool(tokens) and not bool(
        tokens & (_SLOT_SKIP_TOKENS | _NON_DERIVED_SLOT_TOKENS)
    )


def _observed_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows[:200]:
        for column in row:
            if column not in columns:
                columns.append(str(column))
    return columns


def _source_row_key(row: Mapping[str, Any], row_index: int) -> str:
    for key in ("row_id", "deduplication_key", "dedup_key", "group_key", "id"):
        value = row.get(key)
        if not _missing(value):
            return str(value)[:240]

    payload = json.dumps(_row_values(row), sort_keys=True, default=str)
    return f"{row_index}:{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]}"


def _row_values(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if len(out) >= 24:
            break
        if _missing(value):
            continue
        if _field_tokens(str(key)) & _ROW_CONTEXT_SKIP_TOKENS:
            continue
        out[str(key)] = _compact(value)
    return out


def _source_chunks_from_row(row: Mapping[str, Any]) -> list[str]:
    values = [
        *_as_source_list(row.get("source_chunks")),
        *_as_source_list(row.get("source_chunk")),
    ]
    return _unique(str(value) for value in values if value)


def _task_priority(task: BestGuessTask) -> tuple[int, int, int, str, int, str]:
    return (
        -len(task.source_chunks),
        -len(task.source_ids),
        -len(task.row_values),
        task.target_table,
        task.row_index,
        task.canonical_column,
    )


def _accepted(candidate: BestGuessCandidate) -> bool:
    if not candidate.best_guess_value:
        return False
    threshold = 0.8 if candidate.operator == "sibling_row_scan" else 0.5
    return candidate.confidence >= threshold


def _rejection_reason(candidate: BestGuessCandidate) -> str:
    if not candidate.best_guess_value:
        return "empty value"
    if candidate.operator == "sibling_row_scan":
        return "sibling-only signal needs stronger corroboration"
    return "below confidence threshold"


def _candidate_stats(candidates: Sequence[BestGuessCandidate]) -> dict[str, Any]:
    if not candidates:
        return {"min": None, "median": None, "max": None}
    values = sorted(candidate.confidence for candidate in candidates)
    return {
        "min": round(values[0], 3),
        "median": round(values[len(values) // 2], 3),
        "max": round(values[-1], 3),
    }


def _compact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, inner in value.items():
        if key == "text" or _missing(inner):
            continue
        if isinstance(inner, Mapping):
            compact = _compact_mapping(inner)
            if compact:
                out[str(key)] = compact
        elif isinstance(inner, (list, tuple, set)):
            compact_list = [_compact(item) for item in list(inner)[:12] if not _missing(item)]
            if compact_list:
                out[str(key)] = compact_list
        else:
            out[str(key)] = _compact(inner)
    return out


def _compact(value: Any) -> Any:
    text = str(value)
    return text[:497] + "..." if len(text) > 500 else value


def _flatten(
    value: Mapping[str, Any],
    *,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 2,
) -> Iterable[tuple[str, Any]]:
    for key, inner in value.items():
        field = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(inner, Mapping) and depth < max_depth:
            yield from _flatten(inner, prefix=field, depth=depth + 1)
        else:
            yield field, inner


def _field_tokens(field: str) -> set[str]:
    field = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(field))
    return {
        token
        for token in re.split(r"[^A-Za-z0-9]+", field.lower())
        if token
    }


def _field_signature(field: str) -> tuple[str, ...]:
    filler = {"field", "label", "name", "type", "value", "values"}
    return tuple(sorted(_field_tokens(field) - filler))


def _clean_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9_.]+", "_", str(value or "").lower()).strip("_.")


def _clean_value(value: Any) -> str:
    if _missing(value):
        return ""
    text = re.sub(r"\s+", " ", str(value).strip())
    return text[:500]


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _stable_id(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _as_list(values: Any) -> list[Any]:
    if _missing(values):
        return []
    if isinstance(values, list):
        return values
    if isinstance(values, (tuple, set)):
        return list(values)
    return [values]


def _as_source_list(values: Any) -> list[Any]:
    if _missing(values):
        return []
    if isinstance(values, str):
        try:
            parsed = json.loads(values)
        except json.JSONDecodeError:
            return [value.strip(" \t\r\n\"'[]") for value in re.split(r"[,;\s]+", values)]
        return _as_source_list(parsed)
    return _as_list(values)


def _unique(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if _missing(value):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_STRINGS
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _batches(
    values: Sequence[BestGuessTask],
    size: int,
) -> Iterable[list[BestGuessTask]]:
    for index in range(0, len(values), size):
        yield list(values[index : index + size])
