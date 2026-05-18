#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_WORKING_FILES = [
    "tmp/prompt_lab_cases.jsonl",
    "tmp/seeded_candidates.jsonl",
    "tmp/verifications.jsonl",
    "tmp/accepted_repairs.jsonl",
    "tmp/prompt_dataset.json",
]

DEFAULT_BENCHMARK_DIRS = [
    "benchmark_results/process_repair_gepa_smoke",
    "benchmark_results/process_repair_gepa_full",
    "benchmark_results/planner_gepa_smoke_min",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_entries(repo_root: Path, rel_paths: Iterable[str]) -> list[dict]:
    entries = []
    for rel in rel_paths:
        path = repo_root / rel
        if not path.exists():
            continue
        if path.is_file():
            entries.append({
                "path": rel,
                "type": "file",
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            })
        elif path.is_dir():
            files = sorted(p for p in path.rglob("*") if p.is_file())
            entries.append({
                "path": rel,
                "type": "dir",
                "file_count": len(files),
                "size": sum(p.stat().st_size for p in files),
            })
    return entries


def copy_or_move(repo_root: Path, archive_dir: Path, rel_paths: Iterable[str], *, move_working_files: bool) -> None:
    for rel in rel_paths:
        src = repo_root / rel
        if not src.exists():
            continue
        dst = archive_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            if move_working_files:
                shutil.move(str(src), str(dst))
            else:
                shutil.copy2(src, dst)
        elif src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)


def reset_working_files(repo_root: Path, rel_paths: Iterable[str]) -> None:
    for rel in rel_paths:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".json":
            path.write_text(json.dumps({"train": [], "val": []}, indent=2))
        else:
            path.write_text("")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--phase-name", required=True)
    parser.add_argument("--archive-root", default="archives/prompt_tuning")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    archive_dir = (repo_root / args.archive_root / f"{ts}_{args.phase_name}").resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)

    working_entries = collect_entries(repo_root, DEFAULT_WORKING_FILES)
    benchmark_entries = collect_entries(repo_root, DEFAULT_BENCHMARK_DIRS)

    copy_or_move(repo_root, archive_dir, DEFAULT_WORKING_FILES, move_working_files=True)
    copy_or_move(repo_root, archive_dir, DEFAULT_BENCHMARK_DIRS, move_working_files=False)
    reset_working_files(repo_root, DEFAULT_WORKING_FILES)

    manifest = {
        "phase_name": args.phase_name,
        "archived_at": ts,
        "working_files": working_entries,
        "benchmark_dirs": benchmark_entries,
    }
    (archive_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"archive_dir": str(archive_dir), "manifest": manifest}, indent=2))


if __name__ == "__main__":
    main()
