#!/usr/bin/env python3
"""
Offline GEPA optimization for the AGGREGATE repair prompt.

Uses historical AGGREGATE command traces from benchmark_results.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from gepa.adapters.default_adapter.default_adapter import DefaultAdapter, DefaultDataInst, EvaluationResult
from gepa.api import optimize
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gasl.aggregate_repair_prompting import format_aggregate_repair_case


REQUIRED_KEYS = (
    "current_rows_sufficient",
    "use_project",
    "use_collapse",
    "group_by_field",
    "metric_field",
    "weight_field",
    "refined_instruction",
    "reason",
    "confidence",
)


@dataclass
class AggregateCase:
    case_id: str
    query: str
    aggregate_command: str
    incoming_contract: Dict[str, Any]
    previous_command: str
    next_command: str
    rows: List[Dict[str, Any]]
    error_message: str
    current_rows_sufficient: bool
    suggest_project: bool
    suggest_collapse: bool
    suggested_group_field: str
    allowed_fields: List[str]

    def to_data_inst(self) -> DefaultDataInst:
        text = format_aggregate_repair_case(
            data=self.rows,
            query=self.query,
            aggregate_command=self.aggregate_command,
            incoming_contract=self.incoming_contract,
            previous_command=self.previous_command,
            next_command=self.next_command,
            error_message=self.error_message,
        )
        return {
            "input": text,
            "additional_context": {
                "case_id": self.case_id,
                "current_rows_sufficient": str(self.current_rows_sufficient).lower(),
                "suggest_project": str(self.suggest_project).lower(),
                "suggest_collapse": str(self.suggest_collapse).lower(),
                "suggested_group_field": self.suggested_group_field,
                "allowed_fields": json.dumps(self.allowed_fields),
            },
            "answer": "",
        }


def _ensure_viz_api_key() -> None:
    if os.getenv("VIZ_API_KEY"):
        return
    env_path = REPO_ROOT / ".viz.local.env"
    if not env_path.exists():
        raise SystemExit("VIZ_API_KEY is not set and .viz.local.env was not found.")
    for line in env_path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "VIZ_API_KEY":
            os.environ[key.strip()] = value.strip()
            return
    raise SystemExit("VIZ_API_KEY was not found in .viz.local.env.")


def _build_task_model(model: str):
    _ensure_viz_api_key()
    client = OpenAI(api_key=os.environ["VIZ_API_KEY"])

    def call(messages):
        response = client.responses.create(model=model, input=messages)
        return response.output_text

    return call


def _build_reflection_model(model: str):
    _ensure_viz_api_key()
    client = OpenAI(api_key=os.environ["VIZ_API_KEY"])

    def call(prompt: str) -> str:
        response = client.responses.create(model=model, input=prompt)
        return response.output_text

    return call


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


def _flatten_fields(item: Any, prefix: str = "", depth: int = 0, max_depth: int = 2):
    if depth > max_depth:
        return
    if isinstance(item, dict):
        for key, value in item.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (str, int, float, bool)):
                yield next_prefix
            elif isinstance(value, dict):
                yield from _flatten_fields(value, next_prefix, depth + 1, max_depth)


def _collect_allowed_fields(rows: List[Dict[str, Any]], contract: Dict[str, Any]) -> List[str]:
    fields = list(contract.get("row_schema", []) or [])
    seen = set(fields)
    for row in rows[:8]:
        for field in _flatten_fields(row):
            if field not in seen:
                seen.add(field)
                fields.append(field)
    return fields


def _suggestions(error: str, contract: Dict[str, Any], op: str, by_field: str) -> tuple[bool, bool, bool, str]:
    err = (error or "").lower()
    multiplicity = contract.get("multiplicity_preserved")
    label_field = contract.get("label_field", "")
    row_weight = contract.get("row_weight_field", "")
    current_rows_sufficient = True
    use_project = False
    use_collapse = False
    suggested_group_field = by_field or label_field

    if "count/result is 1" in err or "counted grouped rows/items" in err or "did not actually aggregate" in err:
        current_rows_sufficient = False
        use_project = True
    if "no visible numeric" in err or "sum" in err and "not actually applied" in err:
        current_rows_sufficient = False
        if row_weight:
            use_collapse = True
        else:
            use_project = True
    if "do not contain the required" in err or "field" in err and "not performed" in err:
        current_rows_sufficient = False
        if label_field:
            suggested_group_field = label_field
        use_project = True
    if op == "sum" and row_weight:
        suggested_group_field = by_field or label_field
    if multiplicity is False and not row_weight:
        current_rows_sufficient = False
        use_project = True
    return current_rows_sufficient, use_project, use_collapse, suggested_group_field


def _extract_cases(trace_root: Path, limit: Optional[int], seed: int) -> List[AggregateCase]:
    trace_files = sorted(trace_root.glob("*/q*/gasl_artifacts/traces/*.jsonl"))
    cases: List[AggregateCase] = []
    for trace_path in trace_files:
        question_path = trace_path.parents[2] / "question.json"
        query = ""
        if question_path.exists():
            query = json.loads(question_path.read_text()).get("question", "")
        rows = [json.loads(line) for line in trace_path.open()]
        for i, row in enumerate(rows):
            if row["event"] != "command_start" or row["payload"].get("command_type") != "AGGREGATE":
                continue
            result = rows[i + 1] if i + 1 < len(rows) and rows[i + 1]["event"] == "command_result" else None
            if not result:
                continue
            args = row["payload"]["args"]
            variable = args["variable"]
            incoming_contract = row["payload"]["inputs"].get("contracts", {}).get(variable, {})
            rows_data = row["payload"]["inputs"]["context"].get(variable) or row["payload"]["inputs"]["state"].get(variable, {}).get("items", [])
            if not isinstance(rows_data, list) or not rows_data:
                continue
            previous_command = ""
            next_command = ""
            if i > 0 and rows[i - 1]["event"] == "command_start":
                previous_command = rows[i - 1]["payload"].get("raw_text", "")
            if i + 2 < len(rows) and rows[i + 2]["event"] == "command_start":
                next_command = rows[i + 2]["payload"].get("raw_text", "")
            error_message = result["payload"].get("error_message", "") or ""
            op = args.get("operation", "")
            by_field = args.get("by_field", "")
            current_rows_sufficient, use_project, use_collapse, suggested_group_field = _suggestions(
                error_message,
                incoming_contract,
                op,
                by_field,
            )
            allowed_fields = _collect_allowed_fields(rows_data, incoming_contract)
            status = result["payload"].get("status", "")
            if status == "success" and not error_message:
                current_rows_sufficient = True
                use_project = False
                use_collapse = False
            case = AggregateCase(
                case_id=f"{trace_path.parents[4].name}:{trace_path.parents[2].name}:{row['payload']['step_id']}",
                query=query,
                aggregate_command=row["payload"].get("raw_text", ""),
                incoming_contract=incoming_contract,
                previous_command=previous_command,
                next_command=next_command,
                rows=rows_data,
                error_message=error_message,
                current_rows_sufficient=current_rows_sufficient,
                suggest_project=use_project,
                suggest_collapse=use_collapse,
                suggested_group_field=suggested_group_field,
                allowed_fields=allowed_fields,
            )
            cases.append(case)
    rng = random.Random(seed)
    rng.shuffle(cases)
    if limit:
        cases = cases[:limit]
    return cases


class AggregateRepairEvaluator:
    def __init__(self, cases_by_id: Dict[str, AggregateCase]):
        self.cases_by_id = cases_by_id

    def __call__(self, data: DefaultDataInst, response: str) -> EvaluationResult:
        case = self.cases_by_id[data["additional_context"]["case_id"]]
        try:
            parsed = json.loads(_strip_json_fences(response))
        except Exception:
            return EvaluationResult(
                score=0.0,
                feedback="Response was not valid JSON.",
                objective_scores={"json_valid": 0.0, "substrate_alignment": 0.0},
            )

        schema_valid = all(k in parsed for k in REQUIRED_KEYS)
        confidence_valid = isinstance(parsed.get("confidence"), (int, float)) and 0.0 <= float(parsed.get("confidence")) <= 1.0
        rows_alignment = bool(parsed.get("current_rows_sufficient")) == case.current_rows_sufficient
        project_alignment = bool(parsed.get("use_project")) == case.suggest_project
        collapse_alignment = bool(parsed.get("use_collapse")) == case.suggest_collapse
        group_field = str(parsed.get("group_by_field", "") or "")
        allowed_fields = set(case.allowed_fields)
        group_field_valid = (not group_field) or (group_field in allowed_fields)
        metric_field = str(parsed.get("metric_field", "") or "")
        weight_field = str(parsed.get("weight_field", "") or "")
        metric_valid = (not metric_field) or (metric_field in allowed_fields)
        weight_valid = (not weight_field) or (weight_field in allowed_fields)

        score = (
            0.2 * float(schema_valid)
            + 0.15 * float(confidence_valid)
            + 0.25 * float(rows_alignment)
            + 0.15 * float(project_alignment)
            + 0.10 * float(collapse_alignment)
            + 0.10 * float(group_field_valid)
            + 0.05 * float(metric_valid and weight_valid)
        )
        feedback_parts = []
        if not schema_valid:
            feedback_parts.append("Return the exact JSON schema.")
        if not rows_alignment:
            feedback_parts.append("The keep/reshape decision mismatched the aggregate substrate for this case.")
        if not project_alignment:
            feedback_parts.append("PROJECT usage mismatched the inferred grain repair for this case.")
        if not collapse_alignment:
            feedback_parts.append("COLLAPSE usage mismatched the inferred repair for this case.")
        if not group_field_valid:
            feedback_parts.append("Do not invent group_by_field values outside the visible row schema.")
        if not feedback_parts:
            feedback_parts.append("Aggregate repair decision aligns with the case heuristics.")
        return EvaluationResult(
            score=round(score, 4),
            feedback=" ".join(feedback_parts),
            objective_scores={
                "schema_valid": float(schema_valid),
                "rows_alignment": float(rows_alignment),
                "project_alignment": float(project_alignment),
                "collapse_alignment": float(collapse_alignment),
                "group_field_valid": float(group_field_valid),
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-root", default="benchmark_results")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--train-ratio", type=float, default=0.75)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--task-model", default=os.getenv("AGGREGATE_GEPA_TASK_MODEL", "gpt-5.5"))
    parser.add_argument("--reflection-model", default=os.getenv("AGGREGATE_GEPA_REFLECTION_MODEL", "gpt-5.5"))
    parser.add_argument("--max-metric-calls", type=int, default=24)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()

    cases = _extract_cases(Path(args.trace_root), args.limit, args.seed)
    if len(cases) < 12:
        raise SystemExit("Not enough AGGREGATE cases found for GEPA optimization.")
    split = max(1, int(len(cases) * args.train_ratio))
    train_cases = cases[:split]
    val_cases = cases[split:]
    cases_by_id = {c.case_id: c for c in cases}
    trainset = [c.to_data_inst() for c in train_cases]
    valset = [c.to_data_inst() for c in val_cases] if val_cases else None

    seed_prompt = Path("prompts/aggregate_repair.txt").read_text()
    task_model = _build_task_model(args.task_model)
    reflection_model = _build_reflection_model(args.reflection_model)
    evaluator = AggregateRepairEvaluator(cases_by_id)
    adapter = DefaultAdapter(model=task_model, evaluator=evaluator)
    run_dir = args.run_dir or f"benchmark_results/aggregate_repair_gepa_{datetime.now().strftime('%Y%m%dT%H%M%S')}"

    result = optimize(
        seed_candidate={"aggregate_repair_prompt": seed_prompt},
        trainset=trainset,
        valset=valset,
        adapter=adapter,
        reflection_lm=reflection_model,
        max_metric_calls=args.max_metric_calls,
        run_dir=run_dir,
        display_progress_bar=False,
        seed=args.seed,
    )

    out_dir = Path(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    best_prompt = result.best_candidate["aggregate_repair_prompt"]
    (out_dir / "best_aggregate_repair_prompt.txt").write_text(best_prompt)
    summary = {
        "train_cases": len(train_cases),
        "val_cases": len(val_cases),
        "run_dir": str(out_dir),
        "best_candidate": result.best_candidate,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    if args.promote:
        Path("prompts/aggregate_repair.txt").write_text(best_prompt)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
