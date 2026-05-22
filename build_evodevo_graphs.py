"""
Build per-group evo-devo knowledge graphs from data/evo_devo_corpus/.

Mirrors build_haiqu_graphs.py exactly — same extractor, merger, and
checkpoint logic — just pointed at the evo-devo corpus and schemas.

Usage:
    export LLM_API_KEY=...
    export LLM_ENDPOINT=https://apps-dev.inside.anl.gov/argoapi/v1
    python build_evodevo_graphs.py
    python build_evodevo_graphs.py --groups kg_symmetry_locomotion_manoeuvrability
    python build_evodevo_graphs.py --model gpt-5.4-mini --output-dir evo_devo_graphs/v1
    python build_evodevo_graphs.py --limit-papers 3 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from domain_schemas.schema_loader import load_domain_schema
from nano_graphrag.entity_extraction.typed_module import (
    create_domain_extractor_from_schema,
)
from graph_enrichment.graph_merger import (
    add_entities_to_graph,
    add_relationships_to_graph,
)
from create_domain_typed_graph import chunk_text, extract_from_chunk
from gasl.llm import ArgoBridgeLLM
from graph_metadata import metadata_from_schema_and_corpus, save_graph_metadata
from nano_graphrag.graph_slots import get_salience_score, set_salience_score

logging.basicConfig(level=logging.WARNING)


@dataclass
class GroupResult:
    group: str
    schema: str
    papers_attempted: int
    papers_succeeded: int
    papers_skipped_short: int
    papers_failed: int
    nodes: int
    edges: int
    output_path: str
    elapsed_sec: float


CORPUS_DIR = REPO_ROOT / "data" / "evo_devo_corpus"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "evo_devo_graphs"


def discover_groups(corpus_dir: Path) -> List[str]:
    groups = []
    for p in sorted(corpus_dir.iterdir()):
        if not p.is_dir():
            continue
        if (p / "metadata.json").exists() and (p / "papers").is_dir():
            groups.append(p.name)
    return groups


def load_group_metadata(corpus_dir: Path, group: str) -> dict:
    with open(corpus_dir / group / "metadata.json", "r", encoding="utf-8") as f:
        return json.load(f)


def serialize_graph_for_graphml(g: nx.DiGraph) -> nx.DiGraph:
    g = g.copy()
    for node in g.nodes():
        for k, v in list(g.nodes[node].items()):
            if isinstance(v, list):
                g.nodes[node][k] = ",".join(str(x) for x in v)
            elif not isinstance(v, (str, int, float, bool, type(None))):
                g.nodes[node][k] = str(v)
    for src, tgt in g.edges():
        for k, v in list(g.edges[src, tgt].items()):
            if isinstance(v, list):
                g.edges[src, tgt][k] = ",".join(str(x) for x in v)
            elif not isinstance(v, (str, int, float, bool, type(None))):
                g.edges[src, tgt][k] = str(v)
    return g


def save_graph(g: nx.DiGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(serialize_graph_for_graphml(g), path)


def load_state(state_path: Path) -> dict:
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_uuids": []}


def save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    tmp.replace(state_path)


async def extract_paper(
    text: str,
    paper_uuid: str,
    extractor,
    chunk_size: int,
    overlap: int,
    semaphore: Optional[asyncio.Semaphore] = None,
) -> Tuple[Dict[str, Dict], List[Dict]]:
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)

    async def _extract_one(i: int, chunk: str):
        chunk_id = f"{paper_uuid}_chunk_{i}"
        local_entities: Dict[str, Dict] = {}
        local_rels: List[Dict] = []
        try:
            if semaphore is not None:
                async with semaphore:
                    await extract_from_chunk(chunk, chunk_id, extractor, local_entities, local_rels)
            else:
                await extract_from_chunk(chunk, chunk_id, extractor, local_entities, local_rels)
        except Exception as e:
            print(f"    ! chunk {i} failed: {e}")
        return local_entities, local_rels

    results = await asyncio.gather(*[_extract_one(i, c) for i, c in enumerate(chunks)])
    entities: Dict[str, Dict] = {}
    relationships: List[Dict] = []
    for chunk_entities, chunk_rels in results:
        for name, data in chunk_entities.items():
            if name not in entities:
                entities[name] = data
            else:
                existing_desc = entities[name].get("description", "")
                new_desc = data.get("description", "")
                if new_desc and new_desc not in existing_desc:
                    entities[name]["description"] = existing_desc + " | " + new_desc
        relationships.extend(chunk_rels)
    return entities, relationships


async def build_group(
    group: str,
    corpus_dir: Path,
    output_dir: Path,
    model: str,
    chunk_size: int,
    overlap: int,
    refine_turns: int,
    self_refine: bool,
    similarity_threshold: float,
    auto_merge: bool,
    limit_papers: Optional[int],
    min_paper_length: int,
    resume: bool,
    save_every: int,
    chunk_concurrency: Optional[int] = None,
    max_paper_length: Optional[int] = None,
) -> GroupResult:
    t0 = time.time()
    group_dir = corpus_dir / group
    metadata = load_group_metadata(corpus_dir, group)
    schema_name = metadata.get("schema") or group
    papers_meta: List[dict] = metadata.get("papers", [])
    if limit_papers is not None:
        papers_meta = papers_meta[:limit_papers]

    print(f"\n{'='*72}\nGROUP: {group}\n{'='*72}")
    print(f"  question: {metadata.get('question','(none)')}")
    print(f"  schema:   {schema_name}")
    print(f"  papers:   {len(papers_meta)} (limit={limit_papers})")

    schema = load_domain_schema(schema_name)
    print(f"  entity_types:       {len(schema.entity_types)}")
    print(f"  relationship_types: {len(schema.relationship_types)}")

    llm = ArgoBridgeLLM(model=model)
    extractor = create_domain_extractor_from_schema(
        schema, llm_func=llm.call_async,
        num_refine_turns=refine_turns, self_refine=self_refine,
    )
    semaphore = asyncio.Semaphore(chunk_concurrency) if chunk_concurrency else None

    group_out_dir = output_dir / group
    group_out_dir.mkdir(parents=True, exist_ok=True)
    out_graph = group_out_dir / f"{group}_graph.graphml"
    state_path = group_out_dir / f"{group}_state.json"
    state = load_state(state_path) if resume else {"completed_uuids": []}
    completed_uuids = set(state.get("completed_uuids", []))

    if out_graph.exists() and resume and completed_uuids:
        graph = nx.read_graphml(out_graph)
        print(f"  resumed: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges, "
              f"{len(completed_uuids)} papers already done")
    else:
        graph = nx.DiGraph()

    attempted = succeeded = failed = skipped_short = 0

    for paper in papers_meta:
        uuid = paper.get("uuid", "")
        if uuid in completed_uuids:
            continue

        content_file = group_dir / "papers" / paper.get("content_file", "")
        if not content_file.exists():
            failed += 1
            continue

        text = content_file.read_text(encoding="utf-8", errors="replace")
        if len(text) < min_paper_length:
            skipped_short += 1
            continue
        if max_paper_length and len(text) > max_paper_length:
            text = text[:max_paper_length]

        attempted += 1
        try:
            entities, relationships = await extract_paper(
                text, uuid, extractor, chunk_size, overlap, semaphore
            )
            graph, name_mapping = add_entities_to_graph(
                graph, entities, uuid,
                similarity_threshold=similarity_threshold, auto_merge=auto_merge,
            )
            graph = add_relationships_to_graph(graph, relationships, name_mapping, uuid)
            succeeded += 1
            completed_uuids.add(uuid)
        except Exception as e:
            failed += 1
            print(f"  ! paper {uuid[:8]} failed: {e}")
            traceback.print_exc()

        if save_every and (succeeded % save_every == 0):
            save_graph(graph, out_graph)
            save_state(state_path, {
                "completed_uuids": sorted(completed_uuids),
                "model": model,
                "schema": schema_name,
                "last_checkpoint_paper": uuid,
            })
            print(f"    checkpoint: {graph.number_of_nodes()} nodes, "
                  f"{graph.number_of_edges()} edges, {len(completed_uuids)} papers done")

    save_graph(graph, out_graph)
    save_state(state_path, {
        "completed_uuids": sorted(completed_uuids),
        "model": model,
        "schema": schema_name,
        "completed": True,
        "papers_succeeded": succeeded,
        "papers_failed": failed,
        "papers_skipped_short": skipped_short,
    })

    try:
        gm = metadata_from_schema_and_corpus(
            kg_id=group,
            kg_version=output_dir.name,
            schema=schema,
            corpus_metadata=metadata,
        )
        meta_path = save_graph_metadata(group_out_dir, gm)
        print(f"  → wrote {meta_path.name}")
    except Exception as exc:
        print(f"  ! graph_metadata write failed (non-fatal): {exc}")

    elapsed = time.time() - t0
    print(f"\n  → wrote {out_graph}")
    print(f"  nodes: {graph.number_of_nodes()}  edges: {graph.number_of_edges()}")
    print(f"  ok={succeeded}  short={skipped_short}  failed={failed}  elapsed={elapsed:.1f}s")
    return GroupResult(
        group=group, schema=schema_name,
        papers_attempted=attempted, papers_succeeded=succeeded,
        papers_skipped_short=skipped_short, papers_failed=failed,
        nodes=graph.number_of_nodes(), edges=graph.number_of_edges(),
        output_path=str(out_graph), elapsed_sec=elapsed,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="gpt-4o",
                   help="LLM model name (default: gpt-4o)")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR / "v1"),
                   help="Output directory (default: evo_devo_graphs/v1)")
    p.add_argument("--corpus-dir", default=str(CORPUS_DIR),
                   help="Corpus directory (default: data/evo_devo_corpus)")
    p.add_argument("--groups", nargs="*",
                   help="Only build these groups (default: all)")
    p.add_argument("--limit-papers", type=int,
                   help="Max papers per group (default: all)")
    p.add_argument("--chunk-size", type=int, default=1200)
    p.add_argument("--overlap", type=int, default=100)
    p.add_argument("--refine-turns", type=int, default=1)
    p.add_argument("--no-self-refine", action="store_true")
    p.add_argument("--similarity-threshold", type=float, default=0.85)
    p.add_argument("--no-auto-merge", action="store_true")
    p.add_argument("--min-paper-length", type=int, default=500)
    p.add_argument("--max-paper-length", type=int, default=None)
    p.add_argument("--no-resume", action="store_true")
    p.add_argument("--save-every", type=int, default=10)
    p.add_argument("--chunk-concurrency", type=int, default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="List groups and paper counts without building")
    args = p.parse_args()

    corpus_dir = Path(args.corpus_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_groups = discover_groups(corpus_dir)
    groups_to_run = all_groups
    if args.groups:
        names = set(args.groups)
        groups_to_run = [g for g in all_groups if g in names]
        if not groups_to_run:
            sys.exit(f"ERROR: no groups matched: {args.groups}")

    print(f"corpus_dir : {corpus_dir}")
    print(f"output_dir : {output_dir}")
    print(f"model      : {args.model}")
    print(f"groups     : {groups_to_run}")
    print(f"limit/grp  : {args.limit_papers}")

    if args.dry_run:
        for g in groups_to_run:
            meta = load_group_metadata(corpus_dir, g)
            print(f"  {g}: {meta.get('paper_count', 0)} papers, schema={meta.get('schema', g)}")
        return

    results: List[GroupResult] = []
    for group in groups_to_run:
        try:
            result = asyncio.run(build_group(
                group=group,
                corpus_dir=corpus_dir,
                output_dir=output_dir,
                model=args.model,
                chunk_size=args.chunk_size,
                overlap=args.overlap,
                refine_turns=args.refine_turns,
                self_refine=not args.no_self_refine,
                similarity_threshold=args.similarity_threshold,
                auto_merge=not args.no_auto_merge,
                limit_papers=args.limit_papers,
                min_paper_length=args.min_paper_length,
                resume=not args.no_resume,
                save_every=args.save_every,
                chunk_concurrency=args.chunk_concurrency,
                max_paper_length=args.max_paper_length,
            ))
            results.append(result)
        except Exception as e:
            print(f"\nFATAL error in group {group}: {e}")
            traceback.print_exc()

    summary_path = output_dir / "build_summary.json"
    summary = [
        {"group": r.group, "schema": r.schema,
         "papers_succeeded": r.papers_succeeded, "papers_failed": r.papers_failed,
         "nodes": r.nodes, "edges": r.edges, "elapsed_sec": r.elapsed_sec}
        for r in results
    ]
    summary_path.write_text(json.dumps(summary, indent=2))

    print(f"\n{'='*72}")
    print(f"BUILD COMPLETE — {len(results)} groups")
    print(f"{'='*72}")
    print(f"{'group':<45} {'ok':>5} {'skip':>5} {'fail':>5} {'nodes':>6} {'edges':>6} {'sec':>6}")
    for r in results:
        print(f"{r.group:<45} {r.papers_succeeded:>5} {r.papers_skipped_short:>5} "
              f"{r.papers_failed:>5} {r.nodes:>6} {r.edges:>6} {r.elapsed_sec:>6.1f}s  "
              f"→ {Path(r.output_path).name}")


if __name__ == "__main__":
    main()
