"""Offline tests for the question-driven pipeline.

All external dependencies (LLM, Firecrawl, GASL, extractor) are faked so the
orchestration logic runs end-to-end without network or model access.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain_schemas.schema_loader import DomainSchema, EntityType, RelationshipType
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


def fake_search_fn(query: str, max_results: int):
    return [
        {
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{abs(hash(query)) % 100000}",
            "title": f"Paper for {query}",
            "markdown": "UV-C reduces TB. " * 80,
        }
    ]


def fake_gasl_runner(graph, metadata, state_file):
    Path(state_file).parent.mkdir(parents=True, exist_ok=True)
    return {
        "final_answer": "Upper-room UV-C reduces airborne TB by ~1.5 log in hospital wards.",
        "iterations": 2,
        "final_state": {"variables": {}},
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
        max_review_rounds=1,
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
