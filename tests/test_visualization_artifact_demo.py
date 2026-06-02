from visualization.demo_catalog import build_trace_demo_from_artifacts
from visualization.server import create_app


ENZYME_GRAPH = (
    "enzyme_graphs/multi_scale_gpt55_c400/"
    "multi_scale_structural_all/multi_scale_structural_all_graph.graphml"
)


def test_build_trace_demo_from_artifacts_enzyme_q002():
    demo = build_trace_demo_from_artifacts(
        qid="q002",
        run_id="enzyme_demo_20260531_trace_2q_fg2",
        graph_path=ENZYME_GRAPH,
    )

    assert demo["id"] == "multi_scale_structural_all-q002"
    assert demo["graph_path"].endswith("multi_scale_structural_all_graph.graphml")
    assert demo["question"]
    assert demo["replay"]
    assert demo["replay"][-1]["event"] == "query_complete"


def test_artifact_demo_endpoint_returns_demo_payload():
    app = create_app()
    client = app.test_client()

    response = client.get(
        "/api/artifact-demo",
        query_string={
            "run_id": "enzyme_demo_20260531_trace_2q_fg2",
            "qid": "q002",
            "graph_path": ENZYME_GRAPH,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["id"] == "multi_scale_structural_all-q002"
    assert payload["replay"][-1]["event"] == "query_complete"
