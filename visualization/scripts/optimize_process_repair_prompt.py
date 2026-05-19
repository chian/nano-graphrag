#!/usr/bin/env python3
"""
Offline GEPA optimization for the PROCESS repair prompt.

Uses traced PROCESS cases and deterministic contract-validity labels.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from gepa.api import optimize
from gepa.adapters.default_adapter.default_adapter import DefaultAdapter, DefaultDataInst, EvaluationResult

from gasl.process_repair_prompting import format_process_repair_case
from gasl.llm.argo_bridge import ArgoBridgeLLM
from gasl.llm.runtime_config import resolve_runtime_llm_config


ALLOWED_SELECTOR_HINTS = {"keep_current", "lexical", "vector", "central", "broaden", "narrow"}


@dataclass
class RepairCase:
    case_id: str
    query: str
    instruction: str
    incoming_contract: Dict[str, Any]
    interpretation: Optional[Dict[str, Any]]
    selection_diagnostics: Dict[str, Any]
    probe_result: Dict[str, Any]
    rows: List[Dict[str, Any]]
    history: List[Dict[str, Any]]
    contract_valid: bool
    failure_mode: str
    ordered_hint: bool

    def to_data_inst(self) -> DefaultDataInst:
        case_text = format_process_repair_case(
            data=self.rows,
            query=self.query,
            instruction=self.instruction,
            history=self.history,
            incoming_contract=self.incoming_contract,
            interpretation=self.interpretation,
            selection_diagnostics=self.selection_diagnostics,
            probe_result=self.probe_result,
        )
        return {
            "input": case_text,
            "additional_context": {
                "case_id": self.case_id,
                "contract_valid": str(self.contract_valid).lower(),
                "failure_mode": self.failure_mode,
                "ordered_hint": str(self.ordered_hint).lower(),
            },
            "answer": "",
        }


class ProcessRepairEvaluator:
    def __init__(self, cases_by_id: Dict[str, RepairCase]):
        self.cases_by_id = cases_by_id

    def __call__(self, data: DefaultDataInst, response: str) -> EvaluationResult:
        case = self.cases_by_id[data["additional_context"]["case_id"]]
        try:
            parsed = json.loads(_strip_json_fences(response))
        except Exception:
            return EvaluationResult(
                score=0.0,
                feedback="Response was not valid JSON with the required schema.",
                objective_scores={"json_valid": 0.0, "contract_alignment": 0.0},
            )

        selector = str(parsed.get("selector_hint", "") or "")
        sufficient = bool(parsed.get("current_rows_sufficient", False))
        refined_instruction = str(parsed.get("refined_instruction", "") or "")
        confidence = float(parsed.get("confidence", 0.0) or 0.0)

        json_valid = 1.0
        selector_valid = 1.0 if selector in ALLOWED_SELECTOR_HINTS else 0.0
        contract_alignment = 1.0 if sufficient == case.contract_valid else 0.0
        ordered_alignment = 1.0
        if case.ordered_hint and case.contract_valid:
            ordered_alignment = 1.0 if ("preserve order" in refined_instruction.lower() or "current rows" in refined_instruction.lower()) else 0.0
        confidence_sane = 1.0 if 0.0 <= confidence <= 1.0 else 0.0

        score = (
            0.25 * json_valid +
            0.15 * selector_valid +
            0.35 * contract_alignment +
            0.15 * ordered_alignment +
            0.10 * confidence_sane
        )

        feedback_parts = []
        if selector_valid == 0.0:
            feedback_parts.append("Use one allowed selector_hint only.")
        if contract_alignment == 0.0:
            if case.contract_valid:
                feedback_parts.append("This case is a positive contract-valid example. The repair should usually keep the current rows sufficient.")
            else:
                feedback_parts.append(f"This case is contract-invalid. Failure mode: {case.failure_mode}. The repair should mark current_rows_sufficient=false or choose a narrowing/broadening strategy.")
        if ordered_alignment == 0.0:
            feedback_parts.append("The case indicates ordered/ranked rows; preserve order and constrain to current rows.")
        if confidence_sane == 0.0:
            feedback_parts.append("Confidence must be a float in [0.0, 1.0].")
        if not feedback_parts:
            feedback_parts.append("The repair output matched the contract-validity label and schema for this case.")

        return EvaluationResult(
            score=score,
            feedback=" ".join(feedback_parts),
            objective_scores={
                "json_valid": json_valid,
                "selector_valid": selector_valid,
                "contract_alignment": contract_alignment,
                "ordered_alignment": ordered_alignment,
                "confidence_sane": confidence_sane,
            },
        )


def _strip_json_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl >= 0:
            s = s[nl + 1 :]
        end = s.rfind("```")
        if end >= 0:
            s = s[:end]
        s = s.strip()
    return s


def _classify_failure_mode(status: str, error_message: str, next_status: Optional[str]) -> str:
    err = (error_message or "").lower()
    if "invalid model" in err or "connection error" in err:
        return "infra"
    if "variable" in err and "not found" in err:
        return "missing_variable"
    if "llm judge validation failed" in err:
        return "contract_mismatch"
    if status == "empty":
        return "empty"
    if next_status == "error":
        return "downstream_error"
    return "ok"


def _extract_cases(trace_root: Path, limit: Optional[int], seed: int) -> List[RepairCase]:
    trace_files = sorted(trace_root.glob("*/q*/gasl_artifacts/traces/*.jsonl"))
    cases: List[RepairCase] = []
    for trace_path in trace_files:
        run_id = trace_path.parts[-5]
        qid = trace_path.parts[-3]
        question_path = trace_path.parents[2] / "question.json"
        query = ""
        if question_path.exists():
            query = json.loads(question_path.read_text()).get("question", "")
        rows = [json.loads(line) for line in trace_path.open()]
        for i, row in enumerate(rows):
            if row["event"] != "command_start" or row["payload"].get("command_type") != "PROCESS":
                continue
            result = rows[i + 1] if i + 1 < len(rows) and rows[i + 1]["event"] == "command_result" else None
            next_cmd = rows[i + 2] if i + 2 < len(rows) and rows[i + 2]["event"] == "command_start" else None
            next_result = rows[i + 3] if i + 3 < len(rows) and rows[i + 3]["event"] == "command_result" else None
            if not result:
                continue
            status = result["payload"].get("status", "")
            error_message = result["payload"].get("error_message", "") or ""
            next_status = next_result["payload"].get("status") if next_result else None
            failure_mode = _classify_failure_mode(status, error_message, next_status)
            if failure_mode == "infra":
                continue
            incoming_contracts = row["payload"]["inputs"].get("contracts", {})
            variable = row["payload"]["args"]["variable"]
            incoming_contract = incoming_contracts.get(variable, {})
            ordered_hint = bool(incoming_contract.get("ordered")) or "top " in row["payload"]["raw_text"].lower()
            # Reconstruct a minimal case. Probe data are not traced; use neutral placeholders.
            rows_data = row["payload"]["inputs"]["context"].get(variable) or row["payload"]["inputs"]["state"].get(variable, {}).get("items", [])
            if not isinstance(rows_data, list) or not rows_data:
                continue
            contract_valid = status == "success" and (next_status in (None, "success"))
            case = RepairCase(
                case_id=f"{run_id}:{qid}:{row['payload']['step_id']}",
                query=query,
                instruction=row["payload"]["args"]["instruction"],
                incoming_contract=incoming_contract,
                interpretation=None,
                selection_diagnostics={},
                probe_result={},
                rows=rows_data,
                history=[],
                contract_valid=contract_valid,
                failure_mode=failure_mode,
                ordered_hint=ordered_hint,
            )
            cases.append(case)
    rng = random.Random(seed)
    rng.shuffle(cases)
    if limit:
        cases = cases[:limit]
    return cases


def _build_task_model(model: str):
    cfg = resolve_runtime_llm_config(explicit_model=model)
    llm = ArgoBridgeLLM(model=cfg.model or model, api_key=cfg.api_key, base_url=cfg.base_url)
    def call(messages):
        prompt = ""
        for m in messages:
            prompt += f"{m['role'].upper()}:\n{m['content']}\n\n"
        return llm.call(prompt)
    return call


def _build_reflection_model(model: str):
    cfg = resolve_runtime_llm_config(explicit_model=model)
    llm = ArgoBridgeLLM(model=cfg.model or model, api_key=cfg.api_key, base_url=cfg.base_url)
    return lambda prompt: llm.call(prompt)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-root", default="benchmark_results")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--train-ratio", type=float, default=0.75)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--task-model", default=os.getenv("PROCESS_GEPA_TASK_MODEL", "gpt54"))
    parser.add_argument("--reflection-model", default=os.getenv("PROCESS_GEPA_REFLECTION_MODEL", "gpt54"))
    parser.add_argument("--max-metric-calls", type=int, default=40)
    parser.add_argument("--run-dir", default=None)
    args = parser.parse_args()

    trace_root = Path(args.trace_root)
    cases = _extract_cases(trace_root, args.limit, args.seed)
    if len(cases) < 8:
        raise SystemExit("Not enough non-infra PROCESS cases found for GEPA optimization.")

    split = max(1, int(len(cases) * args.train_ratio))
    train_cases = cases[:split]
    val_cases = cases[split:]
    cases_by_id = {c.case_id: c for c in cases}
    trainset = [c.to_data_inst() for c in train_cases]
    valset = [c.to_data_inst() for c in val_cases] if val_cases else None

    seed_prompt = Path("prompts/process_repair.txt").read_text()
    task_model = _build_task_model(args.task_model)
    reflection_model = _build_reflection_model(args.reflection_model)
    evaluator = ProcessRepairEvaluator(cases_by_id)
    adapter = DefaultAdapter(model=task_model, evaluator=evaluator)
    run_dir = args.run_dir or f"benchmark_results/process_repair_gepa_{datetime.now().strftime('%Y%m%dT%H%M%S')}"

    result = optimize(
        seed_candidate={"process_repair_prompt": seed_prompt},
        trainset=trainset,
        valset=valset,
        adapter=adapter,
        reflection_lm=reflection_model,
        max_metric_calls=args.max_metric_calls,
        run_dir=run_dir,
        display_progress_bar=False,
        seed=args.seed,
    )

    best_prompt = result.best_candidate["process_repair_prompt"]
    out_dir = Path(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "best_process_repair_prompt.txt").write_text(best_prompt)
    summary = {
        "train_cases": len(train_cases),
        "val_cases": len(val_cases),
        "run_dir": str(out_dir),
        "best_candidate": result.best_candidate,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
