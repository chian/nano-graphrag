from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from method_loop import END_SOURCE_FAILED, Episode, EpisodeView, Leaf, SourceEnd
from source_table_language import (
    AdmissionRule,
    LanguageResult,
    SourceSpan,
    TableProgram,
    TableRegion,
    TableWorkspace,
    TargetEntity,
    TargetField,
    apply_resolution,
    discover_table_regions,
    execute_program,
    language_reference,
    parse_program,
    resolution_view,
    text_without_table_regions,
)

from question_pipeline.episode_binding.provider_binding import (
    EXTRACT_OK,
    GoalTransition,
    PageMaterial,
    PageRunState,
    PageUnit,
    _incidence_input,
    _incidence_step,
    page_fate,
)
from question_pipeline.utilities.acquisition import ObservationKind, stable_id
from question_pipeline.utilities.model import (
    ModelTier,
    ask_json,
    register_call_site_tier,
)
from question_pipeline.utilities.tables import (
    ColumnEvidenceRole,
    TableSpec,
    TableTargetSpec,
)


_SOURCE_TABLE_PROGRAM_TIER = register_call_site_tier(
    "source-table-episode-program",
    ModelTier.REASONING,
)
_SOURCE_TABLE_RESOLUTION_TIER = register_call_site_tier(
    "source-table-episode-community-resolution",
    ModelTier.REASONING,
)
_SOURCE_TABLE_QUERY_TIER = register_call_site_tier(
    "source-table-episode-query",
    ModelTier.REASONING,
)

SOURCE_TABLE_PARSE_FAILED = "source_table_parse_failed"
SOURCE_TABLE_QUERY_FAILED = "source_table_query_failed"


@dataclass(frozen=True)
class ParsedSourceTableRow:
    """One source-table entity projected onto current goal-result columns."""

    row_id: str
    source_index: int
    values: Mapping[str, Any]
    source_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class SourceTableDataset:
    region: TableRegion
    program: Optional[TableProgram]
    target: Optional[TargetEntity]
    rows: tuple[ParsedSourceTableRow, ...]
    source_chunks: Mapping[str, SourceSpan]
    language_result: Optional[LanguageResult] = None
    skip_reason: str = ""

    @property
    def goal_table_name(self) -> str:
        return self.target.name if self.target is not None else ""

    @property
    def available_goal_columns(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                column for row in self.rows for column in row.values
            )
        )


@dataclass(frozen=True)
class SourceTableFilter:
    column: str
    text: str


@dataclass(frozen=True)
class SourceTableQuery:
    """One model-proposed query executed over admitted parsed rows."""

    required_columns: tuple[str, ...] = ()
    contains: tuple[SourceTableFilter, ...] = ()
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
class SourceTableQueryResult:
    """The Goal transition produced by one source-table query."""

    goal_transition: GoalTransition


@dataclass(frozen=True)
class SourceTableQueryUnit:
    """One source-table query and the unprocessed entities it selected."""

    page: PageUnit
    source_record: Mapping[str, Any]
    dataset: SourceTableDataset
    query: SourceTableQuery
    rows: tuple[ParsedSourceTableRow, ...]
    episode_id: str
    episode_path: tuple[tuple[str, str], ...]
    label: str
    result: Optional[SourceTableQueryResult] = None

    def attach_result(self, result: SourceTableQueryResult) -> None:
        if self.result is not None:
            raise ValueError(
                f"result already attached to source-table query {self.label!r}"
            )
        object.__setattr__(self, "result", result)


def _source_target_from_goal_table(table: TableTargetSpec) -> TargetEntity:
    columns_by_slot: dict[str, list[Any]] = {}
    for column in table.all_columns():
        columns_by_slot.setdefault(column.value_slot, []).append(column)

    fields: dict[str, TargetField] = {}
    subject_columns = set(table.subject_key_columns)
    required_columns = set(table.required_columns())
    for slot, columns in columns_by_slot.items():
        reported = next(
            (
                column
                for column in columns
                if column.role is ColumnEvidenceRole.REPORTED
            ),
            None,
        )
        best_guess = next(
            (
                column
                for column in columns
                if column.role is ColumnEvidenceRole.BEST_GUESS
            ),
            None,
        )
        declaration = reported or best_guess
        if declaration is None:
            continue
        fields[slot] = TargetField(
            name=slot,
            value_type=declaration.value_type or "text",
            unit=declaration.unit,
            description=declaration.description,
            aliases=tuple(
                dict.fromkeys(
                    alias
                    for column in columns
                    for alias in (
                        column.name,
                        *column.aliases,
                        *column.field_hints,
                    )
                    if alias
                )
            ),
            reported_column=(reported.name if reported is not None else ""),
            best_guess_column=(
                best_guess.name if best_guess is not None else ""
            ),
            identity=any(column.name in subject_columns for column in columns),
            required=any(column.name in required_columns for column in columns),
        )
    return TargetEntity(
        name=table.name,
        fields=fields,
        admission_rules=tuple(
            AdmissionRule(
                rule_id=rule.rule_id,
                field=rule.field,
                operator=rule.operator,
                value=rule.value,
                basis=rule.basis,
            )
            for rule in table.admission_rules
        ),
    )


def _source_target_contract_from_goal(
    table_spec: TableSpec,
) -> tuple[dict[str, TargetEntity], dict[str, Any]]:
    targets = {
        name: _source_target_from_goal_table(table)
        for name, table in table_spec.tables.items()
        if table.deliverable
    }
    contract = {
        name: {
            "description": table_spec.tables[name].description,
            "grain": table_spec.tables[name].grain,
            "semantic_fields": {
                field.name: {
                    "value_type": field.value_type,
                    "unit": field.unit,
                    "description": field.description,
                    "aliases": list(field.aliases),
                    "identity": field.identity,
                    "required": field.required,
                    "reported_column": field.reported_column,
                    "best_guess_column": field.best_guess_column,
                }
                for field in target.fields.values()
            },
            "admission_rules": [
                {
                    "rule_id": rule.rule_id,
                    "field": rule.field,
                    "operator": rule.operator,
                    "value": rule.value,
                    "basis": rule.basis,
                }
                for rule in target.admission_rules
            ],
        }
        for name, target in targets.items()
    }
    return targets, contract


async def _resolve_candidate_mentions(
    llm: Any,
    result: LanguageResult,
) -> LanguageResult:
    if len(result.mentions) <= 1:
        return result

    prompt = f"""SOURCE-GROUNDED MENTIONS:
{json.dumps(resolution_view(result), ensure_ascii=False, default=str)}

Partition every presented mention into real-world entities. Combine mentions
only when they refer to the same underlying entity, including when names or
other identity strings use different spelling, formatting, precision, or
wording. Use all mutually consistent fields and source context together;
candidate connections are hints, not limits. Complementary fields may be
combined. Conflicting identity or event facts mean the mentions stay separate.
Return every presented mention id exactly once. Do not create ids, values, or
fields.

Return exactly:
{{"communities": [["mention_id", "mention_id"], ["mention_id"]]}}"""
    payload = await ask_json(
        llm,
        prompt,
        system_prompt=(
            "You resolve candidate source mentions into entity communities. "
            "Return one JSON object and make no acquisition or stopping decision."
        ),
        tier=_SOURCE_TABLE_RESOLUTION_TIER,
        call_site="source-table-episode-community-resolution",
    )
    if not isinstance(payload, Mapping):
        raise ValueError("table community resolution must return an object")
    raw_communities = payload.get("communities")
    if not isinstance(raw_communities, Sequence) or isinstance(
        raw_communities, (str, bytes)
    ):
        raise ValueError("table community resolution requires communities")
    communities: list[tuple[str, ...]] = []
    for raw in raw_communities:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError("each table community must be a list")
        communities.append(tuple(str(item) for item in raw))
    return apply_resolution(result, communities)


def _source_chunks(
    workspace: TableWorkspace,
    result: LanguageResult,
) -> dict[str, SourceSpan]:
    rows = workspace.rows(result.program.parse.parser_kind)
    chunks = {
        row.row_id: SourceSpan(
            span_id=row.row_id,
            kind="table_row",
            start_offset=row.start_offset,
            end_offset=row.end_offset,
            text=workspace.source_text[row.start_offset : row.end_offset],
        )
        for row in rows
    }
    chunks.update(result.spans)
    return chunks


def _project_source_mentions_to_goal_columns(
    result: LanguageResult,
    target: TargetEntity,
    chunks: Mapping[str, SourceSpan],
) -> tuple[ParsedSourceTableRow, ...]:
    projected: list[ParsedSourceTableRow] = []
    for mention_position, mention in enumerate(result.admitted_mentions):
        by_field: dict[str, list[Any]] = {}
        for assertion in mention.assertions:
            by_field.setdefault(assertion.field, []).append(assertion)

        values: dict[str, Any] = {}
        source_chunk_ids: list[str] = []
        for field_name, assertions in by_field.items():
            field = target.fields.get(field_name)
            if field is None or not field.reported_column:
                continue
            comparison_values = {
                json.dumps(
                    assertion.comparison_value,
                    sort_keys=True,
                    default=str,
                )
                for assertion in assertions
            }
            if len(comparison_values) != 1:
                continue
            values[field.reported_column] = assertions[0].raw_value
            for assertion in assertions:
                source_chunk_ids.extend(assertion.source_row_ids)
                source_chunk_ids.extend(assertion.source_span_ids)
        source_chunk_ids = [
            chunk_id
            for chunk_id in dict.fromkeys(
                [
                    *source_chunk_ids,
                    *(
                        evidence_id
                        for rule in mention.rule_results
                        for evidence_id in rule.evidence_ids
                    ),
                ]
            )
            if chunk_id in chunks
        ]
        if not values or not source_chunk_ids:
            continue
        projected.append(
            ParsedSourceTableRow(
                row_id=mention.mention_id,
                source_index=mention_position,
                values=values,
                source_chunk_ids=tuple(source_chunk_ids),
            )
        )
    return tuple(projected)


async def interpret_source_table_region(
    llm: Any,
    *,
    table_spec: TableSpec,
    region: TableRegion,
    source_record: Mapping[str, Any],
) -> SourceTableDataset:
    """Compile and execute one program over a table found in a source."""

    workspace = TableWorkspace(
        source_text=str(source_record.get("text") or ""),
        source_title=str(source_record.get("title") or ""),
        region=region,
    )
    targets, contract = _source_target_contract_from_goal(table_spec)
    prompt = f"""DECLARED TARGET ENTITIES:
{json.dumps(contract, ensure_ascii=False, sort_keys=True, default=str)}

SOURCE TABLE WORKSPACE:
{json.dumps(workspace.initial_view(), ensure_ascii=False, default=str)}

TABLE LANGUAGE:
{json.dumps(language_reference(), ensure_ascii=False, sort_keys=True)}

Decide whether this source table contains entities for one declared target. If
it does, write a table-language program. Map source columns to semantic fields,
not directly to storage columns. Use source context for headings, legends,
units, scopes, and footnotes. A satisfy command is valid only when its cited
span directly establishes a declared admission rule for its scope. Do not
invent cell values or alter the declared target or rules. If this table does
not represent any declared target, return a skip decision.

Return either:
{{"decision": "skip", "reason": "brief source-grounded reason"}}

or:
{{
  "decision": "map",
  "target_entity": "declared target name",
  "commands": [
    {{"op": "parse", "parser_kind": "markdown", "data_start_row": 1, "header_rows": [0]}},
    {{"op": "entries", "mode": "one_per_row", "identity_source_columns": [0]}},
    {{"op": "map_column", "source_column": 0, "target_field": "semantic_field", "parse_as": "text"}},
    {{"op": "emit"}}
  ],
  "rationale": "brief explanation of the source layout and context"
}}"""
    payload = await ask_json(
        llm,
        prompt,
        system_prompt=(
            "You write validated programs in the supplied table language. "
            "Return one JSON object. You may judge semantic relevance and "
            "source meaning, but never decide whether acquisition continues."
        ),
        tier=_SOURCE_TABLE_PROGRAM_TIER,
        call_site="source-table-episode-program",
    )
    if not isinstance(payload, Mapping):
        raise ValueError("table-language planning must return an object")
    if str(payload.get("decision") or "").strip().lower() == "skip":
        return SourceTableDataset(
            region=region,
            program=None,
            target=None,
            rows=(),
            source_chunks={},
            skip_reason=str(payload.get("reason") or "").strip(),
        )

    target_name = str(payload.get("target_entity") or "")
    target = targets.get(target_name)
    if target is None:
        raise ValueError("table-language program did not select a declared target")
    program = parse_program(
        payload,
        target=target,
        span_ids=tuple(workspace.spans),
    )
    result = execute_program(workspace, program, target)
    result = await _resolve_candidate_mentions(llm, result)
    chunks = _source_chunks(workspace, result)
    return SourceTableDataset(
        region=region,
        program=program,
        target=target,
        rows=_project_source_mentions_to_goal_columns(result, target, chunks),
        source_chunks=chunks,
        language_result=result,
    )


async def propose_source_table_query(
    llm: Any,
    *,
    question: str,
    table_spec: TableSpec,
    dataset: SourceTableDataset,
    unprocessed_rows: Sequence[ParsedSourceTableRow],
    previous_queries: Sequence[Mapping[str, Any]],
    goal_states: Sequence[Mapping[str, Any]],
) -> SourceTableQuery:
    """Propose one query over admitted entities using earlier measured yield."""

    sample = [
        {"row_id": row.row_id, "values": dict(row.values)}
        for row in unprocessed_rows[:20]
    ]
    prompt = f"""QUESTION:
{question}

DECLARED TABLE CONTRACT:
{json.dumps(table_spec.prompt_context(), ensure_ascii=False, sort_keys=True)}

PARSED SOURCE TABLE:
{json.dumps({'goal_table_name': dataset.goal_table_name, 'available_goal_columns': list(dataset.available_goal_columns), 'unprocessed_row_count': len(unprocessed_rows), 'sample': sample}, ensure_ascii=False)}

CURRENT TABLE-FILL STATE:
{json.dumps(list(goal_states), ensure_ascii=False, default=str)}

PREVIOUS QUERIES AND MEASURED RESULTS:
{json.dumps(list(previous_queries), ensure_ascii=False, default=str)}

Propose one query over the remaining admitted entities. Use previous measured
yields to target useful entities earlier queries missed. required_columns keeps
entities where those projected columns are non-empty. contains performs
case-insensitive literal matching within a projected column. Empty filters
select all remaining entities. You propose the query only; numerical control
decides whether another query will be attempted.

Return exactly:
{{
  "required_columns": ["projected result column"],
  "contains": [{{"column": "projected result column", "text": "literal text"}}],
  "rationale": "brief strategy based on prior outcomes"
}}"""
    payload = await ask_json(
        llm,
        prompt,
        system_prompt=(
            "You propose one deterministic query over an already interpreted "
            "source table. Return one JSON object. Never decide whether to continue."
        ),
        tier=_SOURCE_TABLE_QUERY_TIER,
        call_site="source-table-episode-query",
    )
    if not isinstance(payload, Mapping):
        raise ValueError("table query proposal must return a JSON object")
    available = set(dataset.available_goal_columns)
    required = tuple(
        dict.fromkeys(
            str(value)
            for value in (payload.get("required_columns") or ())
            if str(value) in available
        )
    )
    filters: list[SourceTableFilter] = []
    for raw in payload.get("contains") or ():
        if not isinstance(raw, Mapping):
            continue
        column = str(raw.get("column") or "")
        value = " ".join(str(raw.get("text") or "").split())
        if column in available and value:
            filters.append(SourceTableFilter(column=column, text=value))
    return SourceTableQuery(
        required_columns=required,
        contains=tuple(filters),
        rationale=str(payload.get("rationale") or "").strip(),
    )


def _query_source_rows(
    rows: Sequence[ParsedSourceTableRow],
    query: SourceTableQuery,
) -> tuple[ParsedSourceTableRow, ...]:
    selected: list[ParsedSourceTableRow] = []
    for row in rows:
        if any(
            not str(row.values.get(column) or "").strip()
            for column in query.required_columns
        ):
            continue
        if any(
            item.text.casefold()
            not in str(row.values.get(item.column) or "").casefold()
            for item in query.contains
        ):
            continue
        selected.append(row)
    return tuple(selected)


class SourceTableQuerySource:
    """Generate and execute one adaptive source-table query per pull."""

    def __init__(
        self,
        *,
        region: TableRegion,
        page: PageUnit,
        source_record: Mapping[str, Any],
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        interpret: Callable[..., Awaitable[SourceTableDataset]],
        propose: Callable[..., Awaitable[SourceTableQuery]],
        make_leaf: Callable[[SourceTableQueryUnit], Leaf],
        goal_states: Callable[[], Sequence[Mapping[str, Any]]],
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        open_prompt_scope: Callable[[str, tuple[tuple[str, str], ...]], Any],
    ) -> None:
        self.region = region
        self.page = page
        self.source_record = source_record
        self.episode_id = episode_id
        self.episode_path = episode_path
        self._interpret = interpret
        self._propose = propose
        self._make_leaf = make_leaf
        self._goal_states = goal_states
        self._open_cost_scope = open_cost_scope
        self._open_prompt_scope = open_prompt_scope
        self.dataset: Optional[SourceTableDataset] = None
        self.processed_row_ids: set[str] = set()
        self.history: list[dict[str, Any]] = []

    async def _prepare(self) -> None:
        if self.dataset is not None:
            return
        observation_id = f"{self.region.region_id}#interpret"
        with self._open_prompt_scope(self.episode_id, self.episode_path):
            with self._open_cost_scope(
                ObservationKind.PROBE_SEARCH.value,
                observation_id,
                self.episode_id,
                self.episode_path,
            ):
                self.dataset = await self._interpret(
                    region=self.region,
                    source_record=self.source_record,
                )

    async def next(self, view: EpisodeView) -> Leaf | SourceEnd | None:
        try:
            await self._prepare()
        except Exception:
            return SourceEnd(END_SOURCE_FAILED, SOURCE_TABLE_PARSE_FAILED)
        assert self.dataset is not None
        remaining = tuple(
            row
            for row in self.dataset.rows
            if row.row_id not in self.processed_row_ids
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
            return SourceEnd(END_SOURCE_FAILED, SOURCE_TABLE_QUERY_FAILED)
        rows = _query_source_rows(remaining, query)
        return self._make_leaf(
            SourceTableQueryUnit(
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


class SourceTableBinding:
    """Construct source-table Episodes without invoking chunk retrieval."""

    def _make_source_table_episode(
        self,
        state: PageRunState,
        region: TableRegion,
        *,
        page_path: tuple[tuple[str, str], ...],
    ) -> Episode:
        source_table_path = page_path + (
            (self.source_table_grain.name, region.region_id),
        )
        source_table_ref = Episode.identity(
            self.controller.context,
            self.source_table_grain,
            region.region_id,
            parent_path=page_path,
        )
        source = SourceTableQuerySource(
            region=region,
            page=state.unit,
            source_record=state.source_record,
            episode_id=source_table_ref.episode_id,
            episode_path=source_table_path,
            interpret=self.interpret_source_table_region,
            propose=self.propose_source_table_query,
            make_leaf=self._make_source_table_query_leaf,
            goal_states=self.goal_states,
            open_cost_scope=self.open_cost_scope,
            open_prompt_scope=self.open_prompt_scope,
        )
        return Episode(
            grain=self.source_table_grain,
            key=region.region_id,
            source=source,
            on_unit=lambda leaf, contribution, record: self._on_source_table_query(
                state, source, leaf, contribution, record
            ),
            to_parent=self._episode_update,
        )

    def _make_source_table_query_leaf(self, unit: SourceTableQueryUnit) -> Leaf:
        return Leaf(
            unit=unit,
            extract=self._extract_source_table_query,
            accept=self._accept_source_table_query,
            result=self._source_table_query_result,
            label=unit.label,
        )

    def _source_table_query_result(
        self,
        unit: SourceTableQueryUnit,
        material: PageMaterial,
    ) -> Any:
        transition = self.crediter(unit, material)
        unit.attach_result(SourceTableQueryResult(goal_transition=transition))
        return transition.observation

    def _extract_source_table_query(
        self,
        unit: SourceTableQueryUnit,
    ) -> PageMaterial:
        selected_chunk_ids = tuple(
            dict.fromkeys(
                chunk_id
                for row in unit.rows
                for chunk_id in row.source_chunk_ids
            )
        )
        chunks: list[dict[str, Any]] = []
        for index, chunk_id in enumerate(selected_chunk_ids):
            span = unit.dataset.source_chunks[chunk_id]
            chunks.append(
                {
                    "chunk_index": index,
                    "chunk_id": chunk_id,
                    "source_id": str(unit.source_record.get("id") or ""),
                    "start_offset": span.start_offset,
                    "end_offset": span.end_offset,
                    "text": span.text,
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
        records = tuple(
            {
                "table": unit.dataset.goal_table_name,
                "index": index,
                "values": dict(row.values),
                "source_chunks": list(row.source_chunk_ids),
            }
            for index, row in enumerate(unit.rows)
        )
        return PageMaterial(
            source_id=str(unit.source_record.get("id") or ""),
            fate=page_fate(extraction=EXTRACT_OK),
            records=records,
            source_record=unit.source_record,
            chunks=tuple(chunks),
            text_chars=sum(len(chunk["text"]) for chunk in chunks),
        )

    async def _accept_source_table_query(
        self,
        unit: SourceTableQueryUnit,
        material: PageMaterial,
    ) -> PageMaterial:
        if not material.records:
            return material
        return await self.accept_evidence(unit, material)

    def _on_source_table_query(
        self,
        state: PageRunState,
        source: SourceTableQuerySource,
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
            "entities_selected": len(unit.rows),
            "distinct_findings": len(findings),
            "new_findings_within_page": len(new_findings),
            "repeat_findings_within_page": len(repeated_findings),
            "remaining_entities": (
                len(source.dataset.rows) - len(source.processed_row_ids)
                if source.dataset is not None
                else 0
            ),
            "volume_credit": _incidence_step(record).volume_credit.as_record(),
        }
        source.history.append(history)
        state.source_table_history.append(history)
        state.source_table_units.append(unit)
        state.seen_finding_ids.update(findings)
        if isinstance(material, PageMaterial):
            state.materials.append(material)
        state.ingestion.update(
            {
                "extraction_state": "extracting_source_table_entities",
                "source_table_row_count": sum(
                    len(item.records) for item in state.materials
                ),
                "source_table_queries": len(state.source_table_history),
            }
        )
