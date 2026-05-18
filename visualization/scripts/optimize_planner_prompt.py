#!/usr/bin/env python3
"""
Offline GEPA optimization for the planner prompt.

Uses existing plan_generation prompt observations from benchmark/demo runs.
The objective is execution-grounded:
- JSON plan shape
- GASL command parse success
- variable-flow validity
- no regression vs the original prompt outcome on the same case
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gepa.adapters.default_adapter.default_adapter import DefaultAdapter, DefaultDataInst, EvaluationResult
from gepa.api import optimize
from openai import OpenAI

from gasl.parser import GASLParser


SECTION_RE = {
    "query": re.compile(r"Query:\s*(.*?)\n\n🔍 AVAILABLE FIELDS from Graph Schema:", re.S),
    "graph_schema": re.compile(r"🔍 AVAILABLE FIELDS from Graph Schema:\n(.*?)\n\n🔍 AVAILABLE FIELDS from State Schema:", re.S),
    "state_schema": re.compile(r"🔍 AVAILABLE FIELDS from State Schema:\n(.*?)\n\nCRITICAL: FIELD NAME REQUIREMENTS", re.S),
    "execution_history": re.compile(r"Execution History:\n(.*?)\n\nRecently Produced Artifacts:", re.S),
    "execution_history_legacy": re.compile(r"Execution History:\n(.*?)\n\nAVAILABLE GASL COMMANDS:", re.S),
    "produced_artifacts": re.compile(r"Recently Produced Artifacts:\n(.*?)\n\nAVAILABLE GASL COMMANDS:", re.S),
}


@dataclass
class PlannerCase:
    case_id: str
    query: str
    graph_schema: str
    state_schema: str
    execution_history: str
    produced_artifacts: str
    baseline_score: float
    baseline_labels: Dict[str, Any]

    def to_data_inst(self) -> DefaultDataInst:
        text = (
            f"Query:\n{self.query}\n\n"
            f"Graph Schema:\n{self.graph_schema}\n\n"
            f"State Schema:\n{self.state_schema}\n\n"
            f"Execution History:\n{self.execution_history}\n\n"
            f"Recently Produced Artifacts:\n{self.produced_artifacts}\n\n"
            "Return only a JSON GASL plan object."
        )
        return {
            "input": text,
            "additional_context": {
                "case_id": self.case_id,
                "baseline_score": str(self.baseline_score),
            },
            "answer": "",
        }


def _extract_json(text: str) -> str:
    s = (text or "").strip()
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


def _required_keys_present(parsed: Dict[str, Any], required: List[str]) -> bool:
    return all(key in parsed for key in required)


def _produced_vars(cmd: Any) -> set[str]:
    args = getattr(cmd, "args", {}) or {}
    produced = set()
    for key in ("variable", "result_var", "result_variable", "target_variable", "target"):
        value = args.get(key)
        if key == "variable" and getattr(cmd, "command_type", "") != "DECLARE":
            continue
        if isinstance(value, str):
            produced.add(value)
    if getattr(cmd, "command_type", "") == "ON":
        try:
            nested = GASLParser().parse_command(args.get("action", ""))
            produced.update(_produced_vars(nested))
        except Exception:
            pass
    return produced


def _required_vars(cmd: Any) -> List[str]:
    args = getattr(cmd, "args", {}) or {}
    pairs = {
        "PROCESS": ["variable"],
        "COUNT": ["source"],
        "AGGREGATE": ["variable"],
        "PROJECT": ["variable"],
        "COLLAPSE": ["variable"],
        "UPDATE": ["variable"],
        "CLASSIFY": ["variable"],
        "RANK": ["variable"],
        "GRAPHWALK": ["from_variable"],
        "SUBGRAPH": ["around_variable"],
        "GRAPHPATTERN": ["in_variable"],
        "JOIN": ["variable1", "variable2"],
        "COMPARE": ["variable1", "variable2"],
        "SHOW": ["variable"],
        "SELECT": ["source"],
        "ADD_FIELD": ["variable", "source_variable"],
        "CREATE_NODES": ["source_variable"],
        "CREATE_EDGES": ["source_variable"],
        "CREATE_GROUPS": ["source_variable"],
    }
    required: List[str] = []
    for key in pairs.get(getattr(cmd, "command_type", ""), []):
        value = args.get(key)
        if isinstance(value, str) and value:
            required.append(value)
    if getattr(cmd, "command_type", "") == "ON":
        try:
            nested = GASLParser().parse_command(args.get("action", ""))
            required.extend(_required_vars(nested))
        except Exception:
            pass
    return required


def _analyze_plan_text(text: str) -> tuple[Dict[str, Any], float]:
    parser = GASLParser()
    try:
        parsed = json.loads(_extract_json(text))
    except Exception:
        parsed = {}
    labels: Dict[str, Any] = {
        "parse_success": bool(parsed),
        "has_plan_shape": _required_keys_present(parsed, ["plan_id", "why", "commands", "config"]),
        "command_parse_success": False,
        "variable_flow_valid": False,
        "config_shape_valid": False,
    }
    if not labels["has_plan_shape"]:
        return labels, 0.0
    commands = parsed.get("commands")
    if not isinstance(commands, list) or not commands:
        return labels, 0.1
    config = parsed.get("config")
    labels["config_shape_valid"] = isinstance(config, dict) and {"stop_on_error", "continue_on_empty"}.issubset(set(config.keys()))
    parse_ok = 0
    define_ok = 0
    define_total = 0
    declared: set[str] = set()
    for idx, raw in enumerate(commands, start=1):
        try:
            cmd = parser.parse_command(raw, idx)
            parse_ok += 1
        except Exception:
            continue
        produced = _produced_vars(cmd)
        required = _required_vars(cmd)
        for var_name in required:
            define_total += 1
            if var_name in declared:
                define_ok += 1
        declared.update(produced)
    labels["command_parse_success"] = parse_ok == len(commands)
    labels["variable_flow_valid"] = define_ok == define_total
    command_ratio = parse_ok / max(1, len(commands))
    flow_ratio = define_ok / max(1, define_total)
    score = 0.45 * float(labels["has_plan_shape"]) + 0.35 * command_ratio + 0.2 * flow_ratio
    return labels, round(min(1.0, score), 4)


def _extract_section(text: str, key: str) -> str:
    pattern = SECTION_RE[key]
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _extract_cases(cases_path: Path, limit: int | None, seed: int) -> List[PlannerCase]:
    rows = [json.loads(line) for line in cases_path.open()]
    cases: List[PlannerCase] = []
    for row in rows:
        if row.get("prompt_name") != "plan_generation":
            continue
        prompt_text = row.get("prompt_text", "")
        query = _extract_section(prompt_text, "query")
        graph_schema = _extract_section(prompt_text, "graph_schema")
        state_schema = _extract_section(prompt_text, "state_schema")
        execution_history = _extract_section(prompt_text, "execution_history") or _extract_section(prompt_text, "execution_history_legacy")
        produced_artifacts = _extract_section(prompt_text, "produced_artifacts")
        if not query or not graph_schema:
            continue
        baseline_labels, baseline_score = _analyze_plan_text(row.get("response_text", ""))
        cases.append(
            PlannerCase(
                case_id=row["case_id"],
                query=query,
                graph_schema=graph_schema,
                state_schema=state_schema,
                execution_history=execution_history or "No execution history yet.",
                produced_artifacts=produced_artifacts or "No produced artifacts yet.",
                baseline_score=baseline_score,
                baseline_labels=baseline_labels,
            )
        )
    rng = random.Random(seed)
    rng.shuffle(cases)
    if limit:
        cases = cases[:limit]
    return cases


class PlannerEvaluator:
    def __init__(self, cases_by_id: Dict[str, PlannerCase]):
        self.cases_by_id = cases_by_id

    def __call__(self, data: DefaultDataInst, response: str) -> EvaluationResult:
        case = self.cases_by_id[data["additional_context"]["case_id"]]
        labels, score = _analyze_plan_text(response)
        baseline = case.baseline_score
        no_regression = 1.0 if score >= baseline else 0.0
        total = 0.7 * score + 0.3 * no_regression
        feedback = []
        if not labels.get("has_plan_shape"):
            feedback.append("Return a strict JSON plan object with plan_id, why, commands, and config.")
        if not labels.get("command_parse_success"):
            feedback.append("One or more commands were not valid GASL syntax.")
        if not labels.get("variable_flow_valid"):
            feedback.append("Commands reference variables before they are declared or produced.")
        if no_regression == 0.0:
            feedback.append("This plan regressed below the original prompt outcome for this case.")
        if not feedback:
            feedback.append("Plan shape and variable flow are sound.")
        return EvaluationResult(
            score=round(total, 4),
            feedback=" ".join(feedback),
            objective_scores={
                "plan_score": score,
                "no_regression": no_regression,
                "parse_success": float(labels.get("parse_success", False)),
                "variable_flow_valid": float(labels.get("variable_flow_valid", False)),
            },
        )


def _build_task_model(model: str):
    _ensure_viz_api_key()
    client = OpenAI(api_key=os.environ["VIZ_API_KEY"])
    def call(messages):
        response = client.responses.create(
            model=model,
            input=messages,
        )
        return response.output_text
    return call


def _build_reflection_model(model: str):
    _ensure_viz_api_key()
    client = OpenAI(api_key=os.environ["VIZ_API_KEY"])
    def call(prompt: str) -> str:
        response = client.responses.create(
            model=model,
            input=prompt,
        )
        return response.output_text
    return call


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
        key = key.strip()
        if key == "VIZ_API_KEY":
            os.environ[key] = value.strip()
            return
    raise SystemExit("VIZ_API_KEY was not found in .viz.local.env.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="tmp/prompt_lab_cases.jsonl")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--train-ratio", type=float, default=0.75)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--task-model", default=os.getenv("PLANNER_GEPA_TASK_MODEL", "gpt-5.5"))
    parser.add_argument("--reflection-model", default=os.getenv("PLANNER_GEPA_REFLECTION_MODEL", "gpt-5.5"))
    parser.add_argument("--max-metric-calls", type=int, default=80)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()

    cases = _extract_cases(Path(args.cases), args.limit, args.seed)
    if len(cases) < 12:
        raise SystemExit("Not enough planner cases found for GEPA optimization.")
    split = max(1, int(len(cases) * args.train_ratio))
    train_cases = cases[:split]
    val_cases = cases[split:]
    cases_by_id = {c.case_id: c for c in cases}
    trainset = [c.to_data_inst() for c in train_cases]
    valset = [c.to_data_inst() for c in val_cases] if val_cases else None

    seed_prompt = Path("prompts/plan_generation.txt").read_text()
    task_model = _build_task_model(args.task_model)
    reflection_model = _build_reflection_model(args.reflection_model)
    evaluator = PlannerEvaluator(cases_by_id)
    adapter = DefaultAdapter(model=task_model, evaluator=evaluator)
    run_dir = args.run_dir or f"benchmark_results/planner_gepa_{datetime.now().strftime('%Y%m%dT%H%M%S')}"

    result = optimize(
        seed_candidate={"planner_prompt": seed_prompt},
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
    best_prompt = result.best_candidate["planner_prompt"]
    (out_dir / "best_plan_generation_prompt.txt").write_text(best_prompt)
    summary = {
        "train_cases": len(train_cases),
        "val_cases": len(val_cases),
        "run_dir": str(out_dir),
        "best_candidate": result.best_candidate,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    if args.promote:
        Path("prompts/plan_generation.txt").write_text(best_prompt)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
