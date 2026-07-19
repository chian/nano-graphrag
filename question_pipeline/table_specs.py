"""Editable table specifications for generic table-fill runs."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

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


TableSpecPath = str | Path

_OBSERVED_TABLE_SPEC_RE = re.compile(
    r"^round_(?P<label>.+)_observed_table_spec\.(?:ya?ml|json)$",
)


def load_table_spec(
    path: TableSpecPath | Iterable[TableSpecPath] | None,
) -> TableSpec:
    """Load and combine editable table-fill specs from YAML or JSON."""

    payload: dict[str, Any] = {}
    for spec_path in _iter_spec_paths(path):
        payload = merge_table_spec_payloads(
            payload,
            _load_table_spec_payload(spec_path),
        )
    return _coerce_table_spec(payload)


def table_spec_paths_with_seed_tables(
    seed_tables_dir: TableSpecPath | Iterable[TableSpecPath] | None,
    explicit_paths: TableSpecPath | Iterable[TableSpecPath] | None,
) -> list[Path]:
    """Return prior observed specs followed by explicit spec additions."""

    return [
        *observed_table_spec_paths_for_seed(seed_tables_dir),
        *_iter_spec_paths(explicit_paths),
    ]


def load_table_spec_with_seed_tables(
    seed_rows_by_name: Mapping[str, Iterable[Mapping[str, Any]]],
    seed_tables_dir: TableSpecPath | Iterable[TableSpecPath] | None,
    explicit_paths: TableSpecPath | Iterable[TableSpecPath] | None,
) -> TableSpec:
    """Carry forward seed table contracts before applying explicit specs."""

    observed_paths = observed_table_spec_paths_for_seed(seed_tables_dir)
    base = (
        load_table_spec(observed_paths)
        if observed_paths
        else observed_table_spec(seed_rows_by_name)
    )
    return merge_table_specs(
        base,
        load_table_spec(explicit_paths),
    )


def observed_table_spec_paths_for_seed(
    seed_tables_dir: TableSpecPath | Iterable[TableSpecPath] | None,
) -> list[Path]:
    """Find the newest observed table spec adjacent to seed table exports."""

    out: list[Path] = []
    for root in _iter_spec_paths(seed_tables_dir):
        path = _newest_observed_table_spec_path(
            _candidate_table_spec_dirs(root),
        )
        if path is not None and path not in out:
            out.append(path)
    return out


def merge_table_specs(*specs: TableSpec) -> TableSpec:
    """Combine specs in order, with later same-name entries taking precedence."""

    payload: dict[str, Any] = {}
    for spec in specs:
        payload = merge_table_spec_payloads(payload, spec.to_dict())
    return _coerce_table_spec(payload)


def merge_table_spec_payloads(
    base: Mapping[str, Any] | None,
    addition: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Combine raw table-spec payloads before coercion.

    Table specs are complete contracts after this step. A focused spec may add
    a new named table or update a same-name table without omitting other names
    already present in the observed seed spec.
    """

    base = dict(base or {})
    addition = dict(addition or {})
    merged = {
        **{
            key: value
            for key, value in base.items()
            if key not in {"tables", "migrations"}
        },
        **{
            key: value
            for key, value in addition.items()
            if key not in {"tables", "migrations"}
        },
    }
    merged["tables"] = _merge_table_payloads(
        base.get("tables"),
        addition.get("tables"),
    )
    merged["migrations"] = _merge_migration_payloads(
        base.get("migrations"),
        addition.get("migrations"),
    )
    return merged


def _load_table_spec_payload(path: Path) -> dict[str, Any]:
    """Load one editable table-fill spec from YAML or JSON."""

    if not path:
        return {}

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

    return dict(payload)


def _coerce_table_spec(payload: Mapping[str, Any]) -> TableSpec:
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


def _iter_spec_paths(
    path: TableSpecPath | Iterable[TableSpecPath] | None,
) -> list[Path]:
    if path is None:
        return []
    if isinstance(path, Path):
        return [path]
    if isinstance(path, str):
        return [
            Path(value)
            for value in path.split(os.pathsep)
            if value.strip()
        ]

    out: list[Path] = []
    for item in path:
        out.extend(_iter_spec_paths(item))
    return out


def _candidate_table_spec_dirs(root: Path) -> list[Path]:
    base = root.parent if root.is_file() else root
    candidates = [
        base,
        base / "table_specs",
        base / "answers" / "table_specs",
        base.parent / "table_specs",
        base.parent.parent / "table_specs",
    ]
    out: list[Path] = []
    for candidate in candidates:
        if candidate.name != "table_specs" or not candidate.is_dir():
            continue
        if candidate not in out:
            out.append(candidate)
    return out


def _newest_observed_table_spec_path(roots: Iterable[Path]) -> Path | None:
    candidates = sorted(
        {
            path
            for root in roots
            for path in root.glob("round_*_observed_table_spec.*")
            if _OBSERVED_TABLE_SPEC_RE.match(path.name)
        },
        key=_observed_table_spec_sort_key,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _observed_table_spec_sort_key(path: Path) -> tuple[int, int, int, str]:
    match = _OBSERVED_TABLE_SPEC_RE.match(path.name)
    label = match.group("label") if match else ""
    try:
        round_number = int(label)
        numeric = 1
    except ValueError:
        round_number = -1
        numeric = 0
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    return numeric, round_number, mtime_ns, path.name


def _merge_table_payloads(
    base: Any,
    addition: Any,
) -> dict[str, dict[str, Any]]:
    merged = _table_payloads_by_name(base)
    for name, table in _table_payloads_by_name(addition).items():
        if name not in merged:
            merged[name] = table
            continue
        merged[name] = _merge_table_payload(merged[name], table)
    return merged


def _merge_table_payload(
    base: Mapping[str, Any],
    addition: Mapping[str, Any],
) -> dict[str, Any]:
    out = {
        **{
            key: value
            for key, value in base.items()
            if key != "columns"
        },
        **{
            key: value
            for key, value in addition.items()
            if key != "columns"
        },
    }
    out["columns"] = _merge_column_payloads(
        base.get("columns"),
        addition.get("columns"),
    )
    return out


def _merge_column_payloads(
    base: Any,
    addition: Any,
) -> dict[str, dict[str, Any]]:
    merged = _column_payloads_by_name(base)
    for name, column in _column_payloads_by_name(addition).items():
        if name not in merged:
            merged[name] = column
            continue
        merged[name] = {**merged[name], **column}
    return merged


def _merge_migration_payloads(base: Any, addition: Any) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for migration in [*_migration_payloads(base), *_migration_payloads(addition)]:
        key = (
            str(migration.get("from_table") or migration.get("from") or "").strip(),
            str(migration.get("to_table") or migration.get("to") or "").strip(),
        )
        if not all(key):
            continue
        merged[key] = migration
    return list(merged.values())


def _table_payloads_by_name(raw: Any) -> dict[str, dict[str, Any]]:
    return {
        name: payload
        for name, payload in _named_payloads(raw).items()
        if name
    }


def _column_payloads_by_name(raw: Any) -> dict[str, dict[str, Any]]:
    return {
        name: payload
        for name, payload in _named_payloads(raw).items()
        if name
    }


def _named_payloads(raw: Any) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        items: Iterable[tuple[Any, Any]] = raw.items()
    elif isinstance(raw, list):
        items = enumerate(raw)
    else:
        raise ValueError("table spec sections must be mappings or lists")

    out: dict[str, dict[str, Any]] = {}
    for fallback_name, value in items:
        payload = _named_payload(fallback_name, value)
        name = str(payload.get("name") or "").strip()
        if name:
            out[name] = payload
    return out


def _named_payload(fallback_name: Any, raw: Any) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if isinstance(raw, str):
        raw = {"name": raw}
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, Mapping)):
        raw = {"columns": list(raw)}
    if not isinstance(raw, Mapping):
        return {}

    payload = dict(raw)
    payload.setdefault("name", fallback_name)
    payload["name"] = str(payload.get("name") or "").strip()
    return payload


def _migration_payloads(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("migrations must be a list")
    return [dict(item) for item in raw if isinstance(item, Mapping)]


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
