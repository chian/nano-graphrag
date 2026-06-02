from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pytest

from hpc.common import save_graph
from hpc.chunk_manifest import build_chunk_manifest
from hpc.merge_hierarchy import merge_hierarchy
from hpc.review_final_merges import generate_candidates, review_candidates
from hpc.run_shard_extraction import run_shard
from hpc.split_shards import split_chunk_manifest
from nano_graphrag.graph_slots import add_alias, add_source_ref, get_aliases, get_source_refs


def test_build_chunk_manifest_emits_traceable_offsets(tmp_path: Path):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "p1.txt").write_text("abcdefghij", encoding="utf-8")
    inventory_path = tmp_path / "inventory.jsonl"
    inventory_path.write_text(json.dumps({"paper_id": "p1", "path": "p1.txt"}) + "\n", encoding="utf-8")

    summary = build_chunk_manifest(
        inventory_path=inventory_path,
        output_path=tmp_path / "chunks.jsonl",
        paper_root=papers_dir,
        paper_id_key="paper_id",
        path_key="path",
        title_key="title",
        text_key="",
        chunk_size=4,
        overlap=1,
    )

    rows = [json.loads(line) for line in (tmp_path / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["papers"] == 1
    assert rows[0]["paper_id"] == "p1"
    assert rows[0]["start_char"] == 0
    assert rows[0]["end_char"] == 4
    assert rows[1]["start_char"] == 3
    assert rows[0]["chunk_id"].startswith("p1:0:0:4:")


def test_split_chunk_manifest_uses_even_count_partition(tmp_path: Path):
    manifest_path = tmp_path / "chunks.jsonl"
    rows = [{"chunk_id": f"c{i}", "chunk_text": str(i)} for i in range(7)]
    manifest_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    summary = split_chunk_manifest(
        manifest_path=manifest_path,
        out_dir=tmp_path / "shards",
        shard_count=3,
    )

    assert summary["shard_count"] == 3
    shard0 = (tmp_path / "shards" / "shard_000.jsonl").read_text(encoding="utf-8").splitlines()
    shard1 = (tmp_path / "shards" / "shard_001.jsonl").read_text(encoding="utf-8").splitlines()
    shard2 = (tmp_path / "shards" / "shard_002.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(shard0) == 3
    assert len(shard1) == 2
    assert len(shard2) == 2


def test_merge_hierarchy_merges_graphs_in_stages(tmp_path: Path):
    graph_paths = []
    for idx in range(3):
        graph = nx.DiGraph()
        graph.add_node(f"n{idx}", entity_type="X")
        graph_path = tmp_path / f"g{idx}.graphml"
        nx.write_graphml(graph, graph_path)
        graph_paths.append(graph_path)
    summary = merge_hierarchy(
        graph_paths=graph_paths,
        out_dir=tmp_path / "merge",
        fan_in=2,
        similarity_threshold=0.99,
        auto_merge=True,
    )

    final_graph = nx.read_graphml(tmp_path / "merge" / "final_graph.graphml")
    assert summary["stages"]
    assert final_graph.number_of_nodes() == 3


def test_merge_hierarchy_preserves_aliases_and_source_refs(tmp_path: Path):
    left_graph = nx.DiGraph()
    left_graph.add_node("TNF", entity_type="PROTEIN", description="cytokine")
    add_alias(left_graph.nodes["TNF"], "TNF")
    add_source_ref(left_graph.nodes["TNF"], "paper_a_chunk_1")
    left_graph.add_node("TNF receptor", entity_type="PROTEIN", description="receptor")
    add_source_ref(left_graph.nodes["TNF receptor"], "paper_a_chunk_1")
    left_graph.add_edge("TNF", "TNF receptor", description="binds", weight=1.0)
    add_source_ref(left_graph["TNF"]["TNF receptor"], "paper_a_chunk_1")
    left_path = tmp_path / "a.graphml"
    save_graph(left_path, left_graph)

    right_graph = nx.DiGraph()
    right_graph.add_node("tumor necrosis factor", entity_type="PROTEIN", description="pro-inflammatory cytokine")
    add_alias(right_graph.nodes["tumor necrosis factor"], "tumor necrosis factor")
    add_source_ref(right_graph.nodes["tumor necrosis factor"], "paper_b_chunk_7")
    right_graph.add_node("TNF receptor", entity_type="PROTEIN", description="surface receptor")
    add_source_ref(right_graph.nodes["TNF receptor"], "paper_b_chunk_7")
    right_graph.add_edge("tumor necrosis factor", "TNF receptor", description="binds strongly", weight=2.0)
    add_source_ref(right_graph["tumor necrosis factor"]["TNF receptor"], "paper_b_chunk_7")
    right_path = tmp_path / "b.graphml"
    save_graph(right_path, right_graph)

    merge_hierarchy(
        graph_paths=[left_path, right_path],
        out_dir=tmp_path / "merge",
        fan_in=2,
        similarity_threshold=0.9,
        auto_merge=True,
    )

    final_graph = nx.read_graphml(tmp_path / "merge" / "final_graph.graphml")
    merged_node = dict(final_graph.nodes["TNF"])
    merged_edge = dict(final_graph["TNF"]["TNF receptor"])

    assert {"TNF", "tumor necrosis factor"} <= set(get_aliases(merged_node))
    assert {"paper_a_chunk_1", "paper_b_chunk_7", "a", "b"} <= set(get_source_refs(merged_node))
    assert {"paper_a_chunk_1", "paper_b_chunk_7", "a", "b"} <= set(get_source_refs(merged_edge))


@pytest.mark.asyncio
async def test_review_candidates_applies_merge(monkeypatch, tmp_path: Path):
    graph = nx.DiGraph()
    graph.add_node("tumor necrosis factor", entity_type="PROTEIN", description="cytokine")
    graph.add_node("TNF", entity_type="PROTEIN", description="abbrev cytokine")
    graph_path = tmp_path / "graph.graphml"
    nx.write_graphml(graph, graph_path)

    class FakeLLM:
        async def call_async(self, prompt: str) -> str:
            return json.dumps({"merge": True, "confidence": 0.99, "reason": "same entity"})

    monkeypatch.setattr("hpc.review_final_merges.ArgoBridgeLLM", lambda model: FakeLLM())
    candidates = generate_candidates(
        graph,
        similarity_threshold=0.8,
        same_type_only=True,
        max_candidates=None,
    )
    assert candidates
    summary = await review_candidates(
        graph_path=graph_path,
        out_dir=tmp_path / "review",
        model="gpt-test",
        similarity_threshold=0.8,
        same_type_only=True,
        max_candidates=None,
        apply_merges=True,
    )

    reviewed = nx.read_graphml(tmp_path / "review" / "reviewed_graph.graphml")
    assert summary["applied_merges"] == 1
    assert reviewed.number_of_nodes() == 1


@pytest.mark.asyncio
async def test_run_shard_writes_artifacts_and_resume_skips_completed(monkeypatch, tmp_path: Path):
    shard_row = {
        "chunk_id": "paper-1:0:0:24:abcd",
        "paper_id": "paper-1",
        "chunk_text": "TNF binds TNF receptor.",
    }
    shard_path = tmp_path / "shard_000.jsonl"
    shard_path.write_text(json.dumps(shard_row) + "\n", encoding="utf-8")

    class FakeRecord:
        def __init__(self, **payload):
            self._payload = payload

        def to_dict(self) -> dict:
            return dict(self._payload)

    class FakePrediction:
        def __init__(self):
            self.entities = [
                FakeRecord(entity_name="TNF", entity_type="PROTEIN", description="cytokine"),
                FakeRecord(entity_name="TNF receptor", entity_type="PROTEIN", description="receptor"),
            ]
            self.relationships = [
                FakeRecord(
                    src_id="TNF",
                    tgt_id="TNF receptor",
                    relation_type="INTERACTS_WITH",
                    description="binds",
                    weight=1.0,
                )
            ]

    class FakeExtractor:
        async def forward(self, text: str) -> FakePrediction:
            assert text == "TNF binds TNF receptor."
            return FakePrediction()

    class FakeLLM:
        async def call_async(self, prompt: str) -> str:
            return "{}"

    monkeypatch.setattr("hpc.run_shard_extraction.load_domain_schema", lambda name: {"name": name})
    monkeypatch.setattr("hpc.run_shard_extraction.ArgoBridgeLLM", lambda model: FakeLLM())
    monkeypatch.setattr(
        "hpc.run_shard_extraction.create_domain_extractor_from_schema",
        lambda schema, llm_func, num_refine_turns, self_refine: FakeExtractor(),
    )

    output_dir = tmp_path / "run"
    first_summary = await run_shard(
        shard_path=shard_path,
        output_dir=output_dir,
        schema_name="generic_schema",
        model="gpt-test",
        refine_turns=1,
        self_refine=False,
        similarity_threshold=0.85,
        auto_merge=True,
        save_every=1,
        resume=True,
    )

    assert first_summary["chunks_completed"] == 1
    assert (output_dir / "entities.jsonl").exists()
    assert (output_dir / "relationships.jsonl").exists()
    assert (output_dir / "chunk_results.jsonl").exists()
    assert (output_dir / "local_graph.graphml").exists()
    assert (output_dir / "state.json").exists()

    second_summary = await run_shard(
        shard_path=shard_path,
        output_dir=output_dir,
        schema_name="generic_schema",
        model="gpt-test",
        refine_turns=1,
        self_refine=False,
        similarity_threshold=0.85,
        auto_merge=True,
        save_every=1,
        resume=True,
    )

    chunk_results = (output_dir / "chunk_results.jsonl").read_text(encoding="utf-8").splitlines()
    assert second_summary["chunks_completed"] == 1
    assert len(chunk_results) == 1
