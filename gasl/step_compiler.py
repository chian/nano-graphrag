from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Literal, Optional

from nano_graphrag.prompt_system import get_prompt_system

from .parser import GASLParser
from .state import ContextStore, StateStore
from .types import Command


Availability = Literal[
    "materialized_nonempty",
    "materialized_empty",
    "current_output",
    "unavailable",
]
Shape = Literal["rows", "dict", "counter", "unknown"]
CompileAction = Literal["accept", "rewrite", "upstream_repair_needed", "reject"]


@dataclass
class SymbolState:
    name: str
    availability: Availability
    shape: Shape


@dataclass
class StepCompileResult:
    action: CompileAction
    command: Optional[Command]
    rendered_command: str
    reason: str
    symbol_scope: Dict[str, SymbolState]
    defects: list[Dict[str, Any]]


_NONEMPTY_REQUIRED_COMMANDS = {
    "PROCESS",
    "AGGREGATE",
    "PROJECT",
    "COLLAPSE",
    "RANK",
    "GRAPHWALK",
    "JOIN",
    "MERGE",
    "COMPARE",
    "SELECT",
    "GRAPHCONNECT",
    "ADD_FIELD",
}


_EXPECTED_INPUT_SHAPES: Dict[str, Shape] = {
    "PROCESS": "rows",
    "AGGREGATE": "rows",
    "PROJECT": "rows",
    "COLLAPSE": "rows",
    "RANK": "rows",
    "GRAPHWALK": "rows",
    "JOIN": "rows",
    "MERGE": "rows",
    "COMPARE": "rows",
    "SELECT": "rows",
    "GRAPHCONNECT": "rows",
    "ADD_FIELD": "rows",
}


class GASLStepCompiler:
    """Step-local verifier/compiler between planning and execution.

    It only reasons about:
    - availability: materialized_nonempty/materialized_empty/current_output/unavailable
    - shape: rows/dict/counter/unknown
    """

    def __init__(self, llm_func, parser: Optional[GASLParser] = None, prompt_logger=None, trace=None):
        self.llm_func = llm_func
        self.parser = parser or GASLParser()
        self.prompt_logger = prompt_logger
        self.trace = trace

    def compile_step(
        self,
        *,
        command: Command,
        query: str,
        state_store: StateStore,
        context_store: ContextStore,
        history: list[Dict[str, Any]],
    ) -> StepCompileResult:
        current_output = self._current_output_symbol(command)
        symbol_scope = self._build_symbol_scope(command, state_store, context_store, current_output)
        defects = self._verify_command(command, symbol_scope)
        if not defects:
            return StepCompileResult(
                action="accept",
                command=command,
                rendered_command=command.raw_text,
                reason="verified",
                symbol_scope=symbol_scope,
                defects=[],
            )

        rewrite = self._request_typed_rewrite(
            command=command,
            query=query,
            history=history,
            symbol_scope=symbol_scope,
            defects=defects,
            current_output=current_output,
        )
        if rewrite["action"] not in {"rewrite", "accept"}:
            return StepCompileResult(
                action=rewrite["action"],
                command=None,
                rendered_command="",
                reason=rewrite["reason"],
                symbol_scope=symbol_scope,
                defects=defects,
            )

        typed_command = rewrite.get("typed_command") or {}
        rendered = self._render_typed_command(typed_command)
        if not rendered:
            return StepCompileResult(
                action="reject",
                command=None,
                rendered_command="",
                reason="compiler produced unsupported typed command",
                symbol_scope=symbol_scope,
                defects=defects,
            )
        try:
            repaired = self.parser.parse_command(rendered, command.line_number)
        except Exception as exc:
            return StepCompileResult(
                action="reject",
                command=None,
                rendered_command=rendered,
                reason=f"compiled command did not parse: {exc}",
                symbol_scope=symbol_scope,
                defects=defects,
            )
        repaired_defects = self._verify_command(repaired, symbol_scope)
        if repaired_defects:
            return StepCompileResult(
                action="reject",
                command=None,
                rendered_command=rendered,
                reason="compiled command still violates step-local constraints",
                symbol_scope=symbol_scope,
                defects=repaired_defects,
            )
        return StepCompileResult(
            action="rewrite",
            command=repaired,
            rendered_command=rendered,
            reason=rewrite["reason"],
            symbol_scope=symbol_scope,
            defects=defects,
        )

    def _build_symbol_scope(
        self,
        command: Command,
        state_store: StateStore,
        context_store: ContextStore,
        current_output: Optional[str],
    ) -> Dict[str, SymbolState]:
        scope: Dict[str, SymbolState] = {}
        state = state_store.get_state()
        for name, var in state.get("variables", {}).items():
            availability, shape = self._infer_state_symbol(var)
            scope[name] = SymbolState(name=name, availability=availability, shape=shape)
        for name in context_store.keys():
            value = context_store.get(name)
            availability, shape = self._infer_context_symbol(value)
            existing = scope.get(name)
            if existing is None or self._availability_rank(availability) > self._availability_rank(existing.availability):
                scope[name] = SymbolState(name=name, availability=availability, shape=shape)
        if current_output:
            produced_shape = self._infer_output_shape(command)
            scope[current_output] = SymbolState(
                name=current_output,
                availability="current_output",
                shape=produced_shape,
            )
        for consumed in self._consumed_vars(command):
            scope.setdefault(
                consumed,
                SymbolState(name=consumed, availability="unavailable", shape="unknown"),
            )
        return scope

    def _verify_command(self, command: Command, symbol_scope: Dict[str, SymbolState]) -> list[Dict[str, Any]]:
        defects: list[Dict[str, Any]] = []
        if not self.parser.validate_command(command):
            defects.append({"kind": "schema", "message": "parser rejected command shape"})
        expected_shape = _EXPECTED_INPUT_SHAPES.get(command.command_type)
        require_nonempty = command.command_type in _NONEMPTY_REQUIRED_COMMANDS
        for variable in self._consumed_vars(command):
            symbol = symbol_scope.get(variable) or SymbolState(variable, "unavailable", "unknown")
            if symbol.availability in {"current_output", "unavailable"}:
                defects.append(
                    {
                        "kind": "availability",
                        "symbol": variable,
                        "availability": symbol.availability,
                        "message": f"symbol {variable} is not available as an input",
                    }
                )
            elif require_nonempty and symbol.availability == "materialized_empty":
                defects.append(
                    {
                        "kind": "availability",
                        "symbol": variable,
                        "availability": symbol.availability,
                        "message": f"symbol {variable} is materialized but empty",
                    }
                )
            if expected_shape and symbol.shape not in {expected_shape, "unknown"}:
                defects.append(
                    {
                        "kind": "shape",
                        "symbol": variable,
                        "shape": symbol.shape,
                        "expected": expected_shape,
                        "message": f"symbol {variable} has shape {symbol.shape}, expected {expected_shape}",
                    }
                )
        return defects

    def _request_typed_rewrite(
        self,
        *,
        command: Command,
        query: str,
        history: list[Dict[str, Any]],
        symbol_scope: Dict[str, SymbolState],
        defects: list[Dict[str, Any]],
        current_output: Optional[str],
    ) -> Dict[str, Any]:
        prompt = self._build_compile_prompt(
            command=command,
            query=query,
            history=history,
            symbol_scope=symbol_scope,
            defects=defects,
            current_output=current_output,
        )
        obs_id = None
        default = {"action": "upstream_repair_needed", "typed_command": {}, "reason": "no legal step-local rewrite"}
        try:
            if self.prompt_logger:
                obs_id = self.prompt_logger.record_invocation(
                    prompt_name="command_compile",
                    prompt_text=prompt,
                    model=getattr(self.llm_func, "model", None),
                    metadata={"command_type": command.command_type, "query": query},
                )
            raw = self.llm_func.call(prompt)
            parsed = self._parse_json(raw)
            if self.prompt_logger and obs_id:
                self.prompt_logger.record_outcome(
                    obs_id,
                    prompt_name="command_compile",
                    response_text=raw,
                    parsed=parsed,
                    labels={"parse_success": bool(parsed), "action": parsed.get("action")},
                )
            return parsed or default
        except Exception:
            if self.prompt_logger and obs_id:
                self.prompt_logger.record_outcome(
                    obs_id,
                    prompt_name="command_compile",
                    response_text=None,
                    parsed=default,
                    labels={"parse_success": False},
                )
            return default

    def _build_compile_prompt(
        self,
        *,
        command: Command,
        query: str,
        history: list[Dict[str, Any]],
        symbol_scope: Dict[str, SymbolState],
        defects: list[Dict[str, Any]],
        current_output: Optional[str],
    ) -> str:
        base = get_prompt_system().get_prompt("command_compile", optimize=False)
        symbol_json = json.dumps(
            {
                name: {"availability": state.availability, "shape": state.shape}
                for name, state in sorted(symbol_scope.items())
            },
            indent=2,
        )
        return (
            f"{base}\n\n"
            f"Query:\n{query}\n\n"
            f"Current command:\n{command.raw_text}\n\n"
            f"Command type:\n{command.command_type}\n\n"
            f"Current output symbol:\n{current_output or ''}\n\n"
            f"Available symbol scope:\n{symbol_json}\n\n"
            f"Defects:\n{json.dumps(defects, indent=2)}\n\n"
            f"Recent history:\n{json.dumps(history[-6:], indent=2, default=str)}\n"
        )

    @staticmethod
    def _render_typed_command(typed_command: Dict[str, Any]) -> str:
        command_type = str(typed_command.get("command_type", "")).upper()
        args = typed_command.get("args") or {}
        if command_type == "SELECT":
            distinct = " DISTINCT" if args.get("distinct") else ""
            return f"SELECT{distinct} {args['source']} FIELDS {args['fields']} AS {args['target']}"
        if command_type == "GRAPHCONNECT":
            return f"GRAPHCONNECT {args['variable1']} to {args['variable2']} via {args['via_pattern']} AS {args['result_variable']}"
        if command_type == "AGGREGATE":
            return f"AGGREGATE {args['variable']} by {args['by_field']} with {args['operation']} AS {args['result_variable']}"
        if command_type == "PROJECT":
            suffix = " PRESERVE_MULTIPLICITY" if args.get("preserve_multiplicity") else ""
            keys = f" KEYS {args['keys']}" if args.get("keys") else ""
            weight = f" WEIGHT {args['weight_field']}" if args.get("weight_field") else ""
            return f"PROJECT {args['variable']} GRAIN {args['grain']} FIELDS {args['fields']}{keys}{weight}{suffix} AS {args['result_variable']}"
        if command_type == "COLLAPSE":
            weight = f" COUNT AS {args['weight_field']}" if args.get("weight_field") else ""
            return f"COLLAPSE {args['variable']} BY {args['by_field']}{weight} AS {args['result_variable']}"
        if command_type == "MERGE":
            variables = args["variables"]
            if isinstance(variables, list):
                variables = ",".join(variables)
            return f"MERGE {variables} AS {args['result_variable']}"
        if command_type == "JOIN":
            return f"JOIN {args['variable1']} with {args['variable2']} on {args['join_field']} AS {args['result_variable']}"
        if command_type == "COMPARE":
            return f"COMPARE {args['variable1']} with {args['variable2']} on {args['comparison_field']} AS {args['result_variable']}"
        if command_type == "GRAPHWALK":
            depth = f" depth {args['depth']}" if args.get("depth") else ""
            return f"GRAPHWALK from {args['from_variable']} follow {args['relationship_types']}{depth} AS {args['result_var']}"
        if command_type == "PROCESS":
            target = f" AS {args['target_variable']}" if args.get("target_variable") else ""
            return f"PROCESS {args['variable']} {args['instruction']}{target}"
        if command_type == "RANK":
            order = f" order {args['order']}" if args.get("order") else ""
            return f"RANK {args['variable']} by {args['field']}{order}"
        if command_type == "ADD_FIELD":
            return f"ADD_FIELD {args['variable']} field: {args['field_name']} = {args['source_variable']}"
        return ""

    @staticmethod
    def _consumed_vars(command: Command) -> Iterable[str]:
        args = command.args
        command_type = command.command_type
        if command_type in {"PROCESS", "AGGREGATE", "PROJECT", "COLLAPSE", "UPDATE", "CLASSIFY", "SCORE", "RANK"}:
            variable = args.get("variable")
            if isinstance(variable, str):
                yield variable
        elif command_type in {"JOIN", "COMPARE", "GRAPHCONNECT"}:
            for key in ("variable1", "variable2"):
                variable = args.get(key)
                if isinstance(variable, str):
                    yield variable
        elif command_type == "MERGE":
            variables = args.get("variables")
            if isinstance(variables, str):
                for variable in variables.split(","):
                    variable = variable.strip()
                    if variable:
                        yield variable
        elif command_type == "GRAPHWALK":
            variable = args.get("from_variable")
            if isinstance(variable, str):
                yield variable
        elif command_type == "SELECT":
            variable = args.get("source")
            if isinstance(variable, str):
                yield variable
        elif command_type == "ADD_FIELD":
            for key in ("variable", "source_variable"):
                variable = args.get(key)
                if isinstance(variable, str):
                    yield variable
        elif command_type in {"CREATE_NODES", "CREATE_EDGES", "CREATE_GROUPS"}:
            variable = args.get("source_variable")
            if isinstance(variable, str):
                yield variable

    @staticmethod
    def _current_output_symbol(command: Command) -> Optional[str]:
        for key in ("result_variable", "target_variable", "result_var", "target"):
            value = command.args.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _infer_output_shape(command: Command) -> Shape:
        if command.command_type == "COUNT":
            return "counter"
        if command.command_type == "DECLARE":
            return "unknown"
        return _EXPECTED_INPUT_SHAPES.get(command.command_type, "rows")

    @staticmethod
    def _availability_rank(availability: Availability) -> int:
        order = {
            "unavailable": 0,
            "current_output": 1,
            "materialized_empty": 2,
            "materialized_nonempty": 3,
        }
        return order[availability]

    @staticmethod
    def _infer_state_symbol(var: Any) -> tuple[Availability, Shape]:
        if not isinstance(var, dict):
            return GASLStepCompiler._infer_context_symbol(var)
        meta = var.get("_meta", {})
        var_type = meta.get("type")
        if var_type == "LIST":
            count = len(var.get("items", []))
            return ("materialized_nonempty" if count > 0 else "materialized_empty", "rows")
        if var_type == "DICT":
            data_keys = [k for k in var.keys() if k not in {"_meta", "provenance"}]
            return ("materialized_nonempty" if data_keys else "materialized_empty", "dict")
        if var_type == "COUNTER":
            value = var.get("value", 0)
            return ("materialized_nonempty" if value else "materialized_empty", "counter")
        return ("materialized_nonempty", "unknown")

    @staticmethod
    def _infer_context_symbol(value: Any) -> tuple[Availability, Shape]:
        if isinstance(value, list):
            return ("materialized_nonempty" if len(value) > 0 else "materialized_empty", "rows")
        if isinstance(value, dict):
            if "items" in value and isinstance(value.get("items"), list):
                return ("materialized_nonempty" if len(value["items"]) > 0 else "materialized_empty", "rows")
            return ("materialized_nonempty" if len(value) > 0 else "materialized_empty", "dict")
        if isinstance(value, (int, float)):
            return ("materialized_nonempty" if value else "materialized_empty", "counter")
        if value is None:
            return ("materialized_empty", "unknown")
        return ("materialized_nonempty", "unknown")

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        s = text.strip()
        if s.startswith("```"):
            nl = s.find("\n")
            if nl >= 0:
                s = s[nl + 1:]
            end = s.rfind("```")
            if end >= 0:
                s = s[:end]
            s = s.strip()
        return json.loads(s)
