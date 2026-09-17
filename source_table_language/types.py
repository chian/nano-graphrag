"""Typed vocabulary for the reusable table language.

The language describes source-local operations.  It knows about addressable
source spans, source rows, target entity fields, and candidate mentions.  It
does not know about Episodes, rarefaction, or any particular storage backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class SourceLine:
    text: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class TableRegion:
    region_id: str
    parser_hint: str
    start_offset: int
    end_offset: int
    text: str
    lines: tuple[SourceLine, ...]


@dataclass(frozen=True)
class SourceSpan:
    span_id: str
    kind: str
    start_offset: int
    end_offset: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "kind": self.kind,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "text": self.text,
        }


@dataclass(frozen=True)
class SourceCell:
    column_index: int
    text: str
    start_offset: int
    end_offset: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "column_index": self.column_index,
            "text": self.text,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
        }


@dataclass(frozen=True)
class SourceRow:
    row_id: str
    row_index: int
    raw_text: str
    start_offset: int
    end_offset: int
    cells: tuple[SourceCell, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "row_index": self.row_index,
            "raw_text": self.raw_text,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "cells": [cell.to_dict() for cell in self.cells],
        }


@dataclass(frozen=True)
class TargetField:
    """One semantic field on the entity being assembled.

    ``reported_column`` is the current table projection.  A future graph sink
    can consume the same field without that projection.
    """

    name: str
    value_type: str
    unit: str = ""
    description: str = ""
    aliases: tuple[str, ...] = ()
    reported_column: str = ""
    best_guess_column: str = ""
    identity: bool = False
    required: bool = False


@dataclass(frozen=True)
class AdmissionRule:
    rule_id: str
    field: str
    operator: str
    value: Any
    basis: str = ""


@dataclass(frozen=True)
class TargetEntity:
    name: str
    fields: Mapping[str, TargetField]
    admission_rules: tuple[AdmissionRule, ...] = ()


@dataclass(frozen=True)
class Scope:
    kind: str = "all_rows"
    source_column: Optional[int] = None
    marker: str = ""
    first_row: Optional[int] = None
    last_row: Optional[int] = None


@dataclass(frozen=True)
class ParseCommand:
    parser_kind: str
    data_start_row: int
    header_rows: tuple[int, ...] = ()


@dataclass(frozen=True)
class EntryCommand:
    mode: str = "one_per_row"
    identity_source_columns: tuple[int, ...] = ()


@dataclass(frozen=True)
class MapColumnCommand:
    source_column: int
    target_field: str
    parse_as: str = "text"


@dataclass(frozen=True)
class MapContextCommand:
    span_id: str
    target_field: str
    value: Any
    scope: Scope = field(default_factory=Scope)


@dataclass(frozen=True)
class SatisfyCommand:
    rule_id: str
    span_id: str
    scope: Scope = field(default_factory=Scope)


@dataclass(frozen=True)
class TableProgram:
    target_entity: str
    parse: ParseCommand
    entries: EntryCommand
    column_maps: tuple[MapColumnCommand, ...]
    context_maps: tuple[MapContextCommand, ...] = ()
    satisfied_rules: tuple[SatisfyCommand, ...] = ()
    rationale: str = ""


@dataclass(frozen=True)
class FieldAssertion:
    assertion_id: str
    mention_id: str
    field: str
    raw_value: Any
    comparison_value: Any
    comparison_type: str
    source_row_ids: tuple[str, ...]
    source_span_ids: tuple[str, ...]
    evidence_kind: str = "reported"


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    status: str
    evidence_ids: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class Mention:
    mention_id: str
    entity_type: str
    source_row_ids: tuple[str, ...]
    assertions: tuple[FieldAssertion, ...]
    rule_results: tuple[RuleResult, ...]
    admission_status: str


@dataclass(frozen=True)
class CandidateConnection:
    left_mention_id: str
    right_mention_id: str
    agreements: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    structural_basis: str = ""


@dataclass(frozen=True)
class LanguageResult:
    program: TableProgram
    mentions: tuple[Mention, ...]
    connections: tuple[CandidateConnection, ...]
    spans: Mapping[str, SourceSpan]

    @property
    def admitted_mentions(self) -> tuple[Mention, ...]:
        return tuple(
            mention
            for mention in self.mentions
            if mention.admission_status == "accepted"
        )
