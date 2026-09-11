"""Typed table state plus reusable export loading and merge helpers.

The live table is the result-state boundary for table-fill acquisition.
Evidence is accepted before it reaches :class:`TypedTableStore`; acquisition
credit may be assigned only after this store has materialized the accepted
cell in the declared typed result state.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import criteria
from .control import stable_id
from .evidence_registry import (
    AcceptedBestGuessCell,
    AcceptedCell,
    EvidenceCommit,
)
from .table_specs import ColumnEvidenceRole, ColumnRef, TableRef


_ROUND_MANIFEST_RE = re.compile(r"^round_(?P<round>\d+)_manifest\.json$")
_ROUND_TABLE_RE = re.compile(r"^round_(?P<round>\d+)_(?P<table>.+)\.json$")

LOGICAL_VALUE_SLOT_IDENTITY_VERSION = "logical_value_slot_credit_v1"
LOGICAL_ROW_STATE_IDENTITY_VERSION = "logical_row_state_v1"


@dataclass(frozen=True)
class ResultColumn:
    """One physical result column admitted by the table contract."""

    table: str
    column: str
    table_id: str
    column_id: str
    value_slot: str
    slot_id: str
    required: bool
    role: ColumnEvidenceRole
    aliases: tuple[str, ...] = ()
    description: str = ""
    value_type: str = ""
    unit: str = ""


@dataclass(frozen=True)
class ResultColumnExclusion:
    """A declared column excluded from result-state accounting."""

    table: str
    column: str
    exclusion_class: str


@dataclass(frozen=True)
class LogicalSlotDefinition:
    """One semantic result slot and all its physical evidence routes."""

    table: str
    table_id: str
    value_slot: str
    slot_id: str
    columns: tuple[ResultColumn, ...]
    required: bool

    @property
    def column_ids(self) -> tuple[str, ...]:
        return tuple(column.column_id for column in self.columns)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.column for column in self.columns)


@dataclass(frozen=True)
class ResultContract:
    """The single physical-column to logical-slot contract for a run."""

    columns: tuple[ResultColumn, ...]
    slots: tuple[LogicalSlotDefinition, ...]
    excluded: tuple[ResultColumnExclusion, ...]
    subject_key_columns: Mapping[str, tuple[str, ...]]
    tables: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": [
                {
                    "table": column.table,
                    "table_id": column.table_id,
                    "column": column.column,
                    "column_id": column.column_id,
                    "value_slot": column.value_slot,
                    "slot_id": column.slot_id,
                    "required": column.required,
                    "role": column.role.value,
                    "value_type": column.value_type,
                    "unit": column.unit,
                }
                for column in self.columns
            ],
            "logical_slots": [
                {
                    "table": slot.table,
                    "table_id": slot.table_id,
                    "value_slot": slot.value_slot,
                    "slot_id": slot.slot_id,
                    "column_ids": list(slot.column_ids),
                    "required": slot.required,
                }
                for slot in self.slots
            ],
            "excluded_columns": [
                {
                    "table": item.table,
                    "column": item.column,
                    "class": item.exclusion_class,
                }
                for item in self.excluded
            ],
            "subject_key_columns": {
                table: list(columns)
                for table, columns in self.subject_key_columns.items()
            },
            "typed_column_count": sum(
                1 for column in self.columns if column.value_type or column.unit
            ),
        }


def result_contract(table_spec: Any) -> ResultContract:
    """Select result columns once and collapse evidence alternatives to slots."""

    columns: list[ResultColumn] = []
    excluded: list[ResultColumnExclusion] = []
    subject_keys: dict[str, tuple[str, ...]] = {}
    tables: list[str] = []
    spec_tables = getattr(table_spec, "tables", None) or {}
    for table_name, table in spec_tables.items():
        if not getattr(table, "deliverable", True):
            continue
        name = str(table_name)
        table_ref = TableRef.create(name)
        tables.append(name)
        subject_keys[name] = tuple(
            str(column)
            for column in (getattr(table, "subject_key_columns", ()) or ())
        )
        identity_columns = {
            str(column) for column in (getattr(table, "key_columns", ()) or ())
        }
        identity_columns.update(subject_keys[name])
        required_names = {
            str(column)
            for column in (
                table.required_columns()
                if callable(getattr(table, "required_columns", None))
                else ()
            )
        }
        for column in table.all_columns():
            column_name = str(column.name)
            if column_name in identity_columns:
                excluded.append(
                    ResultColumnExclusion(name, column_name, "identity")
                )
                continue
            exclusion = criteria.datapoint_exclusion_class(column_name)
            if exclusion:
                excluded.append(ResultColumnExclusion(name, column_name, exclusion))
                continue
            value_slot = str(
                getattr(column, "value_slot", None) or column_name
            )
            columns.append(
                ResultColumn(
                    table=name,
                    column=column_name,
                    table_id=table_ref.id,
                    column_id=ColumnRef.create(table_ref, column_name).id,
                    value_slot=value_slot,
                    slot_id=ColumnRef.create(table_ref, value_slot).id,
                    required=column_name in required_names,
                    role=ColumnEvidenceRole.coerce(getattr(column, "role", None)),
                    aliases=tuple(
                        str(item)
                        for item in (getattr(column, "aliases", ()) or ())
                    ),
                    description=str(getattr(column, "description", "") or ""),
                    value_type=str(getattr(column, "value_type", "") or ""),
                    unit=str(getattr(column, "unit", "") or ""),
                )
            )

    grouped: dict[tuple[str, str], list[ResultColumn]] = {}
    for column in columns:
        grouped.setdefault((column.table_id, column.slot_id), []).append(column)
    slots = tuple(
        LogicalSlotDefinition(
            table=members[0].table,
            table_id=table_id,
            value_slot=members[0].value_slot,
            slot_id=slot_id,
            columns=tuple(members),
            required=any(column.required for column in members),
        )
        for (table_id, slot_id), members in grouped.items()
    )
    return ResultContract(
        columns=tuple(columns),
        slots=slots,
        excluded=tuple(excluded),
        subject_key_columns=subject_keys,
        tables=tuple(tables),
    )


@dataclass(frozen=True)
class LogicalSlotValue:
    """Accepted typed cells occupying one subject's logical result slot."""

    identity: str
    table: str
    table_id: str
    subject_id: str
    value_slot: str
    slot_id: str
    required: bool
    accepted_cell_ids: tuple[str, ...]
    physical_columns: tuple[str, ...]
    preferred_cell_id: str


@dataclass(frozen=True)
class LogicalRowState:
    """One subject's completeness over the contract's required logical slots."""

    identity: str
    table: str
    table_id: str
    subject_id: str
    present_slot_ids: tuple[str, ...]
    required_slot_ids: tuple[str, ...]
    complete: bool


@dataclass(frozen=True)
class LogicalTableProjection:
    """Canonical post-storage state consumed by credit and completeness."""

    slot_definitions: tuple[LogicalSlotDefinition, ...]
    slot_values: tuple[LogicalSlotValue, ...]
    rows: tuple[LogicalRowState, ...]

    @property
    def identities(self) -> frozenset[str]:
        return frozenset(value.identity for value in self.slot_values)

    @property
    def completed_subjects(self) -> frozenset[tuple[str, str, str]]:
        return frozenset(
            (row.table_id, row.table, row.subject_id)
            for row in self.rows
            if row.complete
        )

    def table_summary(self, table: str) -> dict[str, Any]:
        table_rows = [row for row in self.rows if row.table == table]
        table_values = [
            value for value in self.slot_values if value.table == table
        ]
        definitions = [
            slot for slot in self.slot_definitions if slot.table == table
        ]
        required_ids = tuple(
            slot.slot_id
            for slot in definitions
            if slot.required
        )
        missing_by_slot = {
            slot_id: sum(
                1 for row in table_rows if slot_id not in row.present_slot_ids
            )
            for slot_id in required_ids
        }
        return {
            "subjects": len(table_rows),
            "complete_subjects": sum(1 for row in table_rows if row.complete),
            "partial_subjects": sum(1 for row in table_rows if not row.complete),
            "required_slot_ids": list(required_ids),
            "missing_by_slot_id": {
                slot_id: count
                for slot_id, count in missing_by_slot.items()
                if count
            },
            "slot_coverage": {
                slot.slot_id: {
                    "value_slot": slot.value_slot,
                    "required": slot.required,
                    "alternative_columns": list(slot.column_names),
                    "occupied_subjects": sum(
                        value.slot_id == slot.slot_id for value in table_values
                    ),
                    "missing_subjects": sum(
                        slot.slot_id not in row.present_slot_ids
                        for row in table_rows
                    ),
                    "reported_subjects": sum(
                        value.slot_id == slot.slot_id
                        and any(
                            column.column in value.physical_columns
                            and column.role is ColumnEvidenceRole.REPORTED
                            for column in slot.columns
                        )
                        for value in table_values
                    ),
                    "best_guess_subjects": sum(
                        value.slot_id == slot.slot_id
                        and any(
                            column.column in value.physical_columns
                            and column.role is ColumnEvidenceRole.BEST_GUESS
                            for column in slot.columns
                        )
                        for value in table_values
                    ),
                    "physical_column_subjects": {
                        column.column: sum(
                            value.slot_id == slot.slot_id
                            and column.column in value.physical_columns
                            for value in table_values
                        )
                        for column in slot.columns
                    },
                }
                for slot in definitions
            },
        }


@dataclass
class SeedTables:
    rows_by_name: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    max_round_index: int | None = None

    @property
    def row_count(self) -> int:
        return sum(len(rows) for rows in self.rows_by_name.values())

    @property
    def next_round_index(self) -> int:
        if self.max_round_index is None:
            return 0
        return self.max_round_index + 1


@dataclass(frozen=True)
class TableMutation:
    """One accepted-evidence write and its exact criteria-state boundary."""

    before_state_id: str
    after_state_id: str
    before_projection: LogicalTableProjection
    after_projection: LogicalTableProjection
    admitted_cell_ids: frozenset[str]


class TypedTableStore:
    """Materialize only registry-accepted cells into a declared table state.

    The store decides no credit and calls no model. It owns the typed state
    mutation that must precede the single credit assigner. Rows remain grouped
    by the table contract's stable subject identity; conflicting accepted
    values are retained as separate partial observations of that same subject
    so the criteria projection can preserve, rather than overwrite, evidence.
    """

    def __init__(
        self,
        table_spec: Any,
        evidence_registry: Any,
        rows_by_name: dict[str, list[dict[str, Any]]],
    ) -> None:
        self.table_spec = table_spec
        self.result_contract = result_contract(table_spec)
        self.evidence_registry = evidence_registry
        self._rows = rows_by_name
        self._supported_cells: dict[
            str, AcceptedCell | AcceptedBestGuessCell
        ] = {}
        for cell in self.evidence_registry.accepted_cells():
            if self._cell_present(cell):
                self._supported_cells[cell.id] = cell

    @property
    def rows_by_name(self) -> dict[str, list[dict[str, Any]]]:
        return self._rows

    def logical_projection(self) -> LogicalTableProjection:
        """Project accepted stored cells into the contract's logical slots once."""

        columns_by_id = {
            column.column_id: column for column in self.result_contract.columns
        }
        slots_by_key = {
            (slot.table_id, slot.slot_id): slot
            for slot in self.result_contract.slots
        }
        grouped: dict[
            tuple[str, str, str],
            list[AcceptedCell | AcceptedBestGuessCell],
        ] = {}
        for cell in self._supported_cells.values():
            column = columns_by_id.get(cell.column_id)
            if column is None:
                continue
            grouped.setdefault(
                (column.table_id, cell.subject_id, column.slot_id), []
            ).append(cell)

        values: list[LogicalSlotValue] = []
        for (table_id, subject_id, slot_id), cells in sorted(grouped.items()):
            definition = slots_by_key[(table_id, slot_id)]
            ordered = sorted(
                cells,
                key=lambda cell: (
                    isinstance(cell, AcceptedBestGuessCell),
                    cell.id,
                ),
            )
            values.append(
                LogicalSlotValue(
                    identity=stable_id(
                        {
                            "version": LOGICAL_VALUE_SLOT_IDENTITY_VERSION,
                            "table_id": table_id,
                            "slot_id": slot_id,
                            "subject_id": subject_id,
                        }
                    ),
                    table=definition.table,
                    table_id=table_id,
                    subject_id=subject_id,
                    value_slot=definition.value_slot,
                    slot_id=slot_id,
                    required=definition.required,
                    accepted_cell_ids=tuple(cell.id for cell in ordered),
                    physical_columns=tuple(
                        dict.fromkeys(cell.column for cell in ordered)
                    ),
                    preferred_cell_id=ordered[0].id,
                )
            )

        required_by_table = {
            table_id: tuple(
                slot.slot_id
                for slot in self.result_contract.slots
                if slot.table_id == table_id and slot.required
            )
            for table_id in {
                slot.table_id for slot in self.result_contract.slots
            }
        }
        present_by_subject: dict[tuple[str, str, str], set[str]] = {}
        table_ids = {
            slot.table: slot.table_id for slot in self.result_contract.slots
        }
        for table in self.result_contract.tables:
            table_id = table_ids.get(table, TableRef.create(table).id)
            refs = criteria.row_subject_refs(
                table,
                self._rows.get(table, ()),
                self.table_spec,
            )
            for ref in refs:
                if ref is not None and ref.bound:
                    present_by_subject.setdefault(
                        (table_id, table, ref.id), set()
                    )
        for value in values:
            present_by_subject.setdefault(
                (value.table_id, value.table, value.subject_id), set()
            ).add(value.slot_id)
        rows = tuple(
            LogicalRowState(
                identity=stable_id(
                    {
                        "version": LOGICAL_ROW_STATE_IDENTITY_VERSION,
                        "table_id": table_id,
                        "subject_id": subject_id,
                    }
                ),
                table=table,
                table_id=table_id,
                subject_id=subject_id,
                present_slot_ids=tuple(sorted(present)),
                required_slot_ids=required_by_table.get(table_id, ()),
                complete=bool(required_by_table.get(table_id))
                and set(required_by_table[table_id]) <= present,
            )
            for (table_id, table, subject_id), present in sorted(
                present_by_subject.items()
            )
        )
        return LogicalTableProjection(
            slot_definitions=self.result_contract.slots,
            slot_values=tuple(values),
            rows=rows,
        )

    def replace_rows(
        self,
        rows_by_name: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> None:
        replacement = {
            str(table): [dict(row) for row in rows if isinstance(row, Mapping)]
            for table, rows in rows_by_name.items()
        }
        self._rows.clear()
        self._rows.update(replacement)
        self._supported_cells.clear()
        for cell in self.evidence_registry.accepted_cells():
            if self._cell_present(cell):
                self._supported_cells[cell.id] = cell

    def _state_id(self) -> str:
        return stable_id(
            {
                "version": "typed_table_state_v1",
                "rows": self._rows,
                "supported_cell_ids": sorted(self._supported_cells),
            }
        )

    def apply(
        self,
        records: Sequence[Mapping[str, Any]],
        commit: EvidenceCommit,
    ) -> TableMutation:
        if not isinstance(commit, EvidenceCommit):
            raise TypeError("typed table storage requires an EvidenceCommit")
        before_state_id = self._state_id()
        before_projection = self.logical_projection()
        accepted = [*commit.accepted_cells, *commit.accepted_best_guess_cells]
        record_index = self._record_index(records)
        candidate_ids: set[str] = set()
        for cell in accepted:
            source_row = self._source_row(cell, record_index)
            if source_row is None:
                continue
            if self._store_cell(cell, source_row) and self._cell_present(cell):
                candidate_ids.add(cell.id)
                self._supported_cells[cell.id] = cell
        return TableMutation(
            before_state_id=before_state_id,
            after_state_id=self._state_id(),
            before_projection=before_projection,
            after_projection=self.logical_projection(),
            admitted_cell_ids=frozenset(candidate_ids),
        )

    def _deliverable_tables(self) -> tuple[str, ...]:
        tables = getattr(self.table_spec, "tables", None) or {}
        return tuple(
            str(name)
            for name, table in tables.items()
            if bool(getattr(table, "deliverable", True))
        )

    def _record_index(
        self, records: Sequence[Mapping[str, Any]]
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        out: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for record in records:
            if not isinstance(record, Mapping):
                continue
            table = str(record.get("table") or "")
            values = record.get("values")
            if not table or not isinstance(values, Mapping):
                continue
            refs = criteria.row_subject_refs(table, [values], self.table_spec)
            ref = refs[0] if refs else None
            if ref is None or not ref.bound:
                continue
            out.setdefault((table, ref.id), []).append(dict(values))
        return out

    @staticmethod
    def _decoded_value(cell: AcceptedCell | AcceptedBestGuessCell) -> Any:
        try:
            return json.loads(cell.value_json)
        except json.JSONDecodeError as exc:
            raise ValueError("accepted cell contains invalid value_json") from exc

    def _source_row(
        self,
        cell: AcceptedCell | AcceptedBestGuessCell,
        index: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    ) -> dict[str, Any] | None:
        candidates = index.get((cell.table, cell.subject_id)) or ()
        if isinstance(cell, AcceptedBestGuessCell):
            return dict(candidates[0]) if candidates else None
        for row in candidates:
            value = row.get(cell.column)
            if (
                not criteria.is_missing_value(value)
                and criteria.normalize_key_value(value) == cell.normalized_value
            ):
                return dict(row)
        return None

    def _subject_keys(self, table: str) -> tuple[str, ...]:
        tables = getattr(self.table_spec, "tables", None) or {}
        spec = tables.get(table)
        return tuple(
            str(name)
            for name in (getattr(spec, "subject_key_columns", ()) or ())
        )

    def _existing_rows(self, table: str, subject_id: str) -> list[dict[str, Any]]:
        rows = self._rows.setdefault(table, [])
        refs = criteria.row_subject_refs(table, rows, self.table_spec)
        return [
            row
            for row, ref in zip(rows, refs)
            if ref is not None and ref.id == subject_id
        ]

    @staticmethod
    def _add_source(row: dict[str, Any], field: str, source_id: str) -> None:
        key = f"{field}_source_ids"
        values = row.get(key)
        sources = (
            [str(item) for item in values]
            if isinstance(values, list)
            else [str(values)] if values else []
        )
        if source_id not in sources:
            sources.append(source_id)
        row[key] = sources
        row_sources = row.get("source_ids")
        all_sources = (
            [str(item) for item in row_sources]
            if isinstance(row_sources, list)
            else [str(row_sources)] if row_sources else []
        )
        if source_id not in all_sources:
            all_sources.append(source_id)
        row["source_ids"] = all_sources

    def _store_cell(
        self,
        cell: AcceptedCell | AcceptedBestGuessCell,
        source_row: Mapping[str, Any],
    ) -> bool:
        value = self._decoded_value(cell)
        existing = self._existing_rows(cell.table, cell.subject_id)
        target = next(
            (
                row
                for row in existing
                if criteria.is_missing_value(row.get(cell.column))
                or criteria.normalize_key_value(row.get(cell.column))
                == cell.normalized_value
            ),
            None,
        )
        if target is None:
            target = {
                key: source_row[key]
                for key in self._subject_keys(cell.table)
                if key in source_row and not criteria.is_missing_value(source_row[key])
            }
            if len(target) != len(self._subject_keys(cell.table)):
                return False
            self._rows.setdefault(cell.table, []).append(target)
        target[cell.column] = value
        self._add_source(target, cell.column, cell.source_id)
        return True

    def _cell_present(self, cell: Any) -> bool:
        for row in self._existing_rows(cell.table, cell.subject_id):
            value = row.get(cell.column)
            if (
                not criteria.is_missing_value(value)
                and criteria.normalize_key_value(value) == cell.normalized_value
            ):
                return True
        return False


def load_seed_tables(path: str | Path | None) -> SeedTables:
    """Load previously exported JSON tables from a file or directory."""
    if not path:
        return SeedTables()

    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"Seed table path not found: {root}")

    if root.is_file():
        if root.name.endswith("_manifest.json"):
            return _load_manifest_tables([root])
        return _load_table_files([root])

    manifests = sorted(root.glob("*_manifest.json"))
    if manifests:
        return _load_manifest_tables(manifests)

    return _load_table_files(
        sorted(
            file_path
            for file_path in root.glob("*.json")
            if not file_path.name.endswith("_manifest.json")
        )
    )


def merge_rows_by_table(
    first: Mapping[str, Iterable[dict[str, Any]]],
    second: Mapping[str, Iterable[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Merge table rows by exact normalized row content."""
    merged: dict[str, list[dict[str, Any]]] = {}
    for name in sorted(set(first) | set(second)):
        merged[name] = merge_rows(
            list(first.get(name, [])),
            list(second.get(name, [])),
        )
    return merged


def merge_rows(*groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for group in groups:
        for row in group:
            key = _stable_row_key(row)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _load_manifest_tables(manifests: Iterable[Path]) -> SeedTables:
    rows_by_name: dict[str, list[dict[str, Any]]] = {}
    sources: list[dict[str, Any]] = []
    max_round_index: int | None = None

    for manifest_path in manifests:
        max_round_index = _max_round_index(
            max_round_index,
            _round_index_from_manifest_path(manifest_path),
        )
        entries = _read_json(manifest_path)
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            table_name = str(entry.get("variable") or "").strip()
            if not table_name:
                continue

            json_path = _resolve_table_path(
                entry.get("json_path"),
                manifest_path=manifest_path,
            )
            rows = _read_dict_rows(json_path)
            if not rows:
                continue

            max_round_index = _max_round_index(
                max_round_index,
                _round_index_from_value(entry.get("round")),
            )
            rows_by_name[table_name] = merge_rows(
                rows_by_name.get(table_name, []),
                rows,
            )
            sources.append(
                {
                    "table": table_name,
                    "path": str(json_path),
                    "rows": len(rows),
                    "manifest": str(manifest_path),
                }
            )

    return SeedTables(
        rows_by_name=rows_by_name,
        sources=sources,
        max_round_index=max_round_index,
    )


def _load_table_files(paths: Iterable[Path]) -> SeedTables:
    rows_by_name: dict[str, list[dict[str, Any]]] = {}
    sources: list[dict[str, Any]] = []
    max_round_index: int | None = None

    for path in paths:
        table_name = _table_name_from_path(path)
        if not table_name:
            continue

        rows = _read_dict_rows(path)
        if not rows:
            continue

        max_round_index = _max_round_index(
            max_round_index,
            _round_index_from_table_path(path),
        )
        rows_by_name[table_name] = merge_rows(rows_by_name.get(table_name, []), rows)
        sources.append(
            {
                "table": table_name,
                "path": str(path),
                "rows": len(rows),
                "manifest": None,
            }
        )

    return SeedTables(
        rows_by_name=rows_by_name,
        sources=sources,
        max_round_index=max_round_index,
    )


def _table_name_from_path(path: Path) -> str:
    match = _ROUND_TABLE_RE.match(path.name)
    if match:
        return match.group("table")
    if path.stem == "manifest" or path.stem.endswith("_manifest"):
        return ""
    return path.stem


def _round_index_from_manifest_path(path: Path) -> int | None:
    match = _ROUND_MANIFEST_RE.match(path.name)
    if not match:
        return None
    return _round_index_from_value(match.group("round"))


def _round_index_from_table_path(path: Path) -> int | None:
    match = _ROUND_TABLE_RE.match(path.name)
    if not match:
        return None
    return _round_index_from_value(match.group("round"))


def _round_index_from_value(value: Any) -> int | None:
    try:
        round_index = int(value)
    except (TypeError, ValueError):
        return None
    if round_index < 0:
        return None
    return round_index


def _max_round_index(*values: int | None) -> int | None:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return max(numeric)


def _resolve_table_path(value: Any, *, manifest_path: Path) -> Path:
    raw = Path(str(value or ""))
    if raw.is_absolute() and raw.exists():
        return raw

    candidates = [
        Path.cwd() / raw,
        manifest_path.parent / raw,
        manifest_path.parent / raw.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]


def _read_dict_rows(path: Path) -> list[dict[str, Any]]:
    data = _read_json(path)
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _stable_row_key(row: Mapping[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
