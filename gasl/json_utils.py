"""JSON extraction helpers for LLM responses."""

from __future__ import annotations


def extract_json(text: str) -> str:
    """Extract the first balanced JSON object or array from an LLM response."""
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
        starts = [idx for idx in (s.find("{"), s.find("[")) if idx >= 0]
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
