from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpc.common import read_json_records, shard_ranges, write_json, write_jsonl


def split_chunk_manifest(
    *,
    manifest_path: Path,
    out_dir: Path,
    shard_count: int,
    prefix: str = "shard",
) -> dict:
    rows = read_json_records(manifest_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    shard_files: list[dict] = []
    for shard_idx, (start, end) in enumerate(shard_ranges(len(rows), shard_count)):
        shard_rows = rows[start:end]
        shard_path = out_dir / f"{prefix}_{shard_idx:03d}.jsonl"
        write_jsonl(shard_path, shard_rows)
        shard_files.append(
            {
                "shard_idx": shard_idx,
                "path": str(shard_path),
                "rows": len(shard_rows),
                "start_index": start,
                "end_index": end,
            }
        )
    summary = {
        "manifest_path": str(manifest_path),
        "out_dir": str(out_dir),
        "shard_count": shard_count,
        "rows": len(rows),
        "shards": shard_files,
    }
    write_json(out_dir / "manifest.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Split a chunk manifest into deterministic shard files by count.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--shards", type=int, default=100)
    parser.add_argument("--prefix", default="shard")
    args = parser.parse_args()
    split_chunk_manifest(
        manifest_path=args.manifest,
        out_dir=args.out_dir,
        shard_count=args.shards,
        prefix=args.prefix,
    )


if __name__ == "__main__":
    main()
