#!/usr/bin/env python3
"""
Cheap invariant check for generic GASL runtime code.

This is not a full linter. It is a narrow tripwire intended to catch obvious
schema/domain hardcoding in generic runtime paths.
"""

from __future__ import annotations

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
    if findings:
        print("Runtime invariant violations detected:")
        for finding in findings:
            print(f" - {finding}")
        return 1
    print("Runtime invariant check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
