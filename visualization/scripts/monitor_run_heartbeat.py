#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import time
from datetime import datetime
from pathlib import Path


def _ts() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description="Write periodic run heartbeat lines to disk.")
    parser.add_argument("--pid", type=int, required=True, help="Worker pid to watch")
    parser.add_argument("--run-dir", required=True, help="Run directory to monitor")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds")
    parser.add_argument("--out", default="", help="Optional explicit output log path")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_path = Path(args.out) if args.out else run_dir / "monitor.log"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("a", encoding="utf-8") as fh:
        while True:
            pid_alive = os.path.exists(f"/proc/{args.pid}")
            qdirs = len([p for p in run_dir.glob("q*") if p.is_dir()])
            gasl_done = len(list(run_dir.glob("q*/gasl.json")))
            prompt_obs = len(list(run_dir.glob("q*/gasl_artifacts/prompt_observations.jsonl")))
            line = (
                f"{_ts()} pid={args.pid} alive={int(pid_alive)} "
                f"qdirs={qdirs} gasl_done={gasl_done} prompt_obs={prompt_obs}"
            )
            fh.write(line + "\n")
            fh.flush()
            if not pid_alive:
                break
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
