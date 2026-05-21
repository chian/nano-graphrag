#!/usr/bin/env python3
"""
Audit a GASL trace against the documented runtime workflow checklist.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


REQUIRED_EVENTS = [
    "planner_prompt",
    "planner_response",
    "planner_plan",
]

CONDITIONAL_EVENTS = {
    "command_local_repair": "command_repair_response",
    "iteration_repair": "plan_iteration_prompt",
    "final_answer": "final_answer_response",
}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_gasl_workflow_trace.py <trace.jsonl>", file=sys.stderr)
        return 2
    trace_path = Path(sys.argv[1])
    if not trace_path.exists():
        print(f"missing trace: {trace_path}", file=sys.stderr)
        return 2

    events = []
    with trace_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            events.append(obj.get("event", ""))

    counts = Counter(events)
    missing = [event for event in REQUIRED_EVENTS if counts[event] == 0]

    print("required:")
    for event in REQUIRED_EVENTS:
        print(f"  {event}: {counts[event]}")
    print("conditional:")
    for label, event in CONDITIONAL_EVENTS.items():
        print(f"  {label} ({event}): {counts[event]}")

    if missing:
        print("missing required events:")
        for event in missing:
            print(f"  - {event}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
