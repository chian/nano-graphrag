"""
Append-only prompt observation logging for offline prompt optimization.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class PromptObservationLogger:
    """Logs prompt invocations and judged outcomes to JSONL for later optimization."""

    def __init__(self, base_dir: Path, job_id: Optional[str] = None):
        self.job_id = job_id or datetime.now().strftime("%Y%m%dT%H%M%S")
        self.obs_dir = Path(base_dir) / "gasl_artifacts"
        self.obs_dir.mkdir(parents=True, exist_ok=True)
        self.obs_file = self.obs_dir / "prompt_observations.jsonl"
        self.manifest_file = self.obs_dir / "agent_manifest.snapshot.json"

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]

    def record_invocation(
        self,
        *,
        prompt_name: str,
        prompt_text: str,
        model: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        obs_id = str(uuid.uuid4())
        self._write({
            "event": "invocation",
            "observation_id": obs_id,
            "prompt_name": prompt_name,
            "prompt_hash": self._hash_text(prompt_text),
            "model": model,
            "prompt_text": prompt_text,
            "metadata": metadata or {},
        })
        return obs_id

    def record_outcome(
        self,
        observation_id: str,
        *,
        prompt_name: str,
        response_text: Optional[str] = None,
        parsed: Optional[Dict[str, Any]] = None,
        labels: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._write({
            "event": "outcome",
            "observation_id": observation_id,
            "prompt_name": prompt_name,
            "response_text": response_text,
            "parsed": parsed or {},
            "labels": labels or {},
            "metrics": metrics or {},
            "metadata": metadata or {},
        })

    def _write(self, payload: Dict[str, Any]) -> None:
        row = {
            "ts": datetime.now().isoformat(),
            "job_id": self.job_id,
            **payload,
        }
        with self.obs_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")

    def write_manifest(self, manifest: Dict[str, Any]) -> Path:
        self.manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return self.manifest_file
