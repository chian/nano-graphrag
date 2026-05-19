#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.prompt_lab.common import load_cases_from_observation_files, write_jsonl


def _ts() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _run(cmd: str, log_fh) -> int:
    log_fh.write(f"{_ts()} RUN {cmd}\n")
    log_fh.flush()
    proc = subprocess.run(cmd, shell=True, cwd=REPO_ROOT, text=True, capture_output=True)
    if proc.stdout:
        log_fh.write(proc.stdout)
    if proc.stderr:
        log_fh.write(proc.stderr)
    log_fh.write(f"{_ts()} RC {proc.returncode}\n")
    log_fh.flush()
    return proc.returncode


def _completed_count(run_root: Path, pattern: str) -> int:
    return sum(1 for _ in run_root.glob(f"{pattern}/q*/gasl.json"))


def _obs_files(run_root: Path, pattern: str) -> List[Path]:
    return sorted(run_root.glob(f"{pattern}/q*/gasl_artifacts/prompt_observations.jsonl"))


def _run_dirs(run_root: Path, pattern: str) -> List[Path]:
    return sorted([p for p in run_root.glob(pattern) if p.is_dir()])


def _write_cases_from_runs(run_root: Path, pattern: str, out_path: Path, prompt_names: set[str] | None = None) -> int:
    files = _obs_files(run_root, pattern)
    cases = load_cases_from_observation_files(files, prompt_names=prompt_names)
    write_jsonl(out_path, [c.to_dict() for c in cases])
    return len(cases)


def _launch_rerun(per_graph: int, run_tag: str, log_fh) -> int:
    run_id = datetime.now().strftime(f"corpus_%Y%m%dT%H%M%S_{run_tag}")
    cmd = (
        f"nohup .venv/bin/python visualization/scripts/run_trace_corpus.py "
        f"--per-graph {per_graph} --run-id {shlex.quote(run_id)} "
        f"> benchmark_results/{run_id}/runner.log 2>&1 & echo $!"
    )
    os.makedirs(REPO_ROOT / "benchmark_results" / run_id, exist_ok=True)
    proc = subprocess.run(cmd, shell=True, cwd=REPO_ROOT, text=True, capture_output=True)
    pid_text = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    try:
        pid = int(pid_text)
    except Exception:
        pid = 0
    log_fh.write(f"{_ts()} LAUNCHED rerun run_id={run_id} pid={pid}\n")
    log_fh.flush()
    return pid


def main() -> None:
    parser = argparse.ArgumentParser(description="Supervise post-tuning runs, analyze at threshold, optimize, and rerun.")
    parser.add_argument("--run-root", default="benchmark_results")
    parser.add_argument("--pattern", default="corpus_20260518_posttune*")
    parser.add_argument("--active-pid", type=int, required=True)
    parser.add_argument("--threshold", type=int, default=40)
    parser.add_argument("--poll", type=int, default=600)
    parser.add_argument("--per-graph-rerun", type=int, default=5)
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    run_root = Path(args.run_root)
    out_dir = Path(args.out_dir) if args.out_dir else run_root / "posttune_supervision"
    out_dir.mkdir(parents=True, exist_ok=True)
    selected_root = out_dir / "selected_traces"
    cases_path = out_dir / "cases.jsonl"
    seeded_path = out_dir / "seeded_candidates.jsonl"
    verifications_path = out_dir / "verifications.jsonl"
    accepted_path = out_dir / "accepted_repairs.jsonl"
    dataset_path = out_dir / "prompt_dataset.json"
    failure_json = out_dir / "failure_summary.json"
    next_text = out_dir / "NEXT_ACTION.txt"
    log_path = out_dir / "supervisor.log"

    current_pid = args.active_pid
    analysis_done = False
    with log_path.open("a", encoding="utf-8") as log_fh:
        log_fh.write(f"{_ts()} START current_pid={current_pid} pattern={args.pattern} threshold={args.threshold}\n")
        log_fh.flush()
        while True:
            completed = _completed_count(run_root, args.pattern)
            alive = os.path.exists(f"/proc/{current_pid}") if current_pid else False
            log_fh.write(f"{_ts()} STATUS completed={completed} alive={int(alive)} pid={current_pid}\n")
            log_fh.flush()

            if completed >= args.threshold and not analysis_done:
                _run(
                    f".venv/bin/python visualization/scripts/analyze_posttune_failures.py "
                    f"--run-root {shlex.quote(str(run_root))} "
                    f"--pattern {shlex.quote(args.pattern)} "
                    f"--out-json {shlex.quote(str(failure_json))} "
                    f"--out-text {shlex.quote(str(next_text))}",
                    log_fh,
                )
                case_count = _write_cases_from_runs(run_root, args.pattern, cases_path, prompt_names={"aggregate_repair", "plan_generation"})
                log_fh.write(f"{_ts()} CASES wrote {case_count} to {cases_path}\n")
                log_fh.flush()
                _run(
                    f".venv/bin/python tools/prompt_lab/seed_candidates_from_cases.py "
                    f"--cases {shlex.quote(str(cases_path))} --only-positive --out {shlex.quote(str(seeded_path))}",
                    log_fh,
                )
                _run(
                    f".venv/bin/python tools/prompt_lab/verify_repair_candidates.py "
                    f"--cases {shlex.quote(str(cases_path))} "
                    f"--candidates {shlex.quote(str(seeded_path))} "
                    f"--verifier-cmd "
                    f"'.venv/bin/python tools/prompt_lab/verifiers/nano_graphrag_verifier.py --case {{case_path}} --candidate {{candidate_path}}' "
                    f"--out {shlex.quote(str(verifications_path))} "
                    f"--accepted-repairs-out {shlex.quote(str(accepted_path))} "
                    f"--progress-every 25",
                    log_fh,
                )
                _run(
                    f".venv/bin/python tools/prompt_lab/build_labeled_prompt_dataset.py "
                    f"--cases {shlex.quote(str(cases_path))} "
                    f"--candidates {shlex.quote(str(seeded_path))} "
                    f"--verifications {shlex.quote(str(verifications_path))} "
                    f"--out {shlex.quote(str(dataset_path))}",
                    log_fh,
                )
                selected_root.mkdir(parents=True, exist_ok=True)
                for child in list(selected_root.iterdir()):
                    if child.is_symlink() or child.is_file():
                        child.unlink()
                for run_dir in _run_dirs(run_root, args.pattern):
                    link = selected_root / run_dir.name
                    if not link.exists():
                        link.symlink_to(run_dir.resolve(), target_is_directory=True)
                _run(
                    f".venv/bin/python visualization/scripts/optimize_aggregate_repair_prompt.py "
                    f"--trace-root {shlex.quote(str(selected_root))} "
                    f"--limit 40 "
                    f"--run-dir {shlex.quote(str(out_dir / 'aggregate_repair_gepa_from_posttune'))}",
                    log_fh,
                )
                analysis_done = True
                if not alive:
                    current_pid = _launch_rerun(args.per_graph_rerun, "posttune_after_opt", log_fh)

            if not alive and completed < args.threshold:
                current_pid = _launch_rerun(args.per_graph_rerun, "posttune_chain", log_fh)

            time.sleep(args.poll)


if __name__ == "__main__":
    main()
