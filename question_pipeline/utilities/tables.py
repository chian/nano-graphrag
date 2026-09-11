"""Typed table contracts, projection, completion, goals, and best guesses."""

from __future__ import annotations


# ============================================================================
# table_specs.py
# ============================================================================

import json
import os
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from question_pipeline.utilities.acquisition import canonical_subject_identity
from question_pipeline.utilities.acquisition import stable_id
from question_pipeline.utilities.model import ModelTier, ask_json, register_call_site_tier


TABLE_IDENTITY_VERSION = "table_identity_v1"
COLUMN_IDENTITY_VERSION = "column_identity_v1"


class ColumnEvidenceRole(str, Enum):
    """The only two evidence routes a result column may accept."""

    REPORTED = "reported"
    BEST_GUESS = "best_guess"

    @classmethod
    def coerce(cls, value: Any) -> "ColumnEvidenceRole":
        if isinstance(value, cls):
            return value
        text = str(value or cls.REPORTED.value).strip().lower().replace("-", "_")
        try:
            return cls(text)
        except ValueError as exc:
            raise ValueError(
                f"column role must be one of {[item.value for item in cls]}, got {value!r}"
            ) from exc

# Table-contract synthesis is model string work: the model names the tables,
# grains, and columns implied by the question. Coercion and the usable-schema
# decision remain deterministic. This untested call site stays on reasoning.
_TABLE_CONTRACT_SYNTHESIS_TIER = register_call_site_tier(
    "table-contract-synthesis",
    ModelTier.REASONING,
)

_TABLE_CONTRACT_SYSTEM_PROMPT = """You design explicit result-table contracts
for scientific evidence acquisition. Return one valid JSON object and no
markdown or prose. The contract must be generic to the supplied question and
must not invent results, sources, or domain facts."""


@dataclass(frozen=True)
class TableRef:
    """Stable address of one declared result table."""

    id: str
    name: str

    @classmethod
    def create(cls, name: str) -> "TableRef":
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("TableRef.name must be non-empty")
        return cls(
            id=stable_id({"version": TABLE_IDENTITY_VERSION, "name": normalized}),
            name=normalized,
        )


@dataclass(frozen=True)
class ColumnRef:
    """Stable address of one declared real result column."""

    id: str
    table_id: str
    table: str
    name: str

    @classmethod
    def create(cls, table: str | TableRef, name: str) -> "ColumnRef":
        table_ref = table if isinstance(table, TableRef) else TableRef.create(table)
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("ColumnRef.name must be non-empty")
        return cls(
            id=stable_id(
                {
                    "version": COLUMN_IDENTITY_VERSION,
                    "table_id": table_ref.id,
                    "name": normalized,
                }
            ),
            table_id=table_ref.id,
            table=table_ref.name,
            name=normalized,
        )


@dataclass(frozen=True)
class TableColumnSpec:
    name: str
    role: ColumnEvidenceRole = ColumnEvidenceRole.REPORTED
    #: One semantic result field. Reported and best-guess representations of
    #: the same value declare the same slot while remaining separate columns.
    value_slot: str = ""
    nullable: bool = True
    description: str = ""
    aliases: tuple[str, ...] = ()
    field_hints: tuple[str, ...] = ()
    #: The declared shape of this column's values, from a closed set:
    #: ``"" | number | integer | range | date | year | category | text``.
    #: ``""`` -- every column of every spec in this tree today -- declares
    #: nothing, and a consumer checking a value against a declared type reduces
    #: to checking that the value is non-empty and non-missing. So adding these
    #: fields changes no existing spec's meaning.
    value_type: str = ""
    #: A declared unit or scale token, e.g. ``km``, ``USD``, ``per_100k``.
    unit: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", ColumnEvidenceRole.coerce(self.role))
        object.__setattr__(
            self,
            "value_slot",
            str(self.value_slot or self.name).strip() or self.name,
        )
        if (
            self.role is ColumnEvidenceRole.BEST_GUESS
            and self.value_type not in {"number", "integer"}
        ):
            raise ValueError(
                f"best-guess column {self.name!r} must declare value_type "
                f"number or integer, got {self.value_type!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "role": self.role.value,
            "nullable": self.nullable,
        }
        if self.value_slot != self.name:
            out["value_slot"] = self.value_slot
        if self.description:
            out["description"] = self.description
        if self.aliases:
            out["aliases"] = list(self.aliases)
        if self.field_hints:
            out["field_hints"] = list(self.field_hints)
        # Conditionally, like the three above: an empty declaration emits no
        # key, so `pipeline._table_spec_id` hashes a byte-identical payload for
        # every spec in the tree and `_outcome_matches_current_table_spec` does
        # not start rejecting seeded outcomes.
        if self.value_type:
            out["value_type"] = self.value_type
        if self.unit:
            out["unit"] = self.unit
        return out


@dataclass(frozen=True)
class TableColdStartAnchorSpec:
    """One declared cross-table value that may seed an empty target table.

    The target column is a key column on the empty table.  The source table
    and column name where the value already exists.  This is acquisition
    metadata, not a join instruction: it tells the fill scheduler which
    already-observed value may appear in a search query while leaving every
    other target key unbound.
    """

    target_column: str
    source_table: str
    source_column: str

    def to_dict(self) -> dict[str, str]:
        return {
            "target_column": self.target_column,
            "source_table": self.source_table,
            "source_column": self.source_column,
        }


@dataclass(frozen=True)
class TableTargetSpec:
    name: str
    description: str = ""
    grain: str = ""
    deliverable: bool = True
    key_columns: tuple[str, ...] = ()
    #: The columns that identify a SUBJECT, as opposed to `key_columns`, which
    #: says which columns a row must fill to count as complete. The two were
    #: one field and the merge was silent: on the recorded corpus 135 of 303
    #: rows lack a canonical identity slot, so requiring identity for
    #: completeness moves 45% of the completeness accounting as a side effect of
    #: an identity fix. Separate fields keep the two changes separately
    #: attributable.
    subject_key_columns: tuple[str, ...] = ()
    columns: tuple[TableColumnSpec, ...] = ()
    cold_start_anchors: tuple[TableColdStartAnchorSpec, ...] = ()
    keep_existing_rows: bool = True

    def all_columns(self) -> tuple[TableColumnSpec, ...]:
        columns = {column.name: column for column in self.columns}
        for name in reversed(self.key_columns):
            if name in columns:
                column = columns[name]
                columns[name] = TableColumnSpec(
                    name=column.name,
                    role=column.role,
                    value_slot=column.value_slot,
                    nullable=False,
                    description=column.description,
                    aliases=column.aliases,
                    field_hints=column.field_hints,
                    # Carried, not dropped. This rebuild is what every reader of
                    # a key column sees -- including `to_dict`, which serializes
                    # through here -- so losing a declaration here would lose it
                    # from the round trip too, and in the permissive direction:
                    # an untyped subject-key column passes a non-triviality
                    # check a typed one would refuse.
                    value_type=column.value_type,
                    unit=column.unit,
                )
            else:
                columns[name] = TableColumnSpec(name=name, nullable=False)
        return tuple(columns.values())

    def required_columns(self) -> tuple[str, ...]:
        return tuple(
            _spec_unique(
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

    def best_guess_columns(self) -> tuple[TableColumnSpec, ...]:
        return tuple(
            column
            for column in self.all_columns()
            if column.role is ColumnEvidenceRole.BEST_GUESS
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
        if self.subject_key_columns:
            out["subject_key_columns"] = list(self.subject_key_columns)
        if self.cold_start_anchors:
            out["cold_start_anchors"] = [
                anchor.to_dict() for anchor in self.cold_start_anchors
            ]
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

    def column_yield_diagnostic(self) -> dict[str, Any]:
        """Why this spec did or did not produce a column schema.

        `is_empty` answers "does this spec hold any tables", which is NOT the
        same question as "does this spec yield any columns", and callers that
        guard on the first while needing the second cannot see the difference.
        Every column accessor on this class filters `if table.deliverable`, so
        a spec holding tables that are all non-deliverable returns `{}` from
        all of them while reporting `is_empty is False`.

        That is the shape a silent failure takes here: downstream receives an
        empty schema, treats it as "this table has no required columns", and
        certifies every row complete with no gaps. This method exists so the
        distinction is a fact a caller can read and emit rather than one it has
        to infer from an empty mapping.
        """

        names = sorted(self.tables)
        deliverable = sorted(self.deliverable_names())
        non_deliverable = [name for name in names if name not in set(deliverable)]
        required = self.required_columns_by_table()
        all_columns = self.all_columns_by_table()
        tables_without_required = sorted(
            name for name, columns in required.items() if not columns
        )
        if not names:
            status, reason = "no_tables", "the spec declares no tables"
        elif not deliverable:
            status, reason = (
                "no_deliverable_tables",
                "every declared table is marked deliverable: false, so every "
                "column accessor returns an empty mapping",
            )
        elif not any(all_columns.values()):
            status, reason = (
                "no_columns",
                "deliverable tables are declared but none of them declares a column",
            )
        elif not any(required.values()):
            status, reason = (
                "no_required_columns",
                "deliverable tables declare columns but none of them is "
                "required, so row completeness cannot be falsified",
            )
        else:
            status, reason = "ok", ""

        return {
            "status": status,
            "reason": reason,
            "usable_schema": status == "ok",
            "is_empty": self.is_empty,
            "table_count": len(names),
            "table_names": names,
            "deliverable_table_names": deliverable,
            "non_deliverable_table_names": non_deliverable,
            "tables_without_required_columns": tables_without_required,
            "required_column_counts": {
                name: len(columns) for name, columns in required.items()
            },
            "all_column_counts": {
                name: len(columns) for name, columns in all_columns.items()
            },
        }

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

    def all_columns_by_table(self) -> dict[str, list[str]]:
        return {
            name: [column.name for column in table.all_columns()]
            for name, table in self.tables.items()
            if table.deliverable
        }

    def key_columns_by_table(self) -> dict[str, list[str]]:
        return {
            name: list(table.key_columns)
            for name, table in self.tables.items()
            if table.deliverable
        }

    def cold_start_anchors_by_table(self) -> dict[str, list[dict[str, str]]]:
        return {
            name: [anchor.to_dict() for anchor in table.cold_start_anchors]
            for name, table in self.tables.items()
            if table.deliverable and table.cold_start_anchors
        }

    def best_guess_columns_by_table(self) -> dict[str, list[str]]:
        return {
            name: [column.name for column in table.best_guess_columns()]
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

#: Any artifact stem. Matches both this tree's Episode-labelled observed specs
#: (``<episode stem>_observed_table_spec.yaml``) and legacy round-numbered
#: ones, and reads NOTHING from the stem: round-numbered continuation
#: inference is deleted with the round concept, so "newest" is decided by
#: modification time alone, never by filename arithmetic.
_OBSERVED_TABLE_SPEC_RE = re.compile(
    r"^.+_observed_table_spec\.(?:ya?ml|json)$",
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


async def synthesize_table_spec(llm: Any, question: str) -> TableSpec:
    """Derive the table-fill contract from the question before acquisition."""

    prompt = f"""RESEARCH QUESTION:
{question}

Design the result table or tables needed to answer this question. This is the
contract against which every acquired source will be extracted, credited, and
counted, so declare the complete requested output now.

Rules:
- Prefer one deliverable table when one row grain can express the answer. Use
  multiple tables only when the question genuinely asks for different grains.
- Give every table a concise snake_case name, a precise row grain, and a short
  description.
- Declare every field requested by the question as a column. Mark requested
  answer fields nullable=false so missing evidence remains a visible deficit.
- key_columns identify a complete row. subject_key_columns identify the stable
  real-world subject whose evidence accumulates across sources; declare both
  explicitly and include every named key in columns.
- Preserve reported ranges, bounds, comparisons, and source wording in their
  reported columns. When an evidence-anchored numeric best guess would be a
  distinct useful output, add a separate real column with role="best_guess";
  never replace or relabel the reported column.
- Give every column a value_slot. Reported and best-guess columns representing
  the same semantic value MUST use the same value_slot. They are alternative
  evidence routes to one completeness and rarefaction target, not two targets.
- A best-guess column must have value_type="number" or "integer". It remains
  nullable=false when the question requires that estimate, so unsupported
  guesses remain missing rather than being fabricated. Never declare a
  best-guess date, year, text, category, or range column.
- value_type must be one of: number, integer, range, date, year, category, text.
  Use an empty unit when values may legitimately carry different units or
  scales; otherwise state the unit.
- aliases and field_hints should contain ordinary source-language labels that
  help extracted fields map to the declared column.
- Do not include workflow, scoring, search, provenance, or evidence-management
  columns. Provenance is carried separately by the evidence registry.
- Do not include migrations or any result rows.

Return exactly this JSON shape:
{{
  "version": 1,
  "tables": {{
    "table_name": {{
      "description": "what the table represents",
      "grain": "one row per ...",
      "deliverable": true,
      "key_columns": ["..."],
      "subject_key_columns": ["..."],
      "columns": {{
        "column_name": {{
          "role": "reported or best_guess",
          "value_slot": "shared semantic field name",
          "nullable": false,
          "description": "what belongs here",
          "aliases": ["source wording"],
          "field_hints": ["related source wording"],
          "value_type": "text",
          "unit": ""
        }}
      }},
      "keep_existing_rows": true
    }}
  }},
  "migrations": []
}}"""
    payload = await ask_json(
        llm,
        prompt,
        system_prompt=_TABLE_CONTRACT_SYSTEM_PROMPT,
        tier=_TABLE_CONTRACT_SYNTHESIS_TIER,
        call_site="table-contract-synthesis",
    )
    if not isinstance(payload, Mapping):
        raise ValueError("table-contract synthesis must return a JSON object")
    spec = _coerce_table_spec(payload)
    diagnostic = spec.column_yield_diagnostic()
    if not diagnostic["usable_schema"]:
        raise ValueError(
            "synthesized table contract is unusable: "
            f"{diagnostic['status']}: {diagnostic['reason']}"
        )
    for table in spec.tables.values():
        if table.deliverable and not table.subject_key_columns:
            raise ValueError(
                f"synthesized table {table.name!r} declares no subject_key_columns"
            )
        reported_slots = {
            column.value_slot
            for column in table.all_columns()
            if column.role is ColumnEvidenceRole.REPORTED
        }
        orphan_best_guesses = sorted(
            column.name
            for column in table.best_guess_columns()
            if column.value_slot not in reported_slots
        )
        if orphan_best_guesses:
            raise ValueError(
                f"synthesized table {table.name!r} has best-guess columns "
                "without a reported column in the same value_slot: "
                + ", ".join(orphan_best_guesses)
            )
    return spec


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
    explicit = load_table_spec(explicit_paths)
    base = _make_unrequested_seed_tables_non_deliverable(base, explicit)
    return merge_table_specs(
        base,
        explicit,
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


def _make_unrequested_seed_tables_non_deliverable(
    base: TableSpec,
    explicit: TableSpec,
) -> TableSpec:
    if explicit.is_empty or not explicit.tables:
        return base

    requested = {
        *explicit.tables,
        *(
            migration.to_table
            for migration in explicit.migrations
            if migration.to_table
        ),
    }
    tables = {
        name: (
            table
            if name in requested or not table.deliverable
            else TableTargetSpec(
                name=table.name,
                description=table.description,
                grain=table.grain,
                deliverable=False,
                key_columns=table.key_columns,
                subject_key_columns=table.subject_key_columns,
                columns=table.columns,
                cold_start_anchors=table.cold_start_anchors,
                keep_existing_rows=table.keep_existing_rows,
            )
        )
        for name, table in base.tables.items()
    }
    return TableSpec(tables=tables, migrations=base.migrations)


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



def declared_subject_identity(
    key_columns: Iterable[Any] | None,
    columns: Iterable[Any] | None,
) -> tuple[str, ...]:
    """The subject identity this table declares, in one fixed resolution order.

    1. What the spec's author declared, restricted to columns the table carries.
    2. The canonical identity slots the table's own column vocabulary supports.
    3. Nothing -- an honest refusal, not a gap to fill.

    Deterministic in its inputs and in nothing else. Rounds 0, 1 and 2 of one
    run see the same column vocabulary and mint the byte-identical declaration,
    however the planner rewords the table between them.

    **Never mints over model-emitted text.** Step 2's slot names are code
    literals cited from `docs/RUNTIME_INVARIANTS.md`; only their presence is
    observed. A declaration derived from a planner's `key_columns` prose drifts
    every round, and a durable id over a drifting declaration manufactures the
    appearance of accumulated evidence -- a posterior reading it reports
    tightening intervals over what is really one observation per cell.

    **Never mints a column the table does not carry.** That is the shortcut
    satisfying every recurrence check at once: no row populates the key, every
    subject is unbound under one shared empty value, and the table collapses
    into a single cell with enormous n.
    """

    names = [str(name) for name in (columns or ())]
    present = set(names)
    declared = tuple(_clean_list(key_columns))
    if declared:
        return tuple(column for column in declared if column in present)
    return canonical_subject_identity(names)


def dump_table_spec_yaml(spec: TableSpec | Mapping[str, Any]) -> str:
    payload = spec.to_dict() if isinstance(spec, TableSpec) else dict(spec)
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)


def observed_table_spec(
    rows_by_name: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    base: TableSpec | None = None,
    table_names: Iterable[str] | None = None,
    declared_names: Iterable[str] | None = None,
) -> TableSpec:
    """Build an editable spec from declared tables plus observed row columns.

    ``declared_names`` is the set of tables the run actually asked for. When it
    is supplied, a table that appears only because it was *observed* is written
    as ``deliverable: false``: having been materialized is not a claim to being
    an answer. A traversal leaves working variables behind, and promoting those
    to deliverables puts intermediate scratch on the scoring surface, where it
    reads as a much larger yield than the run really produced.

    Omitting ``declared_names`` keeps the older, permissive behaviour, for
    callers -- seeding from a previous run's exports -- that have no separate
    notion of what was declared and would otherwise mark everything false.
    """

    base = base or TableSpec()
    declared = {str(name) for name in (declared_names or ()) if str(name).strip()}
    restrict = declared_names is not None
    names = list(
        _spec_unique(
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
            for column in _spec_observed_columns(rows_by_name.get(name, ()))
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
            deliverable=(
                base_table.deliverable
                if base_table is not None
                else (name in declared if restrict else True)
            ),
            key_columns=base_table.key_columns if base_table else (),
            subject_key_columns=declared_subject_identity(
                (base_table.subject_key_columns or base_table.key_columns)
                if base_table
                else (),
                [column.name for column in columns],
            ),
            columns=columns,
            cold_start_anchors=(
                base_table.cold_start_anchors if base_table else ()
            ),
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
            for path in root.glob("*_observed_table_spec.*")
            if _OBSERVED_TABLE_SPEC_RE.match(path.name)
        },
        key=_observed_table_spec_sort_key,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _observed_table_spec_sort_key(path: Path) -> tuple[int, str]:
    """Newest by modification time; the stem breaks exact ties only.

    Deliberately reads no number out of the filename: a stem is Episode
    identity or a named pass, and filename arithmetic over it is the
    round-continuation inference this build deleted.
    """

    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    return mtime_ns, path.name


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
    cold_start_anchors = _coerce_cold_start_anchors(
        raw.get("cold_start_anchors")
    )
    invalid_anchor_columns = sorted(
        {
            anchor.target_column
            for anchor in cold_start_anchors
            if anchor.target_column not in set(key_columns)
        }
    )
    if invalid_anchor_columns:
        raise ValueError(
            f"table {name!r} cold_start_anchors target non-key column(s): "
            + ", ".join(invalid_anchor_columns)
        )
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
        subject_key_columns=declared_subject_identity(
            raw.get("subject_key_columns") or key_columns,
            [column.name for column in columns],
        ),
        columns=columns,
        cold_start_anchors=cold_start_anchors,
        keep_existing_rows=bool(raw.get("keep_existing_rows", True)),
    )


def _coerce_cold_start_anchors(
    raw: Any,
) -> tuple[TableColdStartAnchorSpec, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("cold_start_anchors must be a list")

    anchors: list[TableColdStartAnchorSpec] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"cold_start_anchors[{index}] must be a mapping"
            )
        target_column = str(item.get("target_column") or "").strip()
        source_table = str(item.get("source_table") or "").strip()
        source_column = str(item.get("source_column") or "").strip()
        if not target_column or not source_table or not source_column:
            raise ValueError(
                f"cold_start_anchors[{index}] requires target_column, "
                "source_table, and source_column"
            )
        anchors.append(
            TableColdStartAnchorSpec(
                target_column=target_column,
                source_table=source_table,
                source_column=source_column,
            )
        )
    return tuple(anchors)


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
        role=ColumnEvidenceRole.coerce(raw.get("role")),
        value_slot=str(raw.get("value_slot") or name).strip(),
        nullable=not bool(raw.get("required", False))
        if "nullable" not in raw
        else bool(raw.get("nullable")),
        description=str(raw.get("description") or "").strip(),
        aliases=tuple(_clean_list(raw.get("aliases"))),
        field_hints=tuple(_clean_list(raw.get("field_hints"))),
        # Read back, or a YAML-declared type is silently dropped at load and the
        # non-triviality rule that reads it quietly reduces to "non-empty".
        value_type=_coerce_value_type(raw.get("value_type")),
        unit=str(raw.get("unit") or "").strip(),
    )


#: The closed set a declared `value_type` may name. A member outside it is a
#: declaration this build cannot check, so it is refused at load rather than
#: carried into a checker that would silently pass everything.
VALUE_TYPES = (
    "number",
    "integer",
    "range",
    "date",
    "year",
    "category",
    "text",
)


def _coerce_value_type(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    if text not in VALUE_TYPES:
        raise ValueError(
            f"value_type {text!r} is not one of {VALUE_TYPES}; a type this "
            f"build cannot check is refused rather than carried"
        )
    return text


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
    """First declaration of a column wins, with one additive exception.

    ``observed_table_spec`` feeds this the base spec's columns followed by bare
    ``TableColumnSpec(name=...)`` objects minted from observed row keys, so
    first-wins is what preserves a declaration against an observation. The
    exception runs the other way and only for the two declared-shape fields: a
    kept column that declares neither ``value_type`` nor ``unit`` takes them
    from a later duplicate that does. Without it, a bare observed column
    arriving first -- which the ordering makes unlikely but not impossible for
    callers that build their own list -- would silently erase a declaration, and
    the loss would run in the permissive direction.
    """

    merged: dict[str, TableColumnSpec] = {}
    for column in columns:
        if not column.name:
            continue
        kept = merged.get(column.name)
        if kept is None:
            merged[column.name] = column
            continue
        if (column.value_type or column.unit) and not (kept.value_type or kept.unit):
            merged[column.name] = replace(
                kept,
                value_type=column.value_type,
                unit=column.unit,
            )
    return tuple(merged.values())


def _spec_observed_columns(rows: Iterable[Mapping[str, Any]]) -> list[str]:
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
        for value in _spec_unique(str(value or "").strip() for value in values)
        if value
    ]


def _spec_unique(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


# ============================================================================
# derived_context.py
# ============================================================================

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


DERIVED_CONTEXT_COLUMNS = [
    "source_ids",
    "best_guess_context",
]

_DERIVED_MISSING_STRINGS = {
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

_CONTEXT_FIELD_SKIP_TOKENS = {
    "basis",
    "chunk",
    "chunks",
    "confidence",
    "description",
    "evidence",
    "gap",
    "id",
    "index",
    "key",
    "note",
    "path",
    "query",
    "ref",
    "refs",
    "result",
    "source",
    "status",
    "summary",
    "task",
    "url",
}
_FIELD_HINT_FILLER_TOKENS = {
    "field",
    "label",
    "name",
    "type",
    "value",
    "values",
}

_DERIVED_UUID_CHUNK_RE = re.compile(r"^(?P<source_id>.+)_chunk_\d+$")


@dataclass(frozen=True)
class ContextSlot:
    name: str
    field_hints: tuple[str, ...]
    source_field_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ContextHit:
    field: str
    value: str
    basis: str
    confidence: float


def infer_best_guess_context(
    row: Mapping[str, Any],
    *,
    context_slots: Iterable[ContextSlot | Mapping[str, Any] | str] | None = None,
    source_records: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Infer requested context slots from a table row and source sidecars."""

    if not isinstance(row, Mapping):
        row = {}

    slots = normalize_context_slots(context_slots)
    source_ids = source_ids_from_row(row)
    source_records = source_records or {}
    return {
        "source_ids": source_ids,
        "best_guess_context": {
            slot.name: hit_to_dict(hit)
            for slot in slots
            for hit in [_infer_slot(row, slot, source_ids, source_records)]
            if hit is not None
        },
    }


def hit_to_dict(hit: _ContextHit) -> dict[str, Any]:
    return {
        "value": hit.value,
        "field": hit.field,
        "basis": hit.basis,
        "confidence": round(hit.confidence, 3),
    }


def normalize_context_slots(
    slots: Iterable[ContextSlot | Mapping[str, Any] | str] | None,
) -> list[ContextSlot]:
    """Normalize configured slot specs into stable field-matching rules."""

    normalized: list[ContextSlot] = []
    seen: set[str] = set()
    for raw in slots or []:
        slot = _coerce_context_slot(raw)
        if slot is None or slot.name in seen:
            continue
        seen.add(slot.name)
        normalized.append(slot)
    return normalized


def source_ids_from_row(row: Mapping[str, Any]) -> list[str]:
    """Return canonical source ids from row source_refs/source_chunks fields."""

    values: list[Any] = []
    for field in ("source_refs", "source_chunks", "source_chunk"):
        values.extend(_derived_as_source_list(row.get(field)))

    ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in re.split(r"[,;\s]+", str(value or "")):
            source_id = _canonical_source_id(part)
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            ids.append(source_id)
    return ids


def normalize_source_records(
    records: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]] | None,
) -> dict[str, Mapping[str, Any]]:
    """Normalize source metadata into an id-keyed mapping."""

    if records is None:
        return {}

    if isinstance(records, Mapping):
        items: Iterable[Any] = records.items()
    else:
        items = (
            (record.get("id"), record)
            for record in records
            if isinstance(record, Mapping)
        )

    normalized: dict[str, Mapping[str, Any]] = {}
    for key, record in items:
        if not isinstance(record, Mapping):
            continue
        source_id = _canonical_source_id(key or record.get("id"))
        if source_id:
            normalized[source_id] = record
    return normalized


def context_slots_from_count_targets(
    count_targets: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build context slots from executable target key columns."""

    slots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in count_targets:
        if not isinstance(target, Mapping):
            continue
        for column in _derived_as_list(target.get("key_columns")):
            name = str(column or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            slots.append({"name": name, "field_hints": [name]})
    return slots


def _coerce_context_slot(raw: Mapping[str, Any] | str) -> ContextSlot | None:
    if isinstance(raw, ContextSlot):
        return raw
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, Mapping):
        return None

    name = _derived_clean_field_name(raw.get("name") or raw.get("key") or "")
    if not name:
        return None

    field_hints = tuple(
        _derived_unique(
            str(value).strip()
            for value in [
                name,
                *_derived_as_list(raw.get("field_hints")),
                *_derived_as_list(raw.get("fields")),
                *_derived_as_list(raw.get("columns")),
            ]
            if str(value or "").strip()
        )
    )
    source_field_hints = tuple(
        _derived_unique(
            str(value).strip()
            for value in _derived_as_list(raw.get("source_field_hints"))
            if str(value or "").strip()
        )
    )
    return ContextSlot(
        name=name,
        field_hints=field_hints or (name,),
        source_field_hints=source_field_hints,
    )


def _infer_slot(
    row: Mapping[str, Any],
    slot: ContextSlot,
    source_ids: list[str],
    source_records: Mapping[str, Mapping[str, Any]],
) -> _ContextHit | None:
    hits = [
        hit
        for field, value in _derived_flatten(row)
        for hit in [_row_slot_hit(field, value, slot)]
        if hit is not None
    ]
    if hits:
        return sorted(hits, key=lambda item: (-item.confidence, item.field))[0]

    if len(source_ids) != 1 or not slot.source_field_hints:
        return None
    source = source_records.get(source_ids[0])
    if source is None:
        return None

    source_hits = [
        hit
        for field, value in _derived_flatten(source, max_depth=2)
        for hit in [_source_slot_hit(field, value, slot)]
        if hit is not None
    ]
    if not source_hits:
        return None
    return sorted(source_hits, key=lambda item: (-item.confidence, item.field))[0]


def _row_slot_hit(field: str, value: Any, slot: ContextSlot) -> _ContextHit | None:
    if _derived_field_should_skip(field):
        return None
    text = _clean_text(value, max_length=240)
    if not text:
        return None

    score = _field_hint_score(field, slot.field_hints)
    if score <= 0:
        return None
    return _ContextHit(
        field=field,
        value=text,
        basis="row field",
        confidence=score,
    )


def _source_slot_hit(field: str, value: Any, slot: ContextSlot) -> _ContextHit | None:
    text = _clean_text(value, max_length=240, require_alpha=False)
    if not text:
        return None

    score = _field_hint_score(field, slot.source_field_hints)
    if score <= 0:
        return None
    return _ContextHit(
        field=f"source.{field}",
        value=text,
        basis="source metadata field",
        confidence=min(0.6, score),
    )


def _field_hint_score(field: str, hints: Iterable[str]) -> float:
    field_key = _derived_clean_field_name(field)
    field_tokens = _meaningful_field_tokens(field_key)
    best = 0.0
    for hint in hints:
        hint_key = _derived_clean_field_name(hint)
        if not hint_key:
            continue
        if field_key == hint_key:
            best = max(best, 0.95)
            continue
        if field_key.endswith(f".{hint_key}"):
            best = max(best, 0.9)
            continue
        hint_tokens = _meaningful_field_tokens(hint_key)
        if not hint_tokens:
            continue
        if hint_tokens <= field_tokens:
            best = max(best, 0.8)
        elif field_tokens <= hint_tokens:
            best = max(best, 0.65)
    return best


def _derived_flatten(
    value: Mapping[str, Any],
    *,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 2,
) -> Iterable[tuple[str, Any]]:
    for key, inner in value.items():
        field = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(inner, Mapping) and depth < max_depth:
            yield from _derived_flatten(inner, prefix=field, depth=depth + 1, max_depth=max_depth)
        else:
            yield field, inner


def _derived_field_should_skip(field: str) -> bool:
    field = str(field or "")
    return field.startswith("_") or bool(
        _derived_field_tokens(field) & _CONTEXT_FIELD_SKIP_TOKENS
    )


def _derived_field_tokens(field: str) -> set[str]:
    field = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(field))
    return {
        token
        for token in re.split(r"[^A-Za-z0-9]+", field.lower())
        if token
    }


def _meaningful_field_tokens(field: str) -> set[str]:
    tokens = _derived_field_tokens(field)
    meaningful = tokens - _FIELD_HINT_FILLER_TOKENS
    return meaningful or tokens


def _derived_clean_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9_.]+", "_", str(value or "").lower()).strip("_.")


def _clean_text(
    value: Any,
    *,
    max_length: int,
    require_alpha: bool = True,
) -> str:
    if _derived_missing(value):
        return ""
    if isinstance(value, (list, tuple, set)):
        value = "; ".join(str(item) for item in value if not _derived_missing(item))
    elif isinstance(value, Mapping):
        value = "; ".join(
            f"{key}: {inner}"
            for key, inner in value.items()
            if not _derived_missing(inner)
        )
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text or len(text) > max_length:
        return ""
    if require_alpha and not re.search(r"[A-Za-z]", text):
        return ""
    return text


def _canonical_source_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _DERIVED_UUID_CHUNK_RE.match(text)
    if match is not None:
        return match.group("source_id")
    return text


def _derived_as_list(values: Any) -> list[Any]:
    if _derived_missing(values):
        return []
    if isinstance(values, list):
        return values
    if isinstance(values, (tuple, set)):
        return list(values)
    return [values]


def _derived_as_source_list(values: Any) -> list[Any]:
    if _derived_missing(values):
        return []
    if isinstance(values, str):
        try:
            parsed = json.loads(values)
        except json.JSONDecodeError:
            return [
                value.strip(" \t\r\n\"'[]")
                for value in re.split(r"[,;\s]+", values)
            ]
        return _derived_as_source_list(parsed)
    return _derived_as_list(values)


def _derived_unique(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _derived_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _DERIVED_MISSING_STRINGS
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


# ============================================================================
# criteria.py
# ============================================================================

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from question_pipeline.utilities.acquisition import canonical_subject_identity, stable_id
from question_pipeline.utilities.evidence import is_provenance_name



#: v3 changed the criterion field set and historical provenance metadata.
#: Field-provenance promotion was retired by v6 and is not producible now.
#: v4: engine-minted structural columns (`occurrence_count`, `items`,
#: `item_ids`, `row_count`, `contributing_rows`) stopped projecting as
#: criteria. Excluding columns changes WHICH criteria exist, hence criterion
#: ids, hence every downstream join -- so this is a projection-version change
#: even though no reward formula moved. `reward.py` records that criterion ids
#: do not join across projection versions; that is exactly what this protects.
#: v5: `_MISSING_STRINGS` gained "not specified in current evidence" -- the
#: token `goals`, `pipeline` and this module's own table writer already treat as
#: absence -- so that one module owns what "nothing here" means. This is a
#: PROJECTION-VERSION change, not a cleanup, because `_missing` gates
#: `_subject_key_values` (:861) and `_row_content` (:965) as well as
#: `_project_field` (:1059): a row whose declared key column carries the token
#: stops contributing that pair, `bound` flips, and `_subject_for_row` hashes
#: both into the subject id. So the change moves WHICH SUBJECTS EXIST, hence
#: criterion ids, hence every downstream join. v4 and v5 criterion, subject,
#: snapshot and transition ids DO NOT JOIN. The honest direction is "different
#: criteria, not fewer": for a criterion whose id does not move a cell carrying
#: the token drops from SUPPORTED to UNRESOLVED, but where the token sits in a
#: declared subject-key column the subject is re-keyed and its criteria are
#: removed and re-minted -- and a re-minted criterion is `SUPPORT_GAINED`, which
#: `reward.CreditLedger` cannot suppress because it dedupes by criterion id.
#: v6 makes the durable registry's resolved direct-assertion chain the sole
#: supported basis. Raw values, provenance annotations, and best guesses remain
#: noncrediting inputs.
CRITERIA_PROJECTION_VERSION = "criteria_projection_v6"
CRITERIA_SNAPSHOT_VERSION = "criteria_snapshot_v1"
CRITERIA_TRANSITION_VERSION = "criteria_transition_v1"

#: Longest display form retained for one observed value.
MAX_VALUE_LENGTH = 240


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class CriterionStatus(str, Enum):
    """Whether a criterion is established by the rows it was projected from.

    Only two members.  ``conflicting`` is deliberately absent -- see the module
    docstring; multiplicity is carried on :attr:`CriterionState.values` instead
    of being labelled with a semantics the rows do not support.
    """

    SUPPORTED = "supported"
    UNRESOLVED = "unresolved"


class EvidenceBasis(str, Enum):
    """How a criterion's state was established, as an explicit claim.

    The member is a statement about the join that was actually performed.
    Nothing here may be emitted for a join the projection did not do.
    """

    #: A direct assertion resolves through its deterministic acceptance, exact
    #: span/chunk, content-addressed source version, and source document/blob.
    RESOLVED_ASSERTION_CHAIN = "resolved_assertion_chain"

    # Historical serialized vocabulary. Current projection cannot produce
    # these members; PRODUCIBLE_EVIDENCE_BASES is the closed live boundary.
    FIELD_REF_ACCEPTED = "field_ref_accepted"
    FIELD_REF_UNMATCHED = "field_ref_unmatched"
    FIELD_REF_UNCHECKED = "field_ref_unchecked"
    ROW_REF_ACCEPTED = "row_ref_accepted"
    ROW_REF_UNMATCHED = "row_ref_unmatched"
    ROW_REF_UNCHECKED = "row_ref_unchecked"
    ROW_VALUE_ONLY = "row_value_only"
    JUDGED_BEST_GUESS_ACCEPTED = "judged_best_guess_accepted"
    JUDGED_BEST_GUESS_UNMATCHED = "judged_best_guess_unmatched"
    JUDGED_BEST_GUESS_UNCHECKED = "judged_best_guess_unchecked"

    #: No support.  Carried by every unresolved state.
    NONE = "none"


#: Compatibility metadata for historical serialized bases. Live admission is
#: the closed PRODUCIBLE_EVIDENCE_BASES set, never a threshold over this map.
BASIS_STRENGTH: Mapping[EvidenceBasis, int] = {
    EvidenceBasis.NONE: 0,
    EvidenceBasis.ROW_VALUE_ONLY: 1,
    EvidenceBasis.ROW_REF_UNMATCHED: 2,
    EvidenceBasis.ROW_REF_UNCHECKED: 3,
    EvidenceBasis.ROW_REF_ACCEPTED: 4,
    EvidenceBasis.FIELD_REF_UNMATCHED: 5,
    EvidenceBasis.JUDGED_BEST_GUESS_UNMATCHED: 5,
    EvidenceBasis.FIELD_REF_UNCHECKED: 6,
    EvidenceBasis.JUDGED_BEST_GUESS_UNCHECKED: 6,
    EvidenceBasis.FIELD_REF_ACCEPTED: 7,
    EvidenceBasis.JUDGED_BEST_GUESS_ACCEPTED: 7,
    EvidenceBasis.RESOLVED_ASSERTION_CHAIN: 8,
}

#: The bases this projection version can actually emit.  Anything outside this
#: set appearing on a state produced here is a defect, not a stronger claim.
PRODUCIBLE_EVIDENCE_BASES = frozenset(
    (EvidenceBasis.NONE, EvidenceBasis.RESOLVED_ASSERTION_CHAIN)
)


class TransitionKind(str, Enum):
    """What changed for one criterion between two snapshots."""

    #: Absent or unresolved before, supported after.  This is the transition
    #: reward is credited against.
    SUPPORT_GAINED = "support_gained"

    #: Supported before, unresolved or absent after.
    SUPPORT_LOST = "support_lost"

    #: Supported on both sides, on a different evidence basis.
    BASIS_CHANGED = "basis_changed"

    #: Same status and basis, different values or sources.
    EVIDENCE_CHANGED = "evidence_changed"

    #: The criterion did not exist before and is unresolved now.
    CRITERION_ADDED = "criterion_added"

    #: The criterion existed unresolved and is gone now.
    CRITERION_REMOVED = "criterion_removed"


# ---------------------------------------------------------------------------
# Refs and state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionRef:
    """One criterion, identified rather than described.

    ``id`` is derived from the table, the semantic subject key, and the field,
    and from nothing else.  ``subject_bound`` says whether the subject was
    addressable through declared key columns or canonical identity slots; an
    unbound subject falls back to row content and its ID is **not** stable
    across rounds by construction, which is why the flag travels with the ref
    rather than being inferred later.
    """

    id: str
    table: str
    field: str
    subject_id: str
    subject_key: tuple[tuple[str, str], ...] = ()
    identity_fields: tuple[str, ...] = ()
    subject_bound: bool = False

    @classmethod
    def create(
        cls,
        *,
        table: str,
        field: str,
        subject_id: str,
        subject_key: Sequence[tuple[str, str]] = (),
        identity_fields: Sequence[str] = (),
        subject_bound: bool = False,
    ) -> "CriterionRef":
        table = _text(table)
        field = _text(field)
        subject_id = _text(subject_id)
        criterion_id = stable_id(
            {
                "version": CRITERIA_PROJECTION_VERSION,
                "table": table,
                "subject_id": subject_id,
                "field": field,
            }
        )
        return cls(
            id=criterion_id,
            table=table,
            field=field,
            subject_id=subject_id,
            subject_key=tuple((str(name), str(value)) for name, value in subject_key),
            identity_fields=tuple(str(name) for name in identity_fields),
            subject_bound=bool(subject_bound),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.id,
            "table": self.table,
            "field": self.field,
            "subject_id": self.subject_id,
            "subject_key": [list(pair) for pair in self.subject_key],
            "identity_fields": list(self.identity_fields),
            "subject_bound": self.subject_bound,
        }


@dataclass(frozen=True)
class SubjectRef:
    """Stable typed identity of one projected table subject."""

    id: str
    table: str
    key: tuple[tuple[str, str], ...]
    identity_fields: tuple[str, ...]
    bound: bool


@dataclass(frozen=True)
class CriterionState:
    """One criterion's status, with the basis on which it was established.

    A supported state carries the registry-resolved source, source-version,
    span, assertion, and acceptance identifiers for its accepted value.

    ``subject_source_ids`` is every source referenced anywhere on the subject's
    rows. It is noncrediting co-location context for inspection.
    """

    ref: CriterionRef
    status: CriterionStatus
    basis: EvidenceBasis
    values: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    subject_source_ids: tuple[str, ...] = ()
    assertion_ids: tuple[str, ...] = ()
    acceptance_ids: tuple[str, ...] = ()
    source_version_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is CriterionStatus.UNRESOLVED:
            if self.basis is not EvidenceBasis.NONE:
                raise ValueError("an unresolved criterion has no evidence basis")
            if self.values:
                raise ValueError("an unresolved criterion carries no value")
        elif self.basis is EvidenceBasis.NONE:
            raise ValueError("a supported criterion must name its evidence basis")
        if self.basis not in PRODUCIBLE_EVIDENCE_BASES:
            raise ValueError(
                f"{self.basis.value} is not producible by "
                f"{CRITERIA_PROJECTION_VERSION}; a state must never claim a "
                "join the projection did not perform"
            )

    @property
    def criterion_id(self) -> str:
        return self.ref.id

    @property
    def supported(self) -> bool:
        return self.status is CriterionStatus.SUPPORTED

    @property
    def basis_strength(self) -> int:
        return BASIS_STRENGTH[self.basis]

    def identity(self) -> dict[str, Any]:
        """The content that makes this state this state.

        Everything an equal pair of states must agree on, and nothing else.
        Two projections producing the same evidence for the same criteria
        therefore produce one snapshot ID.
        """

        return {
            "criterion_id": self.ref.id,
            "status": self.status.value,
            "basis": self.basis.value,
            "values": list(self.values),
            "source_ids": list(self.source_ids),
            "subject_source_ids": list(self.subject_source_ids),
            "assertion_ids": list(self.assertion_ids),
            "acceptance_ids": list(self.acceptance_ids),
            "source_version_ids": list(self.source_version_ids),
            "span_ids": list(self.span_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.ref.to_dict(),
            "status": self.status.value,
            "evidence_basis": self.basis.value,
            "evidence_basis_strength": self.basis_strength,
            "values": list(self.values),
            "source_ids": list(self.source_ids),
            "subject_source_ids": list(self.subject_source_ids),
            "assertion_ids": list(self.assertion_ids),
            "acceptance_ids": list(self.acceptance_ids),
            "source_version_ids": list(self.source_version_ids),
            "span_ids": list(self.span_ids),
        }


@dataclass(frozen=True)
class CriteriaSnapshot:
    """Every criterion's state at one point in a run.

    ``id`` is content-addressed over the states alone.  It carries no round
    index and no timestamp, so two rounds whose evidence is identical produce
    one snapshot ID -- which is what makes "nothing changed" observable as an
    identity rather than as an empty diff of two distinct IDs.
    """

    id: str
    version: str
    states: tuple[CriterionState, ...]

    @classmethod
    def create(cls, states: Iterable[CriterionState]) -> "CriteriaSnapshot":
        ordered = tuple(sorted(states, key=lambda state: state.ref.id))
        snapshot_id = stable_id(
            {
                "version": CRITERIA_SNAPSHOT_VERSION,
                "states": [state.identity() for state in ordered],
            }
        )
        return cls(id=snapshot_id, version=CRITERIA_SNAPSHOT_VERSION, states=ordered)

    @property
    def supported(self) -> tuple[CriterionState, ...]:
        return tuple(state for state in self.states if state.supported)

    @property
    def unresolved(self) -> tuple[CriterionState, ...]:
        return tuple(state for state in self.states if not state.supported)

    @property
    def supported_ids(self) -> frozenset[str]:
        return frozenset(state.ref.id for state in self.supported)

    @property
    def unresolved_ids(self) -> frozenset[str]:
        return frozenset(state.ref.id for state in self.unresolved)

    def by_criterion(self) -> dict[str, CriterionState]:
        return {state.ref.id: state for state in self.states}

    def state(self, criterion_id: str) -> CriterionState | None:
        for state in self.states:
            if state.ref.id == criterion_id:
                return state
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_snapshot_id": self.id,
            "criteria_snapshot_version": self.version,
            "criteria_projection_version": CRITERIA_PROJECTION_VERSION,
            "criterion_count": len(self.states),
            "supported_criterion_ids": sorted(self.supported_ids),
            "unresolved_criterion_ids": sorted(self.unresolved_ids),
            "states": [state.to_dict() for state in self.states],
        }


@dataclass(frozen=True)
class CriterionTransition:
    """One criterion's change between two snapshots.

    Carries the criterion ID and **both** snapshot IDs, so a reward credited
    against a transition can be traced back to the exact pair of projections it
    was computed from, and so an attribution join never has to guess which
    snapshot a transition belonged to.
    """

    id: str
    criterion_id: str
    kind: TransitionKind
    before_snapshot_id: str
    after_snapshot_id: str
    table: str = ""
    field: str = ""
    subject_id: str = ""
    before_status: str = ""
    after_status: str = ""
    before_basis: str = ""
    after_basis: str = ""
    gained_source_ids: tuple[str, ...] = ()
    after_source_ids: tuple[str, ...] = ()

    @property
    def is_support_gained(self) -> bool:
        return self.kind is TransitionKind.SUPPORT_GAINED

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_transition_id": self.id,
            "criteria_transition_version": CRITERIA_TRANSITION_VERSION,
            "criterion_id": self.criterion_id,
            "kind": self.kind.value,
            "before_criteria_snapshot_id": self.before_snapshot_id,
            "after_criteria_snapshot_id": self.after_snapshot_id,
            "table": self.table,
            "field": self.field,
            "subject_id": self.subject_id,
            "before_status": self.before_status,
            "after_status": self.after_status,
            "before_evidence_basis": self.before_basis,
            "after_evidence_basis": self.after_basis,
            "gained_source_ids": list(self.gained_source_ids),
            "after_source_ids": list(self.after_source_ids),
        }


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def empty_snapshot() -> CriteriaSnapshot:
    """The snapshot of a run that has projected nothing yet."""

    return CriteriaSnapshot.create(())


def project_rows(
    rows: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    specs: Any = None,
    *,
    accepted_source_ids: Iterable[str] | None = None,
    best_guess_resolutions: Iterable[Mapping[str, Any]] | None = None,
    deliverable_tables: Iterable[str] | None = None,
    evidence_registry: Any = None,
) -> CriteriaSnapshot:
    """Project table rows onto per-criterion state.

    ``rows`` maps a table name to its rows.  ``specs`` is anything exposing a
    ``tables`` mapping of table-spec-shaped entries -- a ``TableSpec`` object,
    its ``to_dict()`` payload, or a hand-built dict -- and may be omitted, in
    which case the criteria set is the union of value-bearing columns observed
    on that table's rows and identity falls back to canonical slots.

    ``evidence_registry`` is the authority for support. A populated row value
    remains unresolved unless its criterion ID and normalized value resolve
    through a complete accepted registry chain.

    ``deliverable_tables``, when supplied, is the **explicit allowlist** of
    tables that project at all. The spec guard defaults open, so callers that
    exclude working tables name the deliverable set explicitly.

    ``accepted_source_ids`` and ``best_guess_resolutions`` remain accepted as
    historical artifact inputs. They do not establish criterion support.
    """

    accepted = _accepted_ids(accepted_source_ids)
    checked = accepted is not None
    tables = _spec_tables(specs)
    allowlist = _names(deliverable_tables) if deliverable_tables is not None else None
    guesses = _judged_best_guesses(best_guess_resolutions)

    states: list[CriterionState] = []
    for table in sorted(_row_tables(rows)):
        if allowlist is not None and table not in allowlist:
            continue
        # Preserve raw positions for stable artifact addressing.
        indexed_rows = [
            (index, row)
            for index, row in enumerate((rows or {}).get(table) or ())
            if isinstance(row, Mapping)
        ]
        table_rows = [row for _, row in indexed_rows]
        spec = tables.get(table)
        if spec is not None and not spec.deliverable:
            continue
        identity_fields = _identity_fields(spec, table_rows)
        fields = _criteria_fields(spec, table_rows, identity_fields)
        if not fields:
            continue
        table_guesses = guesses.get(table, {})
        for subject in _subjects(table, indexed_rows, identity_fields):
            subject_sources = _subject_source_ids(subject.rows)
            for name in fields:
                states.append(
                    _project_field(
                        table=table,
                        field=name,
                        subject=subject,
                        subject_sources=subject_sources,
                        accepted=accepted,
                        checked=checked,
                        guesses=[
                            guess
                            for index in subject.row_indices
                            for guess in table_guesses.get((index, name), ())
                        ],
                        evidence_registry=evidence_registry,
                    )
                )
    return CriteriaSnapshot.create(states)


def diff_snapshots(
    before: CriteriaSnapshot | None,
    after: CriteriaSnapshot | None,
) -> list[CriterionTransition]:
    """Every criterion that changed between two snapshots.

    A criterion whose state is byte-identical on both sides produces no
    transition; there is nothing to credit and nothing to explain.
    """

    before = before if before is not None else empty_snapshot()
    after = after if after is not None else empty_snapshot()
    before_states = before.by_criterion()
    after_states = after.by_criterion()

    transitions: list[CriterionTransition] = []
    for criterion_id in sorted(set(before_states) | set(after_states)):
        old = before_states.get(criterion_id)
        new = after_states.get(criterion_id)
        kind = _transition_kind(old, new)
        if kind is None:
            continue
        ref = (new or old).ref  # type: ignore[union-attr]
        old_sources = set(old.source_ids) if old is not None else set()
        new_sources = tuple(new.source_ids) if new is not None else ()
        transitions.append(
            CriterionTransition(
                id=stable_id(
                    {
                        "version": CRITERIA_TRANSITION_VERSION,
                        "criterion_id": criterion_id,
                        "before_snapshot_id": before.id,
                        "after_snapshot_id": after.id,
                        "kind": kind.value,
                    }
                ),
                criterion_id=criterion_id,
                kind=kind,
                before_snapshot_id=before.id,
                after_snapshot_id=after.id,
                table=ref.table,
                field=ref.field,
                subject_id=ref.subject_id,
                before_status=old.status.value if old is not None else "",
                after_status=new.status.value if new is not None else "",
                before_basis=old.basis.value if old is not None else "",
                after_basis=new.basis.value if new is not None else "",
                gained_source_ids=tuple(
                    source for source in new_sources if source not in old_sources
                ),
                after_source_ids=new_sources,
            )
        )
    return transitions


def _transition_kind(
    before: CriterionState | None,
    after: CriterionState | None,
) -> TransitionKind | None:
    if before is None and after is None:
        return None
    if after is not None and after.supported:
        if before is None or not before.supported:
            return TransitionKind.SUPPORT_GAINED
        if before.basis is not after.basis:
            return TransitionKind.BASIS_CHANGED
        if before.identity() != after.identity():
            return TransitionKind.EVIDENCE_CHANGED
        return None
    if before is not None and before.supported:
        return TransitionKind.SUPPORT_LOST
    if before is None:
        return TransitionKind.CRITERION_ADDED
    if after is None:
        return TransitionKind.CRITERION_REMOVED
    if before.identity() != after.identity():
        return TransitionKind.EVIDENCE_CHANGED
    return None


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Subject:
    """Internal grouping of the rows that address one semantic subject.

    ``row_indices`` preserve the positions those rows held in the supplied
    table for stable artifact addressing.
    """

    id: str
    key: tuple[tuple[str, str], ...]
    identity_fields: tuple[str, ...]
    bound: bool
    rows: tuple[Mapping[str, Any], ...] = ()
    row_indices: tuple[int, ...] = ()

    def ref(self, table: str) -> SubjectRef:
        return SubjectRef(
            id=self.id,
            table=table,
            key=self.key,
            identity_fields=self.identity_fields,
            bound=self.bound,
        )


def _subjects(
    table: str,
    indexed_rows: Sequence[tuple[int, Mapping[str, Any]]],
    identity_fields: tuple[str, ...],
) -> list[_Subject]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    indices: dict[str, list[int]] = {}
    refs: dict[str, _Subject] = {}
    for index, row in indexed_rows:
        subject = _subject_for_row(table, row, identity_fields)
        grouped.setdefault(subject.id, []).append(row)
        indices.setdefault(subject.id, []).append(index)
        refs.setdefault(subject.id, subject)
    return [
        _Subject(
            id=subject_id,
            key=refs[subject_id].key,
            identity_fields=refs[subject_id].identity_fields,
            bound=refs[subject_id].bound,
            rows=tuple(grouped[subject_id]),
            row_indices=tuple(indices[subject_id]),
        )
        for subject_id in sorted(grouped)
    ]


def _subject_for_row(
    table: str,
    row: Mapping[str, Any],
    identity_fields: tuple[str, ...],
) -> _Subject:
    """Identify the semantic subject one row addresses.

    Identity comes from the declared key columns when there are any, and
    otherwise from canonical slots.  A row that offers neither is *unbound*: it
    is still projected, but its subject ID falls back to the row's own content,
    so it will not join across rounds once a field fills in.  That instability
    is real and is reported rather than hidden -- the fix is a spec that
    declares key columns, not a cleverer guess here.
    """

    present = _subject_key_values(row, identity_fields)
    bound = bool(identity_fields) and len(present) == len(identity_fields)
    if identity_fields:
        payload: Any = {"key_values": [list(pair) for pair in present], "bound": bound}
    else:
        present = ()
        payload = {"row_content": _row_content(row)}
    subject_id = stable_id(
        {
            "version": CRITERIA_PROJECTION_VERSION,
            "table": _text(table),
            "identity_fields": list(identity_fields),
            **payload,
        }
    )
    return _Subject(
        id=subject_id,
        key=present,
        identity_fields=identity_fields,
        bound=bound,
    )


def _subject_key_values(
    row: Mapping[str, Any],
    key_columns: Sequence[str],
) -> tuple[tuple[str, str], ...]:
    """Every declared key column this row populates, in the projection's own form.

    The single owner of how a subject key is *spelled*.  Values go through
    :func:`_normalize_value`, which JSON-encodes mappings and sequences,
    renders bools as ``true``/``false``, collapses whitespace, casefolds, and
    truncates at :data:`MAX_VALUE_LENGTH` -- so a list-valued or very long key
    column has exactly one spelling anywhere in this build.

    **Private, and it stays private.**  The result may be *partial*: a row
    populating some declared key columns and not others returns only the ones it
    populates, which is what makes the unbound case observable to the projection
    itself.  A partial key is the one shape that must never be used to join --
    it matches on a prefix and so can land on the wrong subject.  Callers get
    :func:`subject_key`, which is bound-or-nothing; publishing this one would put
    the unguarded form in the public API and leave the safe wrapper as something
    a future caller has to know to prefer.
    """

    return tuple(
        (str(name), _normalize_value(_nested(row, str(name))))
        for name in key_columns
        if not _criteria_missing(_nested(row, str(name)))
    )


def subject_key(
    row: Mapping[str, Any],
    key_columns: Sequence[str],
) -> tuple[tuple[str, str], ...] | None:
    """The row's subject key, or ``None`` when the subject is unbound.

    ``None`` means the row does not populate every declared key column, or that
    no key columns were declared at all.  An unbound subject joins to nothing by
    construction -- its projected ID falls back to row content, which moves as
    soon as a field fills -- so returning ``None`` is the honest answer rather
    than a partial key that would match the wrong subject.
    """

    columns = tuple(key_columns)
    if not columns:
        return None
    values = _subject_key_values(row, columns)
    return values if len(values) == len(columns) else None


def row_subject_ids(
    table: str,
    rows: Sequence[Mapping[str, Any]],
    specs: Any = None,
) -> tuple[str, ...]:
    """The subject id :func:`project_rows` would group each row under.

    One entry per input row, in input order; ``""`` for anything that is not a
    mapping, which the projection also skips.

    Exported because a consumer that wants to reason about a *row's* subject --
    "does this row belong to a subject that already has support?" -- must ask
    the same question the projection will answer, and the answer depends on
    which identity fields the projection chose: declared key columns when a
    spec supplies them, the canonical fallback otherwise, and that choice is
    made from the whole table's rows rather than from any one of them.
    :func:`subject_key` cannot answer it, because it returns ``None`` for every
    row whenever no key columns are declared -- which is most of this corpus.

    Re-deriving the grouping instead is the failure mode ``path_features_v1``
    already hit once: a second spelling of an identity rule fails *silently*,
    because a row that lands in the wrong group looks like a subject nobody has
    seen rather than like an error.
    """

    return tuple(ref.id if ref is not None else "" for ref in row_subject_refs(table, rows, specs))


def row_subject_refs(
    table: str,
    rows: Sequence[Mapping[str, Any]],
    specs: Any = None,
) -> tuple[SubjectRef | None, ...]:
    """The full stable subject address for each input row."""

    mapping_rows = [row for row in rows if isinstance(row, Mapping)]
    spec = _spec_tables(specs).get(_text(table))
    identity_fields = _identity_fields(spec, mapping_rows)
    return tuple(
        _subject_for_row(_text(table), row, identity_fields).ref(_text(table))
        if isinstance(row, Mapping)
        else None
        for row in rows
    )


def normalize_key_value(value: Any) -> str:
    """The projection's comparison form for a single value.

    Exported for the same reason as :func:`subject_key`: a consumer that
    compares its own value against one already inside a snapshot must spell it
    the way the snapshot does.  Re-deriving "casefold and collapse whitespace"
    looks equivalent and is not -- it diverges on sequences, mappings, bools,
    and anything longer than :data:`MAX_VALUE_LENGTH`.
    """

    return _normalize_value(value)


def _identity_fields(
    spec: "_TableSpecView | None",
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Declared key columns, else canonical identity slots present in the rows.

    The canonical fallback uses only the slots the runtime invariants declare
    generic -- ``id``, ``name``, ``entity_type``, ``relation_type``, ``source``,
    ``target``, ``src_id``, ``tgt_id``.  No table, domain, or question name
    appears here or anywhere else in this module.
    """

    if spec is not None and spec.key_columns:
        return spec.key_columns

    # No declaration. The fallback resolves the same canonical vocabulary the
    # declaration owner uses -- one spelling of the rule, imported rather than
    # restated, because a second spelling of an identity rule fails silently: a
    # row landing in the wrong group looks like a subject nobody has seen.
    columns: set[str] = set()
    for row in rows:
        columns.update(str(key) for key in row)
    return canonical_subject_identity(columns)


def _row_content(row: Mapping[str, Any]) -> list[list[str]]:
    """A row's value-bearing content, for identifying an unbound subject."""

    return [
        [str(key), _normalize_value(value)]
        for key, value in sorted(row.items(), key=lambda item: str(item[0]))
        if _is_value_field(str(key)) and not _criteria_missing(value)
    ]


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------


def datapoint_fields(
    table: str,
    rows: Sequence[Mapping[str, Any]] | None,
    specs: Any = None,
) -> tuple[str, ...]:
    """The columns of ``table`` that project as criteria, and nothing else.

    This is the same resolution :func:`project_rows` performs internally, made
    public so that a caller which must act on "is this cell a datapoint" -- a
    provenance deriver, for instance -- asks this module rather than keeping a
    second, drifting opinion.  Provenance, control, and identity columns are
    excluded: an identity column is supported by construction of the row, so
    finding its text in a chunk says nothing about whether the row is evidenced.
    """

    table_rows = [row for row in (rows or ()) if isinstance(row, Mapping)]
    spec = _spec_tables(specs).get(table)
    return _criteria_fields(spec, table_rows, _identity_fields(spec, table_rows))


def _criteria_fields(
    spec: "_TableSpecView | None",
    rows: Sequence[Mapping[str, Any]],
    identity_fields: tuple[str, ...],
) -> tuple[str, ...]:
    """Which columns of a table become criteria.

    Declared columns when a spec supplies them -- so a column nobody has filled
    yet still projects as unresolved -- and otherwise the columns observed
    anywhere on the table's rows.  Without a spec, a field that appears on no
    row is invisible, and unresolved detection is limited accordingly.

    Provenance, control, and identity columns are excluded.  Provenance is not
    a datapoint; the producer's own ``completeness``/``evidence_gap`` verdict is
    not evidence; and the subject's identity fields are supported by
    construction.
    """

    declared: list[str] = []
    if spec is not None:
        declared.extend(spec.columns)
    if not declared:
        seen: set[str] = set()
        for row in rows:
            for key in row:
                name = str(key)
                if name not in seen:
                    seen.add(name)
                    declared.append(name)

    excluded = set(identity_fields)
    fields: list[str] = []
    for name in declared:
        if name in excluded or name in fields:
            continue
        if not _is_value_field(name):
            continue
        fields.append(name)
    return tuple(sorted(fields))


def _project_field(
    *,
    table: str,
    field: str,
    subject: _Subject,
    subject_sources: tuple[str, ...],
    accepted: frozenset[str] | None,
    checked: bool,
    guesses: Sequence["_JudgedBestGuess"] = (),
    evidence_registry: Any = None,
) -> CriterionState:
    ref = CriterionRef.create(
        table=table,
        field=field,
        subject_id=subject.id,
        subject_key=subject.key,
        identity_fields=subject.identity_fields,
        subject_bound=subject.bound,
    )

    display: dict[str, str] = {}
    for row in subject.rows:
        value = _nested(row, field)
        if _criteria_missing(value):
            continue
        normalized = _normalize_value(value)
        shown = _display_value(value)
        if normalized not in display or shown < display[normalized]:
            display[normalized] = shown

    if display:
        bindings_by_value = {
            normalized: tuple(
                evidence_registry.accepted_bindings(ref.id, normalized)
                if evidence_registry is not None
                else ()
            )
            for normalized in display
        }
        bindings = tuple(
            cell
            for normalized in sorted(bindings_by_value)
            for cell in bindings_by_value[normalized]
        )
        if not bindings:
            return CriterionState(
                ref=ref,
                status=CriterionStatus.UNRESOLVED,
                basis=EvidenceBasis.NONE,
                subject_source_ids=subject_sources,
            )
        return CriterionState(
            ref=ref,
            status=CriterionStatus.SUPPORTED,
            basis=EvidenceBasis.RESOLVED_ASSERTION_CHAIN,
            values=tuple(
                display[key]
                for key in sorted(display)
                if bindings_by_value[key]
            ),
            source_ids=tuple(sorted({cell.source_id for cell in bindings})),
            subject_source_ids=subject_sources,
            assertion_ids=tuple(sorted({cell.assertion_id for cell in bindings})),
            acceptance_ids=tuple(sorted({cell.acceptance_id for cell in bindings})),
            source_version_ids=tuple(
                sorted({cell.source_version_id for cell in bindings})
            ),
            span_ids=tuple(sorted({cell.span_id for cell in bindings})),
        )

    # No accepted stated value resolves for this field.
    return CriterionState(
        ref=ref,
        status=CriterionStatus.UNRESOLVED,
        basis=EvidenceBasis.NONE,
        subject_source_ids=subject_sources,
    )


def _project_judged_best_guess(
    *,
    ref: CriterionRef,
    guesses: Sequence["_JudgedBestGuess"],
    subject_sources: tuple[str, ...],
    accepted: frozenset[str] | None,
    checked: bool,
) -> CriterionState:
    """Parse a historical best-guess state shape for artifact compatibility."""

    display: dict[str, str] = {}
    named: set[str] = set()
    for guess in guesses:
        shown = _display_value(guess.value)
        normalized = _normalize_value(guess.value)
        if normalized not in display or shown < display[normalized]:
            display[normalized] = shown
        named.update(guess.source_ids)

    if not display:
        return CriterionState(
            ref=ref,
            status=CriterionStatus.UNRESOLVED,
            basis=EvidenceBasis.NONE,
            subject_source_ids=subject_sources,
        )

    if not checked:
        basis = EvidenceBasis.JUDGED_BEST_GUESS_UNCHECKED
        source_ids = tuple(sorted(named))
    else:
        matched = tuple(sorted(named & (accepted or frozenset())))
        if matched:
            basis = EvidenceBasis.JUDGED_BEST_GUESS_ACCEPTED
            source_ids = matched
        else:
            basis = EvidenceBasis.JUDGED_BEST_GUESS_UNMATCHED
            source_ids = tuple(sorted(named))

    return CriterionState(
        ref=ref,
        status=CriterionStatus.SUPPORTED,
        basis=basis,
        values=tuple(display[key] for key in sorted(display)),
        source_ids=source_ids,
        subject_source_ids=tuple(sorted(set(subject_sources) | named)),
    )


def admits_judged_best_guess(resolution: Any) -> bool:
    """Validate the shape of a historical best-guess artifact.

    This predicate is artifact validation only. Criterion support requires a
    resolved durable registry chain.
    """

    if not isinstance(resolution, Mapping):
        return False
    if resolution.get("accepted") is False:
        return False
    if not _text(resolution.get("target_table")):
        return False
    if not _text(resolution.get("canonical_column")):
        return False
    if _criteria_missing(resolution.get("best_guess_value")):
        return False
    raw_index = resolution.get("source_row_index")
    if isinstance(raw_index, bool) or not isinstance(raw_index, int):
        return False
    if raw_index < 0:
        return False
    return bool(_source_ids(resolution.get("source_ids")))


@dataclass(frozen=True)
class _JudgedBestGuess:
    """One parsed historical best-guess artifact record."""

    table: str
    row_index: int
    field: str
    value: str
    source_ids: frozenset[str]


def _judged_best_guesses(
    resolutions: Iterable[Mapping[str, Any]] | None,
) -> dict[str, dict[tuple[int, str], tuple[_JudgedBestGuess, ...]]]:
    """Index shape-valid historical artifacts by table, row, and column."""

    out: dict[str, dict[tuple[int, str], list[_JudgedBestGuess]]] = {}
    for resolution in resolutions or ():
        if not admits_judged_best_guess(resolution):
            continue
        table = _text(resolution.get("target_table"))
        field = _text(resolution.get("canonical_column"))
        raw_index = resolution.get("source_row_index")
        value = resolution.get("best_guess_value")
        sources = _source_ids(resolution.get("source_ids"))
        out.setdefault(table, {}).setdefault((raw_index, field), []).append(
            _JudgedBestGuess(
                table=table,
                row_index=raw_index,
                field=field,
                value=_display_value(value),
                source_ids=frozenset(sources),
            )
        )
    return {
        table: {key: tuple(items) for key, items in sorted(by_key.items())}
        for table, by_key in out.items()
    }


def _basis_for(
    field_refs: set[str],
    row_refs: set[str],
    accepted: frozenset[str] | None,
    checked: bool,
) -> tuple[EvidenceBasis, tuple[str, ...]]:
    """Decode historical provenance-basis metadata for artifact compatibility."""

    if field_refs:
        if not checked:
            return EvidenceBasis.FIELD_REF_UNCHECKED, tuple(sorted(field_refs))
        matched = tuple(sorted(field_refs & (accepted or frozenset())))
        if matched:
            return EvidenceBasis.FIELD_REF_ACCEPTED, matched
        return EvidenceBasis.FIELD_REF_UNMATCHED, tuple(sorted(field_refs))
    if row_refs:
        if not checked:
            return EvidenceBasis.ROW_REF_UNCHECKED, tuple(sorted(row_refs))
        matched = tuple(sorted(row_refs & (accepted or frozenset())))
        if matched:
            return EvidenceBasis.ROW_REF_ACCEPTED, matched
        return EvidenceBasis.ROW_REF_UNMATCHED, tuple(sorted(row_refs))
    return EvidenceBasis.ROW_VALUE_ONLY, ()


# ---------------------------------------------------------------------------
# Provenance conventions
# ---------------------------------------------------------------------------

#: Row keys that carry provenance or the producer's own verdict rather than a
#: datapoint.  ``source``/``target``/``src_id``/``tgt_id`` are deliberately
#: absent: those are canonical graph slots holding real content, and only the
#: chunk/document senses of "source" are provenance.
_NON_VALUE_FIELDS = frozenset(
    {
        "chunk_id",
        "chunk_ids",
        "completeness",
        "dedup_key",
        "deduplication_key",
        "evidence",
        "evidence_gap",
        "evidence_text",
        "group_key",
        # ENGINE-MINTED STRUCTURAL COLUMNS. A traversal's COLLAPSE and AGGREGATE
        # mint these to describe the GROUPING, not the subject: how many rows
        # merged, which row ids went in. They are operational volume, and
        # They are extraction/identity plumbing rather than declared datapoints.
        #
        # This matters because two fallbacks compose. `_criteria_fields` mints a
        # criterion per observed column when a table has no spec, and
        # `pipeline._deliverable_tables` falls back to every table handed in
        # when a run declares none -- and a traversal hands in its intermediate
        # variables. Excluding these fields keeps that plumbing out of the
        # criterion set before registry resolution is considered.
        #
        # LATENT, MEASURED, AND NOT EXOTIC. No credited datapoint in 88 recorded
        # reward reports carries these fields, and the two runs that exercise
        # the reward path carry neither column. But a sweep of every recorded
        # exported table found `occurrence_count` and `items` as real columns in
        # more than forty runs -- 2,848 and 804 rows in one -- so the column is
        # common and only the projection has not yet met it.
        #
        # INTERIM, AND DO NOT EXTEND THIS LIST TO CLOSE THE CLASS.
        #
        # These five names are a denylist, and a denylist only excludes what its
        # author thought of -- the reason this file's sibling `provenance.py`
        # argues for allowlists. The class-closing fix is landing in `gasl/` as
        # `engine_columns` on the emitted contract: each command declares, at
        # the construction site, which columns it authored rather than which
        # carry data-derived values. A `_`-prefix convention was considered and
        # REJECTED, on the grounds that it would let this file's parser dictate
        # the engine's output vocabulary and would add a ninth name-based
        # classifier to close the leak from an eighth.
        #
        # So when `engine_columns` arrives, the correct change is to consume it
        # and let these five retire to covering NON-GASL producers only -- not
        # to add a sixth, seventh and eighth name here. Extending the list is
        # the move this note exists to prevent.
        #
        # `count` and `result` are minted by the same engine code and are
        # deliberately NOT here: both are plausible domain column names (a count
        # of deaths, a study's result), and excluding them would silently drop
        # real datapoints to close a latent exposure. A denylist that starts
        # eating real fields is worse than the hole it plugs.
        "contributing_rows",
        "item_ids",
        "items",
        "occurrence_count",
        "row_count",
        "path_depth",
        "quote",
        "quotes",
        "row_context",
        "row_id",
        "source_chunk",
        "source_chunks",
        "source_id",
        "source_ids",
        "source_ref",
        "source_refs",
        "source_row_index",
        "source_row_key",
        "table_name",
    }
)

_NON_VALUE_SUFFIXES = (
    "_chunk_id",
    "_chunk_ids",
    "_dedup_key",
    "_evidence",
    "_evidence_text",
    "_quote",
    "_quotes",
    "_row_id",
    "_source_chunk",
    "_source_chunks",
    "_source_id",
    "_source_ids",
    "_source_ref",
    "_source_refs",
)

_ROW_SOURCE_FIELDS = (
    "source_refs",
    "source_ref",
    "source_ids",
    "source_id",
    "source_chunks",
    "source_chunk",
    "chunk_ids",
    "chunk_id",
)

#: The provenance naming convention lives in `provenance`, which owns it and
#: is a pure leaf. `goals` reads the same predicate, so what this module
#: refuses to credit and what that module refuses to search for cannot drift.
_is_provenance_name = is_provenance_name


#: Retained only to build `<field>` + suffix lookups when reading a specific
#: field's provenance; membership tests go through `_is_provenance_name`.
_FIELD_SOURCE_SUFFIXES = (
    "_source_refs",
    "_source_ref",
    "_source_ids",
    "_source_id",
    "_source_chunks",
    "_source_chunk",
)

_CHUNK_SUFFIX_RE = re.compile(r"^(?P<source_id>.+)_chunk_\d+$")

_SOURCE_SPLIT_RE = re.compile(r"[,;\s]+")


#: The engine's canonical graph abstraction, quoted from
#: `docs/RUNTIME_INVARIANTS.md` -- "allowed as code literals in generic runtime
#: code because they are part of the engine's canonical graph abstraction
#: rather than domain- or source-specific schema".
#:
#: They are therefore, by that same definition, **not domain data**. A row
#: materialised from a graph edge carries them (`src_id = "COVID-19"` names the
#: edge's source entity), and counting them as datapoints inflates every
#: downstream measure with plumbing: measured at 104 of 676 criteria -- 15.4%
#: -- on 30 real rows, with `id` and `entity_name` holding the same string, so
#: one non-datapoint counted twice.
#:
#: This is not a denylist of fields somebody guessed should not count. It is
#: the project's own declared vocabulary, cited rather than invented, which is
#: why it can be trusted to stay correct as schemas change.
_CANONICAL_GRAPH_KEYS = frozenset(
    {
        "id",
        "name",
        "entity_type",
        "relation_type",
        "source",
        "target",
        "src_id",
        "tgt_id",
        # `RUNTIME_INVARIANTS.md` declares `name`; the implementation emits
        # `entity_name` for the same concept -- in real rows the node `id` and
        # `entity_name` hold the identical string. `group_name` is the grouping
        # key's label. Reconciling the doc's vocabulary with the code's
        # spelling, not inventing new exclusions.
        #
        # Entity names are extraction/identity plumbing, not declared result
        # datapoints, even when their text appears in a source chunk.
        "entity_name",
        "group_name",
    }
)


#: The closed set of reasons a column name is not a datapoint. Class labels, in
#: the order :func:`_is_value_field` tests them; ``""`` means it is one.
DATAPOINT_EXCLUSION_CLASSES = (
    "underscore_prefixed",
    "non_value_field",
    "canonical_graph_key",
    "provenance",
    "non_value_suffix",
)


def datapoint_exclusion_class(name: Any) -> str:
    """Why :func:`is_datapoint_field` refuses a column, as a class label.

    ``""`` when it does not refuse it. Exported beside the predicate so a
    consumer disclosing *what it excluded and why* names the class this module
    excluded on rather than re-deriving a classification from its own reading of
    the name -- which would be a second owner of the rule, differing exactly
    where it matters and silently.
    """

    text = _text(name)
    if not text or text.startswith("_"):
        return "underscore_prefixed"
    if text in _NON_VALUE_FIELDS:
        return "non_value_field"
    if text in _CANONICAL_GRAPH_KEYS:
        return "canonical_graph_key"
    if _is_provenance_name(text):
        return "provenance"
    if text.endswith(_NON_VALUE_SUFFIXES):
        return "non_value_suffix"
    return ""


def _is_value_field(name: str) -> bool:
    if not name or name.startswith("_"):
        return False
    if name in _NON_VALUE_FIELDS or name in _CANONICAL_GRAPH_KEYS:
        return False
    if _is_provenance_name(name):
        return False
    return not name.endswith(_NON_VALUE_SUFFIXES)


def _field_source_ids(row: Mapping[str, Any], field: str) -> set[str]:
    ids: set[str] = set()
    for suffix in _FIELD_SOURCE_SUFFIXES:
        ids.update(_source_ids(row.get(f"{field}{suffix}")))
    return ids


def _row_source_ids(row: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for name in _ROW_SOURCE_FIELDS:
        ids.update(_source_ids(row.get(name)))
    return ids


def _subject_source_ids(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    ids: set[str] = set()
    for row in rows:
        ids.update(_row_source_ids(row))
        for key in row:
            name = str(key)
            if name.endswith(_FIELD_SOURCE_SUFFIXES):
                ids.update(_source_ids(row.get(key)))
    return tuple(sorted(ids))


def _source_ids(value: Any) -> set[str]:
    """Canonical source-document IDs from noncrediting provenance context.

    A chunk reference is reduced to the document it came from, so a chunk-level
    and document-level annotation share one co-location identifier.
    """

    ids: set[str] = set()
    for item in _iter_scalars(value):
        for part in _SOURCE_SPLIT_RE.split(str(item)):
            text = part.strip()
            if not text or text.lower() in _CRITERIA_MISSING_STRINGS:
                continue
            match = _CHUNK_SUFFIX_RE.match(text)
            ids.add(match.group("source_id") if match is not None else text)
    return ids


def _accepted_ids(values: Iterable[str] | None) -> frozenset[str] | None:
    if values is None:
        return None
    accepted: set[str] = set()
    for value in values:
        accepted.update(_source_ids(value))
    return frozenset(accepted)


# ---------------------------------------------------------------------------
# Spec view
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TableSpecView:
    """One table's contract, read from whatever shape the caller supplied."""

    key_columns: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    deliverable: bool = True


def _spec_tables(specs: Any) -> dict[str, _TableSpecView]:
    """Read table contracts from an object or a plain payload.

    Duck-typed on purpose.  Importing the spec loader would drag a YAML
    dependency and file I/O into a module whose whole value is that it can be
    exercised with constructed inputs alone.
    """

    if specs is None:
        return {}
    tables = specs.get("tables") if isinstance(specs, Mapping) else getattr(specs, "tables", None)
    if not isinstance(tables, Mapping):
        return {}

    out: dict[str, _TableSpecView] = {}
    for name, table in tables.items():
        key = _text(name)
        if not key or table is None:
            continue
        out[key] = _TableSpecView(
            # `subject_key_columns` is the identity declaration; `key_columns`
            # is the completeness contract and is only a fallback for specs
            # written before the two were separated.
            key_columns=(
                _names(_spec_attr(table, "subject_key_columns"))
                or _names(_spec_attr(table, "key_columns"))
            ),
            columns=_spec_columns(table),
            deliverable=bool(_spec_attr(table, "deliverable", True)),
        )
    return out


def _spec_columns(table: Any) -> tuple[str, ...]:
    columns = _spec_attr(table, "columns")
    if callable(getattr(table, "all_columns", None)):
        columns = table.all_columns()
    if isinstance(columns, Mapping):
        return _names(columns.keys())
    if isinstance(columns, (list, tuple)):
        names: list[str] = []
        for item in columns:
            if isinstance(item, Mapping):
                names.append(_text(item.get("name")))
            elif isinstance(item, str):
                names.append(_text(item))
            else:
                names.append(_text(getattr(item, "name", "")))
        return _names(names)
    return ()


def _spec_attr(table: Any, name: str, default: Any = None) -> Any:
    if isinstance(table, Mapping):
        return table.get(name, default)
    return getattr(table, name, default)


def _names(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set, frozenset)) and not hasattr(values, "__iter__"):
        return ()
    out: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _row_tables(rows: Mapping[str, Sequence[Mapping[str, Any]]] | None) -> list[str]:
    if not isinstance(rows, Mapping):
        return []
    return [_text(name) for name in rows if _text(name)]


# ---------------------------------------------------------------------------
# Value normalization
# ---------------------------------------------------------------------------

#: Strings a producer writes to mean "nothing here".  A normalization
#: convention, not domain vocabulary.
#:
#: THE UNION OF WHAT FIVE PRODUCERS MEANT BY ABSENCE, AND THIS MODULE IS THE ONE
#: OWNER OF IT.  `acquisition`, `best_guess`, `goals` and `pipeline` each kept
#: their own set (8, 11, 9 and 8 entries); they disagreed on `--`, `[null]`,
#: `not reported`, `not specified` and five more, so the same cell was absence to
#: one consumer and a value to another.  The union rather than the intersection
#: or this module's own former 17, because every one of the 18 is a producer
#: writing "nothing here", which is the set's declared subject: a token that
#: means absence to one producer means absence to all of them, and the
#: divergence was an accident of five authors rather than a disagreement about
#: meaning.  `"not specified in current evidence"` came from `goals` alone and is
#: the entry that makes this a v5 projection bump -- see
#: :data:`CRITERIA_PROJECTION_VERSION`.
_CRITERIA_MISSING_STRINGS = frozenset(
    {
        "",
        "-",
        "--",
        "[null]",
        "<null>",
        "n/a",
        "na",
        "none",
        "not applicable",
        "not available",
        "not found",
        "not provided",
        "not reported",
        "not specified",
        "not specified in current evidence",
        "not stated",
        "null",
        "unknown",
    }
)


def missing_tokens() -> tuple[str, ...]:
    """The owned missing-token vocabulary, for a run to record which set it ran.

    A run that emits ``{"module": "criteria", "tokens": 18}`` lets a later
    reader see which convention produced its trace, rather than inferring it
    from the version.
    """

    return tuple(sorted(_CRITERIA_MISSING_STRINGS))


def is_missing_value(value: Any) -> bool:
    """Whether a value means "nothing here" rather than being a value.

    Exported additively over :func:`_missing` -- same function, public name, no
    behaviour change -- for the same reason as :func:`normalize_key_value`: a
    consumer deciding whether a cell carries anything must ask this module
    rather than keep a second, drifting opinion.  A credit, a deficit, or a
    best-guess task minted from one of these tokens counts absence as yield.
    """

    return _criteria_missing(value)


def is_datapoint_field(name: Any) -> bool:
    """Whether a column name denotes a measured value.

    False for provenance, for the producer's own verdict about a row
    (``completeness``, ``evidence_gap``), for engine-minted structural columns,
    for canonical graph slots, and for anything ``_``-prefixed.  Exported for
    the same reason as :func:`normalize_key_value` and :func:`datapoint_fields`:
    a consumer deciding what counts must ask this module rather than keep a
    second, weaker opinion.  A delegation, not a copy -- the next producer
    self-verdict column added to :data:`_NON_VALUE_FIELDS` leaves every caller's
    basis on the same day, with no second edit.
    """

    return _is_value_field(_text(name))


def _criteria_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return " ".join(value.split()).lower() in _CRITERIA_MISSING_STRINGS
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _normalize_value(value: Any) -> str:
    """The comparison form of a value: case- and whitespace-insensitive."""

    return _display_value(value).casefold()


def _display_value(value: Any) -> str:
    if isinstance(value, Mapping):
        text = json.dumps(
            {str(key): _display_value(item) for key, item in sorted(value.items())},
            sort_keys=True,
            separators=(",", ":"),
        )
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = [_display_value(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items = sorted(items)
        text = json.dumps(items, separators=(",", ":"))
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    text = " ".join(text.split())
    return text[:MAX_VALUE_LENGTH]


def _iter_scalars(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        out: list[Any] = []
        for item in value:
            out.extend(_iter_scalars(item))
        return tuple(out)
    return (value,)


def _nested(row: Mapping[str, Any], field: str) -> Any:
    """Read a field, following dotted paths into nested mappings."""

    if field in row:
        return row[field]
    current: Any = row
    for part in str(field).split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _text(value: Any) -> str:
    return str(value or "").strip()


# ============================================================================
# completion.py
# ============================================================================

import hashlib
import json
import os
import re
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_DONE_STATUSES = {"accepted", "deferred", "out_of_scope", "resolved"}
_OPEN_STATUSES = {"", "open", "unresolved", "needs_search", "underexplored"}
_BLOCKING_SEVERITIES = {"error", "high", "critical"}


def new_completion_state() -> dict[str, Any]:
    return {
        "version": 1,
        "scope_status": "missing",
        "expected_axes": [],
        "search_space_probes": [],
        "underexplored_bins": [],
        "estimate_issues": [],
        "unresolved_questions": [],
        "suggested_queries": [],
        "latest_judgment": {},
    }


def normalize_completion_state(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Coerce persisted completion state into one stable shape."""

    if not isinstance(raw, Mapping):
        raw = {}

    state = new_completion_state()
    status = _clean(raw.get("scope_status") or raw.get("status") or "missing")
    if status not in {
        "missing",
        "probing",
        "insufficient_evidence",
        "estimated",
        "inconsistent",
    }:
        status = "missing"
    state["scope_status"] = status
    state["expected_axes"] = _unique_mappings(
        _coerce_axis(axis)
        for axis in _completion_as_list(raw.get("expected_axes") or raw.get("axes"))
    )
    state["search_space_probes"] = _unique_mappings(
        _coerce_probe(probe)
        for probe in _completion_as_list(
            raw.get("search_space_probes")
            or raw.get("scope_probes")
            or raw.get("probes")
        )
    )
    state["underexplored_bins"] = _unique_mappings(
        _coerce_issue(issue)
        for issue in _completion_as_list(raw.get("underexplored_bins"))
    )
    state["estimate_issues"] = _unique_mappings(
        _coerce_issue(issue)
        for issue in _completion_as_list(raw.get("estimate_issues") or raw.get("issues"))
    )
    state["unresolved_questions"] = _unique_strings(raw.get("unresolved_questions"))
    state["suggested_queries"] = _unique_strings(raw.get("suggested_queries"))
    latest = raw.get("latest_judgment")
    state["latest_judgment"] = dict(latest) if isinstance(latest, Mapping) else {}
    if raw.get("updated_at"):
        state["updated_at"] = str(raw.get("updated_at"))
    return state


def completion_update_from_estimate(estimate: Mapping[str, Any]) -> dict[str, Any]:
    """Extract completion-scope fields that the universe estimator can refresh."""

    return {
        "scope_status": (
            "estimated"
            if str(estimate.get("status") or "") == "estimated"
            else "insufficient_evidence"
        ),
        "expected_axes": estimate.get("expected_axes") or [],
        "underexplored_bins": estimate.get("underexplored_bins") or [],
        "unresolved_questions": estimate.get("unresolved_questions") or [],
        "suggested_queries": estimate.get("suggested_queries") or [],
    }


def completion_update_from_critique(critique: Mapping[str, Any]) -> dict[str, Any]:
    """Extract state fields from a consistency critique."""

    accepted = bool(critique.get("accepted") or critique.get("accept"))
    issues = _completion_as_list(critique.get("issues") or critique.get("estimate_issues"))
    bins = _completion_as_list(critique.get("underexplored_bins"))
    open_issues = [
        issue
        for issue in (_coerce_issue(issue) for issue in issues)
        if _is_blocking_issue(issue)
    ]
    open_bins = [
        issue
        for issue in (_coerce_issue(issue) for issue in bins)
        if _clean(issue.get("status")) not in _DONE_STATUSES
    ]
    return {
        "scope_status": (
            "estimated"
            if accepted and not open_issues and not open_bins
            else "inconsistent"
        ),
        "latest_judgment": dict(critique),
        "estimate_issues": issues,
        "underexplored_bins": bins,
        "unresolved_questions": critique.get("unresolved_questions") or [],
        "suggested_queries": critique.get("suggested_queries") or [],
    }


def merge_completion_state(
    previous: Mapping[str, Any] | None,
    update: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge a fresh completion-agent observation into durable state."""

    base = normalize_completion_state(previous)
    fresh = normalize_completion_state(update)
    out = new_completion_state()
    out["scope_status"] = (
        fresh["scope_status"]
        if fresh["scope_status"] != "missing"
        else base["scope_status"]
    )
    out["expected_axes"] = _unique_mappings(
        [*base["expected_axes"], *fresh["expected_axes"]]
    )
    out["search_space_probes"] = _unique_mappings(
        [*base["search_space_probes"], *fresh["search_space_probes"]]
    )
    out["underexplored_bins"] = (
        fresh["underexplored_bins"]
        if "underexplored_bins" in (update or {})
        else base["underexplored_bins"]
    )
    out["estimate_issues"] = (
        fresh["estimate_issues"]
        if (
            isinstance(update, Mapping)
            and ("estimate_issues" in update or "issues" in update)
        )
        else base["estimate_issues"]
    )
    out["unresolved_questions"] = _unique_strings(
        [*fresh["unresolved_questions"], *base["unresolved_questions"]]
    )
    out["suggested_queries"] = _unique_strings(
        [*fresh["suggested_queries"], *base["suggested_queries"]]
    )
    out["latest_judgment"] = fresh["latest_judgment"] or base["latest_judgment"]
    if isinstance(update, Mapping) and update.get("updated_at"):
        out["updated_at"] = str(update.get("updated_at"))
    elif base.get("updated_at"):
        out["updated_at"] = base["updated_at"]
    return out


def completion_probe_summary(
    *,
    query: str,
    results: Iterable[Mapping[str, Any]],
    artifact_label: int | str,
    purpose: str = "",
    axis_bindings: Mapping[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    """Summarize a cheap breadth probe without retaining scraped page bodies."""

    from question_pipeline.utilities.search import compact_search_result

    compact_results = [
        compact_search_result(dict(result))
        for result in results
        if isinstance(result, Mapping)
    ]
    urls = _unique_strings(result.get("url") for result in compact_results)
    domains = _unique_strings(_domain(url) for url in urls)
    titles = _unique_strings(
        result.get("title") or _nested_metadata_value(result, "title")
        for result in compact_results
    )
    payload = {
        "id": _completion_stable_id(
            {
                "query": _normalize_text(query),
                "artifact_label": str(artifact_label),
                "purpose": purpose,
            }
        ),
        "artifact_label": artifact_label,
        "query": str(query or "").strip(),
        "purpose": str(purpose or "").strip(),
        "axis_bindings": dict(axis_bindings or {}),
        "result_count": len(compact_results),
        "unique_url_count": len(urls),
        "unique_domain_count": len(domains),
        "result_count_bucket": result_count_bucket(len(compact_results)),
        "domains": domains[:12],
        "titles": titles[:12],
        "results": compact_results[:10],
    }
    if error:
        payload["error"] = str(error)
    return payload


def result_count_bucket(count: int) -> str:
    if count <= 0:
        return "none"
    if count == 1:
        return "one"
    if count <= 3:
        return "few"
    if count <= 9:
        return "several"
    return "many"


def scope_probe_context(
    state: Mapping[str, Any],
    *,
    limit: int = 16,
) -> dict[str, Any]:
    """Return a compact state excerpt for prompts and gates."""

    normalized = normalize_completion_state(state)
    probes = normalized["search_space_probes"][-limit:]
    return {
        "scope_status": normalized["scope_status"],
        "expected_axes": normalized["expected_axes"],
        "search_space_probe_count": len(normalized["search_space_probes"]),
        "recent_search_space_probes": probes,
        "underexplored_bins": open_completion_bins(normalized),
        "estimate_issues": open_completion_issues(normalized),
        "unresolved_questions": normalized["unresolved_questions"][:20],
        "suggested_queries": normalized["suggested_queries"][:20],
        "latest_judgment": normalized.get("latest_judgment") or {},
    }


def completion_scope_actionable(
    state: Mapping[str, Any] | None,
    universe_estimate: Mapping[str, Any] | None,
) -> bool:
    """Return True when the search space has been probed enough to proceed.

    THE QUESTION THIS ASKS HAS CHANGED, BECAUSE THE OLD ONE BECAME
    UNANSWERABLE. It used to ask "has the universe been estimated?" and
    required `status == "estimated"` with a non-empty `count_targets`. With the
    Chao1 estimator deleted, nothing populates `count_targets` by any route --
    `_fallback_unestimated_estimate` hardcodes `[]` and sends every family to
    `unestimated_count_targets` -- so both conjuncts became permanently false
    and this predicate became an unconditional `False`.

    That turned the caller at `pipeline.py` into an unconditional halt: every
    from-scratch `--pipeline-mode table-fill` run terminated before GASL with
    zero rows and zero rounds. A gate whose question the system has stopped
    being able to answer is not a gate; it is a stop with a misleading name.

    So the count legs are RETIRED rather than relaxed. What remains is what the
    system can still answer and what the gate was really protecting against:
    proceeding with no observation of the search space at all. A probe that
    returned something is evidence the space is reachable; an unestimated
    universe is no longer evidence of anything, because nothing estimates one.

    The scope-critic legs stay: an explicitly flagged estimate issue or an
    underexplored bin is a real, still-answerable objection.
    """

    normalized = normalize_completion_state(state)
    if not normalized["search_space_probes"]:
        return False
    if open_completion_issues(normalized):
        return False
    if open_completion_bins(normalized):
        return False
    return True


def completion_needs_scope_search(
    state: Mapping[str, Any] | None,
    universe_estimate: Mapping[str, Any] | None,
) -> bool:
    """Return True when broad scoping still needs search attention."""

    estimate = universe_estimate or {}
    normalized = normalize_completion_state(state)
    return (
        str(estimate.get("status") or "") != "estimated"
        or not estimate.get("count_targets")
        or bool(estimate.get("unestimated_count_targets"))
        or not normalized["search_space_probes"]
        or normalized["scope_status"] in {"missing", "probing", "inconsistent"}
        or bool(open_completion_issues(normalized))
        or bool(open_completion_bins(normalized))
    )


def open_completion_issues(
    state: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    normalized = normalize_completion_state(state)
    return [
        issue
        for issue in normalized["estimate_issues"]
        if _is_blocking_issue(issue)
    ]


def open_completion_bins(
    state: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    normalized = normalize_completion_state(state)
    return [
        issue
        for issue in normalized["underexplored_bins"]
        if _clean(issue.get("status")) not in _DONE_STATUSES
    ]


def load_seed_completion_state(path: str | Path | None) -> dict[str, Any]:
    """Load the latest persisted completion state adjacent to seed tables."""

    if not path:
        return new_completion_state()

    roots: list[Path] = []
    for raw in str(path).split(os.pathsep):
        if not raw.strip():
            continue
        seed_path = Path(raw)
        roots.extend(
            candidate
            for candidate in (
                seed_path,
                seed_path.parent,
                seed_path / "goals",
                seed_path.parent / "goals",
                seed_path.parent.parent / "goals",
            )
            if candidate.exists()
        )

    candidates = sorted(
        {
            file_path
            for root in roots
            if root.is_dir()
            for file_path in [
                *(root.glob("completion_state.json")),
                *(root.glob("*_completion_state.json")),
            ]
        },
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping):
            return normalize_completion_state(payload)
    return new_completion_state()


def _coerce_axis(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, Mapping):
        return {}
    name = _completion_clean_display(raw.get("name") or raw.get("axis") or raw.get("field"))
    if not name:
        return {}
    return {
        "id": str(raw.get("id") or _completion_stable_id({"axis": name}))[:24],
        "name": name,
        "description": _completion_clean_display(raw.get("description")),
        "status": _clean(raw.get("status") or "open") or "open",
        "supporting_queries": _unique_strings(raw.get("supporting_queries")),
    }


def _coerce_issue(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"description": raw}
    if not isinstance(raw, Mapping):
        return {}
    description = _completion_clean_display(
        raw.get("description")
        or raw.get("issue")
        or raw.get("bin")
        or raw.get("reason")
    )
    axis = _completion_clean_display(raw.get("axis") or raw.get("table") or raw.get("slot"))
    if not description and not axis:
        return {}
    payload = {
        "axis": axis,
        "description": description,
        "status": _clean(raw.get("status") or "open") or "open",
        "severity": _clean(raw.get("severity") or "error") or "error",
        "suggested_queries": _unique_strings(raw.get("suggested_queries")),
    }
    payload["id"] = str(raw.get("id") or _completion_stable_id(payload))[:24]
    return payload


def _coerce_probe(raw: Any) -> dict[str, Any]:
    from question_pipeline.utilities.search import compact_search_result

    if not isinstance(raw, Mapping):
        return {}
    query = _completion_clean_display(raw.get("query"))
    if not query:
        return {}
    results = [
        compact_search_result(dict(result))
        for result in _completion_as_list(raw.get("results"))
        if isinstance(result, Mapping)
    ]
    urls = _unique_strings(
        [*_completion_as_list(raw.get("urls")), *(result.get("url") for result in results)]
    )
    domains = _unique_strings(
        [
            *_completion_as_list(raw.get("domains")),
            *(_domain(url) for url in urls),
        ]
    )
    result_count = _completion_as_int(raw.get("result_count"))
    if result_count <= 0 and results:
        result_count = len(results)
    # Legacy persisted probes labelled themselves under "round". The value is
    # carried as an OPAQUE label only -- nothing parses a number out of it or
    # infers continuation from it; that loader family is deleted with the
    # round concept.
    artifact_label = raw.get("artifact_label", raw.get("round"))
    payload = {
        "id": str(raw.get("id") or _completion_stable_id({"query": _normalize_text(query)}))[
            :24
        ],
        "artifact_label": artifact_label,
        # The Episode that issued the probe, stamped by the pipeline. Carried
        # through normalization so the attribution survives a state merge.
        "episode_id": str(raw.get("episode_id") or ""),
        "query": query,
        "purpose": _completion_clean_display(raw.get("purpose")),
        "axis_bindings": (
            dict(raw.get("axis_bindings"))
            if isinstance(raw.get("axis_bindings"), Mapping)
            else {}
        ),
        "result_count": max(0, result_count),
        "unique_url_count": _completion_as_int(raw.get("unique_url_count")) or len(urls),
        "unique_domain_count": (
            _completion_as_int(raw.get("unique_domain_count")) or len(domains)
        ),
        "result_count_bucket": (
            _clean(raw.get("result_count_bucket"))
            or result_count_bucket(result_count)
        ),
        "domains": domains[:12],
        "titles": _unique_strings(raw.get("titles"))[:12],
        "results": results[:10],
    }
    if raw.get("error"):
        payload["error"] = str(raw.get("error"))
    return payload


def _is_blocking_issue(issue: Mapping[str, Any]) -> bool:
    status = _clean(issue.get("status"))
    severity = _clean(issue.get("severity") or "error")
    return status in _OPEN_STATUSES and severity in _BLOCKING_SEVERITIES


def _unique_mappings(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for value in values:
        if not value:
            continue
        key = str(value.get("id") or "") or _completion_stable_id(value)
        out[key] = dict(value)
    return list(out.values())


def _unique_strings(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Iterable) or isinstance(values, (bytes, Mapping)):
        values = [values]

    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _completion_clean_display(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _nested_metadata_value(result: Mapping[str, Any], key: str) -> Any:
    metadata = result.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    return metadata.get(key)


def _domain(url: str) -> str:
    parsed = urlparse(str(url or ""))
    return parsed.netloc.lower().lstrip("www.")


def _completion_stable_id(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _completion_as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _completion_as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _clean(value: Any) -> str:
    return _normalize_text(value).replace("-", "_")


def _completion_clean_display(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


# ============================================================================
# tables.py
# ============================================================================

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from question_pipeline.utilities.acquisition import stable_id
from question_pipeline.utilities.evidence import AcceptedBestGuessCell, AcceptedCell, EvidenceCommit


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
            exclusion = datapoint_exclusion_class(column_name)
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
            refs = row_subject_refs(
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
            refs = row_subject_refs(table, [values], self.table_spec)
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
                not is_missing_value(value)
                and normalize_key_value(value) == cell.normalized_value
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
        refs = row_subject_refs(table, rows, self.table_spec)
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
                if is_missing_value(row.get(cell.column))
                or normalize_key_value(row.get(cell.column))
                == cell.normalized_value
            ),
            None,
        )
        if target is None:
            target = {
                key: source_row[key]
                for key in self._subject_keys(cell.table)
                if key in source_row and not is_missing_value(source_row[key])
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
                not is_missing_value(value)
                and normalize_key_value(value) == cell.normalized_value
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
            key = _tables_stable_row_key(row)
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


def _tables_stable_row_key(row: Mapping[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)


# ============================================================================
# numeric_candidates.py
# ============================================================================

import hashlib
import json
import re
from typing import Any, Iterable, Mapping



NUMERIC_CANDIDATE_COLUMNS = [
    "candidate_id",
    "source_table",
    "source_row_index",
    "source_row_key",
    "source_field",
    "raw_value",
    "bound_type",
    "parsed_min",
    "parsed_max",
    "parsed_midpoint",
    "best_guess_value",
    "best_guess_basis",
    "comparator",
    "anchor_text",
    "derivation_rule",
    "confidence",
    *DERIVED_CONTEXT_COLUMNS,
    "source_refs",
    "source_chunks",
    "row_context",
]

_NUMERIC_MISSING_STRINGS = {
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
    "[null]",
    "<null>",
    "unknown",
}

_SCALAR_FIELD_HINTS = {
    "amount",
    "average",
    "count",
    "effect",
    "estimate",
    "interval",
    "max",
    "maximum",
    "mean",
    "median",
    "min",
    "minimum",
    "number",
    "quantity",
    "range",
    "rate",
    "ratio",
    "score",
    "threshold",
    "total",
    "value",
}

_SKIP_FIELD_TOKENS = {
    "alias",
    "aliases",
    "basis",
    "caveat",
    "caveats",
    "chunk",
    "chunks",
    "class",
    "context",
    "description",
    "direction",
    "entity",
    "evidence",
    "field",
    "gap",
    "group",
    "id",
    "interpretation",
    "key",
    "measure",
    "metric",
    "method",
    "mode",
    "model",
    "name",
    "note",
    "path",
    "policy",
    "population",
    "reason",
    "ref",
    "refs",
    "relation",
    "relationship",
    "result",
    "route",
    "setting",
    "source",
    "status",
    "study",
    "summary",
    "time",
    "type",
}

_CONTEXT_SKIP_TOKENS = {
    "chunk",
    "chunks",
    "description",
    "key",
    "path",
    "ref",
    "refs",
    "source",
}

_NUMBER = r"-?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
_RANGE_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<low>{_NUMBER})\s*(?:-|to|\u2013|\u2014)\s*"
    rf"(?P<high>{_NUMBER})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_PLUS_MINUS_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<mid>{_NUMBER})\s*(?:\+/-|\u00b1)\s*"
    rf"(?P<err>{_NUMBER})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_COMPARATOR_RE = re.compile(
    rf"^\s*(?P<comparator><=|>=|<|>|\u2264|\u2265|less than|greater than|"
    rf"more than|at most|at least|up to|no more than)\s*"
    rf"(?P<number>{_NUMBER})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_APPROX_RE = re.compile(
    rf"(?:^|[\s(])(?P<marker>~|about|approx\.?|approximately|around|roughly|"
    rf"circa|ca\.|\u2248)\s*(?P<number>{_NUMBER})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(rf"(?<![A-Za-z0-9])(?P<number>{_NUMBER})(?![A-Za-z0-9])")
_RELATIVE_RE = re.compile(
    r"\b(?P<relation>similar to|comparable to|same as|higher than|lower than|"
    r"greater than|less than|larger than|smaller than)\s+"
    r"(?P<anchor>[A-Za-z0-9][A-Za-z0-9 ._/\-]{1,80})",
    re.IGNORECASE,
)
_ORDINAL_RE = re.compile(
    r"\b(?P<marker>low|lower|lowest|high|higher|highest|small|smaller|"
    r"smallest|large|larger|largest)\b",
    re.IGNORECASE,
)


def numeric_candidates_from_tables(
    rows_by_name: Mapping[str, list[dict[str, Any]]],
    *,
    mode: str = "parsed",
    context_slots: Iterable[ContextSlot | Mapping[str, Any] | str] | None = None,
    source_records: Mapping[str, Mapping[str, Any]]
    | Iterable[Mapping[str, Any]]
    | None = None,
    best_guess_context_by_row: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Derive generic numeric candidate rows from exported answer tables."""
    mode = _normalize_mode(mode)
    if mode == "off":
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    include_textual = mode == "all"
    normalized_context_slots = normalize_context_slots(context_slots)
    sources_by_id = normalize_source_records(source_records)
    best_guess_context_by_row = best_guess_context_by_row or {}
    for table_name, rows in rows_by_name.items():
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            for field_name, value in row.items():
                field = str(field_name)
                if not _field_can_hold_scalar(field):
                    if include_textual:
                        candidates.extend(
                            _textual_candidates(
                                table_name=table_name,
                                row_index=row_index,
                                field_name=field,
                                row=row,
                                value=value,
                                context_slots=normalized_context_slots,
                                source_records=sources_by_id,
                                best_guess_context=best_guess_context_by_row.get(
                                    f"{table_name}::{row_index}",
                                    {},
                                ),
                            )
                        )
                    continue
                parsed = _parsed_candidates(
                    table_name=table_name,
                    row_index=row_index,
                    field_name=field,
                    row=row,
                    value=value,
                    context_slots=normalized_context_slots,
                    source_records=sources_by_id,
                    best_guess_context=best_guess_context_by_row.get(
                        f"{table_name}::{row_index}",
                        {},
                    ),
                )
                if parsed:
                    candidates.extend(parsed)
                elif include_textual:
                    candidates.extend(
                        _textual_candidates(
                            table_name=table_name,
                            row_index=row_index,
                            field_name=field,
                            row=row,
                            value=value,
                            context_slots=normalized_context_slots,
                            source_records=sources_by_id,
                            best_guess_context=best_guess_context_by_row.get(
                                f"{table_name}::{row_index}",
                                {},
                            ),
                        )
                    )

    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        key = str(candidate.get("candidate_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _parsed_candidates(
    *,
    table_name: str,
    row_index: int,
    field_name: str,
    row: Mapping[str, Any],
    value: Any,
    context_slots: Iterable[ContextSlot | Mapping[str, Any] | str],
    source_records: Mapping[str, Mapping[str, Any]],
    best_guess_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if _numeric_missing(value):
        return []
    raw = _stringify(value)
    if not raw:
        return []

    parsed = _parse_numeric_value(raw)
    if parsed is None:
        return []
    return [
        _candidate_row(
            table_name=table_name,
            row_index=row_index,
            field_name=field_name,
            row=row,
            raw_value=raw,
            context_slots=context_slots,
            source_records=source_records,
            best_guess_context=best_guess_context,
            **parsed,
        )
    ]


def _textual_candidates(
    *,
    table_name: str,
    row_index: int,
    field_name: str,
    row: Mapping[str, Any],
    value: Any,
    context_slots: Iterable[ContextSlot | Mapping[str, Any] | str],
    source_records: Mapping[str, Mapping[str, Any]],
    best_guess_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if _numeric_missing(value) or _numeric_field_should_skip(field_name):
        return []

    raw = _stringify(value)
    if not raw:
        return []

    candidates: list[dict[str, Any]] = []
    for match in _RELATIVE_RE.finditer(raw):
        candidates.append(
            _candidate_row(
                table_name=table_name,
                row_index=row_index,
                field_name=field_name,
                row=row,
                raw_value=raw,
                context_slots=context_slots,
                source_records=source_records,
                best_guess_context=best_guess_context,
                bound_type="relative",
                parsed_min=None,
                parsed_max=None,
                parsed_midpoint=None,
                best_guess_value=None,
                best_guess_basis="relative text requires an anchored comparison value",
                comparator=match.group("relation").lower(),
                anchor_text=match.group("anchor").strip(" .;,)"),
                derivation_rule="relative_text",
                confidence=0.35,
            )
        )
    if candidates:
        return candidates

    match = _ORDINAL_RE.search(raw)
    if match is None:
        return []
    return [
        _candidate_row(
            table_name=table_name,
            row_index=row_index,
            field_name=field_name,
            row=row,
            raw_value=raw,
            context_slots=context_slots,
            source_records=source_records,
            best_guess_context=best_guess_context,
            bound_type="ordinal",
            parsed_min=None,
            parsed_max=None,
            parsed_midpoint=None,
            best_guess_value=None,
            best_guess_basis="ordinal text requires a declared calibration before plotting",
            comparator=match.group("marker").lower(),
            anchor_text="",
            derivation_rule="ordinal_text",
            confidence=0.2,
        )
    ]


def _parse_numeric_value(raw: str) -> dict[str, Any] | None:
    value = raw.strip()

    plus_minus = _PLUS_MINUS_RE.search(value)
    if plus_minus is not None:
        midpoint = _as_float(plus_minus.group("mid"))
        error = abs(_as_float(plus_minus.group("err")))
        return _numeric_payload(
            bound_type="range",
            parsed_min=midpoint - error,
            parsed_max=midpoint + error,
            parsed_midpoint=midpoint,
            best_guess_value=midpoint,
            best_guess_basis="midpoint of a plus/minus expression",
            comparator="",
            anchor_text="",
            derivation_rule="plus_minus",
            confidence=0.95,
        )

    range_match = _RANGE_RE.search(value)
    if range_match is not None:
        low = _as_float(range_match.group("low"))
        high = _as_float(range_match.group("high"))
        if high < low:
            low, high = high, low
        return _numeric_payload(
            bound_type="range",
            parsed_min=low,
            parsed_max=high,
            parsed_midpoint=(low + high) / 2,
            best_guess_value=(low + high) / 2,
            best_guess_basis="midpoint of a reported range",
            comparator="",
            anchor_text="",
            derivation_rule="range",
            confidence=0.95,
        )

    comparator_match = _COMPARATOR_RE.search(value)
    if comparator_match is not None:
        comparator = comparator_match.group("comparator").lower()
        number = _as_float(comparator_match.group("number"))
        is_upper = comparator in {"<", "<=", "\u2264", "less than", "at most", "up to", "no more than"}
        return _numeric_payload(
            bound_type="upper_bound" if is_upper else "lower_bound",
            parsed_min=None if is_upper else number,
            parsed_max=number if is_upper else None,
            parsed_midpoint=None,
            best_guess_value=number,
            best_guess_basis="censored bound value; use only in plots that mark censoring",
            comparator=comparator,
            anchor_text="",
            derivation_rule="leading_comparator",
            confidence=0.85,
        )

    approximate_match = _APPROX_RE.search(value)
    if approximate_match is not None:
        number = _as_float(approximate_match.group("number"))
        return _numeric_payload(
            bound_type="approximate",
            parsed_min=None,
            parsed_max=None,
            parsed_midpoint=number,
            best_guess_value=number,
            best_guess_basis="approximate scalar reported in text",
            comparator=approximate_match.group("marker").lower(),
            anchor_text="",
            derivation_rule="approximate_scalar",
            confidence=0.75,
        )

    number_match = _NUMBER_RE.search(value)
    if number_match is None:
        return None

    number = _as_float(number_match.group("number"))
    return _numeric_payload(
        bound_type="exact",
        parsed_min=number,
        parsed_max=number,
        parsed_midpoint=number,
        best_guess_value=number,
        best_guess_basis="scalar value",
        comparator="",
        anchor_text="",
        derivation_rule="scalar",
        confidence=0.9,
    )


def _candidate_row(
    *,
    table_name: str,
    row_index: int,
    field_name: str,
    row: Mapping[str, Any],
    raw_value: str,
    context_slots: Iterable[ContextSlot | Mapping[str, Any] | str],
    source_records: Mapping[str, Mapping[str, Any]],
    best_guess_context: Mapping[str, Any],
    bound_type: str,
    parsed_min: float | None,
    parsed_max: float | None,
    parsed_midpoint: float | None,
    best_guess_value: float | None,
    best_guess_basis: str,
    comparator: str,
    anchor_text: str,
    derivation_rule: str,
    confidence: float,
) -> dict[str, Any]:
    source_row_key = _numeric_source_row_key(row, row_index)
    payload = {
        "source_table": table_name,
        "source_row_key": source_row_key,
        "source_field": field_name,
        "raw_value": raw_value,
        "bound_type": bound_type,
        "comparator": comparator,
        "anchor_text": anchor_text,
        "derivation_rule": derivation_rule,
    }
    raw_key = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    source_ids = source_ids_from_row(row)
    context = infer_best_guess_context(
        row,
        context_slots=context_slots,
        source_records={
            source_id: source_records[source_id]
            for source_id in source_ids
            if source_id in source_records
        },
    )
    if best_guess_context:
        merged_context = dict(context.get("best_guess_context") or {})
        merged_context.update(dict(best_guess_context))
        context["best_guess_context"] = merged_context
    return {
        "candidate_id": hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:16],
        "source_table": table_name,
        "source_row_index": row_index,
        "source_row_key": source_row_key,
        "source_field": field_name,
        "raw_value": raw_value,
        "bound_type": bound_type,
        "parsed_min": _round_or_none(parsed_min),
        "parsed_max": _round_or_none(parsed_max),
        "parsed_midpoint": _round_or_none(parsed_midpoint),
        "best_guess_value": _round_or_none(best_guess_value),
        "best_guess_basis": best_guess_basis,
        "comparator": comparator,
        "anchor_text": anchor_text,
        "derivation_rule": derivation_rule,
        "confidence": round(confidence, 3),
        **context,
        "source_refs": _source_list(row.get("source_refs")),
        "source_chunks": _source_list(row.get("source_chunks") or row.get("source_chunk")),
        "row_context": _row_context(row),
    }


def _numeric_payload(
    *,
    bound_type: str,
    parsed_min: float | None,
    parsed_max: float | None,
    parsed_midpoint: float | None,
    best_guess_value: float | None,
    best_guess_basis: str,
    comparator: str,
    anchor_text: str,
    derivation_rule: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "bound_type": bound_type,
        "parsed_min": parsed_min,
        "parsed_max": parsed_max,
        "parsed_midpoint": parsed_midpoint,
        "best_guess_value": best_guess_value,
        "best_guess_basis": best_guess_basis,
        "comparator": comparator,
        "anchor_text": anchor_text,
        "derivation_rule": derivation_rule,
        "confidence": confidence,
    }


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "parsed").strip().lower().replace("-", "_")
    if normalized not in {"off", "parsed", "all"}:
        raise ValueError("numeric candidate mode must be 'off', 'parsed', or 'all'")
    return normalized


def _field_can_hold_scalar(field_name: str) -> bool:
    if _numeric_field_should_skip(field_name):
        return False
    tokens = _numeric_field_tokens(field_name)
    return bool(tokens & _SCALAR_FIELD_HINTS)


def _numeric_field_should_skip(field_name: str) -> bool:
    text = str(field_name or "")
    if text.startswith("_"):
        return True
    tokens = _numeric_field_tokens(text)
    return bool(tokens & _SKIP_FIELD_TOKENS)


def _row_context(row: Mapping[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key, value in row.items():
        if len(context) >= 12:
            break
        if _numeric_missing(value) or _numeric_field_tokens(str(key)) & _CONTEXT_SKIP_TOKENS:
            continue
        context[str(key)] = _numeric_compact(value)
    return context


def _numeric_source_row_key(row: Mapping[str, Any], row_index: int) -> str:
    for key in ("row_id", "deduplication_key", "dedup_key", "group_key", "id"):
        value = row.get(key)
        if not _numeric_missing(value):
            return _stringify(value)[:240]

    payload = json.dumps(_row_context(row), sort_keys=True, default=str)
    return f"{row_index}:{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]}"


def _source_list(value: Any) -> list[str]:
    if _numeric_missing(value):
        return []
    if isinstance(value, str):
        values = re.split(r"[,;\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]

    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _stringify(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _numeric_field_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^A-Za-z0-9]+", str(value).lower())
        if token
    }


def _numeric_compact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _numeric_compact(inner)
            for key, inner in list(value.items())[:8]
            if not _numeric_missing(inner)
        }
    if isinstance(value, (list, tuple, set)):
        return [_numeric_compact(item) for item in list(value)[:8] if not _numeric_missing(item)]
    text = _stringify(value)
    return text[:237] + "..." if len(text) > 240 else value


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return " ".join(_stringify(item) for item in value)
    if isinstance(value, Mapping):
        return " ".join(
            f"{key} {_stringify(inner)}"
            for key, inner in value.items()
            if not _numeric_missing(inner)
        )
    return str(value).strip()


def _numeric_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _NUMERIC_MISSING_STRINGS
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _as_float(value: str) -> float:
    return float(value.replace(",", ""))


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 8)


# ============================================================================
# goals.py
# ============================================================================

import hashlib
import itertools
import json
import math
import random
import re
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from question_pipeline.utilities.evidence import is_provenance_name

#: This module kept its own nine-token set until phase 4E-c. `criteria` now owns
#: what "nothing here" means for every consumer, and its set is the union of
#: what five producers meant by absence -- so this module gains nine tokens
#: (`-`, `--`, `<null>`, `[null]`, `not available`, `not found`, `not provided`,
#: `not reported`, `not stated`) and contributes the one no other set had,
#: `"not specified in current evidence"`.
#:
#: THE DIRECTION IS REGISTERED, NOT ASSUMED. This module decides which columns
#: are worth searching for, so more tokens reading as missing means more cells
#: counted missing, more columns judged fillable, more deficits planned and more
#: searches issued.


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
    label: int | str
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
    table_columns: Mapping[str, Sequence[str]] = field(default_factory=dict)
    table_key_columns: Mapping[str, Sequence[str]] = field(default_factory=dict)
    cold_start_columns: Mapping[str, Sequence[str]] = field(default_factory=dict)
    cold_start_anchors: Mapping[
        str,
        Sequence[Mapping[str, str]],
    ] = field(default_factory=dict)
    best_guess_columns: Mapping[str, Sequence[str]] = field(default_factory=dict)
    all_seen_slot_keys: set[str] = field(default_factory=set)
    new_slot_history: list[dict[str, Any]] = field(default_factory=list)

    def prompt_context(
        self,
        table_rows: Mapping[str, list[dict[str, Any]]],
        gaps: Iterable[str],
        universe_estimate: Mapping[str, Any] | None = None,
        completion_state: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        slots = _observed_slots(table_rows, self.table_schemas)
        open_slots = [slot for slot in slots if slot.status != "covered"]
        # Materialized once: `gaps` is an Iterable, and reading it more than
        # once would silently yield an empty list on the second read.
        gap_list = list(gaps)
        return {
            "target_table_names": sorted(
                str(name)
                for name in table_rows
                if str(name).strip()
            ),
            "tables": [
                _table_profile(
                    name,
                    rows,
                    self.table_columns.get(
                        name,
                        self.table_schemas.get(name, ()),
                    ),
                )
                for name, rows in table_rows.items()
            ],
            "observed_slot_count": len(slots),
            "open_observed_slot_count": len(open_slots),
            "observed_slot_counts": _slot_counts(slots),
            "open_observed_slot_counts": _slot_counts(open_slots),
            # KNOWN TRUNCATION, DECLARED, AND STRUCTURALLY STARVING.
            #
            # These two are prompt payload, not a rule about the data, so by
            # the no-truncation principle they should be windows. They are not
            # converted here because the fix is not local: on the live
            # earthquake run's round-2 table there are 270 open slots measuring
            # 786,337 characters against the 103,919 that `[:40]` sends, and
            # this mapping is delivered WHOLE to every deficit-planner call.
            # Unbounding it without giving `strategy.target_deficit_queries` a
            # second windowed axis would put ~870,000 characters into each of
            # that call's windows.
            #
            # The selection is NOT arbitrary, which is worse than if it were.
            # `_observed_slots` sorts by `(slot_type, key)` and `key` is
            # `f"{table}::{index}-{sha1[:12]}"`, so the discriminator is the
            # STRINGIFIED ROW INDEX and the hash only breaks ties. The observed
            # first twelve are `0-, 1-, 10-, 100-, 101-, 102-, ...`:
            # lexicographic on the index string, hence deterministic and
            # identical every round. The same 40 of 270 slots are shown for the
            # life of the run and the other 230 are structurally unreachable --
            # the same self-sustaining starvation removed from the column path
            # in `_incomplete_columns` two hundred lines below, which a reader
            # should not have to rediscover here.
            "sample_open_slots": [
                slot.to_dict() for slot in open_slots[:40]
            ],
            "sample_open_slots_disclosure": {
                "sent": min(40, len(open_slots)),
                "total": len(open_slots),
                "omitted": max(0, len(open_slots) - 40),
                "selection": (
                    "first 40 by lexicographic stringified row index; "
                    "deterministic and STABLE across rounds, so the omitted "
                    "slots never rotate in and are unreachable for the life "
                    "of the run"
                ),
                "rotates_across_rounds": False,
                "reason": "prompt payload not yet windowed; see module note",
            },
            "sample_gaps": gap_list[:40],
            "sample_gaps_disclosure": {
                "sent": min(40, len(gap_list)),
                "total": len(gap_list),
                "omitted": max(0, len(gap_list) - 40),
                "selection": (
                    "first 40 in the caller's gap order; whether the omitted "
                    "gaps rotate depends entirely on the caller, and on the "
                    "table-gap path they do not"
                ),
                "rotates_across_rounds": False,
                "reason": "prompt payload not yet windowed; see module note",
            },
            "current_universe_estimate": compact_estimate_for_prompt(
                universe_estimate,
                table_rows=table_rows,
            ),
            "completion_scope": scope_probe_context(completion_state or {}),
        }

    def evaluate(
        self,
        *,
        artifact_label: int | str,
        table_rows: Mapping[str, list[dict[str, Any]]],
        universe_estimate: Mapping[str, Any] | None,
        search_frontier: Mapping[str, Any],
        search_outcomes: list[dict[str, Any]],
        units_pulled: int,
        unit_budget: int,
        unit_budget_available: bool,
        gap_search_tasks: list[dict[str, Any]],
        goal_search_tasks: list[dict[str, Any]],
        completion_state: Mapping[str, Any] | None = None,
        update_history: bool = True,
    ) -> FillGoalState:
        slots = _observed_slots(table_rows, self.table_schemas)
        slot_keys = {slot.key for slot in slots}
        open_slots = [slot for slot in slots if slot.status != "covered"]
        estimate = normalize_universe_estimate(
            universe_estimate,
            table_rows=table_rows,
        )
        completion = normalize_completion_state(completion_state)
        completion_issues = open_completion_issues(completion)
        completion_bins = open_completion_bins(completion)

        if (
            not update_history
            and self.new_slot_history
            and self.new_slot_history[-1].get("label") == artifact_label
        ):
            new_slots = set(self.new_slot_history[-1].get("new_slots") or [])
        else:
            previous_slots = set(self.all_seen_slot_keys)
            new_slots = slot_keys - previous_slots
            self.all_seen_slot_keys.update(slot_keys)
            self.new_slot_history.append(
                {
                    "label": artifact_label,
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
            if _goals_as_int(target.get("deficit_count")) > 0
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
                "name": "search space probed",
                "satisfied": bool(completion.get("search_space_probes")),
                "detail": (
                    f"{len(completion.get('search_space_probes') or [])} "
                    "search-space probes recorded"
                ),
            },
            {
                "name": "completion estimate consistent",
                "satisfied": (
                    completion.get("scope_status") == "estimated"
                    and not completion_issues
                    and not completion_bins
                ),
                "detail": (
                    f"scope_status={completion.get('scope_status')}; "
                    f"{len(completion_issues)} blocking estimate issues; "
                    f"{len(completion_bins)} underexplored bins"
                ),
            },
            {
                "name": "answer universe estimated",
                "satisfied": estimate.get("status") == "estimated",
                "detail": (
                    f"status={estimate.get('status')}; "
                    f"{_cited_discovery_source_count(estimate)} "
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
                    "source-supported expected counts"
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
                    table_columns=self.table_columns,
                    cold_start_columns=self.cold_start_columns,
                    table_key_columns=self.table_key_columns,
                    cold_start_anchors=self.cold_start_anchors,
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
            "units_pulled": units_pulled,
            # 0 means the run declared no unit bound; a bound is a positive int.
            "unit_budget": unit_budget,
        }
        search_state = {
            **search_frontier,
            "unit_budget_available": unit_budget_available,
        }
        analysis = _analysis_rows(
            criteria=criteria,
            estimate=estimate,
            completion=completion,
            catalog=catalog,
            coverage=coverage,
            search_state=search_state,
        )
        if not unit_budget_available and not fulfilled:
            analysis.append(
                {
                    "scope": "out_of_scope",
                    "outcome": (
                        f"source-unit bound reached at {units_pulled}/{unit_budget}"
                    ),
                    "what_it_means": (
                        "the operator's declared unit bound cut acquisition; "
                        "this is a bound_hit, never convergence"
                    ),
                    "interpretation": (
                        "a bound hit explains an incomplete run; it is not "
                        "evidence that the task-level stop rule was satisfied"
                    ),
                }
            )

        return FillGoalState(
            label=artifact_label,
            mode="table_fill",
            fulfilled=fulfilled,
            stop_rule=(
                "Stop only after search-space breadth probes and retrieved "
                "discovery evidence yield a consistent question-specific "
                "answer-universe estimate, every final record family has a "
                "source-supported realistic expected count, every estimated "
                "count target is covered by the exported answer tables, and "
                "the search frontier has no queued work."
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
                "table_columns": {
                    name: list(columns)
                    for name, columns in self.table_columns.items()
                },
                "table_key_columns": {
                    name: list(columns)
                    for name, columns in self.table_key_columns.items()
                },
                "cold_start_columns": {
                    name: list(columns)
                    for name, columns in self.cold_start_columns.items()
                },
                "cold_start_anchors": {
                    name: [dict(anchor) for anchor in anchors]
                    for name, anchors in self.cold_start_anchors.items()
                },
                "best_guess_columns": {
                    name: list(columns)
                    for name, columns in self.best_guess_columns.items()
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
    fallback_target_table = _sole_deliverable_table(deliverable_tables)
    raw_count_targets = _first_raw_section(raw, "count_targets", "targets")
    raw_unestimated_targets = _first_raw_section(raw, "unestimated_count_targets")
    raw_out_of_scope_targets = _first_raw_section(raw, "out_of_scope_count_targets")

    targets: list[dict[str, Any]] = []
    unestimated_targets: list[dict[str, Any]] = []
    out_of_scope_targets: list[dict[str, Any]] = []
    for raw_index, item in enumerate(_goals_as_list(raw_count_targets)):
        if not isinstance(item, Mapping):
            continue
        target, expected_minimum = _coerce_count_target(
            item,
            raw,
            fallback_index=raw_index + 1,
            fallback_target_table=fallback_target_table,
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

    for raw_index, item in enumerate(_goals_as_list(raw_unestimated_targets)):
        if not isinstance(item, Mapping):
            continue
        target, _ = _coerce_count_target(
            item,
            raw,
            fallback_index=len(targets) + len(unestimated_targets) + raw_index + 1,
            fallback_target_table=fallback_target_table,
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
                    _goals_clean_display(item.get("reason"))
                    or "expected_minimum_count is missing"
                ),
            }
        )

    for raw_index, item in enumerate(_goals_as_list(raw_out_of_scope_targets)):
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
                    _goals_clean_display(item.get("reason"))
                    or _target_table_rejection_reason(
                        str(target.get("target_table") or ""),
                        deliverable_tables,
                    )
                ),
            }
        )

    status = _goals_clean_display(raw.get("status")).lower() or "missing"
    if status not in {"missing", "insufficient_evidence", "estimated"}:
        status = "missing"
    if unestimated_targets:
        status = "insufficient_evidence"
    elif targets and status != "estimated":
        status = "insufficient_evidence"
    elif not targets and status == "estimated":
        status = "insufficient_evidence"

    return {
        "status": status,
        "scope_summary": _goals_clean_display(raw.get("scope_summary")),
        "search_space_summary": _goals_clean_display(raw.get("search_space_summary")),
        "expected_axes": _record_list(raw.get("expected_axes") or raw.get("axes")),
        "underexplored_bins": _record_list(raw.get("underexplored_bins")),
        "estimate_issues": _record_list(
            raw.get("estimate_issues") or raw.get("issues")
        ),
        "count_targets": targets,
        "unestimated_count_targets": unestimated_targets,
        "out_of_scope_count_targets": out_of_scope_targets,
        "supporting_source_ids": _goals_unique(raw.get("supporting_source_ids")),
        "supporting_queries": _goals_unique(raw.get("supporting_queries")),
        "unresolved_questions": _goals_unique(raw.get("unresolved_questions")),
        "suggested_queries": _goals_unique(raw.get("suggested_queries")),
        "raw": dict(raw),
    }


def _cited_discovery_source_count(estimate: Mapping[str, Any]) -> int:
    """Distinct discovery sources the estimate actually cites, at any level.

    Counting only the estimate-level `supporting_source_ids` reports zero
    forever: that list is deliberately never populated, because
    `_coerce_count_target` falls back to it and a union there would let an
    unprobed family inherit another family's sources and clear
    `_target_validation_errors` -- the guard defeated by data rather than by a
    visible change to the guard.

    This number is not decoration. It reaches an LLM prompt that gates whether
    fetched sources are accepted, so an estimate resting on real observations
    must not describe itself as resting on none.
    """

    seen: set[str] = set()
    for source_id in estimate.get("supporting_source_ids") or []:
        text = str(source_id or "").strip()
        if text:
            seen.add(text)
    for target in estimate.get("count_targets") or []:
        if not isinstance(target, Mapping):
            continue
        for source_id in target.get("supporting_source_ids") or []:
            text = str(source_id or "").strip()
            if text:
                seen.add(text)
    return len(seen)


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
        "expected_axes": _merge_records(
            fresh.get("expected_axes") or [],
            base.get("expected_axes") or [],
        ),
        "underexplored_bins": (
            fresh.get("underexplored_bins") or []
            if isinstance(current, Mapping) and "underexplored_bins" in current
            else base.get("underexplored_bins") or []
        ),
        "estimate_issues": (
            fresh.get("estimate_issues") or []
            if (
                isinstance(current, Mapping)
                and ("estimate_issues" in current or "issues" in current)
            )
            else base.get("estimate_issues") or []
        ),
        "count_targets": [
            _attach_observed_count(target, table_rows or {})
            for target in count_targets
        ],
        "unestimated_count_targets": unestimated_targets,
        "out_of_scope_count_targets": out_of_scope,
        "supporting_source_ids": _goals_unique(
            [
                *(base.get("supporting_source_ids") or []),
                *(fresh.get("supporting_source_ids") or []),
            ],
        ),
        "supporting_queries": _goals_unique(
            [
                *(base.get("supporting_queries") or []),
                *(fresh.get("supporting_queries") or []),
            ],
        ),
        "unresolved_questions": _goals_unique(
            [
                *(fresh.get("unresolved_questions") or []),
                *(base.get("unresolved_questions") or []),
            ],
        ),
        "suggested_queries": _goals_unique(
            [
                *(fresh.get("suggested_queries") or []),
                *(base.get("suggested_queries") or []),
            ],
        ),
    }
    if merged["count_targets"] and not merged["unestimated_count_targets"]:
        if "estimated" in {base.get("status"), fresh.get("status")}:
            merged["status"] = "estimated"
        else:
            merged["status"] = "insufficient_evidence"
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


def _merge_records(
    primary: Iterable[Mapping[str, Any]],
    secondary: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in [*list(primary), *list(secondary)]:
        if not isinstance(record, Mapping):
            continue
        payload = dict(record)
        key = (
            _clean_key(payload.get("id"))
            or _clean_key(payload.get("name"))
            or _clean_key(payload.get("axis"))
            or _clean_key(payload.get("description"))
        )
        if not key:
            raw = json.dumps(payload, sort_keys=True, default=str)
            key = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        if key not in merged:
            merged[key] = payload
    return list(merged.values())


def _record_list(value: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _goals_as_list(value):
        if isinstance(item, Mapping):
            records.append(dict(item))
        elif item:
            records.append({"description": str(item)})
    return records


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
    name = _clean_key(target.get("name"))
    if table or name:
        payload = {
            "target_table": table,
            "name": name,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    columns = tuple(
        sorted(_clean_key(column) for column in _goals_as_list(target.get("key_columns")))
    )
    columns = tuple(column for column in columns if column)
    payload = {
        "key_columns": columns,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _first_raw_section(raw: Mapping[str, Any], *keys: str) -> Any:
    """Return a normalized section, falling back to a preserved model payload."""
    for key in keys:
        value = raw.get(key)
        if value:
            return value

    raw_payload = raw.get("raw")
    if not isinstance(raw_payload, Mapping):
        return None

    for key in keys:
        value = raw_payload.get(key)
        if value:
            return value
    return None


def _coerce_count_target(
    item: Mapping[str, Any],
    raw: Mapping[str, Any],
    *,
    fallback_index: int,
    fallback_target_table: str = "",
) -> tuple[dict[str, Any], int]:
    expected_minimum = _goals_as_int(
        item.get("expected_minimum_count")
        or item.get("minimum_expected_count")
        or item.get("min_count")
        or item.get("lower_bound")
    )
    # `expected_count`, `expected_maximum_count` and `expected_count_basis` are
    # gone with the Chao1 estimator that was their only producer. Only the
    # observed census survives: `expected_minimum_count` is a count of rows
    # actually seen, which was the one of the three that was ever a
    # measurement rather than an extrapolation.
    target_table = (
        item.get("target_table")
        or item.get("table_name")
        or item.get("table")
        or item.get("output_table")
        or fallback_target_table
    )
    target = {
        "name": _goals_clean_display(item.get("name")) or f"target_{fallback_index}",
        "description": _goals_clean_display(item.get("description")),
        "target_table": str(target_table or "").strip(),
        "key_columns": [
            str(column).strip()
            for column in _goals_as_list(item.get("key_columns"))
            if str(column).strip()
        ],
        "expected_minimum_count": expected_minimum if expected_minimum > 0 else None,
        "basis": _goals_clean_display(item.get("basis") or item.get("rationale")),
        "supporting_source_ids": _goals_unique(
            item.get("supporting_source_ids")
            or item.get("source_ids")
            or raw.get("supporting_source_ids")
        ),
        # Which namespace those ids live in. Normalization rebuilds targets
        # from a fixed key list, so a kind not carried here is a kind that
        # never reaches a consumer -- and an unlabelled id is one a join has to
        # guess about. Empty means the producer did not say.
        "supporting_source_id_kind": _goals_clean_display(
            item.get("supporting_source_id_kind")
        ),
        "known_missing_examples": _goals_unique(
            item.get("known_missing_examples") or item.get("missing_examples")
        ),
    }
    target["id"] = _target_id(target)
    return target, expected_minimum


def _sole_deliverable_table(deliverable_tables: set[str]) -> str:
    if len(deliverable_tables) != 1:
        return ""
    return sorted(deliverable_tables)[0]


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

    # The circularity regex that stood here matched prose generated by the
    # Chao1 estimator (`\bcurrent-table\b`, `\balready-contains-\d+`, four
    # more) against `expected_count_basis`. Both the estimator and that field
    # are deleted, so the patterns can no longer match anything -- and a
    # predicate that cannot match reads as "no circularity found", which is the
    # silent no-op this campaign exists to remove. It dies with the string it
    # was coupled to rather than being left as reassurance.
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
    expected_minimum = _goals_as_int(target.get("expected_minimum_count"))
    target["observed_count"] = covered
    target["observed_total_count"] = observed
    # ONE EXPRESSION, TWO NAMES -- STATED RATHER THAN LEFT TO BE NOTICED.
    #
    # `deficit_count` used to be `expected_count - covered`, an extrapolated
    # universe minus coverage, while `minimum_deficit_count` was the census
    # minus coverage. With `expected_count` deleted there is one measured
    # number left, so the two are now identical by construction and the second
    # is computed from the first rather than restated.
    #
    # This is a BEHAVIOUR change to the fill scheduler, not only a change in
    # what a number means: a family whose census equals its coverage now
    # reports zero deficit where it previously reported an extrapolated
    # shortfall. It is forced by the deletion -- there is no other number to
    # measure against -- but it is owed a before/after on a recorded run, and
    # that validation belongs to its own change rather than to this one.
    #
    # If the two should ever diverge again, that is a scheduler decision that
    # needs its own justification, not a silent re-widening of this line.
    minimum_deficit = max(0, expected_minimum - covered)
    target["minimum_deficit_count"] = minimum_deficit
    target["deficit_count"] = minimum_deficit
    target["status"] = "covered" if target["deficit_count"] == 0 else "open"
    return target


def _target_id(target: Mapping[str, Any]) -> str:
    payload = {
        "name": _goals_clean_display(target.get("name")),
        "target_table": _goals_clean_display(target.get("target_table")),
        "key_columns": _goals_unique(target.get("key_columns")),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_fill_deficits(
    table_rows: Mapping[str, list[dict[str, Any]]],
    universe_estimate: Mapping[str, Any] | None,
    *,
    table_columns: Mapping[str, Sequence[str]] | None = None,
    cold_start_columns: Mapping[str, Sequence[str]] | None = None,
    table_key_columns: Mapping[str, Sequence[str]] | None = None,
    cold_start_anchors: Mapping[
        str,
        Sequence[Mapping[str, str]],
    ] | None = None,
    max_row_gaps_per_table: int = 4,
    max_total: int = 32,
) -> list[FillDeficit]:
    """Build concrete, generic search deficits for the next fill pass."""
    estimate = normalize_universe_estimate(
        universe_estimate,
        table_rows=table_rows,
    )
    deficits: dict[str, FillDeficit] = {}

    for deficit in _cold_start_fill_deficits(
        table_rows,
        table_columns=cold_start_columns or table_columns or {},
        table_key_columns=table_key_columns or {},
        cold_start_anchors=cold_start_anchors or {},
    ):
        deficits[deficit.id] = deficit

    for target in estimate.get("count_targets") or []:
        if _goals_as_int(target.get("deficit_count")) <= 0:
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


def _cold_start_fill_deficits(
    table_rows: Mapping[str, list[dict[str, Any]]],
    *,
    table_columns: Mapping[str, Sequence[str]],
    table_key_columns: Mapping[str, Sequence[str]],
    cold_start_anchors: Mapping[str, Sequence[Mapping[str, str]]],
) -> list[FillDeficit]:
    """Emit schema-derived demand for every substantively cold declared table.

    Existing deficit producers both depend on observed supply: a count target
    or a row carrying gap prose.  This producer reads only the declared table
    contract and values another declared table has already observed.  It is
    therefore able to ask for the first row without inventing a row or asking
    a model to infer table grain.

    Row count is not evidence that a table has started filling.  A compiler
    may legitimately materialize key-only partial rows before it finds any of
    the table's declared measures.  Such rows remain cold-start inputs: they
    can feed ordinary row-gap deficits, but must not disable schema-owned
    demand for the first substantive value.  A table leaves cold start only
    when at least one non-key, non-plumbing declared field has a value.

    Keys identify the row and never become search targets.  Provenance and
    engine plumbing are excluded for the same reason as `_fill_candidate_columns`.
    A declared cold-start anchor maps one target key to one source column; all
    other target keys remain deliberately unbound.  If no mapped value has
    been observed yet, one unanchored field-scoped deficit keeps the table from
    becoming permanently unreachable.
    """

    out: list[FillDeficit] = []
    for table_name, columns in table_columns.items():
        key_columns = tuple(
            str(column)
            for column in table_key_columns.get(table_name, ())
            if str(column).strip()
        )
        missing_fields = tuple(
            str(column)
            for column in columns
            if (
                str(column).strip()
                and str(column) not in set(key_columns)
                and not str(column).startswith("_")
                and str(column) not in _FILL_COLUMN_SKIP
                and not is_provenance_name(str(column))
            )
        )
        if not missing_fields:
            continue

        rows = table_rows.get(table_name, [])
        if any(
            not _goals_missing(_get_nested(row, column))
            for row in rows
            for column in missing_fields
        ):
            continue

        anchor_sets = _cold_start_anchor_values(
            table_name,
            table_rows,
            cold_start_anchors.get(table_name, ()),
        ) or [{}]
        for anchor_values in anchor_sets:
            description = (
                f"Acquire the first substantive values for declared table "
                f"{table_name}"
            )
            if anchor_values:
                description += " using already observed key values"
            deficit_id = _fill_deficit_id(
                "schema_cold_start",
                table_name,
                table_name,
                missing_fields,
                anchor_values,
            )
            out.append(
                FillDeficit(
                    id=deficit_id,
                    deficit_type="schema_cold_start",
                    target_id=table_name,
                    target_name=table_name,
                    target_table=table_name,
                    # No substantive declared value is the maximum observable
                    # table-level deficit; 100 is the existing top of this
                    # scheduler's priority scale, not a fitted threshold.
                    priority=100.0,
                    description=description,
                    key_columns=key_columns,
                    missing_fields=missing_fields,
                    anchor_values=anchor_values,
                    observed_count=len(rows),
                    row_count=len(rows),
                )
            )
    return out


def _cold_start_anchor_values(
    target_table: str,
    table_rows: Mapping[str, list[dict[str, Any]]],
    anchors: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    """Distinct partial target keys, kept row-local within each source table."""

    by_source: "OrderedDict[str, list[Mapping[str, str]]]" = OrderedDict()
    for anchor in anchors:
        source_table = str(anchor.get("source_table") or "").strip()
        target_column = str(anchor.get("target_column") or "").strip()
        source_column = str(anchor.get("source_column") or "").strip()
        if (
            not source_table
            or not target_column
            or not source_column
            or source_table == target_table
        ):
            continue
        by_source.setdefault(source_table, []).append(anchor)

    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_table, source_anchors in by_source.items():
        for row in table_rows.get(source_table, []):
            mapped: dict[str, Any] = {}
            for anchor in source_anchors:
                value = _get_nested(row, str(anchor.get("source_column") or ""))
                if _goals_missing(value):
                    continue
                mapped[str(anchor.get("target_column"))] = _compact_value(value)
            if not mapped:
                continue
            signature = json.dumps(mapped, sort_keys=True, default=str)
            if signature in seen:
                continue
            seen.add(signature)
            values.append(mapped)
    return values


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
                if not key.startswith("_") and not _goals_missing(value)
            }
            missing_fields = tuple(
                column for column in required if _goals_missing(row.get(column))
            )
            status = _row_status(row, missing_fields)
            key = f"{table_name}::{_goals_stable_row_key(row, index)}"
            slots[key] = TargetSlot(
                key=key,
                slot_type=table_name,
                status=status,
                table=table_name,
                values=_sample_row_values(values),
                missing_fields=missing_fields,
                source_refs=tuple(_goals_unique(row.get("source_refs"))),
            )
    return sorted(slots.values(), key=lambda slot: (slot.slot_type, slot.key))


def _analysis_rows(
    *,
    criteria: list[dict[str, Any]],
    estimate: dict[str, Any],
    completion: dict[str, Any],
    catalog: dict[str, Any],
    coverage: dict[str, Any],
    search_state: dict[str, Any],
) -> list[dict[str, Any]]:
    count_targets = estimate.get("count_targets") or []
    unestimated_targets = estimate.get("unestimated_count_targets") or []
    completion_issues = open_completion_issues(completion)
    completion_bins = open_completion_bins(completion)
    rows = [
        {
            "scope": "in_scope",
            "outcome": (
                f"{len(completion.get('search_space_probes') or [])} "
                "search-space probes recorded"
            ),
            "what_it_means": (
                "the completion estimate needs broad external samples before "
                "it can bound how much the final tables should cover"
            ),
            "interpretation": _criterion_detail(criteria, "search space probed"),
        },
        {
            "scope": "in_scope",
            "outcome": (
                f"completion scope status is {completion.get('scope_status')} "
                f"with {len(completion_issues)} blocking issue(s) and "
                f"{len(completion_bins)} underexplored bin(s)"
            ),
            "what_it_means": (
                "the scoping critic must clear suspicious estimates and "
                "underexplored regions before the stop rule can pass"
            ),
            "interpretation": _criterion_detail(
                criteria,
                "completion estimate consistent",
            ),
        },
        {
            "scope": "in_scope",
            "outcome": f"answer-universe estimate status is {estimate.get('status')}",
            "what_it_means": (
                "the stop rule needs searched discovery evidence before it can "
                "judge how large the final answer should be"
            ),
            "interpretation": _criterion_detail(criteria, "answer universe estimated"),
        },
        {
            "scope": "in_scope",
            "outcome": f"{len(count_targets)} count targets estimated",
            "what_it_means": (
                "each count target is a question-specific lower bound that the "
                "exported answer tables must meet"
            ),
            "interpretation": _criterion_detail(criteria, "count targets estimated"),
        },
        {
            "scope": "in_scope",
            "outcome": f"{len(unestimated_targets)} target families still unquantified",
            "what_it_means": (
                "every final row family needs a searched lower bound before "
                "the run can know what complete means"
            ),
            "interpretation": _criterion_detail(
                criteria,
                "all target families quantified",
            ),
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
            "interpretation": _criterion_detail(
                criteria,
                "all estimated count targets covered",
            ),
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
            "interpretation": _criterion_detail(criteria, "search frontier drained"),
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


def _criterion_detail(criteria: Sequence[Mapping[str, Any]], name: str) -> str:
    for criterion in criteria:
        if criterion.get("name") == name:
            return str(criterion.get("detail") or "")
    return ""


def _table_profile(
    name: str,
    rows: list[dict[str, Any]],
    schema_columns: Sequence[str],
) -> dict[str, Any]:
    # Every row is scanned for column names. `rows[:50]` hid any column whose
    # first non-missing appearance is past row 50, so the profile told the
    # planner the table had fewer columns than it has -- the same defect as the
    # `rows[:200]` in `_fill_candidate_columns`, on the same data. Collecting
    # names costs nothing; it is the `sample_rows` below that costs prompt.
    columns: list[str] = list(schema_columns)
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return {
        "name": name,
        "rows": len(rows),
        "columns": columns,
        "sample_rows": [_sample_row_values(row) for row in rows[:5]],
    }


def _final_row_signature(
    row: Mapping[str, Any],
    final_key_columns: Sequence[str],
    index: int,
) -> str:
    values = {
        column: _clean_key(_get_nested(row, column))
        for column in final_key_columns
        if not _goals_missing(_get_nested(row, column))
    }
    if values:
        return _stable_signature(values)
    return _goals_stable_row_key(row, index)


def _source_refs(row: Mapping[str, Any]) -> list[str]:
    for column in ("source_refs", "source_ids", "source_id"):
        value = row.get(column)
        if _goals_missing(value):
            continue
        if isinstance(value, str):
            text = value.strip()
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
            return _goals_unique(_goals_as_list(parsed))
        return _goals_unique(_goals_as_list(value))
    return []


def _stable_signature(values: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(sorted(values.items())),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def compact_estimate_for_prompt(
    estimate: Mapping[str, Any] | None,
    *,
    table_rows: Mapping[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    normalized = normalize_universe_estimate(estimate, table_rows=table_rows)
    # `scope_summary` is deliberately NOT forwarded into the prompt. It is
    # producer prose describing how a count was derived, and on a seeded or
    # resumed run it is inherited verbatim from an artifact written by the
    # deleted Chao1 estimator -- "Counts are Chao1 richness estimates over the
    # observed sample...". That string round-tripped out of a stored estimate
    # and back into a live prompt, describing machinery that no longer exists
    # to a model that would plan against it.
    #
    # Dropped here rather than stripped during normalization on purpose:
    # rewriting a recorded artifact's prose would be backfilling history, and
    # deleting it by matching the word "chao1" would be the name-based
    # classification this campaign keeps removing. The stored artifact keeps
    # what it always said; the prompt simply stops carrying a description of
    # how a count was made, because no count is made.
    return {
        "status": normalized.get("status"),
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
                    "minimum_deficit_count",
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
        "expected_axes": [
            {
                key: axis.get(key)
                for key in (
                    "name",
                    "description",
                    "status",
                )
            }
            for axis in normalized.get("expected_axes", [])[:10]
        ],
        "underexplored_bins": normalized.get("underexplored_bins", [])[:10],
        "estimate_issues": normalized.get("estimate_issues", [])[:10],
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
    table_name = _goals_clean_display(target.get("target_table"))
    rows = table_rows.get(table_name, [])
    expected_minimum = _goals_as_int(target.get("expected_minimum_count"))
    observed = _goals_as_int(target.get("observed_count"))
    deficit_count = _goals_as_int(target.get("deficit_count"))
    shortfall_ratio = deficit_count / max(expected_minimum, 1)
    key_columns = tuple(_goals_unique(target.get("key_columns")))
    missing_fields = tuple(_incomplete_columns(rows, key_columns))
    description = (
        _goals_clean_display(target.get("description"))
        or _goals_clean_display(target.get("name"))
        or f"Fill missing rows for {table_name}"
    )
    target_id = _goals_clean_display(target.get("id"))
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
        target_name=_goals_clean_display(target.get("name")),
        target_table=table_name,
        priority=80 + min(20.0, shortfall_ratio * 20),
        description=description,
        key_columns=key_columns,
        missing_fields=missing_fields,
        expected_minimum_count=expected_minimum,
        observed_count=observed,
        deficit_count=deficit_count,
        row_count=len(rows),
        known_missing_examples=tuple(_goals_unique(target.get("known_missing_examples"))),
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
    missing_fields = tuple(_incomplete_columns([row for _, row in gapped], columns))
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
        row_missing_fields = tuple(_missing_columns(row, columns))
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
    """Columns a fill pass could plausibly fill by searching for something.

    Provenance columns are excluded by naming convention rather than by an
    enumerated list. `_FILL_COLUMN_SKIP` catches exact spellings only, so a
    per-field sidecar like `affected country_source_chunks` slipped past it and
    was counted as an empty column with a deficit against it -- and once column
    truncation was removed, every such sidecar surfaced and became a search
    target. Nothing external describes its data as a chunk id, so those
    searches cannot succeed by construction.

    The predicate is `provenance.is_provenance_name`, the same one `criteria`
    uses to refuse provenance as a datapoint. Sharing it is the intent: a
    column this module sends the run looking for should not be one that module
    would refuse to credit.

    That intent is only half realised, and the docstring used to claim it whole.
    The two agree in one direction -- nothing this function proposes is
    rejected by `criteria` as provenance -- but not in the other: the extra
    filters here (`_FILL_COLUMN_SKIP`, and the suffix rules the two consumers
    keep privately) exclude 13 columns that `criteria` will happily credit, so
    the run refuses to search for columns it would score. The disagreement is
    one-directional and it is 13 columns wide, not zero. Stating it as
    agreement is how the next reader stops checking.

    Every row is scanned. The `rows[:200]` that was here was the same defect
    this docstring already claims to have removed, one layer out: it bounded
    the row scan instead of the column list, so a column that first appears in
    row 200 or later is never proposed as a fill target and therefore never
    filled, in this round or any later one. Measured on the live earthquake
    run's round-2 table (303 rows, 206 filled columns): 90 columns were visible
    through `rows[:200]` and 116 were not -- 56% of the table, including
    `country`, `deaths_reported`, `damage`, `displaced_people`,
    `direct_economic_impact`, and three of the four infrastructure-indicator
    columns, among them the best-filled one in the run. This scan is O(rows x
    columns) over data already in memory; there was no cost being bought.
    """

    columns: list[str] = []
    for row in rows:
        for column in row:
            if (
                column.startswith("_")
                or column in _FILL_COLUMN_SKIP
                or is_provenance_name(column)
            ):
                continue
            if column not in columns:
                columns.append(column)
    return columns


def _incomplete_columns(
    rows: list[dict[str, Any]],
    columns: Sequence[str],
) -> list[str]:
    """Every column with at least one missing cell, worst first. No truncation.

    The truncation this replaced was self-sustaining rather than merely lossy.
    A caller keeping a prefix decides which columns are searchable by where
    they fall in the order; columns tied on missing count were ordered by name,
    so the prefix selected by spelling. A column below the cut is never
    searched, so it stays empty, so it stays tied, so it is below the cut again
    next round -- unreachable at any number of rounds. On one recorded run,
    capitalisation was the only reason any indicator column ever surfaced, and
    thirty-one columns tied at zero fill competed for eight places.

    No sort key fixes that, because the columns are tied on the very quantity
    any key would rank them by. Only returning all of them does. A fill-ratio
    tie-break in particular cannot help: every column here is measured over the
    same rows, so the ratio is the missing count over a shared denominator and
    ties on one exactly when it ties on the other.

    Ordering is therefore by severity with the name last purely for
    determinism, which is safe precisely because nothing is dropped. Callers
    that cannot afford the whole list should shrink values, not drop columns.
    """

    if not rows or not columns:
        return []

    measured = [
        (sum(1 for row in rows if _goals_missing(_get_nested(row, column))), column)
        for column in columns
    ]
    return [
        column
        for missing, column in sorted(measured, key=lambda item: (-item[0], item[1]))
        if missing > 0
    ]


def _missing_columns(row: Mapping[str, Any], columns: Sequence[str]) -> list[str]:
    return [column for column in columns if _goals_missing(_get_nested(row, column))]


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
        # Same display-vs-serialized spelling as the missing-column counts: a
        # raw lookup returns nothing, so a deficit carries no anchors at all
        # and query generation has only field names left to work from.
        value = _get_nested(row, column)
        if _goals_missing(value):
            continue
        anchors[column] = _compact_value(value)
    return anchors


def _row_evidence_gap(row: Mapping[str, Any]) -> str:
    for column in ("evidence_gap", "gap", "caveats"):
        value = _goals_clean_display(row.get(column))
        if value:
            return value
    return ""


def _row_gap_score(row: Mapping[str, Any], columns: Sequence[str]) -> int:
    return (
        len(_anchor_values(row, columns)) * 2
        + len(_missing_columns(row, columns))
    )


#: Bumped whenever the hashed payload below changes meaning, so a deficit id
#: minted under one definition can never be silently joined to one minted under
#: another. `search_memory` joins on these ids and persisted artifacts already
#: carry them, so a change in what they hash is a change in what a join means.
#:
#: v2: `_sample_row_values` stopped capping at sixteen fields, so `anchor_values`
#: now covers the whole row and every id changed. Without this marker that
#: reads downstream as every deficit being new, which is a trend rather than
#: the refused comparison it should be -- the same argument `reward.py` makes
#: for `REWARD_VERSION`, applied to the identifier that keys the join.
FILL_DEFICIT_ID_VERSION = "v2"


def _fill_deficit_id(
    deficit_type: str,
    table_name: str,
    anchor: str,
    missing_fields: Sequence[str],
    anchor_values: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "anchor": _goals_clean_display(anchor),
        "anchor_values": _sample_row_values(anchor_values or {}),
        "deficit_type": deficit_type,
        "missing_fields": list(missing_fields),
        "table_name": table_name,
        "id_version": FILL_DEFICIT_ID_VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _row_status(row: Mapping[str, Any], missing_fields: Sequence[str]) -> str:
    completeness = _goals_clean_display(row.get("completeness")).lower()
    if completeness == "complete":
        return "covered"
    if completeness:
        return "open"
    evidence_gap = _goals_clean_display(row.get("evidence_gap")).lower()
    if evidence_gap and evidence_gap not in {"none", "no gap", "complete"}:
        return "open"
    return "open" if missing_fields else "covered"


def _identity_values(row: Mapping[str, Any]) -> dict[str, Any]:
    """Every non-missing field of a row, whole, for hashing into an identity.

    Identity has no prompt budget, so nothing here is shortened. The previous
    identity hashed `_sample_row_values`, which kept the first sixteen fields
    in dict-insertion order and compacted each value to 240 characters. Both
    parts were wrong for an identity and wrong in opposite directions.

    The field cap made identity a function of position. On the live earthquake
    run the sixteen fields it selected were `src_id`, `tgt_id`, `relation_type`,
    `description`, `attributes`, `source_refs`, `source_chunks`, `source_chunk`,
    `attribute_evidence`, `observation_quote`, `entity_name`, `entity_type`,
    `path_depth`, `id`, `row_id`, `deduplication_key` -- not one of them
    semantic. `atomic_fact_type`, `fact_value`, `country_or_location_qualifier`
    and `temporal_qualifier_or_nearest_year` all sort past position sixteen and
    were excluded. A key built from `row_id`, `src_id` and `source_refs` can
    only ever answer "every row is distinct", which is what it did.

    The 240-character value clip was the opposite failure: it merges two rows
    that differ only past character 237 into one identity. A cap that both
    over-splits on position and under-splits on length is not a bound on
    anything, so there is none here.

    This does NOT on its own make row recapture measurable: the fields it now
    includes still contain per-row provenance, so rows stay distinct. What it
    removes is a truncation masquerading as an identity rule. The recapture
    problem is a separate, measured finding about the counting unit.
    """

    return {
        str(key): value
        for key, value in row.items()
        if not _goals_missing(value)
    }


def _goals_stable_row_key(row: Mapping[str, Any], index: int) -> str:
    payload = json.dumps(
        _identity_values(row),
        ensure_ascii=True,
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{index}-{digest}"


def _sample_row_values(row: Mapping[str, Any]) -> dict[str, Any]:
    """Every non-missing field of a row, for display inside a prompt.

    No field cap. The cap that was here decided which of a row's columns a
    model was allowed to see by their position in the row's key order, and the
    positions that lose are the ones added most recently -- which in a
    table-fill run are exactly the columns the run just learned to want.

    `_compact_value` still shortens an individual oversized cell and marks it
    with an ellipsis. That is a remaining truncation, not a defended bound; it
    is visible in the emitted value rather than silent, and removing it needs
    rows delivered across windows rather than one shorter row.
    """

    return {
        str(key): _compact_value(value)
        for key, value in row.items()
        if not _goals_missing(value)
    }


def _compact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _compact_value(inner)
            for key, inner in list(value.items())[:8]
            if not _goals_missing(inner)
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
        if part in current:
            current = current[part]
            continue
        resolved = _resolve_column_key(current, part)
        if resolved is None:
            return None
        current = current[resolved]
    return current


def _resolve_column_key(row: Mapping[str, Any], column: str) -> str | None:
    """Match a column name to a row key differing only in presentation.

    Count targets carry display names -- "epicenter country" -- while exported
    rows key on the serialized form, "epicenter_country". Compared raw, every
    lookup misses, and a miss is indistinguishable from an empty cell: the join
    fails silently instead of erroring. Downstream that reads as a table with
    almost nothing in it, so `observed_count` stays near zero, the deficit
    never shrinks, and the target's priority stays pinned at its ceiling for
    the life of the run.

    Same defect class as the family-name join in `estimator`: one side of a
    join normalized, the other not. Resolution here is exact equality under
    `_clean_key` -- never a similarity guess -- a direct hit always wins, and
    when two row keys normalize alike the first in row order is taken.
    """

    wanted = _clean_key(column)
    if not wanted:
        return None
    for key in row:
        if _clean_key(key) == wanted:
            return key
    return None


def _goals_as_list(values: Any) -> list[Any]:
    if values is None:
        return []
    if isinstance(values, list):
        return values
    if isinstance(values, (tuple, set)):
        return list(values)
    return [values]


def _goals_as_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _optional_int(value: Any) -> int | None:
    coerced = _goals_as_int(value)
    return coerced if coerced > 0 else None


def _clean_key(value: Any) -> str:
    value = _goals_clean_display(value)
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _goals_clean_display(value: Any) -> str:
    if _goals_missing(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


#: One owner, one predicate. `criteria.is_missing_value` already collapses
#: whitespace as well as casefolding, so a cell reading `"not  specified"` is
#: absence here where it was a value before -- disclosed rather than slipped in.
_goals_missing = is_missing_value


def _goals_unique(values: Any) -> list[str]:
    if _goals_missing(values):
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        values = [values]

    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if _goals_missing(value):
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


# ============================================================================
# best_guess.py
# ============================================================================

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
import asyncio
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

from question_pipeline.utilities.model import measured_size, window_items, window_stamps


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
_BEST_GUESS_UUID_CHUNK_RE = re.compile(r"^(?P<source_id>.+)_chunk_(?P<index>\d+)$")

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
    reported_alternatives_by_table: Mapping[
        str, Mapping[str, Sequence[str]]
    ] | None = None,
    subject_key_columns_by_table: Mapping[str, Sequence[str]],
    source_id: str,
    evidence_chunks: Sequence[Mapping[str, Any]] = (),
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
        subject_keys = tuple(subject_key_columns_by_table.get(table) or ())
        if not subject_keys or any(
            is_missing_value(values.get(column)) for column in subject_keys
        ):
            continue
        row_values = dict(values)
        for best_guess_column, reported_columns in (
            (reported_alternatives_by_table or {}).get(table) or {}
        ).items():
            if any(
                _is_exact_reported_number(row_values.get(column))
                for column in reported_columns
            ):
                # Internal task-suppression marker only. It is never returned
                # as an extracted or accepted best-guess cell.
                row_values[best_guess_column] = row_values.get(
                    next(
                        column
                        for column in reported_columns
                        if _is_exact_reported_number(row_values.get(column))
                    )
                )
        position = len(rows_by_name[table])
        rows_by_name[table].append(row_values)
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

    # At page grain, best guesses are LLM-reasoned evidence only. Deterministic
    # same-row propagation belongs to downstream table recovery and cannot
    # manufacture a page-level best-guess evidence type.
    candidates: list[BestGuessCandidate] = []

    # `sibling_row_scan` is deliberately not run at this grain. Its ceiling is
    # 0.78 and `_accepted` requires 0.8 for it, so it can produce no accepted
    # candidate -- and its premise, that the rows it scans share provenance, is
    # trivially true within one page, which is the least independent evidence
    # there is. Repeats within one source are propagation of that source.

    if extract_fn is not None and evidence_chunks:
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
                    dict(item)
                    for item in evidence_chunks
                    if str(item.get("source_chunk") or "")
                    in set(task.source_chunks)
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


_EXACT_REPORTED_NUMBER_RE = re.compile(
    r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?"
)


def _is_exact_reported_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    return _EXACT_REPORTED_NUMBER_RE.fullmatch(str(value).strip()) is not None


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
            match = _BEST_GUESS_UUID_CHUNK_RE.match(str(reference))
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
        current["field_hints"] = _best_guess_unique(
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
        for column in _best_guess_as_list(target.get("key_columns")):
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
        for column in _best_guess_as_list(columns):
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
        columns = _best_guess_observed_columns(rows)
        for column, target in sorted(targets.items()):
            field_hints = _best_guess_unique(
                [
                    column,
                    *list(target.get("field_hints") or []),
                    *_field_hints(column, columns),
                ],
            )
            if not field_hints and not _slot_is_derivable(column):
                continue
            missing_count = sum(1 for row in rows if _best_guess_missing(row.get(column)))
            if missing_count <= 0:
                continue
            observed_count = max(0, len(rows) - missing_count)
            plans.append(
                BestGuessSlotPlan(
                    id=_best_guess_stable_id({"table": table, "column": column}),
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
            source_row_key = _best_guess_source_row_key(row, row_index)
            source_ids = tuple(source_ids_from_row(row))
            source_chunks = tuple(_source_chunks_from_row(row))
            row_values = _row_values(row)
            for slot in by_table.get(table, ()):
                if not _best_guess_missing(row.get(slot.canonical_column)):
                    continue
                task_id = _best_guess_stable_id(
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
            "source_ids": _best_guess_unique(
                source_id
                for candidate in agreeing
                for source_id in candidate.source_ids
            ),
            "source_chunks": _best_guess_unique(
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
        _best_guess_clean_field_name(hint)
        for hint in slot.field_hints
        if _best_guess_clean_field_name(hint)
    }
    hits: list[dict[str, Any]] = []
    for field, value in _best_guess_flatten(row):
        field_key = _best_guess_clean_field_name(field)
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
        id=_best_guess_stable_id(payload),
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
        for match in [_BEST_GUESS_UUID_CHUNK_RE.match(value)]
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
    return _best_guess_unique(hints)


def _slot_is_derivable(column: str) -> bool:
    tokens = _best_guess_field_tokens(column)
    return bool(tokens) and not bool(
        tokens & (_SLOT_SKIP_TOKENS | _NON_DERIVED_SLOT_TOKENS)
    )


def _best_guess_observed_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(str(column))
    return columns


def _best_guess_source_row_key(row: Mapping[str, Any], row_index: int) -> str:
    for key in ("row_id", "deduplication_key", "dedup_key", "group_key", "id"):
        value = row.get(key)
        if not _best_guess_missing(value):
            return str(value)[:240]

    payload = json.dumps(_row_values(row), sort_keys=True, default=str)
    return f"{row_index}:{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]}"


def _row_values(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if len(out) >= 24:
            break
        if _best_guess_missing(value):
            continue
        if _best_guess_field_tokens(str(key)) & _ROW_CONTEXT_SKIP_TOKENS:
            continue
        out[str(key)] = _best_guess_compact(value)
    return out


def _source_chunks_from_row(row: Mapping[str, Any]) -> list[str]:
    values = [
        *_best_guess_as_source_list(row.get("source_chunks")),
        *_best_guess_as_source_list(row.get("source_chunk")),
    ]
    return _best_guess_unique(str(value) for value in values if value)


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
        if key == "text" or _best_guess_missing(inner):
            continue
        if isinstance(inner, Mapping):
            compact = _compact_mapping(inner)
            if compact:
                out[str(key)] = compact
        elif isinstance(inner, (list, tuple, set)):
            compact_list = [_best_guess_compact(item) for item in list(inner) if not _best_guess_missing(item)]
            if compact_list:
                out[str(key)] = compact_list
        else:
            out[str(key)] = _best_guess_compact(inner)
    return out


def _best_guess_compact(value: Any) -> Any:
    # No truncation. Oversized evidence is handled by windowing the call, not
    # by silently clipping the value the model is asked to reason about.
    return value


def _best_guess_flatten(
    value: Mapping[str, Any],
    *,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 2,
) -> Iterable[tuple[str, Any]]:
    for key, inner in value.items():
        field = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(inner, Mapping) and depth < max_depth:
            yield from _best_guess_flatten(inner, prefix=field, depth=depth + 1)
        else:
            yield field, inner


def _best_guess_field_tokens(field: str) -> set[str]:
    field = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(field))
    return {
        token
        for token in re.split(r"[^A-Za-z0-9]+", field.lower())
        if token
    }


def _field_signature(field: str) -> tuple[str, ...]:
    filler = {"field", "label", "name", "type", "value", "values"}
    return tuple(sorted(_best_guess_field_tokens(field) - filler))


def _best_guess_clean_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9_.]+", "_", str(value or "").lower()).strip("_.")


def _clean_value(value: Any) -> str:
    if _best_guess_missing(value):
        return ""
    text = re.sub(r"\s+", " ", str(value).strip())
    return text[:500]


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _best_guess_stable_id(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _best_guess_as_list(values: Any) -> list[Any]:
    if _best_guess_missing(values):
        return []
    if isinstance(values, list):
        return values
    if isinstance(values, (tuple, set)):
        return list(values)
    return [values]


def _best_guess_as_source_list(values: Any) -> list[Any]:
    if _best_guess_missing(values):
        return []
    if isinstance(values, str):
        try:
            parsed = json.loads(values)
        except json.JSONDecodeError:
            return [value.strip(" \t\r\n\"'[]") for value in re.split(r"[,;\s]+", values)]
        return _best_guess_as_source_list(parsed)
    return _best_guess_as_list(values)


def _best_guess_unique(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if _best_guess_missing(value):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


#: One owner, one predicate: `criteria.is_missing_value`.
_best_guess_missing = is_missing_value


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
