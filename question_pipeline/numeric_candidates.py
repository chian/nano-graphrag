"""Generic derived numeric candidates from exported answer tables."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from .derived_context import (
    ContextSlot,
    DERIVED_CONTEXT_COLUMNS,
    infer_best_guess_context,
    normalize_source_records,
    normalize_context_slots,
    source_ids_from_row,
)


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

_MISSING_STRINGS = {
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
    if _missing(value):
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
    if _missing(value) or _field_should_skip(field_name):
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
    source_row_key = _source_row_key(row, row_index)
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
    if _field_should_skip(field_name):
        return False
    tokens = _field_tokens(field_name)
    return bool(tokens & _SCALAR_FIELD_HINTS)


def _field_should_skip(field_name: str) -> bool:
    text = str(field_name or "")
    if text.startswith("_"):
        return True
    tokens = _field_tokens(text)
    return bool(tokens & _SKIP_FIELD_TOKENS)


def _row_context(row: Mapping[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key, value in row.items():
        if len(context) >= 12:
            break
        if _missing(value) or _field_tokens(str(key)) & _CONTEXT_SKIP_TOKENS:
            continue
        context[str(key)] = _compact(value)
    return context


def _source_row_key(row: Mapping[str, Any], row_index: int) -> str:
    for key in ("row_id", "deduplication_key", "dedup_key", "group_key", "id"):
        value = row.get(key)
        if not _missing(value):
            return _stringify(value)[:240]

    payload = json.dumps(_row_context(row), sort_keys=True, default=str)
    return f"{row_index}:{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]}"


def _source_list(value: Any) -> list[str]:
    if _missing(value):
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


def _field_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^A-Za-z0-9]+", str(value).lower())
        if token
    }


def _compact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _compact(inner)
            for key, inner in list(value.items())[:8]
            if not _missing(inner)
        }
    if isinstance(value, (list, tuple, set)):
        return [_compact(item) for item in list(value)[:8] if not _missing(item)]
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
            if not _missing(inner)
        )
    return str(value).strip()


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_STRINGS
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _as_float(value: str) -> float:
    return float(value.replace(",", ""))


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 8)
