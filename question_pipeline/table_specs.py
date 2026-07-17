"""Editable table specifications for generic table-fill runs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


@dataclass(frozen=True)
class TableColumnSpec:
    name: str
    role: str = "reported"
    nullable: bool = True
    description: str = ""
    aliases: tuple[str, ...] = ()
    field_hints: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "role": self.role,
            "nullable": self.nullable,
        }
        if self.description:
            out["description"] = self.description
        if self.aliases:
            out["aliases"] = list(self.aliases)
        if self.field_hints:
            out["field_hints"] = list(self.field_hints)
        return out


@dataclass(frozen=True)
class TableTargetSpec:
    name: str
    description: str = ""
    grain: str = ""
    deliverable: bool = True
    key_columns: tuple[str, ...] = ()
    columns: tuple[TableColumnSpec, ...] = ()
    keep_existing_rows: bool = True

    def all_columns(self) -> tuple[TableColumnSpec, ...]:
        columns = {column.name: column for column in self.columns}
        for name in reversed(self.key_columns):
            if name in columns:
                column = columns[name]
                columns[name] = TableColumnSpec(
                    name=column.name,
                    role=column.role,
                    nullable=False,
                    description=column.description,
                    aliases=column.aliases,
                    field_hints=column.field_hints,
                )
            else:
                columns[name] = TableColumnSpec(name=name, nullable=False)
        return tuple(columns.values())

    def required_columns(self) -> tuple[str, ...]:
        return tuple(
            _unique(
                [
                    *self.key_columns,
                    *(
                        column.name
                        for column in self.columns
                        if not column.nullable
                    ),
                ],
            ),
        )

    def completeness_columns(self) -> tuple[str, ...]:
        return self.required_columns()

    def best_guess_columns(self) -> tuple[TableColumnSpec, ...]:
        return tuple(
            column
            for column in self.all_columns()
            if column.role.lower().replace("-", "_") == "best_guess"
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "deliverable": self.deliverable,
            "keep_existing_rows": self.keep_existing_rows,
        }
        if self.description:
            out["description"] = self.description
        if self.grain:
            out["grain"] = self.grain
        if self.key_columns:
            out["key_columns"] = list(self.key_columns)
        out["columns"] = {
            column.name: column.to_dict()
            for column in self.all_columns()
        }
        return out


@dataclass(frozen=True)
class TableMigrationSpec:
    from_table: str
    to_table: str
    mode: str = "llm"
    instructions: str = ""
    input_variable: str = ""

    def input_variable_name(self) -> str:
        if self.input_variable:
            return self.input_variable
        return seed_input_variable_name(self.from_table, self.to_table)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "from_table": self.from_table,
            "to_table": self.to_table,
            "mode": self.mode,
            "input_variable": self.input_variable_name(),
        }
        if self.instructions:
            out["instructions"] = self.instructions
        return out


@dataclass(frozen=True)
class TableSpec:
    tables: Mapping[str, TableTargetSpec] = field(default_factory=dict)
    migrations: tuple[TableMigrationSpec, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.tables and not self.migrations

    def deliverable_names(self) -> list[str]:
        return [
            name
            for name, table in self.tables.items()
            if table.deliverable
        ]

    def empty_rows_by_table(self) -> dict[str, list[dict[str, Any]]]:
        return {name: [] for name in self.deliverable_names()}

    def required_columns_by_table(self) -> dict[str, list[str]]:
        return {
            name: list(table.required_columns())
            for name, table in self.tables.items()
            if table.deliverable
        }

    def completeness_columns_by_table(self) -> dict[str, list[str]]:
        return {
            name: list(table.completeness_columns())
            for name, table in self.tables.items()
            if table.deliverable
        }

    def best_guess_slot_targets(self) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []
        for name, table in self.tables.items():
            if not table.deliverable:
                continue
            for column in table.best_guess_columns():
                targets.append(
                    {
                        "target_table": name,
                        "columns": [column.name],
                        "field_hints": [
                            column.name,
                            *column.aliases,
                            *column.field_hints,
                        ],
                        "reason": (
                            column.description
                            or "column is declared as a derived best-guess slot"
                        ),
                    }
                )
        return targets

    def context_slots(self) -> list[dict[str, Any]]:
        slots: list[dict[str, Any]] = []
        for table in self.tables.values():
            if not table.deliverable:
                continue
            for column in table.best_guess_columns():
                slots.append(
                    {
                        "name": column.name,
                        "field_hints": [
                            column.name,
                            *column.aliases,
                            *column.field_hints,
                        ],
                    }
                )
        return slots

    def prompt_context(self) -> dict[str, Any]:
        return {
            "target_table_names": self.deliverable_names(),
            "tables": {
                name: table.to_dict()
                for name, table in self.tables.items()
                if table.deliverable
            },
            "migrations": [
                migration.to_dict()
                for migration in self.migrations
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "tables": {
                name: table.to_dict()
                for name, table in self.tables.items()
            },
            "migrations": [
                migration.to_dict()
                for migration in self.migrations
            ],
        }


def load_table_spec(path: str | Path | None) -> TableSpec:
    """Load an editable table-fill spec from YAML or JSON."""

    if not path:
        return TableSpec()

    spec_path = Path(path)
    if not spec_path.exists():
        raise FileNotFoundError(f"Table spec path not found: {spec_path}")

    if spec_path.suffix.lower() == ".json":
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
    else:
        payload = yaml.safe_load(spec_path.read_text(encoding="utf-8"))

    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise ValueError("table spec must be a YAML/JSON mapping")

    return TableSpec(
        tables=_coerce_tables(payload.get("tables")),
        migrations=_coerce_migrations(payload.get("migrations")),
    )


def dump_table_spec_yaml(spec: TableSpec | Mapping[str, Any]) -> str:
    payload = spec.to_dict() if isinstance(spec, TableSpec) else dict(spec)
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)


def observed_table_spec(
    rows_by_name: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    base: TableSpec | None = None,
    table_names: Iterable[str] | None = None,
) -> TableSpec:
    """Build an editable spec from declared tables plus observed row columns."""

    base = base or TableSpec()
    names = list(
        _unique(
            [
                *(table_names or []),
                *base.tables,
                *rows_by_name,
            ],
        )
    )
    tables: dict[str, TableTargetSpec] = {}
    for name in names:
        base_table = base.tables.get(name)
        observed_columns = [
            TableColumnSpec(name=column)
            for column in _observed_columns(rows_by_name.get(name, ()))
        ]
        columns = _merge_columns(
            [
                *(base_table.columns if base_table is not None else ()),
                *observed_columns,
            ],
        )
        tables[name] = TableTargetSpec(
            name=name,
            description=base_table.description if base_table else "",
            grain=base_table.grain if base_table else "",
            deliverable=base_table.deliverable if base_table else True,
            key_columns=base_table.key_columns if base_table else (),
            columns=columns,
            keep_existing_rows=(
                base_table.keep_existing_rows if base_table is not None else True
            ),
        )
    return TableSpec(tables=tables, migrations=base.migrations)


def seed_input_variable_name(table_name: str, to_table: str | None = None) -> str:
    parts = [str(table_name or "table")]
    if to_table:
        parts.extend(["to", str(to_table)])
    safe = re.sub(r"[^A-Za-z0-9]+", "_", "_".join(parts)).strip("_").lower()
    return f"seed_{safe or 'table'}_rows"


def _coerce_tables(raw: Any) -> dict[str, TableTargetSpec]:
    items: Iterable[tuple[Any, Any]]
    if isinstance(raw, Mapping):
        items = raw.items()
    elif isinstance(raw, list):
        items = (
            (
                item.get("name") if isinstance(item, Mapping) else "",
                item,
            )
            for item in raw
        )
    elif raw is None:
        items = ()
    else:
        raise ValueError("tables must be a mapping or list")

    tables: dict[str, TableTargetSpec] = {}
    for fallback_name, value in items:
        table = _coerce_table(fallback_name, value)
        if table is not None:
            tables[table.name] = table
    return tables


def _coerce_table(fallback_name: Any, raw: Any) -> TableTargetSpec | None:
    if raw is None:
        raw = {}
    if isinstance(raw, list):
        raw = {"columns": raw}
    if not isinstance(raw, Mapping):
        return None

    name = str(raw.get("name") or fallback_name or "").strip()
    if not name:
        return None

    key_columns = tuple(_clean_list(raw.get("key_columns") or raw.get("keys")))
    columns = _merge_columns(
        [
            *_coerce_columns(raw.get("columns")),
            *(
                TableColumnSpec(name=column, nullable=False)
                for column in key_columns
            ),
        ],
    )
    return TableTargetSpec(
        name=name,
        description=str(raw.get("description") or "").strip(),
        grain=str(raw.get("grain") or raw.get("row_grain") or "").strip(),
        deliverable=bool(raw.get("deliverable", True)),
        key_columns=key_columns,
        columns=columns,
        keep_existing_rows=bool(raw.get("keep_existing_rows", True)),
    )


def _coerce_columns(raw: Any) -> list[TableColumnSpec]:
    if isinstance(raw, Mapping):
        items = raw.items()
    elif isinstance(raw, list):
        items = enumerate(raw)
    elif raw is None:
        items = ()
    else:
        raise ValueError("table columns must be a mapping or list")

    columns: list[TableColumnSpec] = []
    for fallback_name, item in items:
        column = _coerce_column(fallback_name, item)
        if column is not None:
            columns.append(column)
    return columns


def _coerce_column(fallback_name: Any, raw: Any) -> TableColumnSpec | None:
    if isinstance(raw, str):
        raw = {"name": raw}
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        return None

    name = str(raw.get("name") or fallback_name or "").strip()
    if not name or name.isdigit():
        return None
    return TableColumnSpec(
        name=name,
        role=str(raw.get("role") or "reported").strip() or "reported",
        nullable=not bool(raw.get("required", False))
        if "nullable" not in raw
        else bool(raw.get("nullable")),
        description=str(raw.get("description") or "").strip(),
        aliases=tuple(_clean_list(raw.get("aliases"))),
        field_hints=tuple(_clean_list(raw.get("field_hints"))),
    )


def _coerce_migrations(raw: Any) -> tuple[TableMigrationSpec, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("migrations must be a list")

    migrations: list[TableMigrationSpec] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        from_table = str(item.get("from_table") or item.get("from") or "").strip()
        to_table = str(item.get("to_table") or item.get("to") or "").strip()
        if not from_table or not to_table:
            continue
        migrations.append(
            TableMigrationSpec(
                from_table=from_table,
                to_table=to_table,
                mode=str(item.get("mode") or "llm").strip() or "llm",
                instructions=str(item.get("instructions") or "").strip(),
                input_variable=str(item.get("input_variable") or "").strip(),
            )
        )
    return tuple(migrations)


def _merge_columns(columns: Iterable[TableColumnSpec]) -> tuple[TableColumnSpec, ...]:
    merged: dict[str, TableColumnSpec] = {}
    for column in columns:
        if not column.name or column.name in merged:
            continue
        merged[column.name] = column
    return tuple(merged.values())


def _observed_columns(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for column in row:
            column = str(column)
            if column not in columns:
                columns.append(column)
    return columns


def _clean_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    return [
        value
        for value in _unique(str(value or "").strip() for value in values)
        if value
    ]


def _unique(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
