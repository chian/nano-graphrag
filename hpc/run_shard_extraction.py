from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import networkx as nx

from domain_schemas.schema_loader import load_domain_schema
from gasl.llm import ArgoBridgeLLM
from graph_enrichment.graph_merger import add_entities_to_graph, add_relationships_to_graph
from hpc.common import append_jsonl, read_json_records, save_graph, write_json
from nano_graphrag.entity_extraction.typed_module import create_domain_extractor_from_schema


def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {"completed_chunk_ids": []}


def _save_state(state_path: Path, state: dict) -> None:
    write_json(state_path, state)


async def run_shard(
    *,
    shard_path: Path,
    output_dir: Path,
    schema_name: str,
    model: str,
    refine_turns: int,
    self_refine: bool,
    similarity_threshold: float,
    auto_merge: bool,
    save_every: int,
    resume: bool,
) -> dict:
    rows = read_json_records(shard_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "state.json"
    entities_path = output_dir / "entities.jsonl"
    relationships_path = output_dir / "relationships.jsonl"
    chunk_results_path = output_dir / "chunk_results.jsonl"
    graph_path = output_dir / "local_graph.graphml"
    state = _load_state(state_path) if resume else {"completed_chunk_ids": []}
    completed = set(state.get("completed_chunk_ids", []))
    graph = nx.read_graphml(graph_path) if resume and graph_path.exists() else nx.DiGraph()

    schema = load_domain_schema(schema_name)
    llm = ArgoBridgeLLM(model=model)
    extractor = create_domain_extractor_from_schema(
        schema,
        llm_func=llm.call_async,
        num_refine_turns=refine_turns,
        self_refine=self_refine,
    )

    started = time.time()
    processed = 0
    for idx, row in enumerate(rows, start=1):
        chunk_id = row["chunk_id"]
        if chunk_id in completed:
            continue
        prediction = await extractor.forward(row["chunk_text"])
        entities = {}
        for entity in prediction.entities:
            entity_dict = entity.to_dict()
            entity_dict["source_chunks"] = [chunk_id]
            entities[entity_dict["entity_name"]] = entity_dict
            append_jsonl(
                entities_path,
                {
                    "chunk_id": chunk_id,
                    "paper_id": row["paper_id"],
                    **entity_dict,
                },
            )
        relationships = []
        for rel in prediction.relationships:
            rel_dict = rel.to_dict()
            rel_dict["source_chunk"] = chunk_id
            relationships.append(rel_dict)
            append_jsonl(
                relationships_path,
                {
                    "chunk_id": chunk_id,
                    "paper_id": row["paper_id"],
                    **rel_dict,
                },
            )
        graph, name_mapping = add_entities_to_graph(
            graph,
            entities,
            source_uuid=chunk_id,
            similarity_threshold=similarity_threshold,
            auto_merge=auto_merge,
        )
        graph = add_relationships_to_graph(
            graph,
            relationships,
            name_mapping,
            source_uuid=chunk_id,
        )
        append_jsonl(
            chunk_results_path,
            {
                "chunk_id": chunk_id,
                "paper_id": row["paper_id"],
                "entities": len(entities),
                "relationships": len(relationships),
            },
        )
        completed.add(chunk_id)
        processed += 1
        if save_every and processed % save_every == 0:
            save_graph(graph_path, graph)
            _save_state(
                state_path,
                {
                    "completed_chunk_ids": sorted(completed),
                    "processed": processed,
                    "total": len(rows),
                    "last_chunk_id": chunk_id,
                },
            )

    save_graph(graph_path, graph)
    summary = {
        "shard_path": str(shard_path),
        "graph_path": str(graph_path),
        "entities_path": str(entities_path),
        "relationships_path": str(relationships_path),
        "chunk_results_path": str(chunk_results_path),
        "chunks_total": len(rows),
        "chunks_completed": len(completed),
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "elapsed_sec": round(time.time() - started, 2),
    }
    _save_state(
        state_path,
        {
            "completed_chunk_ids": sorted(completed),
            "processed": processed,
            "total": len(rows),
            "summary": summary,
        },
    )
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run typed extraction over a precomputed shard manifest.")
    parser.add_argument("shard_path", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--refine-turns", type=int, default=1)
    parser.add_argument("--self-refine", action="store_true")
    parser.add_argument("--similarity-threshold", type=float, default=0.85)
    parser.add_argument("--no-auto-merge", action="store_true")
    parser.add_argument("--save-every", type=int, default=50)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run_shard(
            shard_path=args.shard_path,
            output_dir=args.output_dir,
            schema_name=args.schema,
            model=args.model,
            refine_turns=args.refine_turns,
            self_refine=args.self_refine,
            similarity_threshold=args.similarity_threshold,
            auto_merge=not args.no_auto_merge,
            save_every=args.save_every,
            resume=not args.no_resume,
        )
    )


if __name__ == "__main__":
    main()

