#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from visualization.demo_catalog import DEMO_SHORTLIST_12, estimate_demo_micro_actions, get_demo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="videos/paper_symbolism_shortlist_12")
    parser.add_argument("--port", default="5050")
    parser.add_argument("--min-micro-actions", type=int, default=110)
    args = parser.parse_args()

    output_dir = REPO_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    demo_pace = 1.45

    rendered = []
    for qid in DEMO_SHORTLIST_12:
        demo_id = f"paper-symbolism-{qid}"
        demo = get_demo(demo_id)
        if demo is None:
            raise SystemExit(f"Demo not found for {demo_id}")
        micro_actions = estimate_demo_micro_actions(demo["replay"])
        if micro_actions < args.min_micro_actions:
            raise SystemExit(
                f"{demo['id']} failed micro-action QC: {micro_actions} < {args.min_micro_actions}"
            )
        total_s = sum(step["delay_ms"] for step in demo["replay"]) / 1000.0
        duration = max(40, int(round(total_s * demo_pace + 10)))
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
        "# Symbolism / Metaphor Variants for the Selected 12",
        "",
        "Twelve symbol/metaphor variants built from the balanced demo shortlist, chosen for movement, scientific phrasing, and likely GASL-over-RAG advantage.",
        "",
    ]
    for demo_id, title in rendered:
        lines.append(f"- `{demo_id}.mp4` — {title}")
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
