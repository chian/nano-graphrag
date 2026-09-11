"""Resolve a requested field name against the fields rows actually carry.

Commands take field names from planner output, while rows carry field names
authored by whatever produced them — graph properties, an earlier PROCESS, a
projection. Nothing reconciles the two registries, so a requested name that
matches nothing used to read back as `None`, and `None` is a legal value: it
compares equal to another `None`, it satisfies a truth test as "absent", and it
never raises. That is why a missing join key produced a cartesian product
instead of an error.

This module makes the reconciliation explicit and, above all, *reportable*: a
resolution always says which rung of the ladder matched, and a failure always
carries the candidate field names it was choosing between. Nothing here knows
any schema; every candidate comes from the rows or contract handed in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


# Ordered resolution ladder. Earlier rungs are more literal; a caller can refuse
# anything below a chosen rung when an inexact match would be unsafe.
RESOLUTION_EXACT = "exact"
RESOLUTION_NORMALIZED = "normalized"
RESOLUTION_LEAF = "leaf"
RESOLUTION_LADDER = (RESOLUTION_EXACT, RESOLUTION_NORMALIZED, RESOLUTION_LEAF)

UNRESOLVED_MISSING = "missing"
UNRESOLVED_AMBIGUOUS = "ambiguous"


def normalize_field_token(value: Any) -> str:
    """Case-, space- and separator-insensitive form of a field name."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


@dataclass(frozen=True)
class FieldResolution:
    """How a requested field name mapped onto the fields rows actually carry."""

    requested: str
    resolved: Optional[str]
    how: str
    candidates: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.resolved is not None

    @property
    def exact(self) -> bool:
        return self.how == RESOLUTION_EXACT

    def describe(self) -> str:
        if self.ok:
            return f"{self.requested!r} -> {self.resolved!r} ({self.how})"
        if self.how == UNRESOLVED_AMBIGUOUS:
            return (
                f"{self.requested!r} is ambiguous; it could mean any of "
                f"{sorted(self.candidates)}"
            )
        return (
            f"{self.requested!r} matches no field on these rows; "
            f"available fields: {sorted(self.candidates)}"
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "requested": self.requested,
            "resolved": self.resolved,
            "how": self.how,
            "candidates": sorted(self.candidates),
        }


def observed_fields(
    rows: Sequence[Any],
    *,
    contract: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """Field paths these rows actually carry, plus any the contract declares.

    **This scan is exhaustive by construction: every row, every depth.** It has
    to be. The candidate list produced here is what a resolution failure reports
    as "the available fields", and a sampled candidate list turns that sentence
    into a falsehood — a field that genuinely exists on row 300 resolves as
    `missing`, and the caller is handed a truncated list presented as complete.
    That is the same "absence is indistinguishable from a miss" defect this
    module exists to remove, one layer up, so no row bound and no depth bound is
    permitted here. The walk is O(total keys) and cheap even for large states.

    The rows are the authority — a contract's `row_schema` is a declaration that
    may be stale — but declared-and-absent fields are still offered as
    candidates, since a stale declaration is still a useful hint in an error.
    """
    fields: List[str] = []
    seen: set[str] = set()

    def walk(item: Any, prefix: str, ancestors: tuple) -> None:
        if not isinstance(item, Mapping):
            return
        # Rows are JSON-shaped in practice, but guard against a self-referential
        # structure so "no depth bound" cannot become "no termination".
        if any(item is ancestor for ancestor in ancestors):
            return
        for key, value in item.items():
            path = f"{prefix}{key}"
            if path not in seen:
                seen.add(path)
                fields.append(path)
            if isinstance(value, Mapping):
                walk(value, f"{path}.", ancestors + (item,))

    for row in rows:
        walk(row, "", ())

    for declared in (contract or {}).get("row_schema") or []:
        if declared not in seen:
            seen.add(declared)
            fields.append(declared)

    return fields


def resolve_field(
    requested: str,
    candidates: Iterable[str],
    *,
    max_rung: str = RESOLUTION_LEAF,
) -> FieldResolution:
    """Map a requested field name onto one of `candidates`.

    Rungs, tried in order and reported by name:

    - `exact`      the requested string is a candidate verbatim
    - `normalized` exactly one candidate matches ignoring case, spaces and
                   separators (`"Event Date"` -> `"event_date"`)
    - `leaf`       exactly one candidate's last dotted segment matches that way
                   (`"entity_name"` -> `"data.entity_name"`)

    A rung that produces more than one candidate is *ambiguous* and resolves to
    nothing: guessing between two real columns is the failure mode this module
    exists to prevent. `max_rung` lets a caller refuse inexact matches entirely.
    """
    candidate_list = [str(candidate) for candidate in candidates]
    allowed = RESOLUTION_LADDER[: RESOLUTION_LADDER.index(max_rung) + 1]

    if requested in candidate_list:
        return FieldResolution(requested, requested, RESOLUTION_EXACT, candidate_list)

    target = normalize_field_token(requested)
    if not target:
        return FieldResolution(requested, None, UNRESOLVED_MISSING, candidate_list)

    if RESOLUTION_NORMALIZED in allowed:
        matches = [c for c in candidate_list if normalize_field_token(c) == target]
        if len(matches) == 1:
            return FieldResolution(requested, matches[0], RESOLUTION_NORMALIZED, candidate_list)
        if len(matches) > 1:
            return FieldResolution(requested, None, UNRESOLVED_AMBIGUOUS, matches)

    if RESOLUTION_LEAF in allowed:
        matches = [
            c for c in candidate_list
            if normalize_field_token(c.split(".")[-1]) == target
        ]
        if len(matches) == 1:
            return FieldResolution(requested, matches[0], RESOLUTION_LEAF, candidate_list)
        if len(matches) > 1:
            return FieldResolution(requested, None, UNRESOLVED_AMBIGUOUS, matches)

    return FieldResolution(requested, None, UNRESOLVED_MISSING, candidate_list)


def read_field_path(row: Any, path: Optional[str]) -> Any:
    """Read a dotted path off a row, returning None when any segment is absent.

    Callers must not treat the returned None as a value: use `has_field_path` to
    tell "absent" from "present and null".
    """
    if not path:
        return None
    current = row
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return None
    return current


def has_field_path(row: Any, path: Optional[str]) -> bool:
    """True when every segment of `path` is present on `row`."""
    if not path:
        return False
    current = row
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return False
    return True
