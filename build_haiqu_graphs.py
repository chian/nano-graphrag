"""
Build per-group HAIQU knowledge graphs from data/haiqu_corpus/.

For each HAIQU group folder under data/haiqu_corpus/<group>/, this script:
  1. Loads domain_schemas/<group>.yaml as the typed extraction schema.
  2. Reads metadata.json to enumerate papers (data/haiqu_corpus/<group>/papers/<uuid>.md).
  3. Runs the typed entity/relationship extractor (3 LLM calls/chunk with
     self-refine on) over each paper.
  4. Merges entities and relationships into a single per-group NetworkX graph
     using graph_enrichment.graph_merger.
  5. Writes <output-dir>/<group>_graph.graphml plus a state file to allow
     resuming a partially-completed run.

The script intentionally mirrors the building blocks of
create_domain_typed_graph.py and enrich_graph_with_papers.py rather than
introducing new behaviour; the only delta is that this one ingests the
data/haiqu_corpus folder shape produced by seed_haiqu_corpus.py.

Usage:
    export LLM_API_KEY=...
    export LLM_ENDPOINT=https://apps-dev.inside.anl.gov/argoapi/v1
    python build_haiqu_graphs.py --model gpt-5.4-mini
    python build_haiqu_graphs.py --groups haiqu_biosensor_detection \
        --limit-papers 3                 # smoke test
    python build_haiqu_graphs.py --groups haiqu_aerosol_exposure haiqu_cognitive_impact \
        --model gpt-5.4-mini --output-dir haiqu_graphs/v1
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


def discover_groups(corpus_dir: Path) -> List[str]:
    """List <group> subdirectories that have a metadata.json + papers/."""
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
    """GraphML doesn't accept lists / arbitrary objects in attrs — flatten them."""
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
    """Chunk a paper, run the typed extractor on all chunks concurrently, return
    merged-by-name entity dict + relationship list scoped to this paper."""
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
                if data["importance_score"] > entities[name]["importance_score"]:
                    entities[name]["importance_score"] = data["importance_score"]
                for sc in data.get("source_chunks", []):
                    if sc not in entities[name]["source_chunks"]:
                        entities[name]["source_chunks"].append(sc)
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
    schema_name = metadata.get("schema") or group  # group name == schema name in current design
    papers_meta: List[dict] = metadata.get("papers", [])
    if limit_papers is not None:
        papers_meta = papers_meta[:limit_papers]

    print(f"\n{'='*72}\nGROUP: {group}\n{'='*72}")
    print(f"  question: {metadata.get('question','(none)')}")
    print(f"  schema:   {schema_name}")
    print(f"  papers:   {len(papers_meta)} (limit={limit_papers})")

    # Schema + extractor + LLM
    schema = load_domain_schema(schema_name)
    print(f"  entity_types:       {len(schema.entity_types)}")
    print(f"  relationship_types: {len(schema.relationship_types)}")

    llm = ArgoBridgeLLM(model=model)
    extractor = create_domain_extractor_from_schema(
        schema, llm_func=llm.call_async,
        num_refine_turns=refine_turns, self_refine=self_refine,
    )
    semaphore = asyncio.Semaphore(chunk_concurrency) if chunk_concurrency else None

    # Output paths + resume state — each group gets its own subdirectory
    group_out_dir = output_dir / group
    group_out_dir.mkdir(parents=True, exist_ok=True)
    out_graph = group_out_dir / f"{group}_graph.graphml"
    state_path = group_out_dir / f"{group}_state.json"
    state = load_state(state_path) if resume else {"completed_uuids": []}
    completed_uuids = set(state.get("completed_uuids", []))

    # Resume from existing graph if it's there
    if resume and out_graph.exists():
        graph = nx.read_graphml(out_graph)
        if not isinstance(graph, nx.DiGraph):
            graph = nx.DiGraph(graph)
        print(f"  resumed graph: {graph.number_of_nodes()} nodes, "
              f"{graph.number_of_edges()} edges, {len(completed_uuids)} papers done")
    else:
        graph = nx.DiGraph()

    succeeded = 0
    skipped_short = 0
    failed = 0
    attempted = 0

    for i, p in enumerate(papers_meta, 1):
        uuid = p.get("uuid", "")
        if not uuid:
            continue
        if uuid in completed_uuids:
            continue
        attempted += 1
        title = (p.get("title") or "(untitled)")[:80]
        path = group_dir / "papers" / p.get("content_file", f"{uuid}.md")
        if not path.exists():
            print(f"  [{i}/{len(papers_meta)}] MISSING file: {path}")
            failed += 1
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"  [{i}/{len(papers_meta)}] READ ERROR: {e}")
            failed += 1
            continue

        if len(text) < min_paper_length:
            print(f"  [{i}/{len(papers_meta)}] SKIP short ({len(text)} chars): {title}")
            skipped_short += 1
            completed_uuids.add(uuid)  # don't retry next run
            continue

        if max_paper_length is not None and len(text) > max_paper_length:
            print(f"  [{i}/{len(papers_meta)}] SKIP oversized ({len(text)} chars): {title}")
            skipped_short += 1
            completed_uuids.add(uuid)  # don't retry next run
            continue

        print(f"  [{i}/{len(papers_meta)}] {title} ({len(text)} chars)")
        try:
            entities, relationships = await extract_paper(
                text, uuid, extractor, chunk_size=chunk_size, overlap=overlap,
                semaphore=semaphore,
            )
        except Exception as e:
            print(f"    ! extraction failed: {e}")
            traceback.print_exc()
            failed += 1
            continue

        # Merge into the running per-group graph.
        graph, name_mapping = add_entities_to_graph(
            graph, entities, uuid,
            similarity_threshold=similarity_threshold, auto_merge=auto_merge,
        )
        graph = add_relationships_to_graph(graph, relationships, name_mapping, uuid)
        succeeded += 1
        completed_uuids.add(uuid)

        # Periodic checkpoint so a long run isn't all-or-nothing.
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

    # Final write
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

    elapsed = time.time() - t0
    print(f"\n  → wrote {out_graph}")
    print(f"  nodes: {graph.number_of_nodes()}  edges: {graph.number_of_edges()}")
    print(f"  ok={succeeded}  short={skipped_short}  failed={failed}  "
          f"elapsed={elapsed:.1f}s  llm_calls={llm.usage.get('calls', 0)}  "
          f"tokens={llm.usage.get('total_tokens', 0)}")
    return GroupResult(
        group=group,
        schema=schema_name,
        papers_attempted=attempted,
        papers_succeeded=succeeded,
        papers_skipped_short=skipped_short,
        papers_failed=failed,
        nodes=graph.number_of_nodes(),
        edges=graph.number_of_edges(),
        output_path=str(out_graph),
        elapsed_sec=elapsed,
    )


async def amain(args: argparse.Namespace) -> None:
    corpus_dir = Path(args.corpus_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.list_groups:
        for g in discover_groups(corpus_dir):
            md = load_group_metadata(corpus_dir, g)
            print(f"{g:<32} schema={md.get('schema','?'):<32} "
                  f"papers={len(md.get('papers',[]))}")
        return

    available = discover_groups(corpus_dir)
    if not available:
        sys.exit(f"No HAIQU groups found in {corpus_dir}")

    if args.groups:
        unknown = [g for g in args.groups if g not in available]
        if unknown:
            sys.exit(f"Unknown group(s): {unknown}. Available: {available}")
        groups = args.groups
    else:
        groups = available

    print(f"corpus_dir : {corpus_dir}")
    print(f"output_dir : {output_dir}")
    print(f"model      : {args.model}")
    print(f"groups     : {groups}")
    print(f"limit/grp  : {args.limit_papers}")

    results: List[GroupResult] = []
    for g in groups:
        try:
            r = await build_group(
                group=g,
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
            )
            results.append(r)
        except Exception as e:
            print(f"\n!! GROUP {g} FAILED: {e}")
            traceback.print_exc()

    # Summary
    summary_path = output_dir / "build_summary.json"
    summary = {
        "model": args.model,
        "corpus_dir": str(corpus_dir),
        "results": [r.__dict__ for r in results],
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n{'='*72}\nSUMMARY (→ {summary_path})\n{'='*72}")
    for r in results:
        print(f"  {r.group:<32} ok={r.papers_succeeded:>3}  "
              f"short={r.papers_skipped_short:>2}  fail={r.papers_failed:>2}  "
              f"nodes={r.nodes:>5}  edges={r.edges:>5}  "
              f"{r.elapsed_sec:>6.1f}s  → {Path(r.output_path).name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus-dir", default="data/haiqu_corpus",
                   help="Root of the seed_haiqu_corpus.py output (default: data/haiqu_corpus)")
    p.add_argument("--output-dir", default="haiqu_graphs",
                   help="Where to write per-group graphml + state (default: haiqu_graphs)")
    p.add_argument("--groups", nargs="*",
                   help="Only build these groups (default: all discovered)")
    p.add_argument("--list-groups", action="store_true",
                   help="List available groups and exit")
    p.add_argument("--model", default=os.getenv("LLM_MODEL", "gpt55"),
                   help="LLM model name (passed to ArgoBridgeLLM); default gpt55")
    p.add_argument("--limit-papers", type=int, default=None,
                   help="Max papers per group (for smoke tests)")
    p.add_argument("--min-paper-length", type=int, default=500,
                   help="Skip papers with fewer chars than this (default 500)")
    p.add_argument("--chunk-size", type=int, default=2000)
    p.add_argument("--overlap", type=int, default=200)
    p.add_argument("--refine-turns", type=int, default=1)
    p.add_argument("--no-self-refine", action="store_true",
                   help="Disable critique→refine loop (1 LLM call/chunk instead of 3)")
    p.add_argument("--similarity-threshold", type=float, default=0.85,
                   help="Entity-merge similarity threshold (0..1)")
    p.add_argument("--no-auto-merge", action="store_true",
                   help="Disable automatic entity merging")
    p.add_argument("--no-resume", action="store_true",
                   help="Don't reload prior <group>_state.json / partial graph")
    p.add_argument("--save-every", type=int, default=10,
                   help="Checkpoint every N successful papers (default 10)")
    p.add_argument("--chunk-concurrency", type=int, default=None,
                   help="Max concurrent chunk LLM calls per paper (default: unlimited)")
    p.add_argument("--max-paper-length", type=int, default=None,
                   help="Skip papers longer than this many chars, e.g. 500000 to drop RSS feeds (default: unlimited)")
    args = p.parse_args()

    # Quiet nano-graphrag debug noise unless the user already cranked it up.
    if "--verbose" not in sys.argv:
        logging.getLogger("nano-graphrag").setLevel(logging.WARNING)

    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
