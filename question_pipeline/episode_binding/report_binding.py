from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from method_loop import (
    END_SOURCE_FAILED,
    Episode,
    EpisodeGoal,
    EpisodeRequest,
    EpisodeView,
    GoalProposal,
    Leaf,
    SourceEnd,
)

from question_pipeline.episode_binding.provider_binding import (
    EXTRACT_OK,
    EXTRACT_RAISED,
    GoalTransition,
    PageMaterial,
    PageRunState,
    PageUnit,
    TableGoalCandidate,
    _incidence_input,
    _incidence_step,
    page_fate,
)
from question_pipeline.utilities.acquisition import ObservationKind, classify_error
from question_pipeline.utilities.model import (
    ModelTier,
    ask_json,
    register_call_site_tier,
)
from question_pipeline.utilities.tables import TableSpec


# This is an LLM request-size boundary, not a stop rule. A report shorter than
# this is read in one call. Longer reports become sequential units in the same
# Episode, with compact source-linked memory carried between them.
REPORT_WINDOW_TEXT_CHARS = 1_000_000
REPORT_WINDOW_FAILED = "report_window_failed"

_REPORT_WINDOW_TIER = register_call_site_tier(
    "report-window-extraction",
    ModelTier.REASONING,
)


@dataclass(frozen=True)
class ReportWindowExtraction:
    """One model-produced memory update and its source-linked Goal records."""

    memory: Mapping[str, Any]
    records: tuple[Mapping[str, Any], ...]


async def extract_report_window(
    llm: Any,
    *,
    question: str,
    table_spec: TableSpec,
    goal_state: Mapping[str, Any],
    outline: Mapping[str, Any],
    source_preview: str,
    previous_memory: Mapping[str, Any],
    chunks: Sequence[Mapping[str, Any]],
    allowed_chunk_ids: Sequence[str],
    objective: str,
) -> ReportWindowExtraction:
    """Interpret one ordered report window while retaining cross-window state."""

    columns_by_table = {
        str(table): tuple(str(column) for column in columns)
        for table, columns in table_spec.all_columns_by_table().items()
    }
    allowed_ids = {str(item) for item in allowed_chunk_ids if str(item)}
    prompt = f"""QUESTION:
{question}

DECLARED GOAL CONTRACT:
{json.dumps(table_spec.prompt_context(), ensure_ascii=False, sort_keys=True)}

CURRENT GOAL STATE:
{json.dumps(dict(goal_state), ensure_ascii=False, default=str)}

PAGE TITLE AND OUTLINE:
{json.dumps(dict(outline), ensure_ascii=False, sort_keys=True)}

EXACT BEGINNING OF THE PAGE:
{source_preview}

PARENT'S OBJECTIVE FOR THIS REPORT READING:
{objective}

COMPACT MEMORY FROM EARLIER WINDOWS OF THIS SAME REPORT:
{json.dumps(dict(previous_memory), ensure_ascii=False, default=str)}

CURRENT REPORT WINDOW, IN DOCUMENT ORDER:
{json.dumps(list(chunks), ensure_ascii=False, default=str)}

Read the current window as part of one report, not as unrelated snippets.
Use the declared identity anchors to decide when facts in different sections
refer to the same subject and when they refer to different subjects. Preserve
one-to-many findings as separate Goal rows when the contract declares them as
separate findings.

Return an updated compact memory that retains only information useful for
resolving later sections: subject identities and aliases, dates and locations,
relationships among mentions, unresolved links, and exact short evidence
quotes with their source_chunk_ids. Preserve relevant earlier memory. The
memory is working context only: it is not accepted evidence and earns no
credit.

Also return every Goal record that is now sufficiently resolved. Reported
values must be exact source wording or harmless numeric formatting of it.
Never infer or estimate a reported value. Each record must name one declared
Goal table, contain only that table's declared columns, and cite the exact
source_chunk_ids that support its values. A record may cite an earlier chunk
retained in memory and a current chunk when the row is resolved across
sections.

Return exactly:
{{
  "memory": {{"a compact task-appropriate working memory": "..."}},
  "records": [
    {{
      "table": "one declared Goal table",
      "values": {{"declared_column": "exact reported value"}},
      "source_chunk_ids": ["one or more supplied source chunk ids"]
    }}
  ]
}}"""
    payload = await ask_json(
        llm,
        prompt,
        system_prompt=(
            "You read one ordered window of a longer report. Return one JSON "
            "object containing compact source-linked memory and exact "
            "source-grounded Goal records."
        ),
        tier=_REPORT_WINDOW_TIER,
        call_site="report-window-extraction",
    )
    if not isinstance(payload, Mapping):
        raise ValueError("report-window extraction must return a JSON object")
    memory = payload.get("memory")
    if not isinstance(memory, Mapping):
        raise ValueError("report-window memory must be a JSON object")

    raw_records = payload.get("records") or ()
    if not isinstance(raw_records, Sequence) or isinstance(
        raw_records, (str, bytes)
    ):
        raise ValueError("report-window records must be a JSON array")
    records: list[Mapping[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            continue
        table = str(raw.get("table") or "")
        declared_columns = set(columns_by_table.get(table) or ())
        values = raw.get("values")
        if not table or not declared_columns or not isinstance(values, Mapping):
            continue
        admitted_values = {
            str(column): value
            for column, value in values.items()
            if str(column) in declared_columns
        }
        source_chunk_ids = tuple(
            dict.fromkeys(
                str(item)
                for item in raw.get("source_chunk_ids") or ()
                if str(item) in allowed_ids
            )
        )
        if not admitted_values or not source_chunk_ids:
            continue
        records.append(
            {
                "table": table,
                "values": admitted_values,
                "source_chunks": list(source_chunk_ids),
            }
        )
    return ReportWindowExtraction(memory=dict(memory), records=tuple(records))


@dataclass(frozen=True)
class ReportWindowResult:
    """The Goal transition produced by one report window."""

    goal_transition: GoalTransition


@dataclass(frozen=True)
class ReportWindowUnit:
    """One large, ordered window inside a whole-report Episode."""

    page: PageUnit
    spans: tuple[Any, ...]
    available_spans: Mapping[str, Any]
    source_record: Mapping[str, Any]
    report_key: str
    window_index: int
    objective: str
    previous_memory: Mapping[str, Any]
    episode_id: str
    episode_path: tuple[tuple[str, str], ...]
    label: str
    extraction_memory: Optional[Mapping[str, Any]] = None
    result: Optional[ReportWindowResult] = None

    def attach_extraction_memory(self, memory: Mapping[str, Any]) -> None:
        if self.extraction_memory is not None:
            raise ValueError(f"memory already attached to report window {self.label!r}")
        object.__setattr__(self, "extraction_memory", dict(memory))

    def attach_result(self, result: ReportWindowResult) -> None:
        if self.result is not None:
            raise ValueError(f"result already attached to report window {self.label!r}")
        object.__setattr__(self, "result", result)


@dataclass
class ReportEpisodeState:
    """Memory retained only for the lifetime of one report Episode."""

    page: PageRunState
    report_key: str
    objective: str
    memory: dict[str, Any] = field(default_factory=dict)
    seen_spans: dict[str, Any] = field(default_factory=dict)
    windows_completed: int = 0
    failed: bool = False


class ReportWindowSource:
    """Pull large prose windows in document order from one page."""

    def __init__(
        self,
        *,
        state: ReportEpisodeState,
        make_leaf: Callable[[ReportWindowUnit], Leaf],
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        window_text_chars: int = REPORT_WINDOW_TEXT_CHARS,
    ) -> None:
        self._state = state
        self._make_leaf = make_leaf
        self._episode_id = episode_id
        self._episode_path = episode_path
        self._window_text_chars = max(1, int(window_text_chars))

    def next(self, view: EpisodeView) -> Leaf | SourceEnd | None:
        if self._state.failed:
            return SourceEnd(END_SOURCE_FAILED, REPORT_WINDOW_FAILED)
        remaining = self._state.page.remaining_chunks()
        if not remaining:
            return None
        spans: list[Any] = []
        text_chars = 0
        for span in remaining:
            size = len(str(span.text))
            if spans and text_chars + size > self._window_text_chars:
                break
            spans.append(span)
            text_chars += size
        window_index = self._state.windows_completed + 1
        current = {
            self._state.page.chunk_id(span): span for span in spans
        }
        unit = ReportWindowUnit(
            page=self._state.page.unit,
            spans=tuple(spans),
            available_spans={**self._state.seen_spans, **current},
            source_record=self._state.page.source_record,
            report_key=self._state.report_key,
            window_index=window_index,
            objective=self._state.objective,
            previous_memory=dict(self._state.memory),
            episode_id=self._episode_id,
            episode_path=self._episode_path,
            label=f"{self._state.report_key}#window-{window_index:04d}",
        )
        return self._make_leaf(unit)


class ReportBinding:
    """Methods owned by the whole-report Episode."""

    def _make_report_episode(
        self,
        state: PageRunState,
        report_key: str,
        *,
        proposal: Any,
        page_episode_id: str,
        page_path: tuple[tuple[str, str], ...],
        parent_goal: EpisodeGoal,
    ) -> Episode:
        report_path = page_path + ((self.report_grain.name, report_key),)
        report_ref = Episode.identity(
            self.controller.context,
            self.report_grain,
            report_key,
            parent_path=page_path,
        )
        objective = str(getattr(proposal, "objective", "") or "")
        proposal_record = (
            proposal.to_dict()
            if hasattr(proposal, "to_dict")
            else dict(proposal)
            if isinstance(proposal, Mapping)
            else proposal
        )
        goal = EpisodeGoal.for_grain(
            self.report_grain,
            parent=parent_goal,
            objective={
                "page_episode_id": page_episode_id,
                "report_key": report_key,
                "objective": objective,
                "proposal": proposal_record,
            },
        )
        report_state = ReportEpisodeState(
            page=state,
            report_key=report_key,
            objective=objective,
        )
        source = ReportWindowSource(
            state=report_state,
            make_leaf=self._make_report_window_leaf,
            episode_id=report_ref.episode_id,
            episode_path=report_path,
        )
        return Episode(
            grain=self.report_grain,
            key=report_key,
            source=source,
            request=EpisodeRequest(
                goal=goal,
                input=proposal_record,
                prompt_context={"parent_episode_id": page_episode_id},
            ),
            on_unit=lambda leaf, contribution, record: self._on_report_window(
                state, report_state, leaf, contribution, record
            ),
            to_parent=self._episode_result,
            parent_controller_input=self._parent_controller_input,
        )

    def _make_report_window_leaf(self, unit: ReportWindowUnit) -> Leaf:
        return Leaf(
            unit=unit,
            extract=self._extract_report_window,
            accept=self._accept_report_window,
            result=self._report_window_result,
            label=unit.label,
        )

    async def _extract_report_window(
        self,
        unit: ReportWindowUnit,
    ) -> PageMaterial:
        source_id = str(unit.source_record.get("id") or "")
        current_chunks = [
            {
                "source_chunk_id": f"{source_id}_chunk_{span.index}",
                "text": str(span.text),
            }
            for span in unit.spans
        ]
        try:
            with self.open_prompt_scope(unit.episode_id, unit.episode_path):
                with self.open_cost_scope(
                    ObservationKind.SOURCE.value,
                    unit.label,
                    unit.episode_id,
                    unit.episode_path,
                ):
                    extraction = await self.extract_report_window(
                        goal_state=self.goal_prompt_context(),
                        outline=self._page_states[unit.page.label].outline,
                        source_preview=self._page_states[
                            unit.page.label
                        ].source_preview,
                        previous_memory=unit.previous_memory,
                        chunks=current_chunks,
                        allowed_chunk_ids=tuple(unit.available_spans),
                        objective=unit.objective,
                    )
            if not isinstance(extraction, ReportWindowExtraction):
                raise TypeError(
                    "report-window extractor must return ReportWindowExtraction"
                )
        except Exception as exc:  # noqa: BLE001 - one window is one failed unit
            error_class = classify_error(exc)
            print(
                f"[report-window] {unit.label} failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            return PageMaterial(
                source_id=source_id,
                fate=page_fate(
                    extraction=EXTRACT_RAISED,
                    error_class=error_class,
                ),
                source_record=unit.source_record,
                chunks=tuple(
                    self._report_chunk_records(
                        unit,
                        (),
                        failed=True,
                        failure_class=error_class or type(exc).__name__,
                    )
                ),
                text_chars=sum(len(str(span.text)) for span in unit.spans),
            )

        unit.attach_extraction_memory(extraction.memory)
        referenced = {
            str(chunk_id)
            for record in extraction.records
            for chunk_id in record.get("source_chunks") or ()
        }
        records = tuple(
            {
                **dict(record),
                "index": index,
            }
            for index, record in enumerate(extraction.records)
        )
        return PageMaterial(
            source_id=source_id,
            fate=page_fate(extraction=EXTRACT_OK),
            records=records,
            source_record=unit.source_record,
            chunks=tuple(self._report_chunk_records(unit, referenced)),
            text_chars=sum(len(str(span.text)) for span in unit.spans),
        )

    def _report_chunk_records(
        self,
        unit: ReportWindowUnit,
        referenced: Sequence[str] | set[str],
        *,
        failed: bool = False,
        failure_class: str = "",
    ) -> list[dict[str, Any]]:
        source_id = str(unit.source_record.get("id") or "")
        current_ids = {
            f"{source_id}_chunk_{span.index}" for span in unit.spans
        }
        included = current_ids | {str(item) for item in referenced}
        records: list[dict[str, Any]] = []
        for chunk_id, span in unit.available_spans.items():
            if chunk_id not in included:
                continue
            records.append(
                {
                    "chunk_index": int(span.index),
                    "chunk_id": chunk_id,
                    "source_id": source_id,
                    "start_offset": int(span.start_offset),
                    "end_offset": int(span.end_offset),
                    "text": str(span.text),
                    "failed": bool(failed),
                    "failure_class": str(failure_class),
                    "credits_minted": 0,
                    "new_within_page": 0,
                    "repeats_within_page": 0,
                    "row_credits_minted": 0,
                    "report_key": unit.report_key,
                    "report_window": unit.window_index,
                }
            )
        return records

    async def _accept_report_window(
        self,
        unit: ReportWindowUnit,
        material: PageMaterial,
    ) -> PageMaterial:
        if not material.records:
            return material
        return await self.accept_evidence(unit, material)

    def _report_window_result(
        self,
        unit: ReportWindowUnit,
        material: PageMaterial,
    ) -> Any:
        return GoalProposal(TableGoalCandidate(unit=unit, material=material))

    def _on_report_window(
        self,
        state: PageRunState,
        report_state: ReportEpisodeState,
        leaf: Leaf,
        contribution: Any,
        record: Any,
    ) -> None:
        unit = leaf.unit
        transition = contribution.goal_result
        if not isinstance(transition, GoalTransition):
            raise TypeError("report Goal proposal completed without GoalTransition")
        unit.attach_result(ReportWindowResult(goal_transition=transition))
        material = contribution.output
        judged = isinstance(material, PageMaterial) and material.fate.judged
        if judged:
            for span in unit.spans:
                chunk_id = state.chunk_id(span)
                state.processed_chunk_ids.add(chunk_id)
                report_state.seen_spans[chunk_id] = span
        else:
            report_state.failed = True
        report_state.windows_completed += 1

        observation = _incidence_input(contribution.controller_input)
        findings = set(observation.identities)
        new_findings = findings - state.seen_finding_ids
        repeated_findings = findings & state.seen_finding_ids
        if unit.extraction_memory is not None:
            report_state.memory = dict(unit.extraction_memory)
        report_state.memory["_last_window_result"] = {
            "window": unit.window_index,
            "distinct_findings": len(findings),
            "new_findings_within_page": len(new_findings),
            "repeat_findings_within_page": len(repeated_findings),
        }
        history = {
            "report_key": unit.report_key,
            "window": unit.window_index,
            "chunks_processed": len(unit.spans),
            "text_chars": sum(len(str(span.text)) for span in unit.spans),
            "distinct_findings": len(findings),
            "new_findings_within_page": len(new_findings),
            "repeat_findings_within_page": len(repeated_findings),
            "remaining_chunks": len(state.remaining_chunks()),
            "volume_credit": _incidence_step(record).volume_credit.as_record(),
        }
        state.report_history.append(history)
        state.report_units.append(unit)
        state.seen_finding_ids.update(findings)
        if isinstance(material, PageMaterial):
            state.materials.append(material)
        state.ingestion.update(
            {
                "extraction_state": "extracting_report_windows",
                "report_windows": len(state.report_history),
                "unprocessed_chunk_count": len(state.remaining_chunks()),
            }
        )
