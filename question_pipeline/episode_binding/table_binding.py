from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from method_loop import END_SOURCE_FAILED, Episode, EpisodeView, Leaf, SourceEnd

from question_pipeline.utilities.acquisition import stable_id
from question_pipeline.utilities.acquisition import ObservationKind
from question_pipeline.utilities.model import ModelTier, ask_json, register_call_site_tier
from question_pipeline.utilities.tables import ColumnEvidenceRole, TableSpec
from question_pipeline.episode_binding.provider_binding import EXTRACT_OK, PageCredit, PageMaterial, PageRunState, PageUnit, _incidence_input, _incidence_step, page_fate


_TABLE_PARSER_TIER = register_call_site_tier(
    "table-episode-parser",
    ModelTier.REASONING,
)
_TABLE_QUERY_TIER = register_call_site_tier(
    "table-episode-query",
    ModelTier.REASONING,
)

TABLE_PARSE_FAILED = "table_parse_failed"
TABLE_QUERY_FAILED = "table_query_failed"

_HTML_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table\s*>", re.I | re.S)
_HTML_ROW_RE = re.compile(r"<tr\b[^>]*>.*?</tr\s*>", re.I | re.S)
_HTML_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", re.I | re.S)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
_FIXED_COLUMN_RE = re.compile(r"\s{2,}")


@dataclass(frozen=True)
class SourceLine:
    text: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class TableRegion:
    """One non-overlapping source region with measurable table structure."""

    region_id: str
    parser_hint: str
    start_offset: int
    end_offset: int
    text: str
    lines: tuple[SourceLine, ...]


@dataclass(frozen=True)
class ParserColumn:
    source_index: int
    target_column: str


@dataclass(frozen=True)
class TableParserPlan:
    """A model-written declarative parser consumed by fixed code."""

    parser_kind: str
    target_table: str
    data_start_row: int
    columns: tuple[ParserColumn, ...]
    rationale: str = ""


@dataclass(frozen=True)
class ParsedTableRow:
    row_id: str
    source_index: int
    raw_text: str
    start_offset: int
    end_offset: int
    values: Mapping[str, Any]


@dataclass(frozen=True)
class TableDataset:
    region: TableRegion
    plan: TableParserPlan
    rows: tuple[ParsedTableRow, ...]

    @property
    def available_columns(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                column
                for row in self.rows
                for column in row.values
            )
        )


@dataclass(frozen=True)
class TableFilter:
    column: str
    text: str


@dataclass(frozen=True)
class TableQuery:
    """One model-proposed query executed over parsed rows."""

    required_columns: tuple[str, ...] = ()
    contains: tuple[TableFilter, ...] = ()
    rationale: str = ""

    def signature(self) -> str:
        return stable_id(
            {
                "required_columns": list(self.required_columns),
                "contains": [
                    {"column": item.column, "text": item.text}
                    for item in self.contains
                ],
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_columns": list(self.required_columns),
            "contains": [
                {"column": item.column, "text": item.text}
                for item in self.contains
            ],
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class TableQueryUnit:
    """One table query and the unprocessed rows it selected."""

    page: PageUnit
    source_record: Mapping[str, Any]
    dataset: TableDataset
    query: TableQuery
    rows: tuple[ParsedTableRow, ...]
    episode_id: str
    episode_path: tuple[tuple[str, str], ...]
    label: str
    credit_detail: Optional[PageCredit] = None

    def attach_credit(self, detail: PageCredit) -> None:
        if self.credit_detail is not None:
            raise ValueError(
                f"credit detail already attached to table query {self.label!r}"
            )
        object.__setattr__(self, "credit_detail", detail)


@dataclass(frozen=True)
class _GridRow:
    cells: tuple[str, ...]
    raw_text: str
    start_offset: int
    end_offset: int


def _source_lines(text: str) -> tuple[SourceLine, ...]:
    lines: list[SourceLine] = []
    offset = 0
    for raw in str(text).splitlines(keepends=True):
        content = raw.rstrip("\r\n")
        lines.append(
            SourceLine(content, offset, offset + len(content))
        )
        offset += len(raw)
    if offset < len(text):
        lines.append(SourceLine(text[offset:], offset, len(text)))
    return tuple(lines)


def _line_blocks(
    lines: Sequence[SourceLine],
    predicate: Callable[[str], bool],
) -> tuple[tuple[SourceLine, ...], ...]:
    blocks: list[tuple[SourceLine, ...]] = []
    current: list[SourceLine] = []
    for line in lines:
        if predicate(line.text):
            current.append(line)
        else:
            if current:
                blocks.append(tuple(current))
                current = []
    if current:
        blocks.append(tuple(current))
    return tuple(blocks)


def _markdown_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return len(cells) >= 2 and all(
        bool(_MARKDOWN_SEPARATOR_CELL_RE.fullmatch(cell)) for cell in cells
    )


def _stable_width(block: Sequence[SourceLine], splitter: Callable[[str], Sequence[str]]) -> bool:
    widths: list[int] = []
    for line in block:
        try:
            widths.append(len(tuple(splitter(line.text))))
        except (csv.Error, ValueError):
            return False
    useful = [width for width in widths if width >= 2]
    if len(useful) < 3:
        return False
    modal = Counter(useful).most_common(1)[0][1]
    return modal / len(useful) >= 0.75


def _make_region(kind: str, text: str, lines: Sequence[SourceLine]) -> TableRegion:
    start = lines[0].start_offset
    end = lines[-1].end_offset
    region_text = text[start:end]
    return TableRegion(
        region_id=stable_id(
            {
                "kind": kind,
                "start": start,
                "end": end,
                "text": region_text,
            }
        ),
        parser_hint=kind,
        start_offset=start,
        end_offset=end,
        text=region_text,
        lines=tuple(lines),
    )


def discover_table_regions(text: str) -> tuple[TableRegion, ...]:
    """Find strict table-shaped regions without a model call."""

    source = str(text)
    lines = _source_lines(source)
    candidates: list[tuple[int, TableRegion]] = []

    for match in _HTML_TABLE_RE.finditer(source):
        rows = tuple(_HTML_ROW_RE.finditer(match.group(0)))
        if len(rows) < 2:
            continue
        region_lines = tuple(
            SourceLine(
                text=row.group(0),
                start_offset=match.start() + row.start(),
                end_offset=match.start() + row.end(),
            )
            for row in rows
        )
        candidates.append((0, _make_region("html", source, region_lines)))

    markdown_blocks = _line_blocks(lines, lambda value: value.count("|") >= 2)
    for block in markdown_blocks:
        if len(block) >= 2 and any(_markdown_separator(line.text) for line in block):
            candidates.append((1, _make_region("markdown", source, block)))

    tab_blocks = _line_blocks(lines, lambda value: value.count("\t") >= 1)
    for block in tab_blocks:
        if len(block) >= 3 and _stable_width(block, lambda value: value.split("\t")):
            candidates.append((2, _make_region("tab", source, block)))

    for delimiter, kind, priority in ((",", "csv", 3), (";", "semicolon", 4)):
        blocks = _line_blocks(lines, lambda value, token=delimiter: value.count(token) >= 2)
        for block in blocks:
            if len(block) >= 4 and _stable_width(
                block,
                lambda value, token=delimiter: next(csv.reader([value], delimiter=token)),
            ):
                candidates.append((priority, _make_region(kind, source, block)))

    fixed_blocks = _line_blocks(
        lines,
        lambda value: len(_FIXED_COLUMN_RE.split(value.strip())) >= 3,
    )
    for block in fixed_blocks:
        if len(block) >= 4 and _stable_width(
            block,
            lambda value: _FIXED_COLUMN_RE.split(value.strip()),
        ):
            candidates.append((5, _make_region("fixed_width", source, block)))

    selected: list[TableRegion] = []
    for _priority, region in sorted(
        candidates,
        key=lambda item: (item[1].start_offset, item[0], -len(item[1].text)),
    ):
        if any(
            region.start_offset < existing.end_offset
            and existing.start_offset < region.end_offset
            for existing in selected
        ):
            continue
        selected.append(region)
    return tuple(sorted(selected, key=lambda item: item.start_offset))


def text_without_table_regions(text: str, regions: Sequence[TableRegion]) -> str:
    """Mask table bytes while retaining source offsets for prose chunks."""

    characters = list(str(text))
    for region in regions:
        for index in range(region.start_offset, min(region.end_offset, len(characters))):
            if characters[index] not in "\r\n":
                characters[index] = " "
    return "".join(characters)


def _html_cell(value: str) -> str:
    return " ".join(html.unescape(_HTML_TAG_RE.sub("", value)).split())


def _grid_rows(region: TableRegion, parser_kind: str) -> tuple[_GridRow, ...]:
    rows: list[_GridRow] = []
    if parser_kind == "html":
        for match in _HTML_ROW_RE.finditer(region.text):
            cells = tuple(_html_cell(value) for value in _HTML_CELL_RE.findall(match.group(0)))
            if cells:
                rows.append(
                    _GridRow(
                        cells=cells,
                        raw_text=match.group(0),
                        start_offset=region.start_offset + match.start(),
                        end_offset=region.start_offset + match.end(),
                    )
                )
        return tuple(rows)

    for line in region.lines:
        raw = line.text
        if parser_kind == "markdown":
            if _markdown_separator(raw):
                continue
            cells = tuple(cell.strip() for cell in raw.strip().strip("|").split("|"))
        elif parser_kind == "tab":
            cells = tuple(cell.strip() for cell in raw.split("\t"))
        elif parser_kind in {"csv", "semicolon"}:
            delimiter = "," if parser_kind == "csv" else ";"
            cells = tuple(cell.strip() for cell in next(csv.reader([raw], delimiter=delimiter)))
        elif parser_kind == "fixed_width":
            cells = tuple(cell.strip() for cell in _FIXED_COLUMN_RE.split(raw.strip()))
        else:
            raise ValueError(f"unsupported table parser kind {parser_kind!r}")
        if len(cells) >= 2:
            rows.append(
                _GridRow(
                    cells=cells,
                    raw_text=raw,
                    start_offset=line.start_offset,
                    end_offset=line.end_offset,
                )
            )
    return tuple(rows)


def _table_contract(table_spec: TableSpec) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for name, table in table_spec.tables.items():
        if not table.deliverable:
            continue
        tables[name] = {
            "description": table.description,
            "grain": table.grain,
            "subject_key_columns": list(table.subject_key_columns),
            "reported_columns": {
                column.name: column.to_dict()
                for column in table.all_columns()
                if column.role is ColumnEvidenceRole.REPORTED
            },
        }
    return {"tables": tables}


def _preview(region: TableRegion, parser_kind: str) -> list[dict[str, Any]]:
    rows = _grid_rows(region, parser_kind)
    indexes = list(range(min(30, len(rows))))
    if len(rows) > 40:
        indexes.extend(range(len(rows) - 10, len(rows)))
    return [
        {"row": index, "cells": list(rows[index].cells)}
        for index in dict.fromkeys(indexes)
    ]


async def plan_table_parser(
    llm: Any,
    *,
    table_spec: TableSpec,
    region: TableRegion,
) -> TableParserPlan:
    """Ask once for a constrained parser plan for one detected table."""

    contract = _table_contract(table_spec)
    preview = _preview(region, region.parser_hint)
    prompt = f"""TABLE CONTRACT:
{json.dumps(contract, ensure_ascii=False, sort_keys=True)}

DETECTED SOURCE TABLE:
{json.dumps({'parser_hint': region.parser_hint, 'rows': preview}, ensure_ascii=False)}

Write a declarative parser mapping for this source table. The executor already
supports html, markdown, tab, csv, semicolon, and fixed_width rows. Identify
the first data row and map source column indexes to reported columns in exactly
one declared target table. Do not extract values and do not decide whether
processing should stop.

Return exactly:
{{
  "parser_kind": "one supported kind",
  "target_table": "declared table name",
  "data_start_row": 1,
  "columns": [
    {{"source_index": 0, "target_column": "declared reported column"}}
  ],
  "rationale": "brief description of the source layout"
}}"""
    payload = await ask_json(
        llm,
        prompt,
        system_prompt=(
            "You map a visible source table onto a declared result-table schema. "
            "Return one JSON object. Produce a parser specification only; never "
            "invent or summarize source values."
        ),
        tier=_TABLE_PARSER_TIER,
        call_site="table-episode-parser",
    )
    if not isinstance(payload, Mapping):
        raise ValueError("table parser planning must return a JSON object")
    parser_kind = str(payload.get("parser_kind") or region.parser_hint)
    if parser_kind not in {"html", "markdown", "tab", "csv", "semicolon", "fixed_width"}:
        raise ValueError(f"unsupported table parser kind {parser_kind!r}")
    target_table = str(payload.get("target_table") or "")
    table = table_spec.tables.get(target_table)
    if table is None or not table.deliverable:
        raise ValueError("table parser plan did not select a deliverable table")
    reported = {
        column.name
        for column in table.all_columns()
        if column.role is ColumnEvidenceRole.REPORTED
    }
    raw_columns = payload.get("columns")
    if not isinstance(raw_columns, Sequence) or isinstance(raw_columns, (str, bytes)):
        raise ValueError("table parser plan columns must be a list")
    columns: list[ParserColumn] = []
    seen_targets: set[str] = set()
    for raw in raw_columns:
        if not isinstance(raw, Mapping):
            continue
        try:
            source_index = int(raw.get("source_index"))
        except (TypeError, ValueError):
            continue
        target = str(raw.get("target_column") or "")
        if source_index < 0 or target not in reported or target in seen_targets:
            continue
        columns.append(ParserColumn(source_index, target))
        seen_targets.add(target)
    if not columns:
        raise ValueError("table parser plan mapped no reported columns")
    try:
        data_start = max(0, int(payload.get("data_start_row") or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("table parser data_start_row must be an integer") from exc
    return TableParserPlan(
        parser_kind=parser_kind,
        target_table=target_table,
        data_start_row=data_start,
        columns=tuple(columns),
        rationale=str(payload.get("rationale") or "").strip(),
    )


def parse_table_region(region: TableRegion, plan: TableParserPlan) -> TableDataset:
    """Execute a validated parser plan without another model call."""

    grid = _grid_rows(region, plan.parser_kind)
    rows: list[ParsedTableRow] = []
    for source_index, row in enumerate(grid[plan.data_start_row :], start=plan.data_start_row):
        values = {
            column.target_column: row.cells[column.source_index]
            for column in plan.columns
            if column.source_index < len(row.cells)
            and row.cells[column.source_index].strip()
        }
        if not values:
            continue
        rows.append(
            ParsedTableRow(
                row_id=stable_id(
                    {
                        "region_id": region.region_id,
                        "source_index": source_index,
                        "raw_text": row.raw_text,
                    }
                ),
                source_index=source_index,
                raw_text=row.raw_text,
                start_offset=row.start_offset,
                end_offset=row.end_offset,
                values=values,
            )
        )
    return TableDataset(region=region, plan=plan, rows=tuple(rows))


async def propose_table_query(
    llm: Any,
    *,
    question: str,
    table_spec: TableSpec,
    dataset: TableDataset,
    unprocessed_rows: Sequence[ParsedTableRow],
    previous_queries: Sequence[Mapping[str, Any]],
    goal_states: Sequence[Mapping[str, Any]],
) -> TableQuery:
    """Propose one row query using measured outcomes from prior queries."""

    sample = [
        {"row_id": row.row_id, "values": dict(row.values)}
        for row in unprocessed_rows[:20]
    ]
    prompt = f"""QUESTION:
{question}

DECLARED TABLE CONTRACT:
{json.dumps(_table_contract(table_spec), ensure_ascii=False, sort_keys=True)}

PARSED SOURCE TABLE:
{json.dumps({'target_table': dataset.plan.target_table, 'available_columns': list(dataset.available_columns), 'unprocessed_row_count': len(unprocessed_rows), 'sample': sample}, ensure_ascii=False)}

CURRENT TABLE-FILL STATE:
{json.dumps(list(goal_states), ensure_ascii=False, default=str)}

PREVIOUS QUERIES AND MEASURED RESULTS:
{json.dumps(list(previous_queries), ensure_ascii=False, default=str)}

Propose one query over the remaining parsed rows. Use previous measured yields
to target useful rows that earlier queries missed. `required_columns` keeps
rows where those mapped columns are non-empty. `contains` performs
case-insensitive literal matching within a mapped column. Empty filters select
all remaining rows. You propose the query only; numerical control decides
whether another query will be attempted.

Return exactly:
{{
  "required_columns": ["mapped target column"],
  "contains": [{{"column": "mapped target column", "text": "literal text"}}],
  "rationale": "brief strategy based on prior outcomes"
}}"""
    payload = await ask_json(
        llm,
        prompt,
        system_prompt=(
            "You propose one deterministic query over an already parsed source "
            "table. Return one JSON object. Never decide whether to continue or stop."
        ),
        tier=_TABLE_QUERY_TIER,
        call_site="table-episode-query",
    )
    if not isinstance(payload, Mapping):
        raise ValueError("table query proposal must return a JSON object")
    available = set(dataset.available_columns)
    required = tuple(
        dict.fromkeys(
            str(value)
            for value in (payload.get("required_columns") or ())
            if str(value) in available
        )
    )
    filters: list[TableFilter] = []
    for raw in payload.get("contains") or ():
        if not isinstance(raw, Mapping):
            continue
        column = str(raw.get("column") or "")
        value = " ".join(str(raw.get("text") or "").split())
        if column in available and value:
            filters.append(TableFilter(column=column, text=value))
    return TableQuery(
        required_columns=required,
        contains=tuple(filters),
        rationale=str(payload.get("rationale") or "").strip(),
    )


def _query_rows(
    rows: Sequence[ParsedTableRow],
    query: TableQuery,
) -> tuple[ParsedTableRow, ...]:
    selected: list[ParsedTableRow] = []
    for row in rows:
        if any(not str(row.values.get(column) or "").strip() for column in query.required_columns):
            continue
        if any(
            item.text.casefold()
            not in str(row.values.get(item.column) or "").casefold()
            for item in query.contains
        ):
            continue
        selected.append(row)
    return tuple(selected)


class TableQuerySource:
    """Generate and execute one adaptive table query per pull."""

    def __init__(
        self,
        *,
        region: TableRegion,
        page: PageUnit,
        source_record: Mapping[str, Any],
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        plan: Callable[[TableRegion], Awaitable[TableParserPlan]],
        propose: Callable[..., Awaitable[TableQuery]],
        make_leaf: Callable[[TableQueryUnit], Leaf],
        goal_states: Callable[[], Sequence[Mapping[str, Any]]],
        open_cost_scope: Callable[[str, str, str, tuple[tuple[str, str], ...]], Any],
        open_prompt_scope: Callable[[str, tuple[tuple[str, str], ...]], Any],
    ) -> None:
        self.region = region
        self.page = page
        self.source_record = source_record
        self.episode_id = episode_id
        self.episode_path = episode_path
        self._plan = plan
        self._propose = propose
        self._make_leaf = make_leaf
        self._goal_states = goal_states
        self._open_cost_scope = open_cost_scope
        self._open_prompt_scope = open_prompt_scope
        self.dataset: Optional[TableDataset] = None
        self.processed_row_ids: set[str] = set()
        self.history: list[dict[str, Any]] = []

    async def _prepare(self) -> None:
        if self.dataset is not None:
            return
        observation_id = f"{self.region.region_id}#parser"
        with self._open_prompt_scope(self.episode_id, self.episode_path):
            with self._open_cost_scope(
                ObservationKind.PROBE_SEARCH.value,
                observation_id,
                self.episode_id,
                self.episode_path,
            ):
                plan = await self._plan(self.region)
        self.dataset = parse_table_region(self.region, plan)
        if not self.dataset.rows:
            raise ValueError("table parser produced no data rows")

    async def next(self, view: EpisodeView) -> Leaf | SourceEnd | None:
        try:
            await self._prepare()
        except Exception:
            return SourceEnd(END_SOURCE_FAILED, TABLE_PARSE_FAILED)
        assert self.dataset is not None
        remaining = tuple(
            row for row in self.dataset.rows if row.row_id not in self.processed_row_ids
        )
        if not remaining:
            return None

        query_index = len(self.history) + 1
        label = f"{self.region.region_id}#query-{query_index:04d}"
        try:
            with self._open_prompt_scope(self.episode_id, self.episode_path):
                with self._open_cost_scope(
                    ObservationKind.PROBE_SEARCH.value,
                    label,
                    self.episode_id,
                    self.episode_path,
                ):
                    query = await self._propose(
                        dataset=self.dataset,
                        unprocessed_rows=remaining,
                        previous_queries=tuple(self.history),
                        goal_states=tuple(self._goal_states()),
                    )
        except Exception:
            return SourceEnd(END_SOURCE_FAILED, TABLE_QUERY_FAILED)
        rows = _query_rows(remaining, query)
        return self._make_leaf(
            TableQueryUnit(
                page=self.page,
                source_record=self.source_record,
                dataset=self.dataset,
                query=query,
                rows=rows,
                episode_id=self.episode_id,
                episode_path=self.episode_path,
                label=label,
            )
        )


class TableBinding:
    """Construct and run table Episodes without invoking chunk retrieval."""

    def _make_table_episode(
        self,
        state: PageRunState,
        region: TableRegion,
        *,
        page_path: tuple[tuple[str, str], ...],
    ) -> Episode:
        table_path = page_path + ((self.table_grain.name, region.region_id),)
        table_ref = Episode.identity(
            self.controller.context,
            self.table_grain,
            region.region_id,
            parent_path=page_path,
        )
        source = TableQuerySource(
            region=region,
            page=state.unit,
            source_record=state.source_record,
            episode_id=table_ref.episode_id,
            episode_path=table_path,
            plan=self.plan_table_parser,
            propose=self.propose_table_query,
            make_leaf=self._make_table_query_leaf,
            goal_states=self.goal_states,
            open_cost_scope=self.open_cost_scope,
            open_prompt_scope=self.open_prompt_scope,
        )
        return Episode(
            grain=self.table_grain,
            key=region.region_id,
            source=source,
            on_unit=lambda leaf, contribution, record: self._on_table_query(
                state, source, leaf, contribution, record
            ),
            to_parent=self._episode_update,
        )

    def _make_table_query_leaf(self, unit: TableQueryUnit) -> Leaf:
        return Leaf(
            unit=unit,
            extract=self._extract_table_query,
            accept=self._accept_table_query,
            result=self.crediter,
            label=unit.label,
        )

    def _extract_table_query(self, unit: TableQueryUnit) -> PageMaterial:
        chunks: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        source_id = str(unit.source_record.get("id") or "")
        for row in unit.rows:
            chunks.append(
                {
                    "chunk_index": row.source_index,
                    "chunk_id": row.row_id,
                    "source_id": source_id,
                    "start_offset": row.start_offset,
                    "end_offset": row.end_offset,
                    "text": row.raw_text,
                    "failed": False,
                    "failure_class": "",
                    "credits_minted": 0,
                    "new_within_page": 0,
                    "repeats_within_page": 0,
                    "row_credits_minted": 0,
                    "table_region_id": unit.dataset.region.region_id,
                    "table_query": unit.query.to_dict(),
                }
            )
            records.append(
                {
                    "table": unit.dataset.plan.target_table,
                    "index": len(records),
                    "values": dict(row.values),
                    "source_chunks": [row.row_id],
                }
            )
        return PageMaterial(
            source_id=source_id,
            fate=page_fate(extraction=EXTRACT_OK),
            records=tuple(records),
            source_record=unit.source_record,
            chunks=tuple(chunks),
            text_chars=sum(len(row.raw_text) for row in unit.rows),
        )

    async def _accept_table_query(
        self,
        unit: TableQueryUnit,
        material: PageMaterial,
    ) -> PageMaterial:
        if not material.records:
            return material
        return await self.accept_evidence(unit, material)

    def _on_table_query(
        self,
        state: PageRunState,
        source: TableQuerySource,
        leaf: Leaf,
        contribution: Any,
        record: Any,
    ) -> None:
        unit = leaf.unit
        material = contribution.output
        observation = _incidence_input(contribution.controller_input)
        findings = set(observation.identities)
        new_findings = findings - state.seen_finding_ids
        repeated_findings = findings & state.seen_finding_ids
        for chunk in material.chunks if isinstance(material, PageMaterial) else ():
            if isinstance(chunk, dict):
                chunk["credits_minted"] = len(findings)
                chunk["new_within_page"] = len(new_findings)
                chunk["repeats_within_page"] = len(repeated_findings)
        source.processed_row_ids.update(row.row_id for row in unit.rows)
        history = {
            "query": unit.query.to_dict(),
            "rows_selected": len(unit.rows),
            "distinct_findings": len(findings),
            "new_findings_within_page": len(new_findings),
            "repeat_findings_within_page": len(repeated_findings),
            "remaining_rows": (
                len(source.dataset.rows) - len(source.processed_row_ids)
                if source.dataset is not None
                else 0
            ),
            "volume_credit": _incidence_step(record).volume_credit.as_record(),
        }
        source.history.append(history)
        state.table_history.append(history)
        state.table_units.append(unit)
        state.seen_finding_ids.update(findings)
        if isinstance(material, PageMaterial):
            state.materials.append(material)
        state.ingestion.update(
            {
                "extraction_state": "extracting_table_rows",
                "table_row_count": sum(len(item.records) for item in state.materials),
                "table_queries": len(state.table_history),
            }
        )
