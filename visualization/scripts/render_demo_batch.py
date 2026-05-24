#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from visualization.demo_catalog import DEMO_SHORTLIST_12, get_demo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="videos/gasl_cinematic_demos")
    parser.add_argument("--port", default="5050")
    args = parser.parse_args()

    output_dir = REPO_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    for qid in DEMO_SHORTLIST_12:
        demo = get_demo(f"engineering-{qid}") or get_demo(f"hospital_environment-{qid}")
        if demo is None:
            raise SystemExit(f"Demo not found for {qid}")
        total_s = sum(step["delay_ms"] for step in demo["replay"]) / 1000.0
        duration = max(18, int(round(total_s + 4)))
        output = output_dir / f"{demo['id']}.mp4"
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
        "Rendered cinematic replay videos for the 12-question shortlist selected from the 72-question corpus, excluding q001 and q007.",
        "",
    ]
    for qid in DEMO_SHORTLIST_12:
        demo = get_demo(f"engineering-{qid}") or get_demo(f"hospital_environment-{qid}")
        lines.append(f"- `{demo['id']}.mp4` — {demo['title']}")
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
