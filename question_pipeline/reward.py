"""Reward scoring for generic table-fill artifact snapshots."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .derived_context import source_ids_from_row


REWARD_COMPONENT_COLUMNS = [
    "component",
    "direction",
    "raw_value",
    "weight",
    "score",
    "transform",
    "interpretation",
]

REWARD_VERSION = "table_fill_v3"

_SOURCE_DEPTH_TARGET = 3

_MISSING_STRINGS = {
    "",
    "n/a",
    "na",
    "none",
    "not applicable",
    "not available",
    "not found",
    "not provided",
    "not reported",
    "not specified",
    "not stated",
    "null",
    "[null]",
    "<null>",
    "unknown",
}

_PROVENANCE_FIELDS = {
    "candidate_id",
    "chunk_id",
    "chunk_ids",
    "context",
    "dedup_key",
    "doi",
    "evidence",
    "evidence_text",
    "path",
    "pmid",
    "quote",
    "quotes",
    "ref",
    "refs",
    "reference",
    "references",
    "row_context",
    "row_id",
    "source",
    "source_chunk",
    "source_chunks",
    "source_file",
    "source_id",
    "source_ids",
    "source_path",
    "source_ref",
    "source_refs",
    "source_row_index",
    "source_row_key",
    "source_text",
    "source_title",
    "source_url",
    "title",
    "url",
}

_STRUCTURAL_FIELDS = {
    "aliases",
    "deduplication_key",
    "description",
    "entity_name",
    "entity_type",
    "evidence_gap",
    "group_key",
    "group_name",
    "id",
    "path_depth",
    "relation_type",
    "src_id",
    "table_name",
    "tgt_id",
}

_PROVENANCE_PREFIXES = (
    "source_ref_",
    "source_refs_",
    "source_chunk_",
    "source_chunks_",
    "evidence_",
    "quote_",
)

_PROVENANCE_SUFFIXES = (
    "_candidate_id",
    "_chunk_id",
    "_dedup_key",
    "_evidence",
    "_evidence_text",
    "_pmid",
    "_reference",
    "_references",
    "_row_id",
    "_source_chunk",
    "_source_chunks",
    "_source_id",
    "_source_ids",
    "_source_ref",
    "_source_refs",
    "_source_url",
)


@dataclass
class _Coverage:
    cell_values: set[tuple[str, str, str]] = field(default_factory=set)
    source_ids: set[str] = field(default_factory=set)
    source_backed_cell_values: set[tuple[str, str, str]] = field(default_factory=set)
    cell_value_sources: dict[tuple[str, str, str], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )

    @property
    def source_backed_value_units(self) -> int:
        return sum(
            min(len(source_ids), _SOURCE_DEPTH_TARGET)
            for source_ids in self.cell_value_sources.values()
        )

    @property
    def excess_value_source_repeats(self) -> int:
        return sum(
            max(0, len(source_ids) - _SOURCE_DEPTH_TARGET)
            for source_ids in self.cell_value_sources.values()
        )

    def to_counts(self) -> dict[str, int]:
        return {
            "cell_values": len(self.cell_values),
            "source_ids": len(self.source_ids),
            "source_backed_cell_values": len(self.source_backed_cell_values),
            "source_backed_value_units": self.source_backed_value_units,
            "excess_value_source_repeats": self.excess_value_source_repeats,
        }


def score_table_fill_snapshot(
    previous_rows_by_name: Mapping[str, list[dict[str, Any]]] | None,
    current_rows_by_name: Mapping[str, list[dict[str, Any]]] | None,
    *,
    best_guess_state: Mapping[str, Any] | None = None,
    previous_best_guess_rows: Iterable[Mapping[str, Any]] | None = None,
    scored_fields_by_table: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Score one table-fill artifact by marginal, source-backed table progress."""

    previous = _coverage(
        previous_rows_by_name or {},
        scored_fields_by_table=scored_fields_by_table,
    )
    current = _coverage(
        current_rows_by_name or {},
        scored_fields_by_table=scored_fields_by_table,
    )
    previous_best_guess_keys = _best_guess_keys(previous_best_guess_rows or [])
    current_best_guess_keys = _best_guess_keys(
        (best_guess_state or {}).get("resolutions") or []
    )

    raw_values = {
        "new_cell_values": len(current.cell_values - previous.cell_values),
        "new_source_ids": len(current.source_ids - previous.source_ids),
        "new_source_backed_cell_values": len(
            current.source_backed_cell_values
            - previous.source_backed_cell_values
        ),
        "new_source_backed_value_units": max(
            0,
            current.source_backed_value_units
            - previous.source_backed_value_units,
        ),
        "new_best_guess_slots": len(
            current_best_guess_keys - previous_best_guess_keys
        ),
        "new_excess_value_source_repeats": max(
            0,
            current.excess_value_source_repeats
            - previous.excess_value_source_repeats,
        ),
    }

    components = [
        _component(
            "new_source_backed_cell_values",
            raw_values["new_source_backed_cell_values"],
            3.0,
            "New distinct declared table field/value facts with source provenance.",
        ),
        _component(
            "new_source_backed_value_units",
            raw_values["new_source_backed_value_units"],
            1.0,
            "New capped independent source support for declared field/value facts.",
        ),
        _component(
            "new_cell_values",
            raw_values["new_cell_values"],
            0.8,
            "New distinct declared field/value observations across tables.",
        ),
        _component(
            "new_best_guess_slots",
            raw_values["new_best_guess_slots"],
            1.5,
            "New recovered best-guess slots with accepted candidates.",
        ),
        _component(
            "new_source_ids",
            raw_values["new_source_ids"],
            1.0,
            "New distinct cited sources represented in tables.",
        ),
        _component(
            "new_excess_value_source_repeats",
            raw_values["new_excess_value_source_repeats"],
            -1.2,
            "New repeated source support beyond the per-field/value depth target.",
        ),
    ]

    positive_score = round(
        sum(max(0.0, float(row["score"])) for row in components),
        6,
    )
    penalty_score = round(
        sum(min(0.0, float(row["score"])) for row in components),
        6,
    )
    score = round(positive_score + penalty_score, 6)

    return {
        "reward_version": REWARD_VERSION,
        "score": score,
        "positive_score": positive_score,
        "penalty_score": penalty_score,
        "normalized_score": _normalized_score(score, positive_score),
        "source_depth_target": _SOURCE_DEPTH_TARGET,
        "coverage": {
            "previous": previous.to_counts(),
            "current": current.to_counts(),
            "delta": raw_values,
        },
        "best_guess": {
            "previous_resolved_slots": len(previous_best_guess_keys),
            "current_resolved_slots": len(current_best_guess_keys),
            "new_resolved_slots": raw_values["new_best_guess_slots"],
        },
        "components": components,
        "analysis": _analysis(raw_values, score),
    }


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
        for json_path in sorted(directory.glob("round_*_best_guess_context.json")):
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
            keys = _best_guess_keys([row_dict])
            key = next(iter(keys)) if keys else _stable_json(row_dict)
            if key in seen:
                continue
            seen.add(key)
            merged.append(row_dict)
    return merged


def _coverage(
    rows_by_name: Mapping[str, list[dict[str, Any]]],
    *,
    scored_fields_by_table: Mapping[str, Iterable[str]] | None = None,
) -> _Coverage:
    coverage = _Coverage()
    for table_name, rows in rows_by_name.items():
        table = str(table_name or "").strip()
        if not table:
            continue
        scored_fields = _scored_fields(scored_fields_by_table, table)
        for row in rows or []:
            if not isinstance(row, Mapping):
                continue
            semantic_cells = _semantic_cells(row, scored_fields=scored_fields)

            row_source_ids = set(source_ids_from_row(row))
            for field, value in semantic_cells:
                coverage.cell_values.add((table, field, value))
                if row_source_ids:
                    cell_key = (table, field, value)
                    coverage.source_backed_cell_values.add(cell_key)
                    coverage.cell_value_sources[cell_key].update(row_source_ids)

            coverage.source_ids.update(row_source_ids)
    return coverage


def _component(
    name: str,
    raw_value: int,
    weight: float,
    interpretation: str,
) -> dict[str, Any]:
    magnitude = math.sqrt(max(0, raw_value))
    score = round(weight * magnitude, 6)
    return {
        "component": name,
        "direction": "minimize" if weight < 0 else "maximize",
        "raw_value": raw_value,
        "weight": weight,
        "score": score,
        "transform": "signed_sqrt",
        "interpretation": interpretation,
    }


def _analysis(raw_values: Mapping[str, int], score: float) -> list[dict[str, Any]]:
    novel = (
        raw_values.get("new_source_backed_cell_values", 0)
        + raw_values.get("new_source_backed_value_units", 0)
        + raw_values.get("new_best_guess_slots", 0)
    )
    repeated_sources = raw_values.get("new_excess_value_source_repeats", 0)
    return [
        {
            "scope": "in_scope",
            "outcome": "novel_source_backed_value_progress",
            "what_it_means": novel,
            "interpretation": (
                "The round added distinct source-backed field values, "
                "field-value support, or accepted best-guess slots."
                if novel
                else "The round did not add distinct source-backed field "
                "values, field-value support, or accepted best-guess slots."
            ),
        },
        {
            "scope": "in_scope",
            "outcome": "new_value_source_saturation",
            "what_it_means": repeated_sources,
            "interpretation": (
                "Some new source support landed on field values that were "
                "already above the per-value depth target."
                if repeated_sources
                else "New source support stayed within the per-value depth "
                "target."
            ),
        },
        {
            "scope": "in_scope",
            "outcome": "scalar_reward",
            "what_it_means": score,
            "interpretation": (
                "Positive marginal value progress exceeded saturation "
                "penalties."
                if score > 0
                else "Saturation penalties matched or exceeded positive "
                "marginal value progress."
            ),
        },
    ]


def _normalized_score(score: float, positive_score: float) -> float:
    if positive_score <= 0:
        return 0.0
    return round(max(-1.0, min(1.0, score / positive_score)), 6)


def _semantic_cells(
    row: Mapping[str, Any],
    *,
    scored_fields: set[str] | None = None,
) -> list[tuple[str, str]]:
    cells: list[tuple[str, str]] = []
    for raw_field, raw_value in row.items():
        field = str(raw_field or "").strip()
        if not field or _is_provenance_field(field):
            continue
        if scored_fields is not None and field not in scored_fields:
            continue
        for value in _value_atoms(raw_value):
            if _is_missing(value):
                continue
            cells.append((field, value))
    return sorted(set(cells))


def _value_atoms(value: Any) -> list[str]:
    if _is_missing(value):
        return []
    if isinstance(value, Mapping):
        return [
            _stable_json(
                {
                    str(key): nested
                    for key, nested in value.items()
                    if not _is_missing(nested)
                }
            )
        ]
    if isinstance(value, (list, tuple, set)):
        atoms = [_normalize_scalar(item) for item in value if not _is_missing(item)]
        return sorted({atom for atom in atoms if atom})
    atom = _normalize_scalar(value)
    return [atom] if atom else []


def _normalize_scalar(value: Any) -> str:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.12g}"
    if isinstance(value, (int, bool)):
        return str(value).lower()
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def _scored_fields(
    scored_fields_by_table: Mapping[str, Iterable[str]] | None,
    table: str,
) -> set[str] | None:
    if not scored_fields_by_table or table not in scored_fields_by_table:
        return None
    fields = {
        str(field or "").strip()
        for field in scored_fields_by_table.get(table) or []
        if str(field or "").strip()
    }
    return fields or None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, Mapping):
        return not any(not _is_missing(nested) for nested in value.values())
    if isinstance(value, (list, tuple, set)):
        return not any(not _is_missing(item) for item in value)
    return _normalize_scalar(value) in _MISSING_STRINGS


def _is_provenance_field(field: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")
    if not normalized:
        return True
    return (
        normalized.startswith("_")
        or normalized in _STRUCTURAL_FIELDS
        or normalized in _PROVENANCE_FIELDS
        or normalized.startswith(_PROVENANCE_PREFIXES)
        or normalized.endswith(_PROVENANCE_SUFFIXES)
    )


def _best_guess_keys(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_slot_id = str(row.get("row_slot_id") or "").strip()
        if row_slot_id:
            keys.add(row_slot_id)
            continue
        key_parts = [
            row.get("target_table"),
            row.get("source_row_key"),
            row.get("source_row_index"),
            row.get("canonical_column"),
            row.get("best_guess_value"),
        ]
        keys.add(_stable_json([_normalize_scalar(part) for part in key_parts]))
    return keys


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
