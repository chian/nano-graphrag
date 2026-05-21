"""
Plan-iteration helper for GASL runtime loops.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

PLAN_ITERATION_ALLOWED_MODES = {"patch", "pass"}


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


@dataclass
class PlanIterationRequest:
    query: str
    previous_plan: Dict[str, Any]
    results: Dict[str, Any]
    iteration: int
    state: Dict[str, Any]


class PlanIterationAgent:
    def __init__(self, llm_func, prompt_logger=None, trace=None):
        self.llm_func = llm_func
        self.prompt_logger = prompt_logger
        self.trace = trace

    def iterate_plan(self, request: PlanIterationRequest) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        repair_prompt = self.llm_func.create_plan_iteration_prompt(
            query=request.query,
            previous_plan=request.previous_plan,
            results=request.results,
            iteration=request.iteration,
            state=request.state,
        )
        repair_obs_id = None
        if self.prompt_logger:
            repair_obs_id = self.prompt_logger.record_invocation(
                prompt_name="plan_iteration",
                prompt_text=repair_prompt,
                model=getattr(self.llm_func, "model", None),
                metadata={"iteration": request.iteration, "query": request.query},
            )
        raw = self.llm_func.call(repair_prompt)
        parsed = self.parse_response(raw)
        if self.prompt_logger and repair_obs_id:
            self.prompt_logger.record_outcome(
                repair_obs_id,
                prompt_name="plan_iteration",
                response_text=raw,
                parsed=parsed,
                labels={"mode": parsed.get("mode", ""), "parse_success": bool(parsed)},
                metadata={"iteration": request.iteration},
            )
        if self.trace:
            self.trace.log("plan_iteration_prompt", {"iteration": request.iteration, "prompt": repair_prompt})
            self.trace.log("plan_iteration_response", {"iteration": request.iteration, "response": raw, "parsed": parsed})
        if not parsed or parsed.get("mode") not in PLAN_ITERATION_ALLOWED_MODES:
            return None, parsed
        if parsed["mode"] == "patch":
            repaired = self.apply_patch(request.previous_plan, parsed)
            return repaired, parsed
        return None, parsed

    @staticmethod
    def parse_response(text: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(_extract_json(text))
            if not isinstance(parsed, dict):
                return {}
            mode = parsed.get("mode")
            if mode in {"replan", "noop"}:
                parsed["mode"] = "pass"
            return parsed
        except Exception:
            return {}

    @staticmethod
    def apply_patch(plan_json: Dict[str, Any], patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        commands = list(plan_json.get("commands", []))
        changed = False
        replace_command = (patch.get("replace_command") or "").strip()
        replacement_command = (patch.get("replacement_command") or "").strip()
        insert_after = (patch.get("insert_after_command") or "").strip()
        insert_command = (patch.get("insert_command") or "").strip()
        delete_command = (patch.get("delete_command") or "").strip()

        if replace_command and replacement_command:
            for idx, cmd in enumerate(commands):
                if cmd.strip() == replace_command:
                    commands[idx] = replacement_command
                    changed = True
                    break
        if delete_command:
            new_commands = [cmd for cmd in commands if cmd.strip() != delete_command]
            if len(new_commands) != len(commands):
                commands = new_commands
                changed = True
        if insert_after and insert_command:
            for idx, cmd in enumerate(commands):
                if cmd.strip() == insert_after:
                    commands.insert(idx + 1, insert_command)
                    changed = True
                    break
        if not changed:
            return None
        updated = dict(plan_json)
        updated["commands"] = commands
        why = patch.get("reason")
        if why:
            updated["why"] = f"{plan_json.get('why', '')}\nPatch: {why}".strip()
        return updated
