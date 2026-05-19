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


def _run_dirs(run_root: Path, pattern: str) -> List[Path]:
    return sorted([p for p in run_root.glob(pattern) if p.is_dir()])


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


def _launch_codex_exec(context_json: Path, out_dir: Path, log_fh) -> int:
    prompt = f"""
You are taking over an overnight post-tuning cycle in /home/chia/repos/nano-graphrag.

Inputs:
- context JSON: {context_json}

Task:
1. Read the context JSON and inspect many completed post-tuning traces under the staged trace root.
2. Perform open-ended failure analysis across those traces. Do not rely on one query.
3. Decide the next best fix using pattern-level evidence, not one-off query overfitting.
4. If useful, run the prompt-lab and optimization scripts yourself. Choose the scripts, don't assume.
5. Implement the fix.
6. Commit and push.
7. Start the next corpus rerun.
8. Write a brief action summary to {out_dir / "codex_next_action.txt"}.

Constraints:
- Use many examples, not one trace.
- Prefer central fixes over prompt-specific hacks.
- Keep the repo working tree clean except for purposeful changes.
"""
    prompt_file = out_dir / "codex_exec_prompt.txt"
    prompt_file.write_text(prompt.strip() + "\n", encoding="utf-8")
    output_file = out_dir / "codex_next_action.txt"
    cmd = (
        f"setsid codex exec -m gpt-5.5 -C {shlex.quote(str(REPO_ROOT))} "
        f"-s danger-full-access --dangerously-bypass-approvals-and-sandbox "
        f"-o {shlex.quote(str(output_file))} "
        f"- "
        f"> {shlex.quote(str(out_dir / 'codex_exec.log'))} 2>&1 < {shlex.quote(str(prompt_file))} & echo $!"
    )
    proc = subprocess.run(cmd, shell=True, cwd=REPO_ROOT, text=True, capture_output=True)
    pid_text = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    try:
        pid = int(pid_text)
    except Exception:
        pid = 0
    log_fh.write(f"{_ts()} LAUNCHED codex-exec pid={pid}\n")
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
    parser.add_argument("--launch-codex-exec", action="store_true", help="After threshold analysis, hand off to codex exec for next-fix cycle")
    args = parser.parse_args()

    run_root = Path(args.run_root)
    out_dir = Path(args.out_dir) if args.out_dir else run_root / "posttune_supervision"
    out_dir.mkdir(parents=True, exist_ok=True)
    selected_root = out_dir / "selected_traces"
    context_json = out_dir / "codex_context.json"
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
                selected_root.mkdir(parents=True, exist_ok=True)
                for child in list(selected_root.iterdir()):
                    if child.is_symlink() or child.is_file():
                        child.unlink()
                for run_dir in _run_dirs(run_root, args.pattern):
                    link = selected_root / run_dir.name
                    if not link.exists():
                        link.symlink_to(run_dir.resolve(), target_is_directory=True)
                context_json.write_text(
                    __import__("json").dumps(
                        {
                            "repo_root": str(REPO_ROOT),
                            "run_root": str(run_root),
                            "pattern": args.pattern,
                            "completed": completed,
                            "threshold": args.threshold,
                            "selected_trace_root": str(selected_root),
                            "run_dirs": [str(p) for p in _run_dirs(run_root, args.pattern)],
                            "suggested_scripts": [
                                "visualization/scripts/analyze_posttune_failures.py",
                                "tools/prompt_lab/collect_prompt_cases.py",
                                "tools/prompt_lab/seed_candidates_from_cases.py",
                                "tools/prompt_lab/verify_repair_candidates.py",
                                "tools/prompt_lab/build_labeled_prompt_dataset.py",
                                "visualization/scripts/optimize_aggregate_repair_prompt.py",
                                "visualization/scripts/run_trace_corpus.py",
                            ],
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                analysis_done = True
                if not alive:
                    current_pid = _launch_rerun(args.per_graph_rerun, "posttune_after_opt", log_fh)
                if args.launch_codex_exec:
                    _launch_codex_exec(context_json, out_dir, log_fh)
                else:
                    _run(
                        f".venv/bin/python visualization/scripts/analyze_posttune_failures.py "
                        f"--run-root {shlex.quote(str(run_root))} "
                        f"--pattern {shlex.quote(args.pattern)} "
                        f"--out-json {shlex.quote(str(failure_json))} "
                        f"--out-text {shlex.quote(str(next_text))}",
                        log_fh,
                    )

            if not alive and completed < args.threshold:
                current_pid = _launch_rerun(args.per_graph_rerun, "posttune_chain", log_fh)

            time.sleep(args.poll)


if __name__ == "__main__":
    main()
