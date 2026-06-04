import json
from pathlib import Path

import networkx as nx

from visualization.query_engine import RagQueryEngine
from visualization.server import create_app


def _write_graphml(path: Path) -> None:
    graph = nx.DiGraph()
    graph.add_node("node-a", entity_type="ENTITY", description="hand hygiene")
    graph.add_node("node-b", entity_type="ENTITY", description="ventilation")
    graph.add_edge("node-a", "node-b", relation_type="REL")
    nx.write_graphml(graph, path)


def _post_query(client, password: str = "slama"):
    return client.post(
        "/api/query",
        json={
            "question": "What helps?",
            "mode": "rag",
            "model": "gpt-5.4-mini",
            "password": password,
        },
    )


def _stub_rag_answer(monkeypatch):
    seen_api_keys = []

    def generate_answer(self, question, context, **kwargs):
        seen_api_keys.append(kwargs.get("api_key"))
        return {
            "text": "stub answer",
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "calls": 0,
            },
        }

    monkeypatch.setattr(RagQueryEngine, "generate_answer", generate_answer)
    return seen_api_keys


def _write_claude_settings(home: Path, *, token: str) -> None:
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({
            "apiKeyHelper": f"echo {token}",
            "env": {"ANTHROPIC_BASE_URL": "http://shim.example/argoapi"},
        }),
        encoding="utf-8",
    )


def test_password_unlock_resolves_viz_api_key_per_request(monkeypatch, tmp_path):
    monkeypatch.delenv("NANOGRAPHRAG_LLM_TRANSPORT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("VIZ_API_KEY", "first-token")
    seen_api_keys = _stub_rag_answer(monkeypatch)

    graph_path = tmp_path / "graph.graphml"
    _write_graphml(graph_path)
    client = create_app(graph_path=str(graph_path)).test_client()

    response = _post_query(client)
    monkeypatch.setenv("VIZ_API_KEY", "second-token")
    second_response = _post_query(client)

    assert response.status_code == 200
    assert second_response.status_code == 200
    assert seen_api_keys == ["first-token", "second-token"]


def test_password_unlock_uses_runtime_shim_token(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NANOGRAPHRAG_LLM_TRANSPORT", "shim")
    monkeypatch.setenv("NANOGRAPHRAG_SHIM_TOKEN", "saved-token")
    monkeypatch.setenv("NANOGRAPHRAG_SHIM_URL", "http://shim.example/v1")
    monkeypatch.delenv("VIZ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    seen_api_keys = _stub_rag_answer(monkeypatch)

    graph_path = tmp_path / "graph.graphml"
    _write_graphml(graph_path)
    client = create_app(graph_path=str(graph_path)).test_client()

    response = _post_query(client)

    assert response.status_code == 200
    assert seen_api_keys == ["saved-token"]


def test_password_unlock_reads_live_claude_settings_token(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NANOGRAPHRAG_LLM_TRANSPORT", "shim")
    monkeypatch.delenv("NANOGRAPHRAG_SHIM_TOKEN", raising=False)
    monkeypatch.delenv("NANOGRAPHRAG_SHIM_URL", raising=False)
    monkeypatch.delenv("VIZ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    _write_claude_settings(tmp_path, token="first-saved-token")
    seen_api_keys = _stub_rag_answer(monkeypatch)

    graph_path = tmp_path / "graph.graphml"
    _write_graphml(graph_path)
    client = create_app(graph_path=str(graph_path)).test_client()

    response = _post_query(client)
    _write_claude_settings(tmp_path, token="second-saved-token")
    second_response = _post_query(client)

    assert response.status_code == 200
    assert second_response.status_code == 200
    assert seen_api_keys == ["first-saved-token", "second-saved-token"]


def test_wrong_password_rejects_saved_shim_token(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NANOGRAPHRAG_LLM_TRANSPORT", "shim")
    monkeypatch.setenv("NANOGRAPHRAG_SHIM_TOKEN", "saved-token")
    monkeypatch.setenv("NANOGRAPHRAG_SHIM_URL", "http://shim.example/v1")
    monkeypatch.delenv("VIZ_API_KEY", raising=False)
    seen_api_keys = _stub_rag_answer(monkeypatch)

    graph_path = tmp_path / "graph.graphml"
    _write_graphml(graph_path)
    client = create_app(graph_path=str(graph_path)).test_client()

    response = _post_query(client, password="wrong")

    assert response.status_code == 401
    assert seen_api_keys == []
