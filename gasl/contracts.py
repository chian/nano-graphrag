"""
Shared helpers for command output contracts.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def infer_row_schema(data: Any, *, sample_limit: int = 8, max_depth: int = 2) -> List[str]:
    fields: List[str] = []
    seen = set()
    rows = data if isinstance(data, list) else [data]
    for row in rows[:sample_limit]:
        for field_name in iter_row_fields(row, max_depth=max_depth):
            if field_name not in seen:
                seen.add(field_name)
                fields.append(field_name)
    return fields


def iter_row_fields(item: Any, prefix: str = "", *, depth: int = 0, max_depth: int = 2):
    if depth > max_depth:
        return
    if isinstance(item, dict):
        for key, value in item.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield next_prefix
            if isinstance(value, dict):
                yield from iter_row_fields(value, next_prefix, depth=depth + 1, max_depth=max_depth)


def iter_scalar_fields(item: Any, prefix: str = "", *, depth: int = 0, max_depth: int = 2):
    if depth > max_depth:
        return
    if isinstance(item, dict):
        for key, value in item.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (str, int, float, bool)):
                yield next_prefix, value
            elif isinstance(value, dict):
                yield from iter_scalar_fields(value, next_prefix, depth=depth + 1, max_depth=max_depth)
    elif isinstance(item, (str, int, float, bool)):
        yield prefix or "value", item


def make_contract(
    *,
    payload_kind: str,
    data: Any,
    row_schema: Optional[List[str]] = None,
    label_field: str = "",
    metric_field: str = "",
    ordered: bool = False,
    order_basis: str = "",
    order_field: str = "",
    order_direction: str = "unknown",
    scope: str = "current_rows_only",
    usable_by: Optional[Iterable[str]] = None,
    confidence: float = 1.0,
    strategy: str = "",
    grain_type: str = "",
    grain_keys: Optional[Iterable[str]] = None,
    multiplicity_preserved: Optional[bool] = None,
    row_weight_field: str = "",
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "payload_kind": payload_kind,
        "row_schema": row_schema or infer_row_schema(data),
        "label_field": label_field,
        "metric_field": metric_field,
        "ordered": ordered,
        "order_basis": order_basis,
        "order_field": order_field,
        "order_direction": order_direction,
        "scope": scope,
        "usable_by": list(usable_by or []),
        "confidence": float(confidence),
        "strategy": strategy,
        "grain_type": grain_type,
        "grain_keys": list(grain_keys or []),
        "multiplicity_preserved": multiplicity_preserved,
        "row_weight_field": row_weight_field,
        "notes": list(notes or []),
    }


def merge_contract(base: Optional[Dict[str, Any]], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    for key, value in updates.items():
        if value in (None, "", [], {}):
            continue
        merged[key] = value
    if "row_schema" not in merged:
        merged["row_schema"] = []
    if "usable_by" in merged and isinstance(merged["usable_by"], list):
        merged["usable_by"] = list(dict.fromkeys(merged["usable_by"]))
    return merged
