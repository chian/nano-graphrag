from pathlib import Path

import networkx as nx

from visualization.server import create_app


def _write_graphml(path: Path, nodes: list[str], edges: list[tuple[str, str]]) -> None:
    graph = nx.DiGraph()
    for node in nodes:
        graph.add_node(node, entity_type="ENTITY", salience=0.5)
    for source, target in edges:
        graph.add_edge(source, target, relation_type="REL")
    nx.write_graphml(graph, path)


def test_stats_endpoint_prefers_full_graph_when_available(tmp_path: Path):
    render_graph = tmp_path / "render.graphml"
    full_graph = tmp_path / "full.graphml"
    _write_graphml(render_graph, ["a", "b"], [("a", "b")])
    _write_graphml(full_graph, ["a", "b", "c"], [("a", "b"), ("b", "c")])

    app = create_app(graph_path=str(render_graph), full_graph_path=str(full_graph))
    client = app.test_client()

    response = client.get("/api/stats")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["num_nodes"] == 3
    assert payload["num_edges"] == 2


def test_stats_endpoint_falls_back_to_render_graph(tmp_path: Path):
    render_graph = tmp_path / "render.graphml"
    _write_graphml(render_graph, ["a", "b"], [("a", "b")])

    app = create_app(graph_path=str(render_graph))
    client = app.test_client()

    response = client.get("/api/stats")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["num_nodes"] == 2
    assert payload["num_edges"] == 1
