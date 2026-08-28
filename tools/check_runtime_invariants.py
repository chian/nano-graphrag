#!/usr/bin/env python3
"""
Cheap invariant check for generic GASL runtime code.

This is not a full linter. It is a narrow tripwire intended to catch obvious
schema/domain hardcoding in generic runtime paths.
"""

from __future__ import annotations

import ast
import re
import sys
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

# Permitted LOWER layers (phase 4A, docs/ACQUISITION_LOOP.md +
# docs/RUNTIME_INVARIANTS.md §Layering): `rarefaction/` is pure-stdlib
# arithmetic over opaque identity tokens -- below gasl/, not above it, so
# gasl/ may import it. The permission is CONDITIONAL on rarefaction/ staying
# pure, and `scan_layering` enforces the condition (wired in phase 4E-a; the
# entry was inert before): every gasl/ import of a permitted lower layer is
# reported as a layering violation whenever `scan_rarefaction_purity` finds
# that layer impure. So the day rarefaction/ imports anything beyond the
# standard library, both checks fail, and this entry must be re-justified
# rather than widened.
PERMITTED_LOWER_LAYERS = {"rarefaction"}

KNOWN_OUTBOUND_IMPORTS = {
    ("gasl/command_repair_agent.py", "nano_graphrag.prompt_system"),
    ("gasl/commands/contrastive.py", "query_generation.graph_validator"),
    ("gasl/llm/argo_bridge.py", "nano_graphrag.prompt_system"),
    ("gasl/micro_actions.py", "nano_graphrag.prompt_system"),
    ("gasl/step_compiler.py", "nano_graphrag.prompt_system"),
}


def scan_layering(impure_lower_layers: set[str] | None = None) -> list[str]:
    """Report any gasl/ -> outer-layer import that is not already inventoried.

    ``impure_lower_layers`` names the permitted lower layers whose purity
    check failed; a gasl/ import of one of them is then reported here too,
    because the permission to import it was conditional on that purity.
    """
    findings: list[str] = []
    impure = set(impure_lower_layers or ()) & PERMITTED_LOWER_LAYERS
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
                if root in impure:
                    findings.append(
                        f"{rel}:{node.lineno}: gasl/ imports '{module}', a permitted "
                        f"lower layer whose purity check failed; the permission was "
                        f"conditional on '{root}' importing nothing beyond the "
                        f"standard library (docs/RUNTIME_INVARIANTS.md §Layering)."
                    )
                    continue
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


def scan_rarefaction_purity() -> list[str]:
    """rarefaction/ must import nothing beyond the standard library.

    This is the property that makes it a lower layer gasl/ may depend on.
    A missing rarefaction/ is not a finding -- the package is chartered but
    lands with phase 4A.
    """
    findings: list[str] = []
    package = ROOT / "rarefaction"
    if not package.exists():
        return findings
    stdlib = set(sys.stdlib_module_names)
    for path in sorted(package.rglob("*.py")):
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
                modules = [node.module] if node.level == 0 and node.module else []
            else:
                continue
            for module in modules:
                root = module.split(".")[0]
                if root in stdlib or root == "rarefaction":
                    continue
                findings.append(
                    f"{rel}:{node.lineno}: rarefaction/ imports '{module}'. The "
                    f"kernel is a permitted lower layer only while it is pure "
                    f"stdlib; this import voids the gasl/ -> rarefaction "
                    f"permission (docs/ACQUISITION_LOOP.md)."
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
    purity_findings = scan_rarefaction_purity()
    findings.extend(scan_layering({"rarefaction"} if purity_findings else set()))
    findings.extend(purity_findings)
    if findings:
        print("Runtime invariant violations detected:")
        for finding in findings:
            print(f" - {finding}")
        return 1
    print("Runtime invariant check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
