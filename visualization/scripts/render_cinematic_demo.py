#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from visualization.demo_catalog import build_cinematic_demo_from_artifacts, estimate_demo_micro_actions

DEMO_REPLAY_PACE = 1.45
CAMERA_EYE_REPLAY_PACE = 1.65


def build_url(*, run_id: str, qid: str, graph_path: str, full_graph_path: str, target_seconds: int, port: str) -> str:
    params = {
        "run_id": run_id,
        "qid": qid,
        "replay": "1",
        "mode": "gasl",
        "cinematic": "1",
        "target_seconds": str(target_seconds),
    }
    if graph_path:
        params["graph_path"] = graph_path
    if full_graph_path:
        params["full_graph_path"] = full_graph_path
    return f"http://127.0.0.1:{port}/?{urlencode(params)}"


def motion_profile(replay: list[dict]) -> tuple[int, int]:
    highlight_events = 0
    highlight_nodes: set[str] = set()
    for step in replay:
        if step.get("event") != "gasl_highlight":
            continue
        nodes = [node for node in step.get("payload", {}).get("nodes", []) if isinstance(node, str) and node]
        if nodes:
            highlight_events += 1
            highlight_nodes.update(nodes)
    return highlight_events, len(highlight_nodes)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a long-form cinematic demo from committed run artifacts."
    )
    parser.add_argument("run_id")
    parser.add_argument("qid")
    parser.add_argument("--graph-path", default="")
    parser.add_argument("--full-graph-path", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--port", default="5050")
    parser.add_argument("--target-seconds", type=int, default=90)
    parser.add_argument("--min-highlight-events", type=int, default=3)
    parser.add_argument("--min-highlight-nodes", type=int, default=6)
    parser.add_argument("--head-trim-seconds", type=float, default=8.0)
    parser.add_argument("--tail-margin-seconds", type=float, default=6.0)
    args = parser.parse_args()

    output = args.output or f"videos/{args.run_id}-{args.qid}-cinematic.mp4"
    output_path = REPO_ROOT / output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pace_factor = CAMERA_EYE_REPLAY_PACE if args.qid.startswith("paper-") else DEMO_REPLAY_PACE
    replay_target_seconds = args.target_seconds / pace_factor

    demo = build_cinematic_demo_from_artifacts(
        qid=args.qid,
        run_id=args.run_id,
        graph_path=args.graph_path or None,
        full_graph_path=args.full_graph_path or None,
        target_seconds=int(round(replay_target_seconds)),
    )
    micro_actions = estimate_demo_micro_actions(demo["replay"])
    highlight_events, highlight_nodes = motion_profile(demo["replay"])
    if highlight_events < args.min_highlight_events or highlight_nodes < args.min_highlight_nodes:
        raise SystemExit(
            f"{demo['id']} failed motion QC: highlight_events={highlight_events} "
            f"(min {args.min_highlight_events}), highlight_nodes={highlight_nodes} "
            f"(min {args.min_highlight_nodes})"
        )
    total_s = sum(step["delay_ms"] for step in demo["replay"]) / 1000.0
    actual_replay_s = total_s * pace_factor
    duration = int(round(args.head_trim_seconds + actual_replay_s + args.tail_margin_seconds))
    env = dict(os.environ)
    env["DURATION"] = str(duration)
    env["DISPLAY_NUM"] = env.get("DISPLAY_NUM", ":99")
    env["RES"] = env.get("RES", "1600x900")

    url = build_url(
        run_id=args.run_id,
        qid=args.qid,
        graph_path=args.graph_path,
        full_graph_path=args.full_graph_path,
        target_seconds=int(round(replay_target_seconds)),
        port=args.port,
    )
    tmp_dir = Path(tempfile.mkdtemp(prefix="cinematic-render-"))
    tmp_output = tmp_dir / "capture.mp4"
    cmd = [str(REPO_ROOT / "visualization" / "scripts" / "record_viewer_url.sh"), url, str(tmp_output)]
    print(
        f"Rendering {demo['id']} · micro-actions={micro_actions} · "
        f"highlight-events={highlight_events} · highlight-nodes={highlight_nodes} · "
        f"replay≈{actual_replay_s:.1f}s · capture={duration}s"
    )
    try:
        subprocess.run(cmd, cwd=REPO_ROOT, check=True, env=env)
        trim_cmd = [
            "ffmpeg",
            "-y",
            "-i", str(tmp_output),
            "-ss", str(args.head_trim_seconds),
            "-t", str(actual_replay_s + args.tail_margin_seconds),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        subprocess.run(trim_cmd, cwd=REPO_ROOT, check=True)
    finally:
        if tmp_output.exists():
            tmp_output.unlink()
        if tmp_dir.exists():
            tmp_dir.rmdir()


if __name__ == "__main__":
    main()
