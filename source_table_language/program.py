"""Parse and validate LLM-written table-language programs."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .types import (
    EntryCommand,
    MapColumnCommand,
    MapContextCommand,
    ParseCommand,
    SatisfyCommand,
    Scope,
    TableProgram,
    TargetEntity,
)


PARSER_KINDS = frozenset(
    {"html", "markdown", "tab", "csv", "semicolon", "fixed_width"}
)
PARSE_TYPES = frozenset(
    {"text", "category", "number", "integer", "range", "date", "year"}
)
ENTRY_MODES = frozenset({"one_per_row", "continuation_rows"})
SCOPE_KINDS = frozenset(
    {"all_rows", "source_column", "row_range", "rows_with_marker"}
)


def language_reference() -> dict[str, Any]:
    """The command vocabulary presented to a planner."""

    return {
        "program_shape": {
            "target_entity": "declared target entity name",
            "commands": ["command objects in execution order"],
            "rationale": "brief explanation",
        },
        "commands": {
            "parse": {
                "op": "parse",
                "parser_kind": sorted(PARSER_KINDS),
                "data_start_row": "zero-based row position after parser cleanup",
                "header_rows": ["zero-based row positions"],
            },
            "entries": {
                "op": "entries",
                "mode": sorted(ENTRY_MODES),
                "identity_source_columns": [
                    "source columns whose blank values mark continuation rows"
                ],
            },
            "map_column": {
                "op": "map_column",
                "source_column": "zero-based integer",
                "target_field": "declared semantic field",
                "parse_as": sorted(PARSE_TYPES),
            },
            "map_context": {
                "op": "map_context",
                "span_id": "an inspected source span",
                "target_field": "declared semantic field",
                "value": "literal value present in that span",
                "scope": "one scope object",
            },
            "satisfy": {
                "op": "satisfy",
                "rule_id": "declared admission rule",
                "span_id": "source span that directly establishes the rule",
                "scope": "one scope object",
            },
            "emit": {"op": "emit"},
        },
        "scope_shape": {
            "kind": sorted(SCOPE_KINDS),
            "source_column": "required for source_column/rows_with_marker",
            "marker": "required for rows_with_marker",
            "first_row": "required for row_range",
            "last_row": "required for row_range",
        },
    }


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a list")
    return value


def _scope(raw: Any) -> Scope:
    values = dict(raw) if isinstance(raw, Mapping) else {}
    kind = str(values.get("kind") or "all_rows")
    if kind not in SCOPE_KINDS:
        raise ValueError(f"unsupported table-language scope {kind!r}")
    source_column = values.get("source_column")
    first_row = values.get("first_row")
    last_row = values.get("last_row")
    scope = Scope(
        kind=kind,
        source_column=(int(source_column) if source_column is not None else None),
        marker=str(values.get("marker") or ""),
        first_row=(int(first_row) if first_row is not None else None),
        last_row=(int(last_row) if last_row is not None else None),
    )
    if kind == "rows_with_marker" and (
        scope.source_column is None or not scope.marker
    ):
        raise ValueError("rows_with_marker requires source_column and marker")
    if kind == "source_column" and scope.source_column is None:
        raise ValueError("source_column scope requires source_column")
    if kind == "row_range" and (
        scope.first_row is None
        or scope.last_row is None
        or scope.first_row > scope.last_row
    ):
        raise ValueError("row_range requires an ordered first_row and last_row")
    return scope


def parse_program(
    payload: Mapping[str, Any],
    *,
    target: TargetEntity,
    span_ids: Sequence[str],
) -> TableProgram:
    """Parse one program and reject references outside its declared surface."""

    if not isinstance(payload, Mapping):
        raise ValueError("table-language program must be an object")
    target_name = str(payload.get("target_entity") or "")
    if target_name != target.name:
        raise ValueError(
            f"program targets {target_name!r}; expected {target.name!r}"
        )
    commands = _sequence(payload.get("commands"), "commands")
    parse: ParseCommand | None = None
    entries: EntryCommand | None = None
    maps: list[MapColumnCommand] = []
    context_maps: list[MapContextCommand] = []
    satisfied: list[SatisfyCommand] = []
    emitted = False
    available_spans = set(str(item) for item in span_ids)
    available_rules = {rule.rule_id for rule in target.admission_rules}

    for position, raw in enumerate(commands):
        if not isinstance(raw, Mapping):
            raise ValueError(f"commands[{position}] must be an object")
        op = str(raw.get("op") or "")
        if op == "parse":
            if parse is not None:
                raise ValueError("program may contain exactly one parse command")
            parser_kind = str(raw.get("parser_kind") or "")
            if parser_kind not in PARSER_KINDS:
                raise ValueError(f"unsupported parser kind {parser_kind!r}")
            data_start = int(raw.get("data_start_row") or 0)
            if data_start < 0:
                raise ValueError("data_start_row must be non-negative")
            parse = ParseCommand(
                parser_kind=parser_kind,
                data_start_row=data_start,
                header_rows=tuple(
                    int(value)
                    for value in _sequence(
                        raw.get("header_rows") or (), "header_rows"
                    )
                ),
            )
        elif op == "entries":
            if entries is not None:
                raise ValueError("program may contain exactly one entries command")
            mode = str(raw.get("mode") or "one_per_row")
            if mode not in ENTRY_MODES:
                raise ValueError(f"unsupported entry mode {mode!r}")
            identity_columns = tuple(
                int(value)
                for value in _sequence(
                    raw.get("identity_source_columns") or (),
                    "identity_source_columns",
                )
            )
            if mode == "continuation_rows" and not identity_columns:
                raise ValueError(
                    "continuation_rows requires identity_source_columns"
                )
            entries = EntryCommand(mode, identity_columns)
        elif op == "map_column":
            field = str(raw.get("target_field") or "")
            if field not in target.fields:
                raise ValueError(f"unknown target field {field!r}")
            parse_as = str(raw.get("parse_as") or "text")
            if parse_as not in PARSE_TYPES:
                raise ValueError(f"unsupported parse type {parse_as!r}")
            maps.append(
                MapColumnCommand(
                    source_column=int(raw.get("source_column")),
                    target_field=field,
                    parse_as=parse_as,
                )
            )
        elif op == "map_context":
            field = str(raw.get("target_field") or "")
            span_id = str(raw.get("span_id") or "")
            if field not in target.fields:
                raise ValueError(f"unknown target field {field!r}")
            if span_id not in available_spans:
                raise ValueError(f"unknown context span {span_id!r}")
            context_maps.append(
                MapContextCommand(
                    span_id=span_id,
                    target_field=field,
                    value=raw.get("value"),
                    scope=_scope(raw.get("scope")),
                )
            )
        elif op == "satisfy":
            rule_id = str(raw.get("rule_id") or "")
            span_id = str(raw.get("span_id") or "")
            if rule_id not in available_rules:
                raise ValueError(f"unknown admission rule {rule_id!r}")
            if span_id not in available_spans:
                raise ValueError(f"unknown context span {span_id!r}")
            satisfied.append(
                SatisfyCommand(rule_id, span_id, _scope(raw.get("scope")))
            )
        elif op == "emit":
            if emitted:
                raise ValueError("program may contain exactly one emit command")
            emitted = True
        else:
            raise ValueError(f"unsupported table-language command {op!r}")

    if parse is None or entries is None or not maps or not emitted:
        raise ValueError(
            "program requires parse, entries, at least one map_column, and emit"
        )
    if commands and str(commands[-1].get("op") or "") != "emit":
        raise ValueError("emit must be the last table-language command")
    ordered_rules = {
        rule.field
        for rule in target.admission_rules
        if rule.operator in {"gt", "gte", "lt", "lte"}
    }
    comparable_types = {"number", "integer", "range", "date", "year"}
    mapped_types = {
        command.target_field: command.parse_as for command in maps
    }
    explicitly_satisfied = {command.rule_id for command in satisfied}
    unresolved_ordered = sorted(
        field
        for field in ordered_rules
        if mapped_types.get(field) not in comparable_types
        and not any(
            rule.field == field and rule.rule_id in explicitly_satisfied
            for rule in target.admission_rules
        )
    )
    if unresolved_ordered:
        raise ValueError(
            "ordered admission fields require a numeric/date parse or an "
            "evidence-linked satisfy command: " + ", ".join(unresolved_ordered)
        )
    return TableProgram(
        target_entity=target.name,
        parse=parse,
        entries=entries,
        column_maps=tuple(maps),
        context_maps=tuple(context_maps),
        satisfied_rules=tuple(satisfied),
        rationale=str(payload.get("rationale") or "").strip(),
    )
