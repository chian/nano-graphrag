"""
Build per-group knowledge graphs from a typed paper corpus.

For each group folder under <corpus-dir>/<group>/, this script:
  1. Loads domain_schemas/<group>.yaml as the typed extraction schema.
  2. Reads metadata.json to enumerate papers in <group>/papers/.
  3. Runs the typed entity/relationship extractor (3 LLM calls/chunk with
     self-refine on) over each paper.
  4. Merges entities and relationships into a single per-group NetworkX graph
     using graph_enrichment.graph_merger.
  5. Writes <output-dir>/<group>_graph.graphml plus a state file to allow
     resuming a partially-completed run.

The script intentionally mirrors the building blocks of create_domain_typed_graph.py
and enrich_graph_with_papers.py rather than introducing a second extraction stack.
It ingests the corpus folder shape produced by the seed scripts:

  <corpus-dir>/<group>/metadata.json
  <corpus-dir>/<group>/papers/<paper>.md

Usage:
    export LLM_API_KEY=...
    export LLM_ENDPOINT=https://apps-dev.inside.anl.gov/argoapi/v1

    python build_haiqu_graphs.py --model gpt-5.4-mini
    python build_haiqu_graphs.py \\
        --corpus-dir data/my_corpus \\
        --output-dir graphs/my_run \\
        --groups my_group \\
        --chunk-size 1200 \\
        --overlap 100 \\
        --transport direct
    python build_haiqu_graphs.py --groups haiqu_biosensor_detection \\
        --limit-papers 3                 # smoke test
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple
from nano_graphrag.graph_slots import get_salience_score, set_salience_score

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
    merge_graphs,
)
from create_domain_typed_graph import chunk_text, extract_from_chunk
from gasl.llm import ArgoBridgeLLM
from graph_metadata import metadata_from_schema_and_corpus, save_graph_metadata


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


@dataclass
class PaperExtractionResult:
    index: int
    uuid: str
    title: str
    status: str
    text_length: int
    entities: Dict[str, Dict]
    relationships: List[Dict]
    error: Optional[str] = None


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
    tmp = path.with_suffix(path.suffix + ".tmp")
    nx.write_graphml(serialize_graph_for_graphml(g), tmp)
    tmp.replace(path)


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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_progress_state(
    *,
    checkpoint_completed_uuids: set[str],
    model: str,
    schema_name: str,
    last_checkpoint_paper: Optional[str],
    progress: Optional[dict] = None,
    final_stats: Optional[dict] = None,
) -> dict:
    state = {
        "completed_uuids": sorted(checkpoint_completed_uuids),
        "model": model,
        "schema": schema_name,
    }
    if last_checkpoint_paper:
        state["last_checkpoint_paper"] = last_checkpoint_paper
    if progress is not None:
        state["progress"] = progress
    if final_stats is not None:
        state.update(final_stats)
    return state


def batched(items: List[Tuple[int, dict]], batch_size: int) -> List[List[Tuple[int, dict]]]:
    batch_size = max(1, batch_size)
    return [items[i:i + batch_size] for i in range(0, len(items), batch_size)]


def compile_metadata_exclude_regex(patterns: Optional[List[str]]) -> List[re.Pattern]:
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns or []]


def metadata_exclude_match(paper_meta: dict, patterns: List[re.Pattern]) -> Optional[str]:
    if not patterns:
        return None

    haystack = "\n".join(
        str(paper_meta.get(key) or "")
        for key in ("title", "url", "description")
    )
    for pattern in patterns:
        if pattern.search(haystack):
            return pattern.pattern
    return None


async def extract_paper(
    text: str,
    paper_uuid: str,
    extractor,
    chunk_size: int,
    overlap: int,
    semaphore: Optional[asyncio.Semaphore] = None,
    completion_threshold: float = 1.0,
    straggler_idle_sec: float = 0.0,
) -> Tuple[Dict[str, Dict], List[Dict]]:
    """Chunk a paper, run the typed extractor on all chunks concurrently, return
    merged-by-name entity dict + relationship list scoped to this paper."""
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    results: List[Optional[Tuple[Dict[str, Dict], List[Dict]]]] = [None] * len(chunks)
    last_completion = time.monotonic()

    async def _extract_one(i: int, chunk: str):
        nonlocal last_completion
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
        last_completion = time.monotonic()
        results[i] = (local_entities, local_rels)

    tasks = [asyncio.create_task(_extract_one(i, chunk)) for i, chunk in enumerate(chunks)]
    if tasks:
        if completion_threshold < 1.0 and straggler_idle_sec > 0:
            threshold_count = max(1, math.ceil(len(tasks) * completion_threshold))
            poll_interval = min(30.0, max(1.0, straggler_idle_sec / 20.0))
            while True:
                done_count = sum(1 for task in tasks if task.done())
                if done_count >= len(tasks):
                    break
                if done_count >= threshold_count and time.monotonic() - last_completion >= straggler_idle_sec:
                    stragglers = [task for task in tasks if not task.done()]
                    print(
                        f"    ! cancelling {len(stragglers)}/{len(tasks)} straggler chunks "
                        f"for {paper_uuid[:8]} ({done_count}/{len(tasks)} done, "
                        f"idle {straggler_idle_sec:.0f}s)"
                    )
                    for task in stragglers:
                        task.cancel()
                    break
                await asyncio.wait(tasks, timeout=poll_interval, return_when=asyncio.FIRST_COMPLETED)
        await asyncio.gather(*tasks, return_exceptions=True)

    entities: Dict[str, Dict] = {}
    relationships: List[Dict] = []
    for result in results:
        if result is None:
            continue
        chunk_entities, chunk_rels = result
        for name, data in chunk_entities.items():
            if name not in entities:
                entities[name] = data
            else:
                if get_salience_score(data, 0.0) > get_salience_score(entities[name], 0.0):
                    set_salience_score(entities[name], get_salience_score(data, 0.0))
                for sc in data.get("source_chunks", []):
                    if sc not in entities[name]["source_chunks"]:
                        entities[name]["source_chunks"].append(sc)
        relationships.extend(chunk_rels)

    return entities, relationships


async def extract_paper_batch(
    batch: List[Tuple[int, dict]],
    papers_total: int,
    group_dir: Path,
    extractor,
    chunk_size: int,
    overlap: int,
    min_paper_length: int,
    max_paper_length: Optional[int],
    completion_threshold: float,
    straggler_idle_sec: float,
    exclude_metadata_regex: Optional[List[re.Pattern]] = None,
    semaphore: Optional[asyncio.Semaphore] = None,
    on_result: Optional[Callable[[PaperExtractionResult], Awaitable[None]]] = None,
) -> List[PaperExtractionResult]:
    async def _extract_one(index: int, paper_meta: dict) -> PaperExtractionResult:
        uuid = paper_meta.get("uuid", "")
        title = (paper_meta.get("title") or "(untitled)")[:80]
        path = group_dir / "papers" / paper_meta.get("content_file", f"{uuid}.md")

        excluded_by = metadata_exclude_match(paper_meta, exclude_metadata_regex or [])
        if excluded_by:
            try:
                text_length = int(paper_meta.get("content_chars") or 0)
            except (TypeError, ValueError):
                text_length = 0
            print(f"  [{index}/{papers_total}] EXCLUDE metadata /{excluded_by}/: {title}")
            return PaperExtractionResult(
                index,
                uuid,
                title,
                "excluded",
                text_length,
                {},
                [],
                error=f"metadata matched /{excluded_by}/",
            )

        if not path.exists():
            print(f"  [{index}/{papers_total}] MISSING file: {path}")
            return PaperExtractionResult(index, uuid, title, "failed", 0, {}, [], error="missing file")

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"  [{index}/{papers_total}] READ ERROR: {exc}")
            return PaperExtractionResult(index, uuid, title, "failed", 0, {}, [], error=str(exc))

        if len(text) < min_paper_length:
            print(f"  [{index}/{papers_total}] SKIP short ({len(text)} chars): {title}")
            return PaperExtractionResult(index, uuid, title, "short", len(text), {}, [])

        if max_paper_length is not None and len(text) > max_paper_length:
            print(f"  [{index}/{papers_total}] SKIP oversized ({len(text)} chars): {title}")
            return PaperExtractionResult(index, uuid, title, "oversized", len(text), {}, [])

        print(f"  [{index}/{papers_total}] {title} ({len(text)} chars)")
        try:
            entities, relationships = await extract_paper(
                text,
                uuid,
                extractor,
                chunk_size=chunk_size,
                overlap=overlap,
                semaphore=semaphore,
                completion_threshold=completion_threshold,
                straggler_idle_sec=straggler_idle_sec,
            )
            return PaperExtractionResult(index, uuid, title, "ok", len(text), entities, relationships)
        except Exception as exc:
            print(f"    ! extraction failed for {uuid[:8]}: {exc}")
            traceback.print_exc()
            return PaperExtractionResult(index, uuid, title, "failed", len(text), {}, [], error=str(exc))

    tasks = [asyncio.create_task(_extract_one(i, p)) for i, p in batch]
    results: List[PaperExtractionResult] = []
    for task in asyncio.as_completed(tasks):
        result = await task
        if on_result is not None:
            await on_result(result)
        results.append(result)
    return sorted(results, key=lambda r: r.index)


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
    paper_concurrency: int,
    chunk_concurrency: Optional[int] = None,
    max_paper_length: Optional[int] = None,
    exclude_metadata_regex: Optional[List[re.Pattern]] = None,
    completion_threshold: float = 1.0,
    straggler_idle_sec: float = 0.0,
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
    persisted_completed_uuids = set(state.get("completed_uuids", []))
    completed_uuids = set(persisted_completed_uuids)
    last_checkpoint_paper = state.get("last_checkpoint_paper")
    run_started_at = utc_now_iso()
    last_batch_progress = state.get("progress", {}).get("last_batch")

    def write_observable_state(
        *,
        active_batch: Optional[dict] = None,
        final_stats: Optional[dict] = None,
    ) -> None:
        progress = {
            "run_started_at": run_started_at,
            "resume_completed_count": len(persisted_completed_uuids),
            "observed_completed_count": len(completed_uuids),
        }
        if last_batch_progress is not None:
            progress["last_batch"] = last_batch_progress
        if active_batch is not None:
            progress["active_batch"] = active_batch
        save_state(
            state_path,
            make_progress_state(
                checkpoint_completed_uuids=persisted_completed_uuids,
                model=model,
                schema_name=schema_name,
                last_checkpoint_paper=last_checkpoint_paper,
                progress=progress,
                final_stats=final_stats,
            ),
        )

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

    pending_papers: List[Tuple[int, dict]] = []
    for i, paper_meta in enumerate(papers_meta, 1):
        uuid = paper_meta.get("uuid", "")
        if uuid and uuid not in completed_uuids:
            pending_papers.append((i, paper_meta))

    for batch_idx, batch in enumerate(batched(pending_papers, paper_concurrency), 1):
        attempted += len(batch)
        active_batch = {
            "batch_idx": batch_idx,
            "batch_size": len(batch),
            "paper_concurrency": paper_concurrency,
            "papers_total": len(papers_meta),
            "started_at": utc_now_iso(),
            "last_event_at": utc_now_iso(),
            "status": "extracting",
            "results_completed": 0,
            "results_by_status": {
                "ok": 0,
                "failed": 0,
                "short": 0,
                "oversized": 0,
                "excluded": 0,
            },
            "papers": [
                {
                    "index": index,
                    "uuid": paper_meta.get("uuid", ""),
                    "title": (paper_meta.get("title") or "(untitled)")[:80],
                }
                for index, paper_meta in batch
            ],
        }

        async def on_batch_result(result: PaperExtractionResult) -> None:
            active_batch["results_completed"] += 1
            active_batch["results_by_status"][result.status] = (
                active_batch["results_by_status"].get(result.status, 0) + 1
            )
            active_batch["last_result"] = {
                "index": result.index,
                "uuid": result.uuid,
                "status": result.status,
                "text_length": result.text_length,
            }
            active_batch["last_event_at"] = utc_now_iso()
            write_observable_state(active_batch=active_batch)

        write_observable_state(active_batch=active_batch)
        batch_results = await extract_paper_batch(
            batch=batch,
            papers_total=len(papers_meta),
            group_dir=group_dir,
            extractor=extractor,
            chunk_size=chunk_size,
            overlap=overlap,
            min_paper_length=min_paper_length,
            max_paper_length=max_paper_length,
            completion_threshold=completion_threshold,
            straggler_idle_sec=straggler_idle_sec,
            exclude_metadata_regex=exclude_metadata_regex,
            semaphore=semaphore,
            on_result=on_batch_result,
        )

        batch_graph = nx.DiGraph()
        batch_success_uuids: List[str] = []
        last_uuid = None
        for result in batch_results:
            last_uuid = result.uuid
            if result.status in {"short", "oversized", "excluded"}:
                skipped_short += 1
                completed_uuids.add(result.uuid)
                continue
            if result.status != "ok":
                failed += 1
                continue
            batch_graph, name_mapping = add_entities_to_graph(
                batch_graph,
                result.entities,
                result.uuid,
                similarity_threshold=similarity_threshold,
                auto_merge=auto_merge,
            )
            batch_graph = add_relationships_to_graph(
                batch_graph,
                result.relationships,
                name_mapping,
                result.uuid,
            )
            batch_success_uuids.append(result.uuid)

        active_batch["status"] = "merging"
        active_batch["last_event_at"] = utc_now_iso()
        write_observable_state(active_batch=active_batch)

        if batch_success_uuids:
            prev_succeeded = succeeded
            merge_started = time.time()
            graph = merge_graphs(
                graph,
                batch_graph,
                "",
                similarity_threshold=similarity_threshold,
                auto_merge=auto_merge,
            )
            succeeded += len(batch_success_uuids)
            completed_uuids.update(batch_success_uuids)
            print(
                f"    batch {batch_idx}: merged {len(batch_success_uuids)} papers into "
                f"{graph.number_of_nodes()} nodes / {graph.number_of_edges()} edges "
                f"in {time.time() - merge_started:.1f}s"
            )
            last_batch_progress = {
                "batch_idx": batch_idx,
                "batch_size": len(batch),
                "merged_papers": len(batch_success_uuids),
                "merged_at": utc_now_iso(),
                "results_by_status": dict(active_batch["results_by_status"]),
            }
            if save_every and (prev_succeeded // save_every) != (succeeded // save_every):
                save_graph(graph, out_graph)
                persisted_completed_uuids = set(completed_uuids)
                last_checkpoint_paper = last_uuid
                print(
                    f"    checkpoint: {graph.number_of_nodes()} nodes, "
                    f"{graph.number_of_edges()} edges, {len(completed_uuids)} papers done"
                )
            write_observable_state()

    # Final write
    save_graph(graph, out_graph)
    persisted_completed_uuids = set(completed_uuids)
    write_observable_state(
        final_stats={
            "completed": True,
            "papers_succeeded": succeeded,
            "papers_failed": failed,
            "papers_skipped_short": skipped_short,
        }
    )

    # Write domain expertise metadata alongside the graph
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
    os.environ["NANOGRAPHRAG_LLM_TRANSPORT"] = args.transport

    if args.list_groups:
        for g in discover_groups(corpus_dir):
            md = load_group_metadata(corpus_dir, g)
            print(f"{g:<32} schema={md.get('schema','?'):<32} "
                  f"papers={len(md.get('papers',[]))}")
        return

    available = discover_groups(corpus_dir)
    if not available:
        sys.exit(f"No groups found in {corpus_dir}")

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
    print(f"transport  : {args.transport}")
    print(f"groups     : {groups}")
    print(f"limit/grp  : {args.limit_papers}")

    results: List[GroupResult] = []
    exclude_metadata_regex = compile_metadata_exclude_regex(args.exclude_metadata_regex)
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
                paper_concurrency=args.paper_concurrency,
                chunk_concurrency=args.chunk_concurrency,
                max_paper_length=args.max_paper_length,
                exclude_metadata_regex=exclude_metadata_regex,
                completion_threshold=args.completion_threshold,
                straggler_idle_sec=args.straggler_idle_sec,
            )
            results.append(r)
        except Exception as e:
            print(f"\n!! GROUP {g} FAILED: {e}")
            traceback.print_exc()

    # Summary
    summary_path = output_dir / "build_summary.json"
    summary = {
        "model": args.model,
        "transport": args.transport,
        "corpus_dir": str(corpus_dir),
        "exclude_metadata_regex": args.exclude_metadata_regex or [],
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
                   help="Root of a typed paper corpus (default: data/haiqu_corpus)")
    p.add_argument("--output-dir", default="haiqu_graphs",
                   help="Where to write per-group graphml + state (default: haiqu_graphs)")
    p.add_argument("--groups", nargs="*",
                   help="Only build these groups (default: all discovered)")
    p.add_argument("--list-groups", action="store_true",
                   help="List available groups and exit")
    p.add_argument("--model", default=os.getenv("LLM_MODEL", "gpt55"),
                   help="LLM model name (passed to ArgoBridgeLLM); default gpt55")
    p.add_argument("--transport", choices=["direct", "shim"], default="direct",
                   help="LLM transport for ArgoBridgeLLM (default: direct)")
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
    p.add_argument("--paper-concurrency", type=int, default=6,
                   help="Papers to extract per batch before one central merge (default: 6)")
    p.add_argument("--chunk-concurrency", type=int, default=None,
                   help="Max concurrent chunk LLM calls across in-flight papers (default: unlimited)")
    p.add_argument("--completion-threshold", type=float, default=1.0,
                   help="Fraction of a paper's chunks required before idle stragglers can be cancelled (default: 1.0)")
    p.add_argument("--straggler-idle-sec", type=float, default=0.0,
                   help="Seconds without chunk completions before cancelling stragglers after threshold (default: disabled)")
    p.add_argument("--max-paper-length", type=int, default=None,
                   help="Skip papers longer than this many chars, e.g. 500000 to drop RSS feeds (default: unlimited)")
    p.add_argument("--exclude-metadata-regex", action="append",
                   help="Case-insensitive regex over paper title, URL, and description to skip bad corpus records")
    args = p.parse_args()

    # Quiet nano-graphrag debug noise unless the user already cranked it up.
    if "--verbose" not in sys.argv:
        logging.getLogger("nano-graphrag").setLevel(logging.WARNING)

    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
