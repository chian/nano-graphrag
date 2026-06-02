from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

import networkx as nx


def read_json_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return payload["records"]
    raise ValueError(f"Unsupported inventory format for {path}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True))
        handle.write("\n")


def chunk_text_with_offsets(text: str, chunk_size: int, overlap: int) -> list[tuple[int, int, str]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[tuple[int, int, str]] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end]
        chunks.append((start, end, chunk))
        if end >= text_len:
            break
        start = end - overlap
    return chunks


def make_chunk_id(paper_id: str, chunk_idx: int, start: int, end: int, chunk_text: str) -> str:
    digest = hashlib.sha1(chunk_text.encode("utf-8")).hexdigest()[:12]
    return f"{paper_id}:{chunk_idx}:{start}:{end}:{digest}"


def load_text_for_record(
    record: dict[str, Any],
    *,
    paper_root: Path | None,
    text_key: str,
    path_key: str,
) -> tuple[str, str]:
    if text_key and record.get(text_key):
        return str(record.get(text_key)), ""
    rel_path = str(record.get(path_key, ""))
    if not rel_path:
        raise ValueError(f"Inventory row missing text and path keys: {record}")
    source_path = (paper_root / rel_path) if paper_root else Path(rel_path)
    return source_path.read_text(encoding="utf-8"), str(source_path)


def shard_ranges(total: int, shard_count: int) -> Iterator[tuple[int, int]]:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    base = total // shard_count
    remainder = total % shard_count
    start = 0
    for idx in range(shard_count):
        size = base + (1 if idx < remainder else 0)
        end = start + size
        yield start, end
        start = end


def group_in_order(items: list[Path], group_size: int) -> list[list[Path]]:
    if group_size <= 0:
        raise ValueError("group_size must be positive")
    return [items[i:i + group_size] for i in range(0, len(items), group_size)]


def serialize_graph_for_graphml(graph: nx.DiGraph) -> nx.DiGraph:
    graph = graph.copy()
    for node in graph.nodes():
        for key, value in list(graph.nodes[node].items()):
            if isinstance(value, list):
                graph.nodes[node][key] = ",".join(str(x) for x in value)
            elif not isinstance(value, (str, int, float, bool, type(None))):
                graph.nodes[node][key] = str(value)
    for src, tgt in graph.edges():
        for key, value in list(graph.edges[src, tgt].items()):
            if isinstance(value, list):
                graph.edges[src, tgt][key] = ",".join(str(x) for x in value)
            elif not isinstance(value, (str, int, float, bool, type(None))):
                graph.edges[src, tgt][key] = str(value)
    return graph


def save_graph(path: Path, graph: nx.DiGraph) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(serialize_graph_for_graphml(graph), path)

