"""Deterministic execution of validated table-language programs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from .source import TableWorkspace
from .types import (
    AdmissionRule,
    CandidateConnection,
    FieldAssertion,
    LanguageResult,
    Mention,
    RuleResult,
    Scope,
    SourceCell,
    SourceRow,
    SourceSpan,
    TableProgram,
    TargetEntity,
)


_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")
_MISSING = frozenset({"", "-", "--", "—", "n/a", "na", "none", "null", "unknown"})
_OPERATORS = frozenset({"eq", "neq", "gt", "gte", "lt", "lte"})


@dataclass(frozen=True)
class _NumericInterval:
    lower: Decimal | None
    upper: Decimal | None


def _stable_id(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _cell(row: SourceRow, column: int) -> SourceCell | None:
    if 0 <= column < len(row.cells):
        return row.cells[column]
    return None


def _entry_groups(
    rows: Sequence[SourceRow],
    program: TableProgram,
) -> tuple[tuple[SourceRow, ...], ...]:
    data = tuple(rows[program.parse.data_start_row :])
    if program.entries.mode == "one_per_row":
        return tuple((row,) for row in data)

    groups: list[list[SourceRow]] = []
    for row in data:
        continuation = bool(groups) and all(
            not str((_cell(row, column) or SourceCell(column, "", 0, 0)).text).strip()
            for column in program.entries.identity_source_columns
        )
        if continuation:
            groups[-1].append(row)
        else:
            groups.append([row])
    return tuple(tuple(group) for group in groups)


def _numbers(value: Any) -> tuple[Decimal, ...]:
    out: list[Decimal] = []
    for token in _NUMBER_RE.findall(str(value or "")):
        try:
            out.append(Decimal(token.replace(",", "")))
        except InvalidOperation:
            continue
    return tuple(out)


def _typed(value: Any, value_type: str) -> Any:
    text = str(value or "").strip()
    if text.casefold() in _MISSING:
        return None
    if value_type in {"number", "integer", "range"}:
        values = _numbers(text)
        if not values:
            return None
        lowered = text.casefold()
        lower_bound = (
            "at least",
            "no fewer than",
            "not less than",
            "more than",
            "greater than",
            "over ",
            ">",
        )
        upper_bound = (
            "at most",
            "no more than",
            "not greater than",
            "less than",
            "fewer than",
            "under ",
            "up to",
            "<",
        )
        if len(values) == 1 and any(token in lowered for token in lower_bound):
            return _NumericInterval(values[0], None)
        if len(values) == 1 and any(token in lowered for token in upper_bound):
            return _NumericInterval(None, values[0])
        if value_type == "integer" and len(values) == 1:
            return values[0].to_integral_value()
        if value_type == "number" and len(values) == 1:
            return values[0]
        if len(values) > 1:
            return _NumericInterval(min(values), max(values))
        number = values[0]
        return _NumericInterval(number, number)
    if value_type == "year":
        values = [value for value in _numbers(text) if 100 <= value <= 9999]
        return values[0].to_integral_value() if values else None
    if value_type == "date":
        normalized = text.replace("/", "-")
        try:
            return datetime.fromisoformat(normalized).date()
        except ValueError:
            years = [value for value in _numbers(text) if 100 <= value <= 9999]
            return date(int(years[0]), 1, 1) if years else None
    return text


def _scope_applies(scope: Scope, rows: Sequence[SourceRow]) -> bool:
    if scope.kind == "all_rows":
        return True
    if scope.kind == "row_range":
        return any(
            scope.first_row is not None
            and scope.last_row is not None
            and scope.first_row <= row.row_index <= scope.last_row
            for row in rows
        )
    if scope.kind in {"source_column", "rows_with_marker"}:
        if scope.source_column is None:
            return False
        cells = [
            cell
            for row in rows
            for cell in [_cell(row, scope.source_column)]
            if cell is not None
        ]
        if scope.kind == "source_column":
            return bool(cells)
        return any(scope.marker in cell.text for cell in cells)
    return False


def _compare_scalar(left: Any, operator: str, right: Any) -> bool:
    if operator == "eq":
        return left == right
    if operator == "neq":
        return left != right
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    if operator == "lt":
        return left < right
    if operator == "lte":
        return left <= right
    raise ValueError(f"unsupported admission operator {operator!r}")


def _compare(value: Any, rule: AdmissionRule, comparison_type: str) -> str:
    if rule.operator not in _OPERATORS:
        return "unresolved"
    right = _typed(rule.value, comparison_type)
    if isinstance(right, _NumericInterval):
        if right.lower != right.upper:
            return "unresolved"
        right = right.lower
    if value is None or right is None:
        return "unresolved"
    if isinstance(value, _NumericInterval):
        lower, upper = value.lower, value.upper
        if rule.operator in {"gte", "gt"}:
            if lower is not None and _compare_scalar(lower, rule.operator, right):
                return "satisfied"
            if upper is not None and not _compare_scalar(upper, rule.operator, right):
                return "rejected"
            return "unresolved"
        if rule.operator in {"lte", "lt"}:
            if upper is not None and _compare_scalar(upper, rule.operator, right):
                return "satisfied"
            if lower is not None and not _compare_scalar(lower, rule.operator, right):
                return "rejected"
            return "unresolved"
        if rule.operator == "eq":
            if lower == upper == right:
                return "satisfied"
            if lower is not None and upper is not None and not lower <= right <= upper:
                return "rejected"
            return "unresolved"
        if rule.operator == "neq":
            return "rejected" if lower == upper == right else "unresolved"
    return "satisfied" if _compare_scalar(value, rule.operator, right) else "rejected"


def _assertions_for_group(
    rows: Sequence[SourceRow],
    program: TableProgram,
    target: TargetEntity,
    spans: Mapping[str, SourceSpan],
    mention_id: str,
) -> tuple[FieldAssertion, ...]:
    assertions: list[FieldAssertion] = []
    for command in program.column_maps:
        for row in rows:
            cell = _cell(row, command.source_column)
            if cell is None or str(cell.text).strip().casefold() in _MISSING:
                continue
            assertion_id = _stable_id(
                {
                    "mention": mention_id,
                    "field": command.target_field,
                    "row": row.row_id,
                    "start": cell.start_offset,
                    "end": cell.end_offset,
                    "value": cell.text,
                }
            )
            assertions.append(
                FieldAssertion(
                    assertion_id=assertion_id,
                    mention_id=mention_id,
                    field=command.target_field,
                    raw_value=cell.text,
                    comparison_value=_typed(cell.text, command.parse_as),
                    comparison_type=command.parse_as,
                    source_row_ids=(row.row_id,),
                    source_span_ids=(),
                )
            )

    for command in program.context_maps:
        if not _scope_applies(command.scope, rows):
            continue
        span = spans[command.span_id]
        literal = str(command.value or "").strip()
        if not literal or literal not in span.text:
            numeric = _numbers(command.value)
            span_numbers = _numbers(span.text)
            if not numeric or not set(numeric) <= set(span_numbers):
                continue
        field = target.fields[command.target_field]
        assertions.append(
            FieldAssertion(
                assertion_id=_stable_id(
                    {
                        "mention": mention_id,
                        "field": command.target_field,
                        "span": command.span_id,
                        "value": command.value,
                    }
                ),
                mention_id=mention_id,
                field=command.target_field,
                raw_value=command.value,
                comparison_value=_typed(command.value, field.value_type),
                comparison_type=field.value_type,
                source_row_ids=tuple(row.row_id for row in rows),
                source_span_ids=(command.span_id,),
            )
        )
    return tuple(assertions)


def _rule_results(
    rows: Sequence[SourceRow],
    assertions: Sequence[FieldAssertion],
    program: TableProgram,
    target: TargetEntity,
) -> tuple[RuleResult, ...]:
    explicit = {
        command.rule_id: command
        for command in program.satisfied_rules
        if _scope_applies(command.scope, rows)
    }
    by_field: dict[str, list[FieldAssertion]] = {}
    for assertion in assertions:
        by_field.setdefault(assertion.field, []).append(assertion)

    out: list[RuleResult] = []
    for rule in target.admission_rules:
        command = explicit.get(rule.rule_id)
        if command is not None:
            out.append(
                RuleResult(
                    rule_id=rule.rule_id,
                    status="satisfied",
                    evidence_ids=(command.span_id,),
                    reason="source context directly establishes this rule",
                )
            )
            continue
        field = target.fields.get(rule.field)
        candidates = by_field.get(rule.field) or []
        if field is None or not candidates:
            out.append(
                RuleResult(
                    rule_id=rule.rule_id,
                    status="unresolved",
                    reason="no mapped source evidence supplies the required field",
                )
            )
            continue
        statuses = {
            _compare(
                candidate.comparison_value,
                rule,
                candidate.comparison_type,
            )
            for candidate in candidates
        }
        status = (
            next(iter(statuses))
            if len(statuses) == 1
            else "unresolved"
        )
        out.append(
            RuleResult(
                rule_id=rule.rule_id,
                status=status,
                evidence_ids=tuple(
                    candidate.assertion_id for candidate in candidates
                ),
                reason=(
                    "mapped field values disagree on the admission result"
                    if len(statuses) > 1
                    else ""
                ),
            )
        )
    return tuple(out)


def _admission_status(results: Sequence[RuleResult]) -> str:
    if any(result.status == "rejected" for result in results):
        return "rejected"
    if any(result.status != "satisfied" for result in results):
        return "unresolved"
    return "accepted"


def _normalized_identity(assertion: FieldAssertion) -> str:
    return " ".join(str(assertion.raw_value or "").casefold().split())


def _candidate_connections(
    mentions: Sequence[Mention],
    target: TargetEntity,
) -> tuple[CandidateConnection, ...]:
    identity_fields = tuple(
        field.name for field in target.fields.values() if field.identity
    )
    if not identity_fields:
        return ()
    values: dict[str, dict[str, tuple[str, ...]]] = {}
    for mention in mentions:
        fields: dict[str, list[str]] = {}
        for assertion in mention.assertions:
            if assertion.field in identity_fields:
                fields.setdefault(assertion.field, []).append(
                    _normalized_identity(assertion)
                )
        values[mention.mention_id] = {
            name: tuple(items) for name, items in fields.items()
        }

    edges: list[CandidateConnection] = []
    for left_index, left in enumerate(mentions):
        for right in mentions[left_index + 1 :]:
            agreements: list[str] = []
            conflicts: list[str] = []
            for field in identity_fields:
                left_values = values[left.mention_id].get(field) or ()
                right_values = values[right.mention_id].get(field) or ()
                if not left_values or not right_values:
                    continue
                if set(left_values) & set(right_values):
                    agreements.append(field)
                else:
                    conflicts.append(field)
            if agreements:
                edges.append(
                    CandidateConnection(
                        left_mention_id=left.mention_id,
                        right_mention_id=right.mention_id,
                        agreements=tuple(agreements),
                        conflicts=tuple(conflicts),
                    )
                )
    return tuple(edges)


def execute_program(
    workspace: TableWorkspace,
    program: TableProgram,
    target: TargetEntity,
) -> LanguageResult:
    """Execute a program and return source-local mentions plus candidate links."""

    rows = workspace.rows(program.parse.parser_kind)
    groups = _entry_groups(rows, program)
    spans = workspace.spans
    mentions: list[Mention] = []
    for group in groups:
        mention_id = _stable_id(
            {
                "entity": target.name,
                "rows": [row.row_id for row in group],
            }
        )
        assertions = _assertions_for_group(
            group, program, target, spans, mention_id
        )
        results = _rule_results(group, assertions, program, target)
        mentions.append(
            Mention(
                mention_id=mention_id,
                entity_type=target.name,
                source_row_ids=tuple(row.row_id for row in group),
                assertions=assertions,
                rule_results=results,
                admission_status=_admission_status(results),
            )
        )
    return LanguageResult(
        program=program,
        mentions=tuple(mentions),
        connections=_candidate_connections(mentions, target),
        spans=spans,
    )
