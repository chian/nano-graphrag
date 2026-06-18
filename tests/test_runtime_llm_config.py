import json

from gasl.llm.runtime_config import _normalize_shim_model, resolve_runtime_llm_config


def test_normalize_shim_model_uses_gpt55_for_gpt55_request():
    assert _normalize_shim_model("gpt-5.5") == "gpt55"
    assert _normalize_shim_model("GPT-5.5") == "gpt55"


def test_normalize_shim_model_defaults_to_gpt55():
    assert _normalize_shim_model(None) == "gpt55"


def test_explicit_shim_env_overrides_claude_settings(tmp_path, monkeypatch):
    claude_settings = tmp_path / ".claude" / "settings.json"
    claude_settings.parent.mkdir()
    claude_settings.write_text(json.dumps({
        "apiKeyHelper": "echo stale-token",
        "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:11111/argoapi"},
    }))

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NANOGRAPHRAG_LLM_TRANSPORT", "shim")
    monkeypatch.setenv("NANOGRAPHRAG_SHIM_TOKEN", "explicit-token")
    monkeypatch.setenv("NANOGRAPHRAG_SHIM_URL", "http://127.0.0.1:12331/v1")

    config = resolve_runtime_llm_config(explicit_model="gpt-5.5")

    assert config.api_key == "explicit-token"
    assert config.base_url == "http://127.0.0.1:12331/v1"
    assert config.model == "gpt55"
