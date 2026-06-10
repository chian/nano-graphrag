from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import build_corpus_graphs as bcg


def _write_group(tmp_path: Path) -> Path:
    corpus_dir = tmp_path / "corpus"
    group_dir = corpus_dir / "demo_group"
    papers_dir = group_dir / "papers"
    papers_dir.mkdir(parents=True)
    metadata = {
        "group": "demo_group",
        "schema": "demo_schema",
        "papers": [
            {"uuid": "u1", "title": "Paper 1", "content_file": "u1.md"},
            {"uuid": "u2", "title": "Paper 2", "content_file": "u2.md"},
        ],
    }
    (group_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (papers_dir / "u1.md").write_text("alpha", encoding="utf-8")
    (papers_dir / "u2.md").write_text("beta", encoding="utf-8")
    return corpus_dir


@pytest.mark.asyncio
async def test_build_group_writes_live_progress_without_advancing_resume_state(tmp_path, monkeypatch):
    corpus_dir = _write_group(tmp_path)
    output_dir = tmp_path / "out"
    observed_states: list[dict] = []
    original_save_state = bcg.save_state

    def recording_save_state(state_path: Path, state: dict) -> None:
        observed_states.append(copy.deepcopy(state))
        original_save_state(state_path, state)

    async def fake_extract_paper_batch(*, on_result=None, **kwargs):
        r1 = bcg.PaperExtractionResult(1, "u1", "Paper 1", "ok", 5, {"u1": {"source_chunks": []}}, [])
        r2 = bcg.PaperExtractionResult(2, "u2", "Paper 2", "ok", 4, {"u2": {"source_chunks": []}}, [])
        if on_result is not None:
            await on_result(r1)
            await on_result(r2)
        return [r1, r2]

    monkeypatch.setattr(bcg, "save_state", recording_save_state)
    monkeypatch.setattr(
        bcg,
        "load_domain_schema",
        lambda _: SimpleNamespace(entity_types=["E"], relationship_types=["R"]),
    )
    monkeypatch.setattr(
        bcg,
        "ArgoBridgeLLM",
        lambda model: SimpleNamespace(call_async=lambda *_args, **_kwargs: None, usage={}),
    )
    monkeypatch.setattr(bcg, "create_domain_extractor_from_schema", lambda *args, **kwargs: object())
    monkeypatch.setattr(bcg, "extract_paper_batch", fake_extract_paper_batch)
    monkeypatch.setattr(
        bcg,
        "add_entities_to_graph",
        lambda graph, entities, uuid, **kwargs: (graph, {}),
    )
    monkeypatch.setattr(bcg, "add_relationships_to_graph", lambda graph, relationships, name_mapping, uuid: graph)
    monkeypatch.setattr(bcg, "merge_graphs", lambda graph, batch_graph, *_args, **_kwargs: graph)
    monkeypatch.setattr(bcg, "save_graph", lambda graph, path: None)
    monkeypatch.setattr(bcg, "metadata_from_schema_and_corpus", lambda **kwargs: {})
    monkeypatch.setattr(bcg, "save_graph_metadata", lambda *_args, **_kwargs: tmp_path / "meta.json")

    await bcg.build_group(
        group="demo_group",
        corpus_dir=corpus_dir,
        output_dir=output_dir,
        model="gpt-test",
        chunk_size=4000,
        overlap=400,
        refine_turns=1,
        self_refine=True,
        similarity_threshold=0.85,
        auto_merge=True,
        limit_papers=None,
        min_paper_length=0,
        resume=True,
        save_every=2,
        paper_concurrency=2,
        chunk_concurrency=None,
        max_paper_length=None,
    )

    mid_batch_state = next(
        state
        for state in observed_states
        if state.get("progress", {}).get("active_batch", {}).get("results_completed") == 1
    )
    assert mid_batch_state["completed_uuids"] == []
    assert mid_batch_state["progress"]["active_batch"]["results_by_status"]["ok"] == 1

    final_state = observed_states[-1]
    assert final_state["completed"] is True
    assert final_state["completed_uuids"] == ["u1", "u2"]


@pytest.mark.asyncio
async def test_extract_paper_batch_runs_papers_concurrently(tmp_path, monkeypatch):
    corpus_dir = _write_group(tmp_path)
    group_dir = corpus_dir / "demo_group"
    both_started = asyncio.Event()
    started: list[str] = []

    async def fake_extract_paper(
        text,
        paper_uuid,
        extractor,
        chunk_size,
        overlap,
        semaphore,
        per_paper_chunk_concurrency,
        completion_threshold,
        straggler_idle_sec,
    ):
        started.append(paper_uuid)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.25)
        return {paper_uuid: {"entity_name": paper_uuid, "source_chunks": []}}, []

    monkeypatch.setattr(bcg, "extract_paper", fake_extract_paper)

    results = await bcg.extract_paper_batch(
        batch=[
            (1, {"uuid": "u1", "title": "Paper 1", "content_file": "u1.md"}),
            (2, {"uuid": "u2", "title": "Paper 2", "content_file": "u2.md"}),
        ],
        papers_total=2,
        group_dir=group_dir,
        extractor=object(),
        chunk_size=4000,
        overlap=400,
        min_paper_length=0,
        max_paper_length=None,
        completion_threshold=1.0,
        straggler_idle_sec=0.0,
    )

    assert [result.status for result in results] == ["ok", "ok"]
    assert set(started) == {"u1", "u2"}


@pytest.mark.asyncio
async def test_extract_paper_batch_excludes_metadata_regex(tmp_path, monkeypatch):
    corpus_dir = _write_group(tmp_path)
    group_dir = corpus_dir / "demo_group"
    started: list[str] = []

    async def fake_extract_paper(
        text,
        paper_uuid,
        extractor,
        chunk_size,
        overlap,
        semaphore,
        per_paper_chunk_concurrency,
        completion_threshold,
        straggler_idle_sec,
    ):
        started.append(paper_uuid)
        return {paper_uuid: {"entity_name": paper_uuid, "source_chunks": []}}, []

    monkeypatch.setattr(bcg, "extract_paper", fake_extract_paper)

    results = await bcg.extract_paper_batch(
        batch=[
            (
                1,
                {
                    "uuid": "u1",
                    "title": "[XML] demo feed",
                    "url": "https://example.test/feed",
                    "content_file": "missing.md",
                    "content_chars": 1000000,
                },
            ),
            (2, {"uuid": "u2", "title": "Paper 2", "content_file": "u2.md"}),
        ],
        papers_total=2,
        group_dir=group_dir,
        extractor=object(),
        chunk_size=4000,
        overlap=400,
        min_paper_length=0,
        max_paper_length=None,
        completion_threshold=1.0,
        straggler_idle_sec=0.0,
        exclude_metadata_regex=[re.compile(r"\[XML\]|/feed")],
    )

    assert [result.status for result in results] == ["excluded", "ok"]
    assert results[0].text_length == 1000000
    assert started == ["u2"]


@pytest.mark.asyncio
async def test_extract_paper_limits_in_flight_chunks_per_paper(monkeypatch):
    release_chunks = asyncio.Event()
    first_two_started = asyncio.Event()
    started: list[str] = []

    monkeypatch.setattr(
        bcg,
        "chunk_text",
        lambda *_args, **_kwargs: ["chunk-0", "chunk-1", "chunk-2", "chunk-3", "chunk-4"],
    )

    async def fake_extract_from_chunk(chunk, chunk_id, extractor, local_entities, local_rels):
        started.append(chunk_id)
        if len(started) == 2:
            first_two_started.set()
        await release_chunks.wait()
        local_entities[chunk_id] = {"entity_name": chunk_id, "source_chunks": []}

    monkeypatch.setattr(bcg, "extract_from_chunk", fake_extract_from_chunk)

    task = asyncio.create_task(
        bcg.extract_paper(
            "paper",
            "paper_uuid",
            extractor=object(),
            chunk_size=1,
            overlap=0,
            per_paper_chunk_concurrency=2,
        )
    )

    await asyncio.wait_for(first_two_started.wait(), timeout=0.25)
    await asyncio.sleep(0)

    assert started == ["paper_uuid_chunk_0", "paper_uuid_chunk_1"]

    release_chunks.set()
    entities, relationships = await asyncio.wait_for(task, timeout=0.25)

    assert set(entities) == {
        "paper_uuid_chunk_0",
        "paper_uuid_chunk_1",
        "paper_uuid_chunk_2",
        "paper_uuid_chunk_3",
        "paper_uuid_chunk_4",
    }
    assert relationships == []
