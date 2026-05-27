#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from visualization.demo_catalog import DEMO_VIDEO_SHAREABLE_14, estimate_demo_micro_actions, get_demo

GRAPH_PREFIXES = [
    "engineering",
    "hospital_environment",
    "biosensor_detection",
    "aerosol_exposure",
]


def lookup_demo(qid: str):
    for prefix in GRAPH_PREFIXES:
        demo = get_demo(f"{prefix}-{qid}")
        if demo is not None:
            return demo
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="videos/gasl_cinematic_demos")
    parser.add_argument("--port", default="5050")
    parser.add_argument("--min-micro-actions", type=int, default=100)
    args = parser.parse_args()

    output_dir = REPO_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    demo_pace = 1.45
    camera_eye_pace = 1.65

    for qid in DEMO_VIDEO_SHAREABLE_14:
        demo = lookup_demo(qid)
        if demo is None:
            raise SystemExit(f"Demo not found for {qid}")
        micro_actions = estimate_demo_micro_actions(demo["replay"])
        if micro_actions < args.min_micro_actions:
            raise SystemExit(
                f"{demo['id']} failed micro-action QC: {micro_actions} < {args.min_micro_actions}"
            )
        total_s = sum(step["delay_ms"] for step in demo["replay"]) / 1000.0
        pace = camera_eye_pace if demo.get("visual_style") == "camera-eye" else demo_pace
        duration = max(45, int(round(total_s * pace + 10)))
        output = output_dir / f"{demo['id']}.mp4"
        print(f"Rendering {demo['id']} · micro-actions={micro_actions} · duration≈{duration}s")
        cmd = [
            str(REPO_ROOT / "visualization" / "scripts" / "record_demo.sh"),
            demo["id"],
            str(output),
            str(args.port),
            "gasl",
        ]
        env = dict(**subprocess.os.environ)
        env["DURATION"] = str(duration)
        env["DISPLAY_NUM"] = ":99"
        env["RES"] = "1600x900"
        subprocess.run(cmd, cwd=REPO_ROOT, check=True, env=env)

    readme = output_dir / "README.md"
    lines = [
        "# GASL Cinematic Demos",
        "",
        "Rendered cinematic replay videos for the 14-question shareable set: the original 12-question shortlist plus q001 and q007.",
        "",
    ]
    for qid in DEMO_VIDEO_SHAREABLE_14:
        demo = lookup_demo(qid)
        lines.append(f"- `{demo['id']}.mp4` — {demo['title']}")
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
