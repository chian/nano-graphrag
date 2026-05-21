"""
Failure-driven command repair for GASL runtime commands.

The abstraction here is command-local and command-agnostic:
- one command failed or produced unusable output
- package local inputs / history / failure envelope
- ask the LLM for a replacement command
- retry that one command in isolation
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

from .search_refinement_agent import LLMSearchRefinementAgent
from nano_graphrag.prompt_system import get_prompt_system


@dataclass
class CommandRepairRequest:
    command_name: str
    prompt_builder: Callable[[list[Dict[str, Any]], int], str]
    row_iterator: Iterable[Dict[str, Any]]
    seed_text: str
    default_payload: Dict[str, Any]
    prompt_name: str
    prompt_logger: Any = None
    prompt_metadata: Optional[Dict[str, Any]] = None
    label_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    sample_limit: int = 20


@dataclass
class CommandFailureEnvelope:
    command_name: str
    stage: str
    status: str
    error_type: str
    error_message: str
    input_count: int
    output_count: int
    processing_method: str
    instruction: str
    query: str
    incoming_contract: Dict[str, Any]


@dataclass
class GenericCommandRepairRequest:
    command_name: str
    command_text: str
    failure: CommandFailureEnvelope
    input_rows: Iterable[Dict[str, Any]]
    query: str
    history: list[Dict[str, Any]]
    inputs: Dict[str, Any]
    prompt_logger: Any = None
    sample_limit: int = 20


@dataclass
class ProcessAlignmentRequest:
    data_iterator: Iterable[Dict[str, Any]]
    query: str
    instruction: str
    interpretation: Optional[Dict[str, Any]]
    probe_result: Dict[str, Any]
    prompt_logger: Any = None
    sample_limit: int = 20


class LLMCommandRepairAgent:
    def __init__(self, llm_func):
        self.llm_func = llm_func
        self._sampler = LLMSearchRefinementAgent(llm_func)

    def run_command_repair(self, request: CommandRepairRequest) -> Dict[str, Any]:
        rows = []
        for row in request.row_iterator:
            rows.append(row)
            if len(rows) >= request.sample_limit:
                break
        rows = self._sampler.sample_rows(rows, seed_text=request.seed_text, k=request.sample_limit)
        prompt_text = request.prompt_builder(rows, len(rows))
        observation_id = None
        try:
            if request.prompt_logger:
                observation_id = request.prompt_logger.record_invocation(
                    prompt_name=request.prompt_name,
                    prompt_text=prompt_text,
                    model=getattr(self.llm_func, "model", None),
                    metadata=request.prompt_metadata or {},
                )
            response = self.llm_func.call(prompt_text)
            parsed = self._parse_json(response)
            if request.prompt_logger and observation_id:
                request.prompt_logger.record_outcome(
                    observation_id,
                    prompt_name=request.prompt_name,
                    response_text=response,
                    parsed=parsed,
                    labels=request.label_builder(parsed) if request.label_builder else {},
                )
            return parsed
        except Exception:
            if request.prompt_logger and observation_id:
                request.prompt_logger.record_outcome(
                    observation_id,
                    prompt_name=request.prompt_name,
                    response_text=None,
                    parsed=request.default_payload,
                    labels={"parse_success": False},
                )
            return request.default_payload

    def get_command_repair(self, request: GenericCommandRepairRequest) -> Dict[str, Any]:
        sampled_inputs = []
        for row in request.input_rows:
            sampled_inputs.append(row)
            if len(sampled_inputs) >= request.sample_limit:
                break
        sampled_inputs = self._sampler.sample_rows(
            sampled_inputs,
            seed_text=f"{request.query}:{request.command_text}",
            k=request.sample_limit,
        )

        base_prompt = self._load_prompt_or_default("command_repair")
        command_guidance = self._load_prompt_or_default(f"command_repair_{request.command_name.lower()}", required=False)
        prompt_text = (
            f"{base_prompt}\n\n"
            f"Command-specific guidance:\n{command_guidance or 'No extra command-specific guidance.'}\n\n"
            f"Query:\n{request.query}\n\n"
            f"Current command:\n{request.command_text}\n\n"
            f"Failure envelope:\n{json.dumps(request.failure.__dict__, indent=2, default=str)}\n\n"
            f"Referenced inputs summary:\n{json.dumps(self._summarize_inputs(request.inputs), indent=2, default=str)}\n\n"
            f"Recent history:\n{json.dumps(request.history[-6:], indent=2, default=str)}\n\n"
            f"Sample input rows:\n{json.dumps(sampled_inputs[:request.sample_limit], indent=2, default=str)}\n"
        )
        obs_id = None
        default = {
            "retry": False,
            "replacement_command": "",
            "reason": "command repair agent unavailable",
            "confidence": 0.0,
        }
        try:
            if request.prompt_logger:
                obs_id = request.prompt_logger.record_invocation(
                    prompt_name="command_repair",
                    prompt_text=prompt_text,
                    model=getattr(self.llm_func, "model", None),
                    metadata={
                        "query": request.query,
                        "command_name": request.command_name,
                        "status": request.failure.status,
                        "error_type": request.failure.error_type,
                    },
                )
            raw = self.llm_func.call(prompt_text)
            parsed = self._parse_json(raw)
            if request.prompt_logger and obs_id:
                request.prompt_logger.record_outcome(
                    obs_id,
                    prompt_name="command_repair",
                    response_text=raw,
                    parsed=parsed,
                    labels={
                        "parse_success": bool(parsed),
                        "retry": bool(parsed.get("retry")),
                        "has_replacement": bool(parsed.get("replacement_command")),
                    },
                )
            return parsed or default
        except Exception:
            if request.prompt_logger and obs_id:
                request.prompt_logger.record_outcome(
                    obs_id,
                    prompt_name="command_repair",
                    response_text=None,
                    parsed=default,
                    labels={"parse_success": False},
                )
            return default

    def get_process_alignment(self, request: ProcessAlignmentRequest) -> Dict[str, Any]:
        rows = []
        for row in request.data_iterator:
            rows.append(row)
            if len(rows) >= request.sample_limit:
                break
        sampled_rows = self._sampler.sample_rows(rows, seed_text=f"{request.query}:{request.instruction}", k=request.sample_limit)
        prompt = f"""You are judging whether the current PROCESS probe is aligned with the intended instruction.

Query:
{request.query}

Instruction:
{request.instruction}

Interpretation:
{request.interpretation or {}}

Probe result summary:
{{
  "processing_method": {request.probe_result.get("processing_method", "")!r},
  "output_count": {len(request.probe_result.get("filtered_items") or request.probe_result.get("processed_items") or [])},
  "summary": {request.probe_result.get("summary", {})}
}}

Sample current rows:
{sampled_rows}

Return strict JSON:
{{
  "aligned": true,
  "alignment_confidence": 0.0,
  "alignment_reason": "<short reason>",
  "instruction_adjustment": "<small adjustment or empty string>"
}}"""
        obs_id = None
        try:
            if request.prompt_logger:
                obs_id = request.prompt_logger.record_invocation(
                    prompt_name="process_alignment",
                    prompt_text=prompt,
                    model=getattr(self.llm_func, "model", None),
                    metadata={"query": request.query, "instruction": request.instruction},
                )
            raw = self.llm_func.call(prompt)
            parsed = self._parse_json(raw)
            if request.prompt_logger and obs_id:
                request.prompt_logger.record_outcome(
                    obs_id,
                    prompt_name="process_alignment",
                    response_text=raw,
                    parsed=parsed,
                    labels={"parse_success": bool(parsed), "aligned": parsed.get("aligned")},
                )
            return parsed
        except Exception:
            if request.prompt_logger and obs_id:
                request.prompt_logger.record_outcome(
                    obs_id,
                    prompt_name="process_alignment",
                    response_text=None,
                    parsed={"aligned": True, "alignment_confidence": 0.0, "alignment_reason": "alignment agent unavailable", "instruction_adjustment": ""},
                    labels={"parse_success": False},
                )
            return {"aligned": True, "alignment_confidence": 0.0, "alignment_reason": "alignment agent unavailable", "instruction_adjustment": ""}

    def get_process_repair(
        self,
        *,
        failure: CommandFailureEnvelope,
        data_iterator: Iterable[Dict[str, Any]],
        query: str,
        instruction: str,
        history: list[Dict[str, Any]],
        incoming_contract: Dict[str, Any],
        interpretation: Optional[Dict[str, Any]],
        selection_diagnostics: Dict[str, Any],
        probe_result: Dict[str, Any],
        prompt_logger: Any = None,
    ) -> Dict[str, Any]:
        from gasl.process_repair_prompting import format_process_repair_case
        from nano_graphrag.prompt_system import get_prompt_system

        return self.run_command_repair(
            CommandRepairRequest(
                command_name="PROCESS",
                row_iterator=data_iterator,
                seed_text=f"{query}:{instruction}",
                prompt_name="process_repair",
                prompt_logger=prompt_logger,
                prompt_metadata={
                    "query": query,
                    "instruction": instruction,
                    "error_type": failure.error_type,
                    "error_message": failure.error_message,
                    "stage": failure.stage,
                    "probe_result_count": len(probe_result.get("filtered_items") or probe_result.get("processed_items") or []),
                },
                prompt_builder=lambda sampled_rows, sampled_count: f"{get_prompt_system().get_prompt('process_repair', optimize=False)}\n\n"
                + f"Failure envelope:\n{failure}\n\n"
                + format_process_repair_case(
                    data=sampled_rows,
                    query=query,
                    instruction=instruction,
                    history=history,
                    incoming_contract=incoming_contract,
                    interpretation=interpretation,
                    selection_diagnostics=selection_diagnostics,
                    probe_result=probe_result,
                ),
                default_payload={
                    "refined_instruction": "",
                    "selector_hint": "keep_current",
                    "current_rows_sufficient": True,
                    "confidence": 0.0,
                    "reason": "command repair agent unavailable",
                },
                label_builder=lambda parsed: {
                    "parse_success": bool(parsed),
                    "current_rows_sufficient": parsed.get("current_rows_sufficient"),
                    "selector_valid": parsed.get("selector_hint") in {"keep_current", "lexical", "vector", "central", "broaden", "narrow"},
                },
            )
        )

    def _load_prompt_or_default(self, prompt_name: str, required: bool = True) -> str:
        try:
            return get_prompt_system().get_prompt(prompt_name, optimize=False)
        except Exception:
            if required:
                raise
            return ""

    @staticmethod
    def _summarize_inputs(inputs: Dict[str, Any]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {"state": {}, "context": {}, "contracts": inputs.get("contracts", {})}
        for section in ("state", "context"):
            for key, value in (inputs.get(section) or {}).items():
                if isinstance(value, dict) and "items" in value:
                    summary[section][key] = {
                        "kind": "state_var",
                        "count": len(value.get("items", [])),
                        "keys": list((value.get("items") or [{}])[0].keys()) if value.get("items") else [],
                    }
                elif isinstance(value, list):
                    summary[section][key] = {
                        "kind": "rows",
                        "count": len(value),
                        "keys": list(value[0].keys()) if value and isinstance(value[0], dict) else [],
                    }
                elif isinstance(value, dict):
                    summary[section][key] = {"kind": "dict", "keys": list(value.keys())[:12]}
                else:
                    summary[section][key] = {"kind": type(value).__name__}
        return summary

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        try:
            text = text.strip()
            if text.startswith("```"):
                lines = text.splitlines()[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end >= start:
                text = text[start:end + 1]
            return json.loads(text)
        except Exception:
            return {}
