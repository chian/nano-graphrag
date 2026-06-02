from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from hpc.common import (
    chunk_text_with_offsets,
    load_text_for_record,
    make_chunk_id,
    read_json_records,
    write_json,
    write_jsonl,
)


def build_chunk_manifest(
    *,
    inventory_path: Path,
    output_path: Path,
    paper_root: Path | None,
    paper_id_key: str,
    path_key: str,
    title_key: str,
    text_key: str,
    chunk_size: int,
    overlap: int,
) -> dict[str, Any]:
    inventory_rows = read_json_records(inventory_path)
    manifest_rows: list[dict[str, Any]] = []
    paper_count = 0
    for paper_idx, row in enumerate(inventory_rows):
        paper_id = str(row.get(paper_id_key) or row.get("id") or f"paper_{paper_idx:06d}")
        paper_title = str(row.get(title_key, ""))
        text, source_path = load_text_for_record(
            row,
            paper_root=paper_root,
            text_key=text_key,
            path_key=path_key,
        )
        paper_count += 1
        for chunk_idx, (start, end, chunk_text) in enumerate(chunk_text_with_offsets(text, chunk_size, overlap)):
            manifest_rows.append(
                {
                    "paper_id": paper_id,
                    "paper_idx": paper_idx,
                    "paper_title": paper_title,
                    "paper_path": source_path,
                    "chunk_idx": chunk_idx,
                    "start_char": start,
                    "end_char": end,
                    "chunk_chars": len(chunk_text),
                    "chunk_id": make_chunk_id(paper_id, chunk_idx, start, end, chunk_text),
                    "chunk_text": chunk_text,
                }
            )

    write_jsonl(output_path, manifest_rows)
    summary = {
        "inventory_path": str(inventory_path),
        "output_path": str(output_path),
        "papers": paper_count,
        "chunks": len(manifest_rows),
        "chunk_size": chunk_size,
        "overlap": overlap,
    }
    write_json(output_path.with_suffix(".summary.json"), summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a canonical chunk manifest from an external corpus inventory.")
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--paper-root", type=Path, default=None)
    parser.add_argument("--paper-id-key", default="paper_id")
    parser.add_argument("--path-key", default="path")
    parser.add_argument("--title-key", default="title")
    parser.add_argument("--text-key", default="")
    parser.add_argument("--chunk-size", type=int, default=4000)
    parser.add_argument("--overlap", type=int, default=400)
    args = parser.parse_args()
    build_chunk_manifest(
        inventory_path=args.inventory,
        output_path=args.output,
        paper_root=args.paper_root,
        paper_id_key=args.paper_id_key,
        path_key=args.path_key,
        title_key=args.title_key,
        text_key=args.text_key,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
    )


if __name__ == "__main__":
    main()

