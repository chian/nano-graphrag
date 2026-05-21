from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .parser import GASLParser


_COMMAND_REQUIRED_ARGS: Dict[str, set[str]] = {
    "GRAPHCONNECT": {"variable1", "variable2", "via_pattern"},
    "REQUIRE": {"variable", "condition"},
    "JOIN": {"variable1", "variable2", "join_field", "result_variable"},
    "MERGE": {"variables", "result_variable"},
    "COMPARE": {"variable1", "variable2", "comparison_field", "result_variable"},
    "PROJECT": {"variable", "grain", "fields"},
    "COLLAPSE": {"variable", "by_field"},
    "AGGREGATE": {"variable", "by_field", "operation"},
    "PROCESS": {"variable", "instruction"},
    "SELECT": {"source", "fields", "target"},
    "ADD_FIELD": {"variable", "field_name", "source_variable"},
}


@dataclass
class TwoPhasePlanResult:
    symbol_table: List[Dict[str, Any]]
    symbol_prompt: str
    symbol_response: str
    plan_prompt: str
    plan_response: str
    plan_json: Dict[str, Any]
    validation: Dict[str, Any]


class TwoPhasePlanner:
    def __init__(self, llm_func, parser: Optional[GASLParser] = None, prompt_logger=None, trace=None):
        self.llm_func = llm_func
        self.parser = parser or GASLParser()
        self.prompt_logger = prompt_logger
        self.trace = trace

    def generate_plan(
        self,
        *,
        query: str,
        schema: Dict[str, Any],
        state: Dict[str, Any],
        history: List[Dict[str, Any]],
        iteration: int,
        existing_symbol_table: Optional[List[Dict[str, Any]]] = None,
    ) -> TwoPhasePlanResult:
        symbol_prompt = ""
        symbol_response = ""
        symbol_table = existing_symbol_table or []
        if not symbol_table:
            symbol_prompt = self.llm_func.create_plan_symbols_prompt(query, schema, state, history)
            symbol_obs_id = None
            if self.prompt_logger:
                symbol_obs_id = self.prompt_logger.record_invocation(
                    prompt_name="plan_symbols",
                    prompt_text=symbol_prompt,
                    model=getattr(self.llm_func, "model", None),
                    metadata={"iteration": iteration, "query": query},
                )
            if self.trace:
                self.trace.log(
                    "planner_symbols_prompt",
                    {"iteration": iteration, "query": query, "prompt": symbol_prompt},
                )
            symbol_response = self.llm_func.call(symbol_prompt)
            symbol_table = self._parse_symbol_response(symbol_response)
            if self.prompt_logger and symbol_obs_id:
                self.prompt_logger.record_outcome(
                    symbol_obs_id,
                    prompt_name="plan_symbols",
                    response_text=symbol_response,
                    parsed={"symbols": symbol_table},
                    labels={"parse_success": bool(symbol_table)},
                    metadata={"iteration": iteration},
                )
            if self.trace:
                self.trace.log(
                    "planner_symbols_response",
                    {
                        "iteration": iteration,
                        "raw_response": symbol_response,
                        "parsed": {"symbols": symbol_table},
                    },
                )

        plan_prompt = self.llm_func.create_plan_prompt(
            query,
            schema,
            state,
            history,
            symbol_table=symbol_table,
        )
        plan_obs_id = None
        if self.prompt_logger:
            plan_obs_id = self.prompt_logger.record_invocation(
                prompt_name="plan_generation",
                prompt_text=plan_prompt,
                model=getattr(self.llm_func, "model", None),
                metadata={
                    "iteration": iteration,
                    "query": query,
                    "phase": "constrained",
                    "symbol_count": len(symbol_table),
                },
            )
        plan_response = self.llm_func.call(plan_prompt)
        plan_json = json.loads(self._extract_json(plan_response))
        if self.prompt_logger and plan_obs_id:
            self.prompt_logger.record_outcome(
                plan_obs_id,
                prompt_name="plan_generation",
                response_text=plan_response,
                parsed=plan_json,
                labels={"parse_success": True, "phase": "constrained"},
                metadata={"iteration": iteration},
            )
        validation = self.validate_plan(plan_json, symbol_table)
        if not validation["ok"]:
            plan_prompt = self.llm_func.create_plan_prompt(
                query,
                schema,
                state,
                history,
                symbol_table=symbol_table,
                validation_defects=validation["defects"],
            )
            plan_obs_id = None
            if self.prompt_logger:
                plan_obs_id = self.prompt_logger.record_invocation(
                    prompt_name="plan_generation",
                    prompt_text=plan_prompt,
                    model=getattr(self.llm_func, "model", None),
                    metadata={
                        "iteration": iteration,
                        "query": query,
                        "phase": "constrained_retry",
                        "symbol_count": len(symbol_table),
                    },
                )
            plan_response = self.llm_func.call(plan_prompt)
            plan_json = json.loads(self._extract_json(plan_response))
            if self.prompt_logger and plan_obs_id:
                self.prompt_logger.record_outcome(
                    plan_obs_id,
                    prompt_name="plan_generation",
                    response_text=plan_response,
                    parsed=plan_json,
                    labels={"parse_success": True, "phase": "constrained_retry"},
                    metadata={"iteration": iteration},
                )
            validation = self.validate_plan(plan_json, symbol_table)
        return TwoPhasePlanResult(
            symbol_table=symbol_table,
            symbol_prompt=symbol_prompt,
            symbol_response=symbol_response,
            plan_prompt=plan_prompt,
            plan_response=plan_response,
            plan_json=plan_json,
            validation=validation,
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        s = text.strip()
        if s.startswith("```"):
            nl = s.find("\n")
            if nl >= 0:
                s = s[nl + 1 :]
            end = s.rfind("```")
            if end >= 0:
                s = s[:end]
            s = s.strip()
        if s and s[0] not in "{[":
            starts = [i for i in (s.find("{"), s.find("[")) if i >= 0]
            if starts:
                s = s[min(starts) :]
        if not s or s[0] not in "{[":
            return s
        open_ch = s[0]
        close_ch = "}" if open_ch == "{" else "]"
        depth = 0
        in_str = False
        escape = False
        for idx, ch in enumerate(s):
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return s[: idx + 1]
        return s

    def _parse_symbol_response(self, response_text: str) -> List[Dict[str, Any]]:
        parsed = json.loads(self._extract_json(response_text))
        symbols = parsed.get("symbols", [])
        if not isinstance(symbols, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for symbol in symbols:
            if not isinstance(symbol, dict):
                continue
            name = str(symbol.get("name", "")).strip()
            if not name:
                continue
            normalized.append(
                {
                    "name": name,
                    "role": str(symbol.get("role", "")).strip(),
                    "shape": str(symbol.get("shape", "")).strip().lower(),
                    "producer": str(symbol.get("producer", "")).strip(),
                    "rationale": str(symbol.get("rationale", "")).strip(),
                }
            )
        return normalized

    def validate_plan(self, plan_json: Dict[str, Any], symbol_table: List[Dict[str, Any]]) -> Dict[str, Any]:
        defects: List[Dict[str, Any]] = []
        commands = plan_json.get("commands", [])
        if not isinstance(commands, list) or not all(isinstance(cmd, str) for cmd in commands):
            defects.append({"kind": "command_shape", "detail": "commands must be a list of GASL command strings"})
            return {"ok": False, "defects": defects}
        parsed = self.parser.parse_plan(plan_json)
        allowed = {symbol["name"] for symbol in symbol_table if symbol.get("name")}
        defined = {symbol["name"] for symbol in symbol_table if symbol.get("producer") == "input" and symbol.get("name")}
        for command in parsed:
            required = _COMMAND_REQUIRED_ARGS.get(command.command_type, set())
            missing = sorted(required - set(command.args.keys()))
            if missing:
                defects.append(
                    {
                        "kind": "interface",
                        "command_type": command.command_type,
                        "command": command.raw_text,
                        "missing_args": missing,
                    }
                )
            for variable in self._consumed_vars(command):
                if variable not in defined:
                    defects.append(
                        {
                            "kind": "undefined_symbol",
                            "command_type": command.command_type,
                            "command": command.raw_text,
                            "symbol": variable,
                        }
                    )
                if allowed and variable not in allowed:
                    defects.append(
                        {
                            "kind": "out_of_vocab_consume",
                            "command_type": command.command_type,
                            "command": command.raw_text,
                            "symbol": variable,
                        }
                    )
            for variable in self._produced_vars(command):
                if allowed and variable not in allowed:
                    defects.append(
                        {
                            "kind": "out_of_vocab_produce",
                            "command_type": command.command_type,
                            "command": command.raw_text,
                            "symbol": variable,
                        }
                    )
                defined.add(variable)
        return {"ok": not defects, "defects": defects}

    @staticmethod
    def _consumed_vars(command) -> Iterable[str]:
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
        elif command_type == "ITERATE":
            variable = args.get("source_var")
            if isinstance(variable, str):
                yield variable
        elif command_type == "SUBGRAPH":
            variable = args.get("around_variable")
            if isinstance(variable, str):
                yield variable
        elif command_type == "GRAPHPATTERN":
            variable = args.get("in_variable")
            if isinstance(variable, str):
                yield variable

    @staticmethod
    def _produced_vars(command) -> Iterable[str]:
        args = command.args
        command_type = command.command_type
        for key in ("result_variable", "target_variable", "result_var"):
            variable = args.get(key)
            if isinstance(variable, str):
                yield variable
        if command_type == "DECLARE":
            variable = args.get("variable")
            if isinstance(variable, str):
                yield variable
        if command_type == "SELECT":
            target = args.get("target")
            if isinstance(target, str):
                yield target
