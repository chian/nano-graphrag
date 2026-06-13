"""Typed extraction + graph enrichment helpers.

Thin wrappers around the existing domain extractor and graph_enrichment
mergers so the schema-synthesis and answer-loop code share one code path.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from graph_enrichment.graph_merger import (
    add_entities_to_graph,
    add_relationships_to_graph,
)
from nano_graphrag.graph_slots import get_salience_score, set_salience_score


def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> List[str]:
    """Split text into overlapping character chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


async def extract_from_text(
    extractor,
    text: str,
    source_id: str,
    *,
    chunk_size: int = 2000,
    overlap: int = 200,
    concurrency: int = 1,
) -> Tuple[Dict[str, dict], List[dict]]:
    """Run the typed extractor over chunked text.

    Returns (entities_by_name, relationships). Entities are merged across
    chunks by name, keeping the highest salience and accumulating source
    chunk ids; relationships are collected with their source chunk.
    """
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")

    entities: Dict[str, dict] = {}
    relationships: List[dict] = []
    semaphore = asyncio.Semaphore(concurrency)

    async def extract_chunk(idx: int, chunk: str):
        chunk_id = f"{source_id}_chunk_{idx}"
        try:
            async with semaphore:
                prediction = await extractor.forward(chunk)
        except Exception as exc:  # noqa: BLE001 - one bad chunk shouldn't abort
            print(f"    [extract] chunk {idx} failed: {exc}")
            return idx, chunk_id, [], []

        return idx, chunk_id, prediction.entities, prediction.relationships

    chunk_results = await asyncio.gather(
        *(
            extract_chunk(idx, chunk)
            for idx, chunk in enumerate(chunk_text(text, chunk_size, overlap))
        )
    )

    for _, chunk_id, chunk_entities, chunk_relationships in sorted(chunk_results):
        for entity in chunk_entities:
            ent = entity.to_dict()
            name = ent.get("entity_name")
            if not name:
                continue
            if name not in entities:
                ent["source_chunks"] = [chunk_id]
                entities[name] = ent
            else:
                existing = entities[name]
                if get_salience_score(ent, 0.0) > get_salience_score(existing, 0.0):
                    set_salience_score(existing, get_salience_score(ent, 0.0))
                if chunk_id not in existing["source_chunks"]:
                    existing["source_chunks"].append(chunk_id)

        for rel in chunk_relationships:
            rel_dict = rel.to_dict()
            rel_dict["source_chunk"] = chunk_id
            relationships.append(rel_dict)

    return entities, relationships


def enrich_graph(
    graph: nx.DiGraph,
    entities: Dict[str, dict],
    relationships: List[dict],
    source_id: str,
    *,
    similarity_threshold: float = 0.85,
    auto_merge: bool = True,
) -> nx.DiGraph:
    """Merge extracted entities/relationships into the graph in place-ish.

    Returns the updated graph (the mergers may return a new object).
    """
    graph, name_mapping = add_entities_to_graph(
        graph,
        entities,
        source_id,
        similarity_threshold=similarity_threshold,
        auto_merge=auto_merge,
    )
    graph = add_relationships_to_graph(graph, relationships, name_mapping, source_id)
    return graph


def schema_type_coverage(
    schema_entity_types: List[str],
    entities: Dict[str, dict],
) -> Dict[str, Any]:
    """Compute how well a set of extractions fit a schema's entity types."""
    allowed = set(schema_entity_types)
    used: Dict[str, int] = {}
    off_schema = 0
    for ent in entities.values():
        etype = ent.get("entity_type", "UNKNOWN")
        used[etype] = used.get(etype, 0) + 1
        if etype not in allowed:
            off_schema += 1
    total = max(1, len(entities))
    return {
        "n_entities": len(entities),
        "types_used": used,
        "off_schema_entities": off_schema,
        "off_schema_rate": round(off_schema / total, 3),
        "schema_types_hit": sorted(set(used) & allowed),
        "schema_types_unused": sorted(allowed - set(used)),
    }
