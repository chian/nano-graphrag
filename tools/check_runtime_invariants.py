#!/usr/bin/env python3
"""
Cheap invariant check for generic GASL runtime code.

This is not a full linter. It is a narrow tripwire intended to catch obvious
schema/domain hardcoding in generic runtime paths.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECK_DIRS = [
    ROOT / "gasl",
]

SKIP_DIRS = {
    ROOT / "gasl" / "answer_layer" / "__pycache__",
    ROOT / "gasl" / "__pycache__",
}

# Non-canonical feature/source-specific fields we do not want leaking through
# generic runtime code. Legacy read-fallbacks are allowed only in graph_slots.py.
BANNED_LITERALS = {
    "source_papers",
    "alternative_names",
    "importance_score",
    "communityIds",
}

ALLOWLIST_PATHS = {
    ROOT / "nano_graphrag" / "graph_slots.py",
}

EXTRA_FILES = [
    ROOT / "nano_graphrag" / "prompt_system.py",
]


# ---------------------------------------------------------------------------
# Layering: gasl/ is the generic query engine and must not import the ingestion
# or query-construction layers.
#
# This exists because a literal check could not see the defect that motivated
# it. `gasl/commands/data_transform.py` and `gasl/commands/contrastive.py`
# imported `get_source_refs` from `nano_graphrag.graph_slots`, which falls back
# to `source_papers` -- a field `docs/RUNTIME_INVARIANTS.md` names verbatim as
# forbidden. Every COLLAPSE, PROJECT and AGGREGATE reached that fallback
# transitively, and this checker reported a clean tree the whole time, because
# the literal lives in a file outside CHECK_DIRS. Scanning strings can only ever
# find hardcoding that is physically present in the scanned paths; structural
# coupling has to be checked structurally.
#
# The two graph_slots imports are gone -- the accessors now live in
# `gasl/provenance.py` without the legacy aliases. The entries below are the
# imports that remain. They are NOT blessed: they are a frozen inventory that
# must not grow, so that a new outbound import fails this check even though
# these known ones do not. Removing one means deleting its line.
FORBIDDEN_IMPORT_ROOTS = {"nano_graphrag", "query_generation", "question_pipeline"}

KNOWN_OUTBOUND_IMPORTS = {
    ("gasl/command_repair_agent.py", "nano_graphrag.prompt_system"),
    ("gasl/commands/contrastive.py", "query_generation.graph_validator"),
    ("gasl/llm/argo_bridge.py", "nano_graphrag.prompt_system"),
    ("gasl/micro_actions.py", "nano_graphrag.prompt_system"),
    ("gasl/step_compiler.py", "nano_graphrag.prompt_system"),
}


def scan_layering() -> list[str]:
    """Report any gasl/ -> outer-layer import that is not already inventoried.
    """
    findings: list[str] = []
    for path in sorted((ROOT / "gasl").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            findings.append(f"{rel}: could not parse ({exc})")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # level > 0 is a relative import, which is inside gasl/ by
                # construction and never a layering violation.
                modules = [node.module] if node.level == 0 and node.module else []
            else:
                continue
            for module in modules:
                root = module.split(".")[0]
                if root not in FORBIDDEN_IMPORT_ROOTS:
                    continue
                if (rel, module) in KNOWN_OUTBOUND_IMPORTS:
                    continue
                findings.append(
                    f"{rel}:{node.lineno}: gasl/ imports '{module}'. The generic query "
                    f"engine must not depend on ingestion or query-construction layers; "
                    f"move what it needs into gasl/, without legacy aliases."
                )
    return findings


def iter_python_files() -> list[Path]:
    out: list[Path] = []
    for directory in CHECK_DIRS:
        for path in directory.rglob("*.py"):
            if any(parent in SKIP_DIRS for parent in path.parents):
                continue
            out.append(path)
    out.extend(path for path in EXTRA_FILES if path.exists())
    return sorted(out)


def scan_file(path: Path) -> list[str]:
    if path in ALLOWLIST_PATHS:
        return []
    text = path.read_text(encoding="utf-8")
    findings: list[str] = []
    for literal in sorted(BANNED_LITERALS):
        if re.search(rf'["\']{re.escape(literal)}["\']', text):
            findings.append(f"{path.relative_to(ROOT)}: literal '{literal}'")
    return findings


def main() -> int:
    findings: list[str] = []
    for path in iter_python_files():
        findings.extend(scan_file(path))
    findings.extend(scan_layering())
    if findings:
        print("Runtime invariant violations detected:")
        for finding in findings:
            print(f" - {finding}")
        return 1
    print("Runtime invariant check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
