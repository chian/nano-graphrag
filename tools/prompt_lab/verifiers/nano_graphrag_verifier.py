#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gasl.parser import GASLParser


def _extract_json(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return ""
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        body = []
        in_fence = False
        for line in lines:
            if line.strip().startswith("```"):
                if in_fence:
                    break
                in_fence = True
                continue
            if in_fence:
                body.append(line)
        if body:
            fenced = "\n".join(body).strip()
            if fenced.startswith("{") and fenced.endswith("}"):
                return fenced
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def _parse_candidate_json(candidate: Dict[str, Any]) -> Dict[str, Any]:
    parsed = candidate.get("parsed")
    if isinstance(parsed, dict) and parsed:
        return parsed
    raw = candidate.get("response_text", "") or ""
    try:
        return json.loads(_extract_json(raw))
    except Exception:
        return {}


def _required_keys_present(parsed: Dict[str, Any], required: Iterable[str]) -> bool:
    return all(key in parsed for key in required)


def _analyze_plan(parsed: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    parser = GASLParser()
    labels: Dict[str, Any] = {
        "parse_success": bool(parsed),
        "has_plan_shape": _required_keys_present(parsed, ("plan_id", "why", "commands", "config")),
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
    labels["config_shape_valid"] = isinstance(config, dict) and {
        "stop_on_error",
        "continue_on_empty",
    }.issubset(set(config.keys()))

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


def _produced_vars(cmd: Any) -> set[str]:
    args = getattr(cmd, "args", {}) or {}
    produced = set()
    for key in (
        "variable",
        "result_var",
        "result_variable",
        "target_variable",
        "target",
    ):
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
        "MERGE": [],
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


def _verify_process_repair(parsed: Dict[str, Any], original_labels: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    required = ("refined_instruction", "selector_hint", "current_rows_sufficient", "confidence", "reason")
    labels = {
        "parse_success": bool(parsed),
        "schema_valid": _required_keys_present(parsed, required),
        "selector_valid": parsed.get("selector_hint") in {"keep_current", "lexical", "vector", "central", "broaden", "narrow"},
        "confidence_valid": isinstance(parsed.get("confidence"), (int, float)) and 0.0 <= float(parsed.get("confidence")) <= 1.0,
    }
    original_bad = not bool(original_labels.get("selector_valid")) or not bool(original_labels.get("parse_success"))
    labels["improves_over_original"] = labels["schema_valid"] and labels["selector_valid"] and (original_bad or labels["confidence_valid"])
    score = 0.25 * float(labels["schema_valid"]) + 0.25 * float(labels["selector_valid"]) + 0.25 * float(labels["confidence_valid"]) + 0.25 * float(labels["improves_over_original"])
    return labels, round(score, 4)


def _verify_process_interpretation(parsed: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    required = ("label_field", "metric_field", "ordered", "scope", "output_contract", "confidence")
    labels = {
        "parse_success": bool(parsed),
        "schema_valid": _required_keys_present(parsed, required),
        "confidence_valid": isinstance(parsed.get("confidence"), (int, float)),
    }
    score = 0.5 * float(labels["schema_valid"]) + 0.5 * float(labels["confidence_valid"])
    return labels, round(score, 4)


def _verify_completion_validator(candidate: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    response = (candidate.get("response_text") or "").strip().upper()
    labels = {"response_valid": response in {"YES", "NO"}}
    return labels, float(labels["response_valid"])


def _verify_strategy_adaptation(candidate: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    response = (candidate.get("response_text") or "").strip()
    labels = {"nonempty": bool(response), "length_ok": len(response) >= 24}
    score = 0.5 * float(labels["nonempty"]) + 0.5 * float(labels["length_ok"])
    return labels, round(score, 4)


def verify(case: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    prompt_name = case.get("prompt_name", "")
    original_labels = case.get("labels", {}) or {}
    parsed = _parse_candidate_json(candidate)
    if prompt_name == "plan_generation":
        labels, score = _analyze_plan(parsed)
    elif prompt_name == "process_repair":
        labels, score = _verify_process_repair(parsed, original_labels)
    elif prompt_name == "process_interpretation":
        labels, score = _verify_process_interpretation(parsed)
    elif prompt_name == "completion_validator":
        labels, score = _verify_completion_validator(candidate)
    elif prompt_name == "strategy_adaptation":
        labels, score = _verify_strategy_adaptation(candidate)
    else:
        labels = {"parse_success": bool(parsed or candidate.get("response_text"))}
        score = float(labels["parse_success"])
    return {
        "pass": score >= 0.8,
        "score": round(score, 4),
        "labels": labels,
        "notes": f"{prompt_name} verifier",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Repo-specific verifier for nano-graphrag prompt-lab candidates.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()

    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    print(json.dumps(verify(case, candidate), indent=2))


if __name__ == "__main__":
    main()
