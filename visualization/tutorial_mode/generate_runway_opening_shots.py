from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve

from runwayml import RunwayML

DEFAULT_SHOTS: list[dict[str, Any]] = [
    {
        "id": "01_eureka_myth",
        "plate": "assets/runway_plates/01_eureka_myth_plate.png",
        "duration": 5,
        "prompt": (
            "A stylized editorial animation. The scene begins still, then a sudden spark of "
            "insight flashes above the thinker. The character jolts upright with delighted "
            "surprise, water ripples outward, and the camera performs a quick push-in to heighten "
            "the mythic eureka feeling. Motion is clean, readable, and graphic, with no extra "
            "characters or visual clutter."
        ),
    },
    {
        "id": "02_wegener_ridicule",
        "plate": "assets/runway_plates/02_wegener_ridicule_plate.png",
        "duration": 8,
        "prompt": (
            "A stylized editorial lecture scene. The speaker stands at the podium with calm, bold "
            "confidence as the audience shifts from skepticism to exaggerated ridicule. A few comic "
            "projectiles arc through the foreground like a visual metaphor rather than literal "
            "realism. The camera begins with a respectful medium shot, then slides slightly to "
            "reveal dismissive audience reactions. The motion should feel sharp, readable, and "
            "theatrical rather than chaotic."
        ),
    },
    {
        "id": "03_tharp_compilation",
        "plate": "assets/runway_plates/03_tharp_compilation_plate.png",
        "duration": 10,
        "prompt": (
            "A careful editorial animation of a scientist compiling evidence at a drafting table. "
            "Paper strips slide into alignment one after another, contour marks build in successive "
            "passes, and the camera drifts slowly across the table as the structure becomes clearer. "
            "The motion is patient, cumulative, and precise. The scene should feel methodical and "
            "legible, not magical or abrupt."
        ),
    },
]


def load_shots(spec_path: str | None) -> list[dict[str, Any]]:
    if not spec_path:
        return DEFAULT_SHOTS
    data = json.loads(Path(spec_path).read_text())
    if not isinstance(data, list):
        raise SystemExit("Spec file must be a JSON array")
    return data


def ensure_key() -> None:
    if not os.environ.get("RUNWAYML_API_SECRET"):
        raise SystemExit("RUNWAYML_API_SECRET is not set")


def poll_task(client: RunwayML, task_id: str, poll_s: float = 5.0, timeout_s: float = 900.0):
    start = time.time()
    while True:
        task = client.tasks.retrieve(task_id)
        if task.status in {"SUCCEEDED", "FAILED", "CANCELLED", "THROTTLED"}:
            return task
        if time.time() - start > timeout_s:
            raise TimeoutError(f"Timed out waiting for task {task_id}")
        time.sleep(poll_s)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gen4_turbo", choices=["gen4_turbo", "gen4.5"])
    parser.add_argument("--ratio", default="1280:720")
    parser.add_argument("--variants", type=int, default=1)
    parser.add_argument("--outdir", default="visualization/tutorial_mode/generated/runway/opening_trial_v1")
    parser.add_argument("--shot", action="append", help="Optional subset of shot ids")
    parser.add_argument("--spec", help="Optional JSON spec file describing shots")
    args = parser.parse_args()

    ensure_key()
    client = RunwayML()
    repo_root = Path(__file__).resolve().parents[2]
    outdir = repo_root / args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    metadata: list[dict[str, Any]] = []

    shots = load_shots(args.spec)
    shot_ids = [s["id"] for s in shots]
    if args.shot:
        unknown = [s for s in args.shot if s not in shot_ids]
        if unknown:
            raise SystemExit(f"Unknown shot ids in --shot: {unknown}")
    selected = [s for s in shots if not args.shot or s["id"] in args.shot]
    for shot in selected:
        plate = (Path(__file__).resolve().parent / shot["plate"]).resolve()
        for variant in range(1, args.variants + 1):
            print(f"Submitting {shot['id']} variant {variant} on {args.model}...")
            with plate.open("rb") as f:
                upload = client.uploads.create_ephemeral(file=f)
            task = client.image_to_video.create(
                model=args.model,
                ratio=args.ratio,
                duration=shot["duration"],
                prompt_image=upload.uri,
                prompt_text=shot["prompt"],
            )
            result = poll_task(client, task.id)
            result_dump = result.model_dump() if hasattr(result, "model_dump") else {}
            record = {
                "shot_id": shot["id"],
                "variant": variant,
                "model": args.model,
                "plate": str(plate),
                "task_id": task.id,
                "status": getattr(result, "status", "UNKNOWN"),
                "output": list(getattr(result, "output", []) or []),
                "result": result_dump,
            }
            if getattr(result, "status", None) == "SUCCEEDED" and getattr(result, "output", None):
                mp4_path = outdir / f"{shot['id']}_v{variant}_{args.model.replace('.', '_')}.mp4"
                urlretrieve(result.output[0], mp4_path)
                record["saved_mp4"] = str(mp4_path)
                print(f"Saved {mp4_path}")
            else:
                print(f"Task {task.id} ended with {record['status']}")
            metadata.append(record)
            (outdir / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str))


if __name__ == "__main__":
    main()
