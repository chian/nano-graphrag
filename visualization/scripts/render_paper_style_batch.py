#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from visualization.demo_catalog import PAPER_STYLE_DEMOS_6, estimate_demo_micro_actions, get_demo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="videos/paper_opening_style_comparisons")
    parser.add_argument("--port", default="5050")
    parser.add_argument("--min-micro-actions", type=int, default=110)
    args = parser.parse_args()

    output_dir = REPO_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    demo_pace = 1.45
    camera_eye_pace = 1.65

    rendered: list[tuple[str, str]] = []
    for demo_id in PAPER_STYLE_DEMOS_6:
        demo = get_demo(demo_id)
        if demo is None:
            raise SystemExit(f"Demo not found for {demo_id}")
        micro_actions = estimate_demo_micro_actions(demo["replay"])
        if micro_actions < args.min_micro_actions:
            raise SystemExit(
                f"{demo['id']} failed micro-action QC: {micro_actions} < {args.min_micro_actions}"
            )
        total_s = sum(step["delay_ms"] for step in demo["replay"]) / 1000.0
        pace = camera_eye_pace if demo.get("visual_style") == "camera-eye" else demo_pace
        duration = max(40, int(round(total_s * pace + 10)))
        output = output_dir / f"{demo['id']}.mp4"
        print(f"Rendering {demo['id']} · micro-actions={micro_actions} · duration≈{duration}s")
        cmd = [
            str(REPO_ROOT / "visualization" / "scripts" / "record_demo.sh"),
            demo["id"],
            str(output),
            str(args.port),
            "gasl",
        ]
        env = dict(**os.environ)
        env["DURATION"] = str(duration)
        env["DISPLAY_NUM"] = ":99"
        env["RES"] = "1600x900"
        subprocess.run(cmd, cwd=REPO_ROOT, check=True, env=env)
        rendered.append((demo["id"], demo["title"]))

    readme = output_dir / "README.md"
    lines = [
        "# Paper-Guided Opening Style Comparisons",
        "",
        "Six comparison videos that reinterpret GASL openings using the six cinematic opening styles described in the CHI 2022 paper on data-video openings.",
        "",
    ]
    for demo_id, title in rendered:
        lines.append(f"- `{demo_id}.mp4` — {title}")
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
