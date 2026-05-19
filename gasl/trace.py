"""
Structured trace logging for GASL runs.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class GASLTraceLogger:
    """Append-only JSONL trace logger for planner and executor debugging."""

    def __init__(self, base_dir: Path, job_id: Optional[str] = None):
        self.job_id = job_id or datetime.now().strftime("%Y%m%dT%H%M%S")
        self.trace_dir = Path(base_dir) / "gasl_artifacts" / "traces"
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.trace_file = self.trace_dir / f"{self.job_id}.jsonl"

    def log(self, event: str, payload: Dict[str, Any]) -> None:
        row = {
            "ts": datetime.now().isoformat(),
            "job_id": self.job_id,
            "event": event,
            "payload": payload,
        }
        with self.trace_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
