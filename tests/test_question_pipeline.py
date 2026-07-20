"""Offline tests for the question-driven pipeline.

All external dependencies (LLM, Firecrawl, GASL, extractor) are faked so the
orchestration logic runs end-to-end without network or model access.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import networkx as nx
import pytest

from domain_schemas.schema_loader import DomainSchema, EntityType, RelationshipType
from nano_graphrag.entity_extraction.typed_module import (
    DomainTypedEntityRelationshipExtractor,
)
from question_pipeline import PipelineConfig, QuestionPipeline
from question_pipeline import schema_synthesis, strategy
from question_pipeline.extraction import chunk_text, extract_from_text, schema_type_coverage


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class FakeLLM:
    """Returns canned JSON keyed by what the prompt is asking for."""

    def __init__(self):
        self.calls = []

    async def call_async(self, prompt: str) -> str:
        self.calls.append(prompt)
        p = prompt.lower()
        if "reviewer feedback" in p or "extraction test results" in p or "design entity types" in p:
            # schema generate/revise
            return json.dumps({
                "domain_name": "UV Disinfection",
                "domain_description": "UV-C controls and their measured effect.",
                "entity_types": [
                    {"name": "ENGINEERING_CONTROL", "description": "a control", "examples": ["UV-C"]},
                    {"name": "PATHOGEN", "description": "a microbe", "examples": ["TB"]},
                    {"name": "EFFECTIVENESS_MEASURE", "description": "effect", "examples": ["log reduction"]},
                ],
                "relationship_types": [
                    {"name": "REDUCES", "description": "control reduces pathogen", "examples": ["UV -> TB"]},
                ],
            })
        if "rigorous reviewer" in p:
            return json.dumps({"verdict": "accept", "score": 0.9, "issues": []})
        if "search queries" in p and "next" in p:
            return json.dumps({"queries": ["uv-c followup one", "uv-c followup two"]})
        if "search queries" in p:
            return json.dumps({"queries": ["uv-c tuberculosis", "upper room uv hospital"]})
        if "judging whether" in p:
            # assessment -> sufficient after graph exists
            return json.dumps({"sufficient": True, "confidence": 0.9, "gaps": [], "rationale": "ok"})
        return "{}"


class FakeRecord:
    def __init__(self, **payload):
        self._payload = payload

    def to_dict(self):
        return dict(self._payload)


class FakePrediction:
    def __init__(self):
        self.entities = [
            FakeRecord(entity_name="UV-C", entity_type="ENGINEERING_CONTROL", description="uv", salience_score=0.8),
            FakeRecord(entity_name="TB", entity_type="PATHOGEN", description="bug", salience_score=0.7),
        ]
        self.relationships = [
            FakeRecord(src_id="UV-C", tgt_id="TB", relation_type="REDUCES", description="kills", weight=0.9, order=1),
        ]


class FakeExtractor:
    async def forward(self, text: str):
        return FakePrediction()


class SlowFakeExtractor:
    def __init__(self):
        self.in_flight = 0
        self.max_in_flight = 0

    async def forward(self, text: str):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return FakePrediction()


class EmptyThenValidLLM:
    def __init__(self):
        self.calls = 0

    async def __call__(self, prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            return ""
        return json.dumps(
            {
                "entities": [
                    {
                        "entity_name": "UV-C",
                        "entity_type": "ENGINEERING_CONTROL",
                        "description": "uv",
                        "importance_score": 0.8,
                    }
                ],
                "relationships": [],
            }
        )


def fake_search_fn(query: str, max_results: int):
    return [
        {
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{abs(hash(query)) % 100000}",
            "title": f"Paper for {query}",
            "markdown": "UV-C reduces TB. " * 80,
        }
    ]


def fake_search_with_oversized_result(query: str, max_results: int):
    return [
        {
            "url": "https://pubmed.ncbi.nlm.nih.gov/oversized",
            "title": "Oversized scrape",
            "markdown": "long " * 500,
        },
        {
            "url": "https://pubmed.ncbi.nlm.nih.gov/usable",
            "title": "Usable paper",
            "markdown": "UV-C reduces TB. " * 80,
        },
    ]


def fake_gasl_runner(graph, metadata, state_file):
    Path(state_file).parent.mkdir(parents=True, exist_ok=True)
    return {
        "final_answer": "Upper-room UV-C reduces airborne TB by ~1.5 log in hospital wards.",
        "iterations": 2,
        "final_state": {"variables": {}},
    }


def fake_table_gasl_runner(graph, metadata, state_file):
    state = {
        "variables": {
            "disease_id50_r0_table": {
                "_meta": {"type": "LIST"},
                "items": [
                    {
                        "group_key": "measles:paper-1",
                        "items": [
                            {
                                "disease": "measles",
                                "table_name": "disease_id50_r0_table",
                                "infectious_dose_value": None,
                                "r0_value": "12-18",
                                "source_refs": ["paper-1"],
                                "evidence_gap": "ID50 missing",
                            },
                            {
                                "disease": "COVID-19",
                                "table_name": "country_r0_table",
                                "country": "Sri Lanka",
                                "source_refs": ["paper-2"],
                            }
                        ],
                        "supporting_path_count": 1,
                    }
                ],
            },
            "country_r0_table": {
                "_meta": {"type": "LIST"},
                "items": [
                    {
                        "country_r0_table": [
                            {
                                "disease": "COVID-19",
                                "country": "Sri Lanka",
                                "r0_value": 1.02,
                                "r0_range": "0.75-1.29",
                                "source_refs": ["paper-2"],
                                "evidence_gap": "",
                            }
                        ],
                        "row_id": "wrapped-country-table",
                    }
                ],
            },
        }
    }
    Path(state_file).parent.mkdir(parents=True, exist_ok=True)
    Path(state_file).write_text(json.dumps(state), encoding="utf-8")
    return {
        "final_answer": "Materialized 2 tables.",
        "iterations": 1,
        "final_state": state,
    }


def _schema() -> DomainSchema:
    return DomainSchema(
        domain_name="UV",
        domain_description="d",
        entity_types={
            "ENGINEERING_CONTROL": EntityType("ENGINEERING_CONTROL", "c", []),
            "PATHOGEN": EntityType("PATHOGEN", "p", []),
        },
        relationship_types={"REDUCES": RelationshipType("REDUCES", "r", None, False, [])},
    )


def _write_seed_graph(path: Path) -> None:
    graph = nx.DiGraph()
    graph.add_node("UV-C", entity_type="ENGINEERING_CONTROL", entity_name="UV-C")
    graph.add_node("TB", entity_type="PATHOGEN", entity_name="TB")
    graph.add_edge("UV-C", "TB", relation_type="REDUCES")
    nx.write_graphml(graph, path)


def test_gasl_job_id_scopes_checkpoints_to_run_directory():
    job_id = QuestionPipeline._gasl_job_id(
        "question_runs/run_20260617/answers/round_0_gasl_state.json"
    )

    assert job_id == "run_20260617_round_0_gasl_state"


# --------------------------------------------------------------------------- #
# Unit tests
# --------------------------------------------------------------------------- #

def test_chunk_text_overlaps_and_covers():
    chunks = chunk_text("abcdefghij", chunk_size=4, overlap=1)
    assert chunks[0] == "abcd"
    assert chunks[1] == "defg"  # starts at end-overlap = 3
    assert "".join(c[0] for c in chunks)  # non-empty


@pytest.mark.asyncio
async def test_extract_and_coverage():
    entities, rels = await extract_from_text(FakeExtractor(), "some text", "p1", chunk_size=100, overlap=0)
    assert set(entities) == {"UV-C", "TB"}
    cov = schema_type_coverage(["ENGINEERING_CONTROL", "PATHOGEN"], entities)
    assert cov["off_schema_rate"] == 0.0
    assert cov["n_entities"] == 2


@pytest.mark.asyncio
async def test_extract_uses_bounded_chunk_concurrency():
    extractor = SlowFakeExtractor()

    entities, rels = await extract_from_text(
        extractor,
        "abcdefghij" * 12,
        "p1",
        chunk_size=10,
        overlap=0,
        concurrency=3,
    )

    assert extractor.max_in_flight == 3
    assert set(entities) == {"UV-C", "TB"}
    assert len(rels) == 12


@pytest.mark.asyncio
async def test_typed_extractor_retries_empty_initial_response():
    llm = EmptyThenValidLLM()
    extractor = DomainTypedEntityRelationshipExtractor(
        entity_types=["ENGINEERING_CONTROL"],
        relationship_types=["REDUCES"],
        entity_type_descriptions="- ENGINEERING_CONTROL: a control",
        relationship_type_descriptions="- REDUCES: reduces",
        llm_func=llm,
        self_refine=False,
    )

    prediction = await extractor.forward("UV-C")

    assert llm.calls == 2
    assert len(prediction.entities) == 1
    assert prediction.entities[0].entity_name == "UV-C"


@pytest.mark.asyncio
async def test_initial_and_followup_queries():
    llm = FakeLLM()
    initial = await strategy.initial_queries(llm, "How effective is UV-C?", n=4)
    assert initial and all(isinstance(q, str) for q in initial)
    followup = await strategy.followup_queries(
        llm, "q", current_answer="ans", gaps=["dose unknown"], top_entities=["UV-C"], n=4
    )
    assert followup


@pytest.mark.asyncio
async def test_synthesize_schema_with_test(monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(
        "question_pipeline.schema_synthesis.create_domain_extractor_from_schema",
        lambda schema, llm_func, num_refine_turns, self_refine: FakeExtractor(),
    )
    result = await schema_synthesis.synthesize_schema(
        llm,
        "How effective is UV-C against TB?",
        sample_texts=[{"id": "s1", "text": "UV-C kills TB"}],
        max_review_passes=1,
    )
    assert "ENGINEERING_CONTROL" in result.schema.entity_types
    assert any(h["stage"] == "test" for h in result.history)


@pytest.mark.asyncio
async def test_full_pipeline_offline(tmp_path: Path):
    config = PipelineConfig(
        question="How effective is upper-room UV-C against TB in hospitals?",
        output_dir=str(tmp_path / "run"),
        max_rounds=2,
        papers_per_round=2,
        max_papers=4,
    )
    pipeline = QuestionPipeline(
        config,
        llm=FakeLLM(),
        search_fn=fake_search_fn,
        extractor_factory=lambda schema: FakeExtractor(),
        gasl_runner=fake_gasl_runner,
    )
    result = await pipeline.run()

    assert result["final_answer"].startswith("Upper-room UV-C")
    assert result["graph_nodes"] >= 2
    assert (tmp_path / "run" / "final_answer.json").exists()
    assert (tmp_path / "run" / "schema.yaml").exists()
    assert (tmp_path / "run" / "graphs" / "current_graph.graphml").exists()
    # Stops at round 0 because the fake assessment returns sufficient+confident.
    assert result["rounds"] == 1


@pytest.mark.asyncio
async def test_pipeline_skips_oversized_firecrawl_results(tmp_path: Path):
    config = PipelineConfig(
        question="How effective is upper-room UV-C against TB in hospitals?",
        output_dir=str(tmp_path / "run"),
        max_rounds=1,
        papers_per_round=2,
        max_papers=2,
        min_paper_length=10,
        max_paper_length=2_000,
    )
    pipeline = QuestionPipeline(
        config,
        llm=FakeLLM(),
        search_fn=fake_search_with_oversized_result,
        extractor_factory=lambda schema: FakeExtractor(),
        gasl_runner=fake_gasl_runner,
    )

    result = await pipeline.run()

    saved_papers = list((tmp_path / "run" / "fetched_papers").glob("*.txt"))
    assert result["papers_fetched"] == 1
    assert len(saved_papers) == 1
    assert saved_papers[0].read_text(encoding="utf-8").startswith("UV-C")


@pytest.mark.asyncio
async def test_pipeline_runs_gasl_on_seed_graph_without_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    graph_path = tmp_path / "seed.graphml"
    _write_seed_graph(graph_path)
    searched = False

    def search_fn(query: str, max_results: int):
        nonlocal searched
        searched = True
        return []

    monkeypatch.setattr("question_pipeline.pipeline.load_domain_schema", lambda name: _schema())
    config = PipelineConfig(
        question="How effective is upper-room UV-C against TB in hospitals?",
        output_dir=str(tmp_path / "run"),
        schema_name="uv",
        graph_path=str(graph_path),
        max_rounds=1,
        max_papers=0,
    )
    pipeline = QuestionPipeline(
        config,
        llm=FakeLLM(),
        search_fn=search_fn,
        extractor_factory=lambda schema: FakeExtractor(),
        gasl_runner=fake_gasl_runner,
    )

    result = await pipeline.run()

    assert searched is False
    assert result["papers_fetched"] == 0
    assert result["graph_nodes"] == 2
    assert (tmp_path / "run" / "graphs" / "current_graph.graphml").exists()


@pytest.mark.asyncio
async def test_table_answer_mode_exports_gasl_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    graph_path = tmp_path / "seed.graphml"
    _write_seed_graph(graph_path)

    monkeypatch.setattr("question_pipeline.pipeline.load_domain_schema", lambda name: _schema())
    config = PipelineConfig(
        question="Build reported tables.",
        output_dir=str(tmp_path / "run"),
        schema_name="uv",
        graph_path=str(graph_path),
        max_rounds=1,
        max_papers=0,
        answer_mode="table",
    )
    pipeline = QuestionPipeline(
        config,
        llm=FakeLLM(),
        extractor_factory=lambda schema: FakeExtractor(),
        gasl_runner=fake_table_gasl_runner,
    )

    result = await pipeline.run()

    disease_json = tmp_path / "run" / "answers" / "tables" / "round_0_disease_id50_r0_table.json"
    country_csv = tmp_path / "run" / "answers" / "tables" / "round_0_country_r0_table.csv"
    manifest = json.loads(
        (
            tmp_path / "run" / "answers" / "tables" / "round_0_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert result["answer_mode"] == "table"
    assert len(result["table_exports"]) == 2
    assert manifest[0]["validation"]["partial_rows"] == 1
    assert "infectious_dose_unit" in manifest[0]["validation"]["missing_by_column"]
    disease_row = json.loads(disease_json.read_text(encoding="utf-8"))[0]
    country_text = country_csv.read_text(encoding="utf-8")
    assert disease_row["disease"] == "measles"
    assert disease_row["supporting_path_count"] == 1
    assert country_text.startswith("disease,pathogen,country,reproduction_measure_type")
    assert "Sri Lanka" in country_text
