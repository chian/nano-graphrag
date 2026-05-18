"""
Shared formatting helpers for AGGREGATE repair prompt optimization.
"""

from __future__ import annotations

from typing import Any, Dict, List


def format_aggregate_repair_case(
    *,
    data: List[Dict[str, Any]],
    query: str,
    aggregate_command: str,
    incoming_contract: Dict[str, Any],
    previous_command: str,
    next_command: str,
    error_message: str,
) -> str:
    sample_rows = [flatten_row(row) for row in data[:8]]
    return f"""Case:

Query:
{query}

Aggregate command:
{aggregate_command}

Incoming contract:
{incoming_contract}

Previous command:
{previous_command}

Next command:
{next_command}

Observed error:
{error_message}

Sample rows:
{sample_rows}
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


def flatten_row(item: Dict[str, Any], *, limit: int = 18) -> Dict[str, Any]:
    flattened: Dict[str, Any] = {}
    for field_name, field_value in iter_scalar_fields(item):
        flattened[field_name] = field_value
        if len(flattened) >= limit:
            break
    return flattened
