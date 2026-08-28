"""Stateful local best-guess recovery for derived answer-table context."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
import asyncio
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

from .criteria import is_missing_value
from .derived_context import source_ids_from_row
from .windowing import measured_size, window_items, window_stamps


ExtractFn = Callable[
    [str, list[dict[str, Any]], list[dict[str, Any]]],
    Awaitable[list[dict[str, Any]]],
]
ProgressFn = Callable[[dict[str, Any]], None]


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

#: This module kept its own eleven-token set until phase 4E-c. `criteria` owns
#: the convention now, and its union adds seven tokens here (`-`, `--`,
#: `<null>`, `[null]`, `not found`, `not provided`, `not specified in current
#: evidence`). Direction, registered rather than assumed: more cells reading as
#: missing means more best-guess tasks and more spend. Left alone, this module
#: would have proposed a guess for a value the crediter then refused.

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

#: Serialized-character budget for the evidence carried by one extraction call.
#:
#: Set to the value the prompt builder previously enforced by clipping, so the
#: bound is unchanged in size and changed only in kind: it is now produced by
#: grouping rather than by cutting, and a batch that would exceed it becomes
#: another batch instead of a truncated one. Every evidence item still reaches
#: some call.
EVIDENCE_CALL_CHARS = 18000


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
    max_tasks: int | None = None,
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
    max_tasks: int | None = None,
    evidence_chars: int = 5000,
    extract_fn: ExtractFn | None = None,
    llm_batch_size: int = 8,
    llm_timeout_sec: float | None = None,
    progress_fn: ProgressFn | None = None,
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
        llm_timeout_sec=llm_timeout_sec,
        progress_fn=progress_fn,
    ).run()


async def page_best_guess(
    *,
    records: Sequence[Mapping[str, Any]],
    columns_by_table: Mapping[str, Sequence[str]],
    source_id: str,
    page_text: str = "",
    extract_fn: ExtractFn | None = None,
    llm_batch_size: int = 8,
    llm_timeout_sec: float | None = None,
    evidence_chars: int = 5000,
) -> dict[str, Any]:
    """Derive missing declared-column values from ONE page's own evidence.

    THE PAGE-SCOPED SIBLING OF :func:`run_best_guess_recovery`, AND IT LIVES
    HERE BECAUSE THIS MODULE OWNS THE CONCEPT. That function takes exported
    table rows (``rows_by_name``) plus every accepted source's text; it has no
    notion of a page and could not serve this grain. A second module producing
    page-scoped guesses would be a second owner of "best guess", so this is a
    new entry point over the *same* plan builder, the same task builder, the
    same operators, the same resolver, and -- load-bearing -- the same
    acceptance predicate :func:`_accepted`. One owner survives the split only if
    the predicate does.

    **WHAT IT IS FOR.** The acquisition loop's second credit kind is minted when
    one extracted record carries a non-trivial value for every declared credit
    column, and `docs/ACQUISITION_LOOP.md` defines that as "verbatim, **or an
    evidenced best guess or range**". A conjunction over every declared column
    from one page's verbatim extraction essentially never fires, so without this
    stage the chartered curve sits flat for a reason no disclosure can state.

    **WHAT IT IS NOT FOR, and this is the boundary that matters.** Nothing here
    is written into any exported row. The round-end pass over exported rows
    remains the only writer of the ``judged_best_guess_*`` basis, and therefore
    the only input to `criteria`, to reward, and to any datapoint claim. What
    this returns is an acquisition control signal that the crediter reads and
    the page-detail record carries. One producer of the criteria basis, one
    producer of an acquisition credit, and this is which.

    ``records`` are one page's extracted records, each ``{"table", "index",
    "values", "source_chunks"}``. Tasks are built only for declared columns a
    record left missing -- that is the page-grain equivalent of the projection's
    "only where no row of the subject supplies the field" guard, which is
    applied against a row and is **not** inherited by a per-resolution
    predicate.

    Returns the resolutions in the shape ``criteria`` reads, the candidates
    behind them, and what the stage cost. **At most one model call per batch of
    open slots**, and none at all when the verbatim pass left nothing open.
    """

    rows_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chunks_by_row: dict[tuple[str, int], tuple[str, ...]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        table = str(record.get("table") or "").strip()
        values = record.get("values")
        if not table or not isinstance(values, Mapping):
            continue
        position = len(rows_by_name[table])
        rows_by_name[table].append(dict(values))
        chunks_by_row[(table, position)] = tuple(
            str(chunk) for chunk in (record.get("source_chunks") or ()) if chunk
        )

    slot_targets = [
        {"target_table": table, "columns": list(columns)}
        for table, columns in columns_by_table.items()
        if columns
    ]
    plan = build_best_guess_plan(
        rows_by_name,
        count_targets=(),
        slot_targets=slot_targets,
    )
    tasks = [
        # The page is the one source every task cites: these values are derived
        # from this page's own text and from nothing else, so attributing them
        # to any other source would manufacture provenance.
        BestGuessTask(
            id=task.id,
            target_table=task.target_table,
            row_index=task.row_index,
            source_row_key=task.source_row_key,
            canonical_column=task.canonical_column,
            best_guess_key=task.best_guess_key,
            row_values=task.row_values,
            source_ids=(str(source_id),),
            source_chunks=chunks_by_row.get(
                (task.target_table, task.row_index), ()
            ),
        )
        for task in build_best_guess_tasks(rows_by_name, plan, max_tasks=None)
    ]

    report: dict[str, Any] = {
        "resolutions": [],
        "candidates": [],
        "task_count": len(tasks),
        "llm_calls": 0,
        "errors": [],
    }
    if not tasks:
        return report

    slot_by_key = {
        (slot.target_table, slot.canonical_column): slot for slot in plan
    }
    candidates: list[BestGuessCandidate] = []
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
                basis=f"same extracted record field {hit['field']}",
            )
        )

    # `sibling_row_scan` is deliberately not run at this grain. Its ceiling is
    # 0.78 and `_accepted` requires 0.8 for it, so it can produce no accepted
    # candidate -- and its premise, that the rows it scans share provenance, is
    # trivially true within one page, which is the least independent evidence
    # there is. Repeats within one source are propagation of that source.

    if extract_fn is not None and page_text:
        open_slots = {candidate.row_slot_id for candidate in candidates}
        open_tasks = [task for task in tasks if task.row_slot_id not in open_slots]
        pairs = [
            (task, evidence_item)
            for task in open_tasks
            for evidence_item in _window_evidence_items(
                task.id,
                "source_text",
                "sources",
                [
                    {"source_id": str(source_id), "text": window}
                    for window in _source_windows(
                        page_text,
                        task,
                        max_chars=max(500, evidence_chars),
                    )
                ],
                budget=max(500, evidence_chars),
            )
        ]
        tasks_by_id = {task.id: task for task in tasks}
        for batch in _batches(
            pairs,
            max(1, llm_batch_size),
            char_budget=max(max(500, evidence_chars), EVIDENCE_CALL_CHARS),
        ):
            batch_tasks = list({task.id: task for task, _ in batch}.values())
            batch_evidence = [item for _, item in batch]
            try:
                call = extract_fn(
                    "source_chunk_extract",
                    [task.to_dict() for task in batch_tasks],
                    batch_evidence,
                )
                if llm_timeout_sec and llm_timeout_sec > 0:
                    parsed = await asyncio.wait_for(call, timeout=llm_timeout_sec)
                else:
                    parsed = await call
            except Exception as exc:  # noqa: BLE001 - one page's guess stage never aborts a run
                report["errors"].append(
                    {
                        "operator": "source_chunk_extract",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                continue
            report["llm_calls"] = int(report["llm_calls"]) + 1
            for item in parsed or ():
                if not isinstance(item, Mapping):
                    continue
                task = tasks_by_id.get(str(item.get("task_id") or ""))
                if task is None:
                    continue
                value = _clean_value(item.get("value"))
                if not value:
                    continue
                try:
                    confidence = float(item.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
                candidates.append(
                    _candidate(
                        task,
                        operator="source_chunk_extract",
                        value=value,
                        confidence=max(0.0, min(1.0, confidence)),
                        basis=str(item.get("basis") or ""),
                        source_ids=(str(source_id),),
                        source_chunks=item.get("source_chunks")
                        or task.source_chunks,
                    )
                )

    resolved = resolve_candidates(candidates)
    report["candidates"] = [candidate.to_dict() for candidate in candidates]
    report["resolutions"] = list(resolved.values())
    return report


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
        max_tasks: int | None,
        evidence_chars: int,
        extract_fn: ExtractFn | None,
        llm_batch_size: int,
        llm_timeout_sec: float | None = None,
        progress_fn: ProgressFn | None = None,
    ):
        self.rows_by_name = rows_by_name
        self.count_targets = list(count_targets)
        self.slot_targets = list(slot_targets)
        self.source_records = source_records
        self.source_texts = source_texts
        self.graph_records = graph_records
        self.max_tasks = None if max_tasks is None else max(0, max_tasks)
        self.evidence_chars = max(500, evidence_chars)
        self.extract_fn = extract_fn
        self.llm_batch_size = max(1, llm_batch_size)
        # Never below one window: a window is already sized to fit a single
        # call, so a call budget under it would split a group the window layer
        # deliberately kept whole.
        self.evidence_call_chars = max(self.evidence_chars, EVIDENCE_CALL_CHARS)
        self.llm_timeout_sec = (
            float(llm_timeout_sec or 0.0) if llm_timeout_sec else None
        )
        self.progress_fn = progress_fn
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
        self.errors: list[dict[str, Any]] = []
        #: Audit trail of every slot where windows disagreed, and how it was
        #: settled. Written whether or not a model was available.
        self.reconciliations: list[dict[str, Any]] = []
        #: Slots an adjudicator actually settled. Only these may resolve when
        #: their candidates disagree; the rest stay contested.
        self.adjudicated_slots: set[str] = set()
        #: Candidates a reconciliation verdict rejected. They stay in
        #: `candidates` for audit and are excluded from resolution.
        self.suppressed_candidate_ids: set[str] = set()

    async def run(self) -> dict[str, Any]:
        self.run_local()
        if self.extract_fn is not None:
            await self._run_llm_operator("source_metadata_extract")
            await self._run_llm_operator("source_chunk_extract")
            await self._run_llm_operator("kg_neighbor_extract")
            await self._reconcile_windows()
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

        # One (task, evidence-window) pair per call's worth of evidence. A task
        # whose evidence exceeds one window appears in several pairs, so every
        # chunk it has is read by some call rather than clipped away.
        pairs = [
            (task, evidence_item)
            for task in open_tasks
            for evidence_item in self._evidence_windows(operator, task)
        ]
        if not pairs:
            self._run_operator(operator, [], attempted=0)
            return

        tasks_by_id = {task.id: task for task, _ in pairs}
        tasks = list(tasks_by_id.values())
        candidates: list[BestGuessCandidate] = []
        batches = list(
            _batches(
                pairs,
                self.llm_batch_size,
                char_budget=self.evidence_call_chars,
            )
        )
        self._emit_progress(
            {
                "event": "operator_start",
                "operator": operator,
                "open_row_slots": len(open_tasks),
                "evidence_tasks": len(tasks),
                "evidence_windows": len(pairs),
                "batches": len(batches),
            }
        )
        for batch_index, batch in enumerate(batches):
            batch_evidence = [evidence_item for _, evidence_item in batch]
            # A task appearing in several windows is sent once; its windows are
            # distinct evidence items carrying the same task_id.
            batch_tasks = list({task.id: task for task, _ in batch}.values())
            self._emit_progress(
                {
                    "event": "batch_start",
                    "operator": operator,
                    "batch_index": batch_index,
                    "batch_count": len(batches),
                    "row_slots": len(batch_tasks),
                    "evidence_items": len(batch_evidence),
                    # Recorded because its absence is why the clipping exposure
                    # here had to be inferred from a windows-per-batch ratio
                    # instead of read off. One number closes that permanently.
                    "evidence_chars": sum(
                        measured_size(item) for item in batch_evidence
                    ),
                    "evidence_call_budget_chars": self.evidence_call_chars,
                }
            )
            try:
                call = self.extract_fn(
                    operator,
                    [task.to_dict() for task in batch_tasks],
                    batch_evidence,
                )
                if self.llm_timeout_sec and self.llm_timeout_sec > 0:
                    parsed = await asyncio.wait_for(
                        call,
                        timeout=self.llm_timeout_sec,
                    )
                else:
                    parsed = await call
            except Exception as exc:  # noqa: BLE001 - one slow sidecar batch should not stop table export
                error = {
                    "operator": operator,
                    "batch_index": batch_index,
                    "row_slots": len(batch_tasks),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                self.errors.append(error)
                self._emit_progress({"event": "batch_error", **error})
                continue

            batch_candidates = self._coerce_llm_candidates(operator, parsed)
            candidates.extend(batch_candidates)
            self._emit_progress(
                {
                    "event": "batch_done",
                    "operator": operator,
                    "batch_index": batch_index,
                    "batch_count": len(batches),
                    "row_slots": len(batch_tasks),
                    "candidate_count": len(batch_candidates),
                    "resolved_row_slots": len(self._resolved()),
                }
            )

        self._run_operator(operator, candidates, attempted=len(tasks))
        self._emit_progress(
            {
                "event": "operator_done",
                "operator": operator,
                "attempted_row_slots": len(tasks),
                "candidate_count": len(candidates),
                "error_count": len(
                    [
                        error
                        for error in self.errors
                        if error.get("operator") == operator
                    ]
                ),
                "open_row_slots_after": max(
                    0,
                    len(self.tasks) - len(self._resolved()),
                ),
            }
        )

    # ------------------------------------------------------------------ #
    # Cross-window reconciliation
    #
    # The same fact is usually captured imperfectly and more than once: two
    # windows of one document, or two documents, disagree on a value not
    # because one is wrong but because each saw part of it. `resolve_candidates`
    # settles that by popularity -- most operators agreeing wins -- which is
    # exactly backwards when one window holds the real evidence and the others
    # hold none.
    #
    # So disagreement is detected deterministically, and only genuinely
    # conflicting slots are put to a model, which is shown the *cited chunks
    # from both sides* and returns a typed verdict: keep one, keep both, or
    # keep neither. Agreement costs nothing, and every outcome is recorded.
    # ------------------------------------------------------------------ #

    def _disagreeing_slots(self) -> dict[str, list[BestGuessCandidate]]:
        """Slots whose accepted candidates propose more than one value.

        LOAD-BEARING GATE, NOT A FILTER FOR TIDINESS. The `_accepted(candidate)`
        test below is the only thing keeping `sibling_row_scan` confidences off
        the credit path by this route. `_reconcile_windows` puts
        `"confidence": candidate.confidence` directly in front of an
        adjudicating model, and that verdict decides which value survives --
        the one path where a candidate's confidence reaches the reward surface
        without passing through `resolve_candidates`.

        `sibling_row_scan` is structurally unacceptable (its confidence caps at
        0.78 against a 0.80 threshold in `_accepted`), so it never reaches the
        adjudicator today. Widening this to show the adjudicator rejected
        candidates "for context" would make sibling confidence live on the
        credit path without anyone touching `_accepted` or the cap, and the
        change would look local and harmless here. If you need rejected
        candidates in that payload, treat it as a reward change: it needs a
        `REWARD_VERSION` bump and the review that goes with one.
        """

        by_slot: dict[str, list[BestGuessCandidate]] = defaultdict(list)
        for candidate in self.candidates:
            if candidate.id in self.suppressed_candidate_ids:
                continue
            if _accepted(candidate):
                by_slot[candidate.row_slot_id].append(candidate)
        return {
            row_slot_id: candidates
            for row_slot_id, candidates in by_slot.items()
            if len({_norm(c.best_guess_value) for c in candidates}) > 1
        }

    def _chunk_evidence(self, candidate: BestGuessCandidate) -> str:
        """The text of the chunks this candidate cited, so both sides are read."""

        texts: list[str] = []
        for reference in candidate.source_chunks:
            match = _UUID_CHUNK_RE.match(str(reference))
            if not match:
                continue
            source_text = self.source_texts.get(match.group("source_id"), "")
            if not source_text:
                continue
            chunks = _chunk_text(source_text)
            index = int(match.group("index"))
            if 0 <= index < len(chunks):
                texts.append(chunks[index])
        return "\n\n".join(texts)

    async def _reconcile_windows(self) -> None:
        disagreements = self._disagreeing_slots()
        if not disagreements:
            return

        self._emit_progress(
            {
                "event": "reconcile_start",
                "disagreeing_row_slots": len(disagreements),
            }
        )

        for row_slot_id, candidates in disagreements.items():
            payload = {
                "row_slot_id": row_slot_id,
                "target_table": candidates[0].target_table,
                "canonical_column": candidates[0].canonical_column,
                "candidates": [
                    {
                        "candidate_id": candidate.id,
                        "best_guess_value": candidate.best_guess_value,
                        "confidence": candidate.confidence,
                        "basis": candidate.basis,
                        "operator": candidate.operator,
                        "source_ids": list(candidate.source_ids),
                        "source_chunks": list(candidate.source_chunks),
                        "evidence_text": self._chunk_evidence(candidate),
                    }
                    for candidate in candidates
                ],
            }
            record: dict[str, Any] = {
                "row_slot_id": row_slot_id,
                "candidate_ids": [candidate.id for candidate in candidates],
                "distinct_values": sorted(
                    {_norm(c.best_guess_value) for c in candidates}
                ),
            }
            try:
                call = self.extract_fn("reconcile_windows", [payload], [])
                if self.llm_timeout_sec and self.llm_timeout_sec > 0:
                    parsed = await asyncio.wait_for(
                        call, timeout=self.llm_timeout_sec
                    )
                else:
                    parsed = await call
            except Exception as exc:  # noqa: BLE001 - fall back, never abort
                record.update(
                    {
                        "reconciled": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                        "fallback": "popularity_resolution",
                    }
                )
                self.reconciliations.append(record)
                self.errors.append(
                    {
                        "operator": "reconcile_windows",
                        "row_slot_id": row_slot_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                continue

            verdict, keep_ids, reason = _coerce_reconciliation(
                parsed,
                row_slot_id=row_slot_id,
                valid_ids={candidate.id for candidate in candidates},
            )
            if verdict is None:
                # An unusable verdict leaves the deterministic resolution in
                # place rather than guessing at what the model meant.
                record.update(
                    {
                        "reconciled": False,
                        "reason": "unusable verdict",
                        "fallback": "popularity_resolution",
                    }
                )
                self.reconciliations.append(record)
                continue

            rejected = [
                candidate.id
                for candidate in candidates
                if candidate.id not in keep_ids
            ]
            self.suppressed_candidate_ids.update(rejected)
            self.adjudicated_slots.add(row_slot_id)
            record.update(
                {
                    "reconciled": True,
                    "verdict": verdict,
                    "kept_candidate_ids": sorted(keep_ids),
                    "rejected_candidate_ids": sorted(rejected),
                    "reason": reason,
                }
            )
            self.reconciliations.append(record)

        self._emit_progress(
            {
                "event": "reconcile_done",
                "disagreeing_row_slots": len(disagreements),
                "reconciled": len(
                    [r for r in self.reconciliations if r.get("reconciled")]
                ),
                "suppressed_candidates": len(self.suppressed_candidate_ids),
            }
        )

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

    def _live_candidates(self) -> list[BestGuessCandidate]:
        return [
            candidate
            for candidate in self.candidates
            if candidate.id not in self.suppressed_candidate_ids
        ]

    def _resolved(self) -> dict[str, dict[str, Any]]:
        return resolve_candidates(
            self._live_candidates(),
            adjudicated_slots=self.adjudicated_slots,
        )

    def _contested(self) -> list[dict[str, Any]]:
        return contested_slots(
            self._live_candidates(),
            adjudicated_slots=self.adjudicated_slots,
        )

    def _state(self) -> dict[str, Any]:
        resolved = list(self._resolved().values())
        contested = self._contested()
        coverage = {
            "planned_slots": len(self.plan),
            "row_slots": len(self.tasks),
            "resolved_row_slots": len(resolved),
            # Contested slots are open, not resolved: the evidence conflicts
            # and nothing adjudicated it.
            "contested_row_slots": len(contested),
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
            "contested_row_slots": contested,
            "reconciliations": list(self.reconciliations),
            "coverage": coverage,
            "errors": list(self.errors),
        }

    def _emit_progress(self, record: dict[str, Any]) -> None:
        if self.progress_fn is None:
            return
        try:
            self.progress_fn(dict(record))
        except Exception:
            return

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
        # REPETITION WITHIN ONE SOURCE IS PROPAGATION, NOT REPLICATION.
        #
        # `dict` rather than `Counter` at the inner level, and insertion-ordered
        # deliberately: the row count is retained for disclosure but never for
        # confidence, and ordered iteration keeps tie-breaking deterministic. A
        # `set` here would make which value wins a tie depend on hash order.
        source_values: dict[tuple[str, str, str], dict[str, int]] = defaultdict(dict)
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
                        counts = source_values[(table, slot.canonical_column, source_id)]
                        counts[value] = counts.get(value, 0) + 1

        candidates: list[BestGuessCandidate] = []
        for task in tasks:
            # value -> the DISTINCT sources carrying it, and separately the
            # number of rows it occurred in. Only the first drives confidence.
            #
            # The previous code summed row counts across sources into one
            # `votes` Counter and fed that sum to `0.55 + count * 0.05`, so a
            # value appearing in five rows all derived from ONE document
            # reached the 0.78 ceiling exactly as if five independent documents
            # had reported it -- while the basis string alongside it said the
            # rows "share existing source provenance", which is the statement
            # that they are not independent. Repeated values are propagation of
            # one source unless the sources differ, and this operator's whole
            # premise is that the rows it scans share provenance, so its own
            # multiplicity is the least independent evidence in the package.
            #
            # This matters beyond tidiness: these candidates become
            # `JUDGED_BEST_GUESS_ACCEPTED`, one of only three bases in
            # `reward.CREDITABLE_EVIDENCE_BASES`, so an inflated confidence
            # sits directly upstream of the reward's success event.
            supporting_sources: dict[str, list[str]] = {}
            rows_seen: dict[str, int] = {}
            for source_id in task.source_ids:
                counts = source_values.get(
                    (task.target_table, task.canonical_column, source_id)
                )
                if not counts:
                    continue
                for value, row_count in counts.items():
                    supporting_sources.setdefault(value, []).append(source_id)
                    rows_seen[value] = rows_seen.get(value, 0) + row_count
            if not supporting_sources:
                continue

            # Ranked by distinct-source support. `max` over an insertion-ordered
            # dict resolves ties to the first value seen, which is stable.
            value = max(
                supporting_sources,
                key=lambda candidate_value: len(supporting_sources[candidate_value]),
            )
            distinct_sources = len(supporting_sources[value])
            occurrences = rows_seen[value]
            confidence = min(0.78, 0.55 + distinct_sources * 0.05)
            candidates.append(
                _candidate(
                    task,
                    operator="sibling_row_scan",
                    value=value,
                    confidence=confidence,
                    # Only the sources that actually carried this value. Without
                    # it `_candidate` falls back to `task.source_ids` -- the
                    # task's ENTIRE source list, including sources that
                    # supported some other value or none -- while the correct
                    # subset was computed here and thrown away.
                    #
                    # Inert today, because the operator cannot be accepted. It
                    # is a landmine for path (b): raise the cap and those
                    # over-claimed ids flow through the accepted-source join in
                    # `criteria.py` and out as `crediting_source_ids`, crediting
                    # sources that never supported the value. Attached now,
                    # while the right list is in hand.
                    source_ids=tuple(supporting_sources[value]),
                    # The suppressed multiplicity is stated rather than dropped,
                    # so a reader can see repetition was observed and refused
                    # instead of inferring it from a confidence that did not move.
                    basis=(
                        "other rows sharing existing source provenance; "
                        f"supported by {distinct_sources} distinct source(s) "
                        f"across {occurrences} row occurrence(s); confidence "
                        "counts distinct sources only, because repetition "
                        "within one source is propagation of that source"
                    ),
                )
            )
        return candidates

    def _evidence_windows(
        self,
        operator: str,
        task: BestGuessTask,
    ) -> list[dict[str, Any]]:
        """Evidence for one task, split into as many calls as it needs.

        Returns a list because evidence is never shortened to fit a single
        call. When it does not fit, it becomes several calls whose candidates
        are merged and, on disagreement, reconciled.
        """

        if operator == "source_metadata_extract":
            records = [
                _compact_mapping(self.source_records.get(source_id, {}))
                for source_id in task.source_ids
                if self.source_records.get(source_id)
            ]
            records = [record for record in records if record]
            if not records:
                return []
            return _window_evidence_items(
                task.id,
                "source_metadata",
                "sources",
                records,
                budget=self.evidence_chars,
            )

        if operator == "source_chunk_extract":
            excerpts = [
                {"source_id": source_id, "text": window}
                for source_id in task.source_ids
                for window in _source_windows(
                    self.source_texts.get(source_id, ""),
                    task,
                    max_chars=self.evidence_chars,
                )
            ]
            if not excerpts:
                return []
            return _window_evidence_items(
                task.id,
                "source_text",
                "sources",
                excerpts,
                budget=self.evidence_chars,
            )

        if operator == "kg_neighbor_extract":
            # Every record from every source. No cap: a derived value is only
            # as good as the evidence it was allowed to see, and a cap here
            # silently decides which evidence that is.
            records = [
                record
                for source_id in task.source_ids
                for record in self.graph_records.get(source_id, ())
            ]
            if not records:
                return []
            return _window_evidence_items(
                task.id,
                "kg_records",
                "records",
                records,
                budget=self.evidence_chars,
            )

        return []

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
    max_tasks: int | None = None,
) -> list[BestGuessTask]:
    if max_tasks is not None and max_tasks <= 0:
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
    # Every derivable slot gets a task. `max_tasks` is retained only as an
    # explicit opt-in ceiling for callers that want one; the default is no
    # ceiling, because a cap here decides in advance which cells are allowed
    # to be filled.
    ordered = sorted(tasks, key=_task_priority)
    return ordered if max_tasks is None else ordered[:max_tasks]


def resolve_candidates(
    candidates: Iterable[BestGuessCandidate],
    *,
    adjudicated_slots: frozenset[str] | set[str] = frozenset(),
) -> dict[str, dict[str, Any]]:
    """Resolve slots on evidence, never by headcount.

    This module used to settle competing values by popularity. Two separate
    defects, and they are worth stating precisely:

    * **Selection.** The winning value was chosen by
      ``max(distinct operators, max confidence, group size)`` -- a headcount.
      The value backed by more mechanisms won regardless of what the sources
      said. This is the substantive defect and it decided answers.
    * **Reported confidence.** It was then *raised* by 0.04 per extra operator
      and 0.02 per extra candidate. This did not promote anything past
      acceptance -- ``_accepted`` thresholds each candidate before grouping --
      but it published a confidence no candidate actually held, computed from
      repeat count. A reader was misled and any future consumer thresholding
      on it would have inherited a popularity score.

    **Why agreement is not evidence here.** A repeated value corroborates only
    if the repeats are *independent* observations. Two research groups
    separately estimating R0 for Italy and landing close together is
    replication, and it is genuine evidence. One paper reporting a value, a
    review citing that paper, a blog summarising the review, and a news article
    quoting the blog is a single measurement echoed four times -- and it looks
    identical from the text. Provenance chains are almost never explicit, so
    this codebase takes the safe prior: **repeats are presumed propagation of
    one source, not independent replication, and therefore carry no additional
    evidential weight.** Until original sources can be traced, popularity means
    nothing. (Tracing them is the future capability that would let agreement
    count again -- and only for the repeats shown to be independent.)

    Nothing votes here now:

    * One distinct value -> resolve it, on its own confidence, unmodified.
    * Several distinct values -> a conflict, which only evidence can settle.
      `_reconcile_windows` adjudicates it by reading the cited chunks from
      each side. A slot it settled is listed in ``adjudicated_slots``.
    * Several distinct values and no adjudication -> **unresolved**. An
      unadjudicated conflict is not knowledge, and quietly returning the more
      popular answer would be asserting one.

    Repeat counts are still recorded, as observations. They are not a score.
    """

    by_slot: dict[str, list[BestGuessCandidate]] = defaultdict(list)
    for candidate in candidates:
        if _accepted(candidate):
            by_slot[candidate.row_slot_id].append(candidate)

    resolved: dict[str, dict[str, Any]] = {}
    for row_slot_id, slot_candidates in by_slot.items():
        value_groups: dict[str, list[BestGuessCandidate]] = defaultdict(list)
        for candidate in slot_candidates:
            value_groups[_norm(candidate.best_guess_value)].append(candidate)

        if len(value_groups) > 1 and row_slot_id not in adjudicated_slots:
            # Contested and unsettled. Reported by `contested_slots`, not
            # resolved into a value here.
            continue

        # Representative candidate: highest own confidence, ties broken by id
        # so the choice is deterministic. This selects which record speaks for
        # the value; it does not select the value.
        best = max(
            slot_candidates,
            key=lambda candidate: (candidate.confidence, candidate.id),
        )
        agreeing = value_groups[_norm(best.best_guess_value)]
        operators = sorted({candidate.operator for candidate in agreeing})
        co_valid = sorted(
            {
                candidate.best_guess_value
                for candidate in slot_candidates
                if _norm(candidate.best_guess_value)
                != _norm(best.best_guess_value)
            }
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
            # The candidate's own confidence. Never raised by agreement.
            "confidence": round(best.confidence, 3),
            "basis": best.basis,
            "operators": operators,
            # Repeat counts, deliberately NOT named "agreement": these are
            # presumed propagations of one source until provenance says
            # otherwise. Recorded so a reader can see the shape of the
            # evidence, never fed back into confidence or acceptance.
            "repeated_observation_count": len(agreeing),
            "distinct_operator_count": len(operators),
            "repeats_presumed_independent": False,
            # Values an adjudicator ruled co-valid (`keep_both`). Preserved
            # rather than discarded, because forcing one winner would destroy
            # a real second value.
            "co_valid_values": co_valid,
            "adjudicated": row_slot_id in adjudicated_slots,
            "source_ids": _unique(
                source_id
                for candidate in agreeing
                for source_id in candidate.source_ids
            ),
            "source_chunks": _unique(
                chunk
                for candidate in agreeing
                for chunk in candidate.source_chunks
            ),
            "candidate_count": len(slot_candidates),
            "conflict_count": max(0, len(value_groups) - 1),
        }
    return dict(sorted(resolved.items()))


def contested_slots(
    candidates: Iterable[BestGuessCandidate],
    *,
    adjudicated_slots: frozenset[str] | set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Slots left unresolved because their conflict was never adjudicated.

    These are reported rather than hidden. A cell with two supported values
    and no adjudication is a real state of the evidence, and presenting either
    value as the answer would overstate what is known.
    """

    by_slot: dict[str, list[BestGuessCandidate]] = defaultdict(list)
    for candidate in candidates:
        if _accepted(candidate):
            by_slot[candidate.row_slot_id].append(candidate)

    contested: list[dict[str, Any]] = []
    for row_slot_id, slot_candidates in sorted(by_slot.items()):
        values = {_norm(c.best_guess_value) for c in slot_candidates}
        if len(values) <= 1 or row_slot_id in adjudicated_slots:
            continue
        contested.append(
            {
                "row_slot_id": row_slot_id,
                "target_table": slot_candidates[0].target_table,
                "canonical_column": slot_candidates[0].canonical_column,
                "competing_values": sorted(
                    {c.best_guess_value for c in slot_candidates}
                ),
                "candidate_ids": sorted(c.id for c in slot_candidates),
                "reason": (
                    "Competing values were not adjudicated, so no value is "
                    "asserted. Resolving by agreement count would report the "
                    "more popular answer rather than the supported one."
                ),
            }
        )
    return contested


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


def _source_windows(
    text: str,
    task: BestGuessTask,
    *,
    max_chars: int,
) -> list[str]:
    """Every relevant chunk of one source, packed into context-sized windows.

    Returns a list because the evidence for one derived value may not fit one
    model call. It is never shortened to make it fit.
    """

    text = str(text or "")
    if not text:
        return []

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
        selected = [chunk for _, chunk in ranked]

    # Pack every selected chunk into context-sized windows. Nothing is
    # discarded and no chunk is split: evidence that does not fit one call
    # becomes another call, and the results are merged and reconciled
    # afterwards. Truncating here would silently decide which evidence the
    # derived value was allowed to rest on.
    windows: list[str] = []
    current: list[str] = []
    size = 0
    for chunk in selected:
        addition = len(chunk) + 2
        if current and size + addition > max_chars:
            windows.append("\n\n".join(current).strip())
            current, size = [], 0
        current.append(chunk)
        size += addition
    if current:
        windows.append("\n\n".join(current).strip())
    return [window for window in windows if window]


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
    for row in rows:
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
            compact_list = [_compact(item) for item in list(inner) if not _missing(item)]
            if compact_list:
                out[str(key)] = compact_list
        else:
            out[str(key)] = _compact(inner)
    return out


def _compact(value: Any) -> Any:
    # No truncation. Oversized evidence is handled by windowing the call, not
    # by silently clipping the value the model is asked to reason about.
    return value


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


#: One owner, one predicate: `criteria.is_missing_value`.
_missing = is_missing_value


def _batches(
    values: Sequence[Any],
    size: int,
    *,
    char_budget: int,
) -> Iterable[list[Any]]:
    """Group values by measured serialized size, capped at ``size`` values.

    A batch closes when either bound is reached. ``size`` keeps the documented
    meaning of `--best-guess-llm-batch-size` as an upper bound on values per
    call; ``char_budget`` is what actually binds in practice.

    Grouping by count alone was the defect. Each value here is an evidence
    window that `_window_evidence_items` already sized to fit one call, and
    those windows are near-full by construction because they only split when
    the budget is hit. Putting eight of them in one call therefore produced a
    payload several times the size any single window was allowed to be, and
    the prompt builder then clipped it -- so a mechanism whose whole design is
    that nothing gets cut was feeding one that cut. A size-bounded group makes
    the call bounded by construction and removes the need to cut at all.

    A value that alone exceeds the budget gets its own batch, uncut, matching
    the window rule it came from.
    """

    budget = max(1, int(char_budget or 1))
    limit = max(1, int(size or 1))
    batch: list[Any] = []
    used = 0
    for value in values:
        length = measured_size(value)
        if batch and (used + length > budget or len(batch) >= limit):
            yield batch
            batch, used = [], 0
        batch.append(value)
        used += length
    if batch:
        yield batch


def _window_evidence_items(
    task_id: str,
    evidence_kind: str,
    payload_key: str,
    items: list[Any],
    *,
    budget: int,
) -> list[dict[str, Any]]:
    """Split evidence items into windows that each fit one model call.

    Nothing is dropped. An item larger than the budget on its own gets a
    window to itself rather than being cut, because a clipped record is worse
    evidence than an oversized one -- the model can see a whole record is
    large, but it cannot see that a record was truncated.

    Every window is stamped with its index and the total, so a model reasoning
    over part of the evidence knows that is what it is doing.
    """

    groups = window_items(items, budget=budget)
    return [
        {
            "task_id": task_id,
            "evidence_kind": evidence_kind,
            **window_stamps(index, len(groups)),
            payload_key: group,
        }
        for index, group in enumerate(groups)
    ]


#: Closed vocabulary for a reconciliation outcome. A verdict is not prose: a
#: downstream reader groups by this identifier, and the count of kept ids must
#: agree with it or the whole verdict is discarded.
RECONCILIATION_VERDICTS = ("keep_one", "keep_both", "keep_none")


def _coerce_reconciliation(
    parsed: Any,
    *,
    row_slot_id: str,
    valid_ids: set[str],
) -> tuple[str | None, set[str], str]:
    """Validate a reconciliation verdict, or refuse it.

    Returns ``(None, set(), reason)`` when the response cannot be trusted --
    an unknown verdict, an id the slot never proposed, or a kept-count that
    contradicts the verdict. A malformed verdict must leave the deterministic
    resolution standing rather than be repaired into something plausible.
    """

    records: list[Any] = []
    if isinstance(parsed, Mapping):
        inner = parsed.get("reconciliations")
        records = list(inner) if isinstance(inner, list) else [parsed]
    elif isinstance(parsed, list):
        records = list(parsed)

    for record in records:
        if not isinstance(record, Mapping):
            continue
        if _clean_value(record.get("row_slot_id")) not in ("", row_slot_id):
            continue

        verdict = str(record.get("verdict") or "").strip().lower()
        if verdict not in RECONCILIATION_VERDICTS:
            return None, set(), f"unknown verdict {verdict!r}"

        raw_ids = record.get("keep_candidate_ids")
        keep = {str(item) for item in raw_ids} if isinstance(raw_ids, list) else set()

        unknown = keep - valid_ids
        if unknown:
            return None, set(), f"verdict names candidates not in this slot: {sorted(unknown)}"

        expected = {"keep_one": 1, "keep_none": 0}
        if verdict in expected and len(keep) != expected[verdict]:
            return None, set(), (
                f"verdict {verdict} but {len(keep)} candidate(s) kept"
            )
        if verdict == "keep_both" and len(keep) < 2:
            return None, set(), "verdict keep_both but fewer than two kept"

        return verdict, keep, str(record.get("reason") or "")

    return None, set(), "no verdict for this row slot"
