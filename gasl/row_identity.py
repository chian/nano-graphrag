from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Literal, Optional

from .contracts import infer_row_schema


IdentityMode = Literal["preserve", "group", "join", "rekey", "explode"]

_VOLATILE_FIELDS = {
    "rank",
    "reason",
    "score_reason",
}


@dataclass(frozen=True)
class IdentitySpec:
    mode: IdentityMode
    grain_type: str
    key_fields: tuple[str, ...] = ()
    preserve_multiplicity: bool = True


def materialize_row_identity(
    rows: list[dict[str, Any]],
    *,
    spec: IdentitySpec,
    source_contract: Optional[Dict[str, Any]] = None,
    source_rows: Optional[list[dict[str, Any]]] = None,
) -> tuple[list[dict[str, Any]], Dict[str, Any]]:
    source_contract = source_contract or {}
    source_rows = source_rows or []
    normalized: list[dict[str, Any]] = []

    for idx, original_row in enumerate(rows):
        row = dict(original_row)
        row_id: Optional[str] = None

        if spec.mode == "preserve":
            row_id = _preserve_row_id(row, idx, source_contract, source_rows)
        else:
            basis = _basis_from_keys(row, spec.key_fields)
            if basis is not None:
                row_id = _deterministic_row_id(spec.mode, spec.grain_type, basis)
            else:
                row_id = _deterministic_row_id(spec.mode, spec.grain_type, _stable_row_snapshot(row))

        row["row_id"] = row_id
        normalized.append(row)

    grain_keys = _resolve_grain_keys(normalized, spec, source_contract)
    identity_meta = {
        "row_schema": infer_row_schema(normalized),
        "grain_type": spec.grain_type or source_contract.get("grain_type", "row"),
        "grain_keys": list(grain_keys),
        "multiplicity_preserved": spec.preserve_multiplicity,
    }
    return normalized, identity_meta


def derive_row_id_for_row(
    row: dict[str, Any],
    *,
    grain_type: str,
    grain_keys: Iterable[str] = (),
) -> str:
    basis = _basis_from_keys(row, tuple(grain_keys))
    if basis is None:
        basis = _stable_row_snapshot(row)
    return _deterministic_row_id("preserve", grain_type or "row", basis)


def _preserve_row_id(
    row: dict[str, Any],
    idx: int,
    source_contract: Dict[str, Any],
    source_rows: list[dict[str, Any]],
) -> str:
    if row.get("row_id"):
        return str(row["row_id"])

    if idx < len(source_rows):
        source_row = source_rows[idx]
        if isinstance(source_row, dict):
            if source_row.get("row_id"):
                return str(source_row["row_id"])
            source_grain_keys = tuple(source_contract.get("grain_keys") or ())
            if source_grain_keys:
                return derive_row_id_for_row(
                    source_row,
                    grain_type=source_contract.get("grain_type", "row"),
                    grain_keys=source_grain_keys,
                )

    source_grain_keys = tuple(source_contract.get("grain_keys") or ())
    if source_grain_keys:
        basis = _basis_from_keys(row, source_grain_keys)
        if basis is not None:
            return _deterministic_row_id("preserve", source_contract.get("grain_type", "row"), basis)
    return _deterministic_row_id("preserve", source_contract.get("grain_type", "row"), _stable_row_snapshot(row))


def _resolve_grain_keys(
    rows: list[dict[str, Any]],
    spec: IdentitySpec,
    source_contract: Dict[str, Any],
) -> tuple[str, ...]:
    if spec.key_fields and _all_rows_populated(rows, spec.key_fields):
        return spec.key_fields

    if spec.mode == "preserve":
        source_grain_keys = tuple(source_contract.get("grain_keys") or ())
        if source_grain_keys and _all_rows_have_fields(rows, source_grain_keys):
            return source_grain_keys

    return ("row_id",)


def _all_rows_populated(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> bool:
    for row in rows:
        for field in fields:
            value = _get_by_path(row, field)
            if value in (None, ""):
                return False
    return True


def _all_rows_have_fields(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> bool:
    for row in rows:
        for field in fields:
            if _path_present(row, field):
                continue
            return False
    return True


def _basis_from_keys(row: dict[str, Any], key_fields: tuple[str, ...]) -> Optional[Dict[str, Any]]:
    if not key_fields:
        return None
    basis: Dict[str, Any] = {}
    for field in key_fields:
        value = _get_by_path(row, field)
        if value in (None, ""):
            return None
        basis[field] = value
    return basis


def _stable_row_snapshot(row: dict[str, Any]) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {}
    for key in sorted(row.keys()):
        if key in {"row_id", "left_row_id", "right_row_id", "parent_row_id"}:
            continue
        if key in _VOLATILE_FIELDS:
            continue
        value = row[key]
        if isinstance(value, dict):
            snapshot[key] = _stable_row_snapshot(value)
        elif isinstance(value, list):
            snapshot[key] = [_normalize_scalar(v) if not isinstance(v, dict) else _stable_row_snapshot(v) for v in value]
        else:
            snapshot[key] = _normalize_scalar(value)
    return snapshot


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _deterministic_row_id(mode: IdentityMode, grain_type: str, basis: Dict[str, Any]) -> str:
    payload = {
        "identity_version": 1,
        "mode": mode,
        "grain_type": grain_type or "row",
        "basis": basis,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:16]


def _get_by_path(item: Any, path: str) -> Any:
    current = item
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _path_present(item: Any, path: str) -> bool:
    current = item
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False
    return True
