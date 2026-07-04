"""Reusable table export loading and merge helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


_ROUND_TABLE_RE = re.compile(r"^round_\d+_(?P<table>.+)\.json$")


@dataclass
class SeedTables:
    rows_by_name: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return sum(len(rows) for rows in self.rows_by_name.values())


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

    manifests = sorted(root.glob("round_*_manifest.json"))
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

    for manifest_path in manifests:
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

    return SeedTables(rows_by_name=rows_by_name, sources=sources)


def _load_table_files(paths: Iterable[Path]) -> SeedTables:
    rows_by_name: dict[str, list[dict[str, Any]]] = {}
    sources: list[dict[str, Any]] = []

    for path in paths:
        table_name = _table_name_from_path(path)
        if not table_name:
            continue

        rows = _read_dict_rows(path)
        if not rows:
            continue

        rows_by_name[table_name] = merge_rows(rows_by_name.get(table_name, []), rows)
        sources.append(
            {
                "table": table_name,
                "path": str(path),
                "rows": len(rows),
                "manifest": None,
            }
        )

    return SeedTables(rows_by_name=rows_by_name, sources=sources)


def _table_name_from_path(path: Path) -> str:
    match = _ROUND_TABLE_RE.match(path.name)
    if match:
        return match.group("table")
    if path.stem == "manifest" or path.stem.endswith("_manifest"):
        return ""
    return path.stem


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
