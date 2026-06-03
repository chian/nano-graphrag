from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from graph_enrichment.graph_merger import merge_graphs
from hpc.common import group_in_order, save_graph, write_json


def merge_graph_group(
    *,
    graph_paths: list[Path],
    similarity_threshold: float,
    auto_merge: bool,
) -> nx.DiGraph:
    merged = nx.DiGraph()
    for graph_path in graph_paths:
        graph = nx.read_graphml(graph_path)
        for node in graph.nodes():
            graph.nodes[node].setdefault("entity_name", str(node))
        merged = merge_graphs(
            merged,
            graph,
            source_uuid=graph_path.stem,
            similarity_threshold=similarity_threshold,
            auto_merge=auto_merge,
        )
    return merged


def merge_hierarchy(
    *,
    graph_paths: list[Path],
    out_dir: Path,
    fan_in: int,
    similarity_threshold: float,
    auto_merge: bool,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    current = sorted(graph_paths)
    stages: list[dict] = []
    stage_idx = 0
    while len(current) > 1:
        stage_dir = out_dir / f"stage_{stage_idx:02d}"
        stage_dir.mkdir(parents=True, exist_ok=True)
        grouped = group_in_order(current, fan_in)
        next_stage: list[Path] = []
        stage_summary = {"stage": stage_idx, "inputs": len(current), "groups": []}
        for group_idx, group in enumerate(grouped):
            merged = merge_graph_group(
                graph_paths=group,
                similarity_threshold=similarity_threshold,
                auto_merge=auto_merge,
            )
            group_path = stage_dir / f"group_{group_idx:03d}.graphml"
            save_graph(group_path, merged)
            next_stage.append(group_path)
            stage_summary["groups"].append(
                {
                    "group_idx": group_idx,
                    "inputs": [str(path) for path in group],
                    "output": str(group_path),
                    "nodes": merged.number_of_nodes(),
                    "edges": merged.number_of_edges(),
                }
            )
        write_json(stage_dir / "summary.json", stage_summary)
        stages.append(stage_summary)
        current = next_stage
        stage_idx += 1
    final_path = out_dir / "final_graph.graphml"
    if not current:
        save_graph(final_path, nx.DiGraph())
    else:
        shutil.copyfile(current[0], final_path)
    summary = {
        "fan_in": fan_in,
        "stages": stages,
        "final_graph_path": str(final_path),
    }
    write_json(out_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Hierarchically merge graph shards in deterministic order.")
    parser.add_argument("graphs", nargs="+", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--fan-in", type=int, default=10)
    parser.add_argument("--similarity-threshold", type=float, default=0.85)
    parser.add_argument("--no-auto-merge", action="store_true")
    args = parser.parse_args()
    merge_hierarchy(
        graph_paths=args.graphs,
        out_dir=args.out_dir,
        fan_in=args.fan_in,
        similarity_threshold=args.similarity_threshold,
        auto_merge=not args.no_auto_merge,
    )


if __name__ == "__main__":
    main()
