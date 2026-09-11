from __future__ import annotations

import json
from dataclasses import dataclass
from copy import deepcopy
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
CompileAction = Literal["accept", "rewrite", "patch_two", "upstream_repair_needed", "reject"]


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
    commands: list[Command]
    rendered_commands: list[str]
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

_DEFECT_EXPLANATION_TEMPLATES: Dict[tuple[str, str], str] = {
    ("availability", "current_output"): (
        "the proposed rewrite still reads its own output symbol '{symbol}' as an input; "
        "output symbols are write-only at this step"
    ),
    ("availability", "unavailable"): (
        "the proposed rewrite references '{symbol}', but no materialized variable with that name exists in local scope"
    ),
    ("availability", "materialized_empty"): (
        "the proposed rewrite depends on '{symbol}', but that symbol is materialized and empty in local scope"
    ),
    ("shape", ""): (
        "the proposed rewrite expects {expected} input from '{symbol}', but local scope has shape {shape}"
    ),
    ("schema", ""): (
        "the proposed rewrite has an invalid GASL command shape and does not pass parser validation"
    ),
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
        previous_command: Optional[Command] = None,
        next_command: Optional[Command] = None,
    ) -> StepCompileResult:
        current_output = self._current_output_symbol(command)
        symbol_scope = self._build_symbol_scope(command, state_store, context_store, current_output)
        defects = self._verify_command(command, symbol_scope)
        if not defects:
            return StepCompileResult(
                action="accept",
                command=command,
                rendered_command=command.raw_text,
                commands=[command],
                rendered_commands=[command.raw_text],
                reason="verified",
                symbol_scope=symbol_scope,
                defects=[],
            )

        rewrite = self._request_rewrite(
            command=command,
            query=query,
            history=history,
            symbol_scope=symbol_scope,
            defects=defects,
            current_output=current_output,
            previous_command=previous_command,
            next_command=next_command,
            state_store=state_store,
            context_store=context_store,
        )
        if rewrite["action"] not in {"rewrite", "patch_two", "accept"}:
            return StepCompileResult(
                action=rewrite["action"],
                command=None,
                rendered_command="",
                commands=[],
                rendered_commands=[],
                reason=rewrite["reason"],
                symbol_scope=symbol_scope,
                defects=defects,
            )

        rendered_commands = rewrite.get("commands") or []
        if not rendered_commands:
            return StepCompileResult(
                action="reject",
                command=None,
                rendered_command="",
                commands=[],
                rendered_commands=[],
                reason="compiler produced unsupported typed command",
                symbol_scope=symbol_scope,
                defects=defects,
            )

        parsed_commands: list[Command] = []
        for idx, rendered in enumerate(rendered_commands, start=1):
            try:
                repaired = self.parser.parse_command(rendered, command.line_number)
            except Exception as exc:
                return StepCompileResult(
                    action="reject",
                    command=None,
                    rendered_command=rendered,
                    commands=[],
                    rendered_commands=rendered_commands,
                    reason=f"compiled command did not parse: {exc}",
                    symbol_scope=symbol_scope,
                    defects=defects,
                )
            parsed_commands.append(repaired)

        repaired_defects = self._verify_command_sequence(parsed_commands, symbol_scope)
        if repaired_defects:
            return StepCompileResult(
                action="reject",
                command=None,
                rendered_command=rendered_commands[0],
                commands=[],
                rendered_commands=rendered_commands,
                reason=self._explain_defect(repaired_defects[0], rendered_commands),
                symbol_scope=symbol_scope,
                defects=repaired_defects,
            )
        return StepCompileResult(
            action="patch_two" if len(parsed_commands) == 2 else "rewrite",
            command=parsed_commands[0],
            rendered_command=rendered_commands[0],
            commands=parsed_commands,
            rendered_commands=rendered_commands,
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
        consumed = set(self._consumed_vars(command))
        if current_output and current_output not in consumed:
            produced_shape = self._infer_output_shape(command)
            scope[current_output] = SymbolState(
                name=current_output,
                availability="current_output",
                shape=produced_shape,
            )
        for consumed in consumed:
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

    def _request_rewrite(
        self,
        *,
        command: Command,
        query: str,
        history: list[Dict[str, Any]],
        symbol_scope: Dict[str, SymbolState],
        defects: list[Dict[str, Any]],
        current_output: Optional[str],
        previous_command: Optional[Command],
        next_command: Optional[Command],
        state_store: StateStore,
        context_store: ContextStore,
    ) -> Dict[str, Any]:
        prompt = self._build_compile_prompt(
            command=command,
            query=query,
            history=history,
            symbol_scope=symbol_scope,
            defects=defects,
            current_output=current_output,
            previous_command=previous_command,
            next_command=next_command,
            state_store=state_store,
            context_store=context_store,
        )
        obs_id = None
        default = {"action": "upstream_repair_needed", "commands": [], "reason": "no legal step-local patch"}
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
            return self._normalize_rewrite_response(parsed or default)
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
        previous_command: Optional[Command],
        next_command: Optional[Command],
        state_store: StateStore,
        context_store: ContextStore,
    ) -> str:
        base = get_prompt_system().get_prompt("command_compile", optimize=False)
        symbol_json = json.dumps(
            {
                name: {"availability": state.availability, "shape": state.shape}
                for name, state in sorted(symbol_scope.items())
            },
            indent=2,
        )
        contracts_json = json.dumps(
            self._build_contract_scope(
                command=command,
                current_output=current_output,
                previous_command=previous_command,
                next_command=next_command,
                state_store=state_store,
                context_store=context_store,
            ),
            indent=2,
            default=str,
        )
        last_failure = next((entry for entry in reversed(history) if entry.get("status") == "error"), None)
        return (
            f"{base}\n\n"
            f"Query:\n{query}\n\n"
            f"Current command:\n{command.raw_text}\n\n"
            f"Previous command:\n{previous_command.raw_text if previous_command else ''}\n\n"
            f"Next command:\n{next_command.raw_text if next_command else ''}\n\n"
            f"Command type:\n{command.command_type}\n\n"
            f"Current output symbol:\n{current_output or ''}\n\n"
            f"Available symbol scope:\n{symbol_json}\n\n"
            f"Variable contracts and declared types:\n{contracts_json}\n\n"
            f"Defects:\n{json.dumps(defects, indent=2)}\n\n"
            f"Last failure:\n{json.dumps(last_failure, indent=2, default=str)}\n\n"
            f"Recent history:\n{json.dumps(history[-6:], indent=2, default=str)}\n"
        )

    def _build_contract_scope(
        self,
        *,
        command: Command,
        current_output: Optional[str],
        previous_command: Optional[Command],
        next_command: Optional[Command],
        state_store: StateStore,
        context_store: ContextStore,
    ) -> Dict[str, Any]:
        contract_scope: Dict[str, Any] = {}
        relevant_symbols = set(self._consumed_vars(command))
        if current_output:
            relevant_symbols.add(current_output)
        for neighbor in (previous_command, next_command):
            if neighbor is None:
                continue
            relevant_symbols.update(self._consumed_vars(neighbor))
            neighbor_output = self._current_output_symbol(neighbor)
            if neighbor_output:
                relevant_symbols.add(neighbor_output)
        for name in sorted(relevant_symbols):
            if not name:
                continue
            declared_type = None
            if state_store.has_variable(name):
                declared_type = state_store.get_variable(name).get("_meta", {}).get("type")
                contract = state_store.get_variable_contract(name)
            else:
                contract = context_store.get_contract(name) if context_store.has(name) else {}
            contract_scope[name] = {
                "declared_type": declared_type,
                "contract": contract,
            }
        return contract_scope

    def _normalize_rewrite_response(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        action = str(parsed.get("action", "upstream_repair_needed"))
        if action == "rewrite_one":
            action = "rewrite"
        commands = parsed.get("commands")
        if not isinstance(commands, list):
            commands = []
        commands = [str(cmd).strip() for cmd in commands if isinstance(cmd, str) and str(cmd).strip()]
        if not commands:
            typed_command = parsed.get("typed_command") or {}
            rendered = self._render_typed_command(typed_command)
            if rendered:
                commands = [rendered]
        if action == "rewrite" and len(commands) == 2:
            action = "patch_two"
        return {
            "action": action,
            "commands": commands[:2],
            "reason": parsed.get("reason", ""),
        }

    def _verify_command_sequence(
        self,
        commands: list[Command],
        symbol_scope: Dict[str, SymbolState],
    ) -> list[Dict[str, Any]]:
        scope = deepcopy(symbol_scope)
        defects: list[Dict[str, Any]] = []
        for idx, command in enumerate(commands):
            local_defects = self._verify_command(command, scope)
            if local_defects:
                for defect in local_defects:
                    defects.append({"patch_index": idx, **defect})
                return defects
            output = self._current_output_symbol(command)
            if output:
                scope[output] = SymbolState(
                    name=output,
                    availability="materialized_nonempty",
                    shape=self._infer_output_shape(command),
                )
        return defects

    def _explain_defect(self, defect: Dict[str, Any], rendered_commands: list[str]) -> str:
        patch_index = int(defect.get("patch_index", 0))
        patch_label = f"patch command {patch_index + 1}"
        kind = str(defect.get("kind", "") or "")
        availability = str(defect.get("availability", "") or "")
        template = _DEFECT_EXPLANATION_TEMPLATES.get((kind, availability))
        if template is None:
            template = _DEFECT_EXPLANATION_TEMPLATES.get((kind, ""), defect.get("message", "compiled command still violates step-local constraints"))
        rendered = rendered_commands[patch_index] if 0 <= patch_index < len(rendered_commands) else ""
        explanation = template.format(**defect)
        if rendered:
            return f"{patch_label} `{rendered}` failed because {explanation}"
        return f"{patch_label} failed because {explanation}"

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
