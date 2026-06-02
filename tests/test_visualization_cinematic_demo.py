import pytest

from visualization.demo_catalog import _SCIENCE_NOTE_BANNED_PHRASES, build_cinematic_demo_from_artifacts
from visualization.server import create_app


ENZYME_GRAPH = (
    "enzyme_graphs/multi_scale_gpt55_c400/"
    "multi_scale_structural_all/multi_scale_structural_all_graph.graphml"
)


def test_build_cinematic_demo_from_artifacts_topology_q001():
    demo = build_cinematic_demo_from_artifacts(
        qid="q001",
        run_id="corpus_20260602_enzyme_topology_1q_v2",
        graph_path=ENZYME_GRAPH,
        target_seconds=90,
    )

    assert demo["id"] == "multi_scale_structural_all-q001"
    assert demo["graph_path"].endswith("multi_scale_structural_all_graph.graphml")
    assert "cinematic" not in demo["title"].lower()
    assert demo["question"]
    assert demo["replay"]
    highlights = [step for step in demo["replay"] if step["event"] == "gasl_highlight"]
    assert highlights
    assert any(step["payload"]["nodes"] for step in highlights)
    evidence_table_sizes = [
        len((step["payload"].get("view_payload") or {}).get("rows") or [])
        for step in demo["replay"]
        if step["event"] == "answer_view" and step["payload"].get("view_kind") == "evidence_table"
    ]
    assert evidence_table_sizes
    assert max(evidence_table_sizes) > min(evidence_table_sizes)
    assert evidence_table_sizes[-1] == max(evidence_table_sizes)
    for step in demo["replay"]:
        payload = step.get("payload", {})
        for key in ("command", "story_kicker", "story_title", "story_body", "selection_rationale"):
            text = str(payload.get(key, "") or "").lower()
            for phrase in _SCIENCE_NOTE_BANNED_PHRASES:
                assert phrase not in text
    assert demo["replay"][-1]["event"] == "query_complete"


def test_build_cinematic_demo_from_artifacts_rejects_missing_answer_views():
    with pytest.raises(ValueError, match="no answer_views artifact"):
        build_cinematic_demo_from_artifacts(
            qid="q002",
            run_id="enzyme_demo_20260531_trace_2q_fg2",
            graph_path=ENZYME_GRAPH,
        )


def test_cinematic_demo_endpoint_returns_payload():
    app = create_app()
    client = app.test_client()

    response = client.get(
        "/api/cinematic-demo",
        query_string={
            "run_id": "corpus_20260602_enzyme_topology_1q_v2",
            "qid": "q001",
            "graph_path": ENZYME_GRAPH,
            "target_seconds": "90",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["id"] == "multi_scale_structural_all-q001"
    highlights = [step for step in payload["replay"] if step["event"] == "gasl_highlight"]
    assert highlights
    assert any(step["payload"]["nodes"] for step in highlights)
    assert payload["replay"][-1]["event"] == "query_complete"


def test_demo_catalog_route_skips_broken_entries():
    app = create_app()
    client = app.test_client()

    response = client.get("/api/demos")

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload["demos"], list)
    assert payload["demos"]
