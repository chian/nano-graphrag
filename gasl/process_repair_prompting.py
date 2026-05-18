"""
Shared formatting helpers for PROCESS repair prompt optimization.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def format_process_repair_case(
    *,
    data: List[Dict[str, Any]],
    query: str,
    instruction: str,
    history: List[Dict[str, Any]],
    incoming_contract: Dict[str, Any],
    interpretation: Optional[Dict[str, Any]],
    selection_diagnostics: Dict[str, Any],
    probe_result: Dict[str, Any],
) -> str:
    sample_rows = [flatten_row(row) for row in data[:8]]
    probe_count = len(probe_result.get("filtered_items") or probe_result.get("processed_items") or [])
    history_tail = history[-4:] if history else []
    return f"""Case:

Query:
{query}

Instruction:
{instruction}

Incoming contract:
{incoming_contract}

Current interpretation:
{interpretation or {}}

Selection diagnostics:
{selection_diagnostics}

Probe positive count:
{probe_count}

Sample rows:
{sample_rows}

Recent workflow history:
{history_tail}
"""


def iter_scalar_fields(item: Any, prefix: str = "", *, depth: int = 0, max_depth: int = 2):
    if depth > max_depth:
        return
    if isinstance(item, dict):
        for key, value in item.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (str, int, float, bool)):
                yield next_prefix, value
            elif isinstance(value, dict):
                yield from iter_scalar_fields(value, next_prefix, depth=depth + 1, max_depth=max_depth)
    elif isinstance(item, (str, int, float, bool)):
        yield prefix or "value", item


def flatten_row(item: Dict[str, Any], *, limit: int = 16) -> Dict[str, Any]:
    flattened: Dict[str, Any] = {}
    for field_name, field_value in iter_scalar_fields(item):
        flattened[field_name] = field_value
        if len(flattened) >= limit:
            break
    return flattened
