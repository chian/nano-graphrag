from __future__ import annotations

import math
import re
from collections import Counter
from statistics import mean, median
from typing import Any

from ..contracts import iter_scalar_fields


def tokenize_query(query: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", query.lower()))


def collect_runtime_variables(runtime_view: dict[str, Any]) -> dict[str, Any]:
    variables: dict[str, Any] = {}
    for name, value in runtime_view.get("state_variables", {}).items():
        variables[name] = _unwrap_state_variable(value)
    for name, value in runtime_view.get("context_variables", {}).items():
        variables[name] = value
    return variables


def collect_variable_metadata(runtime_view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for name, value in runtime_view.get("state_variables", {}).items():
        meta = value.get("_meta", {}) if isinstance(value, dict) else {}
        metadata[name] = {
            "type": meta.get("type", ""),
            "contract": meta.get("contract", {}) if isinstance(meta.get("contract", {}), dict) else {},
        }
    for artifact in runtime_view.get("produced_artifacts", []) or []:
        var = artifact.get("variable")
        if not var:
            continue
        metadata.setdefault(var, {})
        metadata[var].update(
            {
                "payload_kind": artifact.get("payload_kind", ""),
                "row_schema": artifact.get("row_schema", []),
                "label_field": artifact.get("label_field", ""),
                "metric_field": artifact.get("metric_field", ""),
                "grain_type": artifact.get("grain_type", ""),
                "safe_for": artifact.get("safe_for", []),
            }
        )
    return metadata


def enumerate_row_variables(runtime_view: dict[str, Any]) -> list[dict[str, Any]]:
    variables = collect_runtime_variables(runtime_view)
    metadata = collect_variable_metadata(runtime_view)
    rows: list[dict[str, Any]] = []
    for name, value in variables.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            rows.append({"name": name, "rows": value, "meta": metadata.get(name, {})})
    return rows


def _unwrap_state_variable(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    meta = value.get("_meta", {})
    var_type = meta.get("type")
    if var_type == "LIST":
        return value.get("items", [])
    if var_type == "COUNTER":
        return value.get("value", 0)
    if var_type == "DICT":
        return {k: v for k, v in value.items() if k != "_meta"}
    return value


def candidate_group_fields(rows: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> list[str]:
    if not rows or not isinstance(rows[0], dict):
        return []
    keys = list(rows[0].keys())
    out: list[str] = []
    if meta:
        label_field = meta.get("label_field") or meta.get("contract", {}).get("label_field")
        if label_field:
            leaf = label_field.split(".")[-1]
            for candidate in (label_field, leaf):
                if candidate in keys and candidate not in out:
                    out.append(candidate)
    scored: list[tuple[tuple[float, int], str]] = []
    total = len(rows)
    for key in keys:
        vals = [row.get(key) for row in rows if row.get(key) is not None]
        if not vals:
            continue
        scalar_ratio = sum(isinstance(v, (str, int, float, bool)) for v in vals) / len(vals)
        if scalar_ratio < 0.8:
            continue
        distinct = len(set(map(str, vals)))
        if distinct <= 1:
            continue
        uniqueness = distinct / total if total else 1.0
        score = (1.0 - abs(0.35 - min(uniqueness, 1.0)), sum(isinstance(v, str) for v in vals))
        scored.append((score, key))
    scored.sort(reverse=True)
    out.extend(key for _, key in scored if key not in out)
    return out


def distinct_dimension_fields(rows: list[dict[str, Any]], meta: dict[str, Any] | None = None, *, exclude: set[str] | None = None) -> list[str]:
    exclude = exclude or set()
    if not rows or not isinstance(rows[0], dict):
        return []
    scores: list[tuple[tuple[float, int], str]] = []
    total = len(rows)
    for key in rows[0].keys():
        if key in exclude:
            continue
        vals = [row.get(key) for row in rows if row.get(key) is not None]
        if not vals:
            continue
        if sum(isinstance(v, str) for v in vals) / len(vals) < 0.5:
            continue
        distinct = len(set(map(str, vals)))
        if distinct <= 1:
            continue
        uniqueness = distinct / total if total else 1.0
        score = (1.0 - abs(0.5 - min(uniqueness, 1.0)), distinct)
        scores.append((score, key))
    scores.sort(reverse=True)
    return [key for _, key in scores]


def numeric_fields(rows: list[dict[str, Any]], preferred: str | None = None) -> list[str]:
    if not rows or not isinstance(rows[0], dict):
        return []
    if preferred and all(isinstance(row.get(preferred), (int, float)) for row in rows if row.get(preferred) is not None):
        return [preferred]
    scored: list[tuple[tuple[float, int], str]] = []
    for key in rows[0].keys():
        vals = [float(row.get(key)) for row in rows if isinstance(row.get(key), (int, float))]
        if len(vals) < 2:
            continue
        variance = mean([(v - mean(vals)) ** 2 for v in vals])
        distinct = len(set(vals))
        if distinct <= 1:
            continue
        scored.append(((variance, distinct), key))
    scored.sort(reverse=True)
    return [key for _, key in scored]


def infer_support_field(rows: list[dict[str, Any]], *, exclude: set[str] | None = None) -> str | None:
    exclude = exclude or set()
    if not rows or not isinstance(rows[0], dict):
        return None
    scored: list[tuple[tuple[int, int], str]] = []
    for key in rows[0].keys():
        if key in exclude:
            continue
        vals = [row.get(key) for row in rows if row.get(key) is not None]
        if not vals:
            continue
        distinct = len(set(map(str, vals)))
        if distinct <= 1:
            continue
        textiness = sum(isinstance(v, str) for v in vals)
        scored.append(((distinct, textiness), key))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def top_evidence_refs(rows: list[dict[str, Any]], group_field: str, max_groups: int = 3, limit_per_group: int = 2) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get(group_field)
        if key is None:
            continue
        grouped.setdefault(str(key), []).append(row)
    refs: list[dict[str, Any]] = []
    for group_name, group_rows in list(grouped.items())[:max_groups]:
        for row in group_rows[:limit_per_group]:
            item_id = group_name
            for field_name, value in iter_scalar_fields(row, max_depth=2):
                if field_name.endswith(".id") or field_name == "id":
                    item_id = str(value)
                    break
            refs.append(
                {
                    "item_id": item_id,
                    "snippet": short_snippet(row),
                    "source_ids": [],
                }
            )
    return refs


def short_snippet(row: dict[str, Any], limit: int = 180) -> str:
    candidates: list[tuple[int, str]] = []
    if isinstance(row.get("data"), dict):
        for _, value in row["data"].items():
            if isinstance(value, str):
                candidates.append((len(value), value))
    for _, value in row.items():
        if isinstance(value, str):
            candidates.append((len(value), value))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1][:limit]


def histogram(values: list[float], bins: int = 5) -> list[dict[str, Any]]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if math.isclose(lo, hi):
        return [{"bin_lo": lo, "bin_hi": hi, "count": len(values)}]
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    out = []
    for i, count in enumerate(counts):
        out.append({"bin_lo": lo + i * width, "bin_hi": lo + (i + 1) * width, "count": count})
    return out


def distribution_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {}
    return {
        "n": len(values),
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
        "median": median(values),
        "histogram": histogram(values),
    }
