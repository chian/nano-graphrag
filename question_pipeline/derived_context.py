"""Question-configured best-guess context slots for derived table rows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


DERIVED_CONTEXT_COLUMNS = [
    "source_ids",
    "best_guess_context",
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

_UUID_CHUNK_RE = re.compile(r"^(?P<source_id>.+)_chunk_\d+$")


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
        values.extend(_as_source_list(row.get(field)))

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
        for column in _as_list(target.get("key_columns")):
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

    name = _clean_field_name(raw.get("name") or raw.get("key") or "")
    if not name:
        return None

    field_hints = tuple(
        _unique(
            str(value).strip()
            for value in [
                name,
                *_as_list(raw.get("field_hints")),
                *_as_list(raw.get("fields")),
                *_as_list(raw.get("columns")),
            ]
            if str(value or "").strip()
        )
    )
    source_field_hints = tuple(
        _unique(
            str(value).strip()
            for value in _as_list(raw.get("source_field_hints"))
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
        for field, value in _flatten(row)
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
        for field, value in _flatten(source, max_depth=2)
        for hit in [_source_slot_hit(field, value, slot)]
        if hit is not None
    ]
    if not source_hits:
        return None
    return sorted(source_hits, key=lambda item: (-item.confidence, item.field))[0]


def _row_slot_hit(field: str, value: Any, slot: ContextSlot) -> _ContextHit | None:
    if _field_should_skip(field):
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
    field_key = _clean_field_name(field)
    field_tokens = _meaningful_field_tokens(field_key)
    best = 0.0
    for hint in hints:
        hint_key = _clean_field_name(hint)
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


def _flatten(
    value: Mapping[str, Any],
    *,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 2,
) -> Iterable[tuple[str, Any]]:
    for key, inner in value.items():
        field = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(inner, Mapping) and depth < max_depth:
            yield from _flatten(inner, prefix=field, depth=depth + 1, max_depth=max_depth)
        else:
            yield field, inner


def _field_should_skip(field: str) -> bool:
    field = str(field or "")
    return field.startswith("_") or bool(
        _field_tokens(field) & _CONTEXT_FIELD_SKIP_TOKENS
    )


def _field_tokens(field: str) -> set[str]:
    field = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(field))
    return {
        token
        for token in re.split(r"[^A-Za-z0-9]+", field.lower())
        if token
    }


def _meaningful_field_tokens(field: str) -> set[str]:
    tokens = _field_tokens(field)
    meaningful = tokens - _FIELD_HINT_FILLER_TOKENS
    return meaningful or tokens


def _clean_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9_.]+", "_", str(value or "").lower()).strip("_.")


def _clean_text(
    value: Any,
    *,
    max_length: int,
    require_alpha: bool = True,
) -> str:
    if _missing(value):
        return ""
    if isinstance(value, (list, tuple, set)):
        value = "; ".join(str(item) for item in value if not _missing(item))
    elif isinstance(value, Mapping):
        value = "; ".join(
            f"{key}: {inner}"
            for key, inner in value.items()
            if not _missing(inner)
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
    match = _UUID_CHUNK_RE.match(text)
    if match is not None:
        return match.group("source_id")
    return text


def _as_list(values: Any) -> list[Any]:
    if _missing(values):
        return []
    if isinstance(values, list):
        return values
    if isinstance(values, (tuple, set)):
        return list(values)
    return [values]


def _as_source_list(values: Any) -> list[Any]:
    if _missing(values):
        return []
    if isinstance(values, str):
        try:
            parsed = json.loads(values)
        except json.JSONDecodeError:
            return [
                value.strip(" \t\r\n\"'[]")
                for value in re.split(r"[,;\s]+", values)
            ]
        return _as_source_list(parsed)
    return _as_list(values)


def _unique(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_STRINGS
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False
