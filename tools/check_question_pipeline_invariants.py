#!/usr/bin/env python3
"""Enforce the question pipeline's ownership and continuation boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _tree(relative: str) -> ast.Module:
    path = ROOT / relative
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except SyntaxError as exc:
        raise ValueError(f"{relative}: could not parse ({exc})") from exc


def _function(tree: ast.AST, class_name: str, function_name: str) -> ast.FunctionDef:
    for node in getattr(tree, "body", ()):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if isinstance(child, ast.FunctionDef) and child.name == function_name:
                return child
    raise ValueError(f"missing {class_name}.{function_name}")


def check_method_layering() -> list[str]:
    findings: list[str] = []
    forbidden = {"gasl", "question_pipeline", "source_table_language"}
    for path in sorted((ROOT / "method_loop").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            for module in modules:
                if module.split(".")[0] in forbidden:
                    findings.append(
                        f"{relative}:{node.lineno}: generic method_loop imports "
                        f"binding layer {module!r}"
                    )
    return findings


def check_checkpoint_gate() -> list[str]:
    findings: list[str] = []
    runner = _tree("run_question_pipeline.py")
    pipeline = _tree("question_pipeline/pipeline.py")

    for path in sorted((ROOT / "question_pipeline").rglob("*.py")):
        if path.name == "acquisition.py":
            continue
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "question_pipeline.utilities.acquisition":
                continue
            imported = {alias.name for alias in node.names}
            if "load_checkpoint" in imported:
                findings.append(
                    f"{relative}:{node.lineno}: raw load_checkpoint bypasses "
                    "the VerifiedCheckpoint gate"
                )

    try:
        initializer = _function(pipeline, "QuestionPipeline", "__init__")
        parameters = {argument.arg for argument in initializer.args.args}
        parameters.update(argument.arg for argument in initializer.args.kwonlyargs)
        if "verified_checkpoint" not in parameters:
            findings.append(
                "question_pipeline/pipeline.py: QuestionPipeline.__init__ must "
                "require the verified continuation value"
            )
    except ValueError as exc:
        findings.append(str(exc))

    try:
        restore = _function(
            pipeline,
            "QuestionPipeline",
            "_restore_checkpoint_state",
        )
        for node in ast.walk(restore):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"load_checkpoint", "resolve_checkpoint_path"}:
                    findings.append(
                        "question_pipeline/pipeline.py: restore must consume the "
                        "VerifiedCheckpoint instead of reopening a path"
                    )
    except ValueError as exc:
        findings.append(str(exc))

    runner_calls = {
        node.func.id
        for node in ast.walk(runner)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    if "verify_checkpoint" not in runner_calls:
        findings.append("run_question_pipeline.py: --continue must call verify_checkpoint")
    pipeline_calls = [
        node
        for node in ast.walk(runner)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "QuestionPipeline"
    ]
    if not pipeline_calls or not all(
        any(keyword.arg == "verified_checkpoint" for keyword in call.keywords)
        for call in pipeline_calls
    ):
        findings.append(
            "run_question_pipeline.py: QuestionPipeline construction must pass "
            "verified_checkpoint explicitly"
        )
    return findings


def check_evidence_file_ownership() -> list[str]:
    findings: list[str] = []
    owned = {"acceptances.jsonl", "source_assertions.jsonl"}
    for path in sorted((ROOT / "question_pipeline").rglob("*.py")):
        if path.name == "evidence.py":
            continue
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in owned:
                findings.append(
                    f"{relative}:{node.lineno}: evidence registry filename "
                    f"{node.value!r} is owned by utilities/evidence.py"
                )
    return findings


def main() -> int:
    findings: list[str] = []
    for check in (
        check_method_layering,
        check_checkpoint_gate,
        check_evidence_file_ownership,
    ):
        try:
            findings.extend(check())
        except (OSError, ValueError) as exc:
            findings.append(str(exc))
    if findings:
        print("Question-pipeline invariant violations detected:")
        for finding in findings:
            print(f" - {finding}")
        return 1
    print("Question-pipeline invariant check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
