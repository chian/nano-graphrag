from __future__ import annotations

import argparse
import asyncio
import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gasl.llm import ArgoBridgeLLM
from graph_enrichment.entity_merger import calculate_similarity, merge_entities
from hpc.common import save_graph, write_json, write_jsonl


def generate_candidates(
    graph: nx.DiGraph,
    *,
    similarity_threshold: float,
    same_type_only: bool,
    max_candidates: int | None,
) -> list[dict[str, Any]]:
    nodes = sorted(graph.nodes())
    candidates: list[dict[str, Any]] = []
    for left, right in combinations(nodes, 2):
        left_attrs = graph.nodes[left]
        right_attrs = graph.nodes[right]
        if same_type_only and left_attrs.get("entity_type") != right_attrs.get("entity_type"):
            continue
        similarity = calculate_similarity(left, right)
        if similarity < similarity_threshold:
            continue
        candidates.append(
            {
                "left": left,
                "right": right,
                "similarity": similarity,
                "left_type": left_attrs.get("entity_type", ""),
                "right_type": right_attrs.get("entity_type", ""),
            }
        )
    candidates.sort(key=lambda row: row["similarity"], reverse=True)
    return candidates[:max_candidates] if max_candidates is not None else candidates


def _merge_two_nodes(graph: nx.DiGraph, keep: str, drop: str) -> nx.DiGraph:
    merged = merge_entities(dict(graph.nodes[keep]), dict(graph.nodes[drop]), source_uuid=f"llm_review:{drop}")
    for key, value in merged.items():
        graph.nodes[keep][key] = value
    for src, _, attrs in list(graph.in_edges(drop, data=True)):
        if src == keep:
            continue
        if not graph.has_edge(src, keep):
            graph.add_edge(src, keep, **dict(attrs))
    for _, tgt, attrs in list(graph.out_edges(drop, data=True)):
        if tgt == keep:
            continue
        if not graph.has_edge(keep, tgt):
            graph.add_edge(keep, tgt, **dict(attrs))
    graph.remove_node(drop)
    return graph


async def review_candidates(
    *,
    graph_path: Path,
    out_dir: Path,
    model: str,
    similarity_threshold: float,
    same_type_only: bool,
    max_candidates: int | None,
    apply_merges: bool,
) -> dict:
    graph = nx.read_graphml(graph_path)
    candidates = generate_candidates(
        graph,
        similarity_threshold=similarity_threshold,
        same_type_only=same_type_only,
        max_candidates=max_candidates,
    )
    llm = ArgoBridgeLLM(model=model)
    decisions: list[dict[str, Any]] = []
    for candidate in candidates:
        left = candidate["left"]
        right = candidate["right"]
        prompt = (
            "Decide if these two graph nodes refer to the same real-world entity.\n"
            "Return strict JSON with keys merge (boolean), confidence (0..1), reason (string).\n\n"
            f"Node A name: {left}\n"
            f"Node A type: {graph.nodes[left].get('entity_type', '')}\n"
            f"Node A description: {graph.nodes[left].get('description', '')}\n\n"
            f"Node B name: {right}\n"
            f"Node B type: {graph.nodes[right].get('entity_type', '')}\n"
            f"Node B description: {graph.nodes[right].get('description', '')}\n"
        )
        raw = await llm.call_async(prompt)
        parsed = json.loads(raw)
        decision = {**candidate, **parsed}
        decisions.append(decision)
        if apply_merges and parsed.get("merge") is True and left in graph.nodes and right in graph.nodes:
            graph = _merge_two_nodes(graph, left, right)
    out_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = out_dir / "merge_decisions.jsonl"
    write_jsonl(decisions_path, decisions)
    reviewed_graph_path = out_dir / "reviewed_graph.graphml"
    save_graph(reviewed_graph_path, graph)
    summary = {
        "graph_path": str(graph_path),
        "reviewed_graph_path": str(reviewed_graph_path),
        "decisions_path": str(decisions_path),
        "candidates": len(candidates),
        "decisions": len(decisions),
        "applied_merges": sum(1 for row in decisions if row.get("merge") is True),
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an LLM semantic merge review over structured graph-node candidates.")
    parser.add_argument("graph_path", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--similarity-threshold", type=float, default=0.92)
    parser.add_argument("--allow-cross-type", action="store_true")
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--no-apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        review_candidates(
            graph_path=args.graph_path,
            out_dir=args.out_dir,
            model=args.model,
            similarity_threshold=args.similarity_threshold,
            same_type_only=not args.allow_cross_type,
            max_candidates=args.max_candidates,
            apply_merges=not args.no_apply,
        )
    )


if __name__ == "__main__":
    main()
