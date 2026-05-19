from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional


@dataclass
class PromptCase:
    case_id: str
    prompt_name: str
    prompt_hash: str
    prompt_text: str
    response_text: str
    parsed: Dict[str, Any]
    labels: Dict[str, Any]
    metrics: Dict[str, Any]
    metadata: Dict[str, Any]
    source_file: str
    job_id: str
    ts_invocation: str
    ts_outcome: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "prompt_name": self.prompt_name,
            "prompt_hash": self.prompt_hash,
            "prompt_text": self.prompt_text,
            "response_text": self.response_text,
            "parsed": self.parsed,
            "labels": self.labels,
            "metrics": self.metrics,
            "metadata": self.metadata,
            "source_file": self.source_file,
            "job_id": self.job_id,
            "ts_invocation": self.ts_invocation,
            "ts_outcome": self.ts_outcome,
        }


def iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line, strict=False)


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")


def load_cases_from_observation_files(
    observation_files: Iterable[Path],
    prompt_names: Optional[set[str]] = None,
) -> List[PromptCase]:
    cases: List[PromptCase] = []
    for obs_file in observation_files:
        by_id: Dict[str, Dict[str, Any]] = {}
        for row in iter_jsonl(obs_file):
            if prompt_names and row.get("prompt_name") not in prompt_names:
                continue
            obs_id = row.get("observation_id")
            if not obs_id:
                continue
            record = by_id.setdefault(obs_id, {"invocation": None, "outcome": None})
            record[row["event"]] = row
        for obs_id, pair in by_id.items():
            inv = pair.get("invocation") or {}
            out = pair.get("outcome") or {}
            if not inv:
                continue
            cases.append(
                PromptCase(
                    case_id=obs_id,
                    prompt_name=inv.get("prompt_name", ""),
                    prompt_hash=inv.get("prompt_hash", ""),
                    prompt_text=inv.get("prompt_text", ""),
                    response_text=out.get("response_text", "") or "",
                    parsed=out.get("parsed", {}) or {},
                    labels=out.get("labels", {}) or {},
                    metrics=out.get("metrics", {}) or {},
                    metadata={**(inv.get("metadata", {}) or {}), **(out.get("metadata", {}) or {})},
                    source_file=str(obs_file),
                    job_id=inv.get("job_id", ""),
                    ts_invocation=inv.get("ts", ""),
                    ts_outcome=out.get("ts", ""),
                )
            )
    return cases


def render_template(template: str, case: Dict[str, Any]) -> str:
    safe_case = dict(case)
    safe_case["case_json"] = json.dumps(case, indent=2, default=str)
    for key, value in list(case.items()):
        if isinstance(value, (dict, list)):
            safe_case[f"{key}_json"] = json.dumps(value, indent=2, default=str)
    return template.format_map(DefaultFormatDict(safe_case))


class DefaultFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def run_verifier_command(
    verifier_cmd_template: str,
    *,
    case: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="prompt_lab_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        case_path = tmpdir_path / "case.json"
        candidate_path = tmpdir_path / "candidate.json"
        case_path.write_text(json.dumps(case, indent=2, default=str), encoding="utf-8")
        candidate_path.write_text(json.dumps(candidate, indent=2, default=str), encoding="utf-8")
        cmd = verifier_cmd_template.format(case_path=case_path, candidate_path=candidate_path, tmpdir=tmpdir_path)
        proc = subprocess.run(
            cmd,
            shell=True,
            text=True,
            capture_output=True,
            env=os.environ.copy(),
            check=False,
        )
        if proc.returncode != 0:
            return {
                "pass": False,
                "score": 0.0,
                "labels": {"verifier_error": True},
                "notes": proc.stderr.strip() or proc.stdout.strip(),
            }
        try:
            return json.loads(proc.stdout.strip())
        except Exception:
            return {
                "pass": False,
                "score": 0.0,
                "labels": {"verifier_parse_error": True},
                "notes": proc.stdout.strip(),
            }


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))
