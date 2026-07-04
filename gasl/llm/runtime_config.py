"""
Repo-only LLM transport selection.

Default behavior stays unchanged. To route repo calls through a local shim
without affecting Codex itself, set:

    NANOGRAPHRAG_LLM_TRANSPORT=shim

Optional overrides:
    NANOGRAPHRAG_SHIM_URL
    NANOGRAPHRAG_SHIM_TOKEN
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RuntimeLLMConfig:
    api_key: Optional[str]
    base_url: Optional[str]
    model: Optional[str]
    transport: str


_REPO_ENV_LOADED = False


def load_repo_env_files() -> None:
    """Load repo-local env files without overriding shell-provided values."""
    global _REPO_ENV_LOADED
    if _REPO_ENV_LOADED:
        return
    _REPO_ENV_LOADED = True

    repo_root = Path(__file__).resolve().parents[2]
    for path in (repo_root / ".env", repo_root / ".viz.local.env"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(
                key.strip(),
                value.strip().strip("'").strip('"'),
            )


def _shim_from_claude_settings() -> tuple[Optional[str], Optional[str]]:
    settings_path = Path.home() / ".claude" / "settings.json"
    try:
        data = json.loads(settings_path.read_text())
    except Exception:
        return None, None

    helper = data.get("apiKeyHelper", "")
    token = None
    if helper.startswith("echo "):
        candidate = helper[5:]
        if candidate and candidate != "no-auth":
            token = candidate

    base = data.get("env", {}).get("ANTHROPIC_BASE_URL", "")
    if base.endswith("/argoapi"):
        base = base[: -len("/argoapi")]
    if base and not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1"
    return token, (base or None)


def _normalize_shim_model(requested_model: Optional[str]) -> Optional[str]:
    override = os.getenv("NANOGRAPHRAG_SHIM_MODEL")
    if override:
        return override
    model = (requested_model or "").strip()
    if not model:
        return "gpt55"
    lowered = model.lower()
    direct_map = {
        # Stay within the GPT-5 family when translating public model ids to the
        # Argo shim's accepted ids. Preserve size class where possible.
        "gpt-5.5": "gpt55",
        "gpt-5.4-mini": "gpt5mini",
        "gpt-5-mini": "gpt5mini",
        "gpt-5-nano": "gpt5nano",
        "gpt-5": "gpt5",
        "gpt-5.4": "gpt54",
        "gpt-5.2": "gpt52",
        "gpt-5.1": "gpt51",
        "gpt-4.1-mini": "gpt41mini",
        "gpt-4.1": "gpt41",
    }
    return direct_map.get(lowered, model)


def resolve_runtime_llm_config(
    *,
    explicit_api_key: Optional[str] = None,
    explicit_base_url: Optional[str] = None,
    explicit_model: Optional[str] = None,
) -> RuntimeLLMConfig:
    load_repo_env_files()

    transport = os.getenv("NANOGRAPHRAG_LLM_TRANSPORT", "direct").strip().lower()
    if transport != "shim":
        return RuntimeLLMConfig(
            api_key=(
                explicit_api_key
                or os.getenv("LLM_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or os.getenv("VIZ_API_KEY")
            ),
            base_url=explicit_base_url or os.getenv("OPENAI_BASE_URL"),
            model=explicit_model,
            transport="direct",
        )

    env_shim_token = os.getenv("NANOGRAPHRAG_SHIM_TOKEN")
    env_shim_url = os.getenv("NANOGRAPHRAG_SHIM_URL")
    auto_token, auto_url = _shim_from_claude_settings()
    shim_token = env_shim_token or auto_token
    shim_url = env_shim_url or auto_url

    return RuntimeLLMConfig(
        api_key=shim_token or explicit_api_key,
        base_url=shim_url or explicit_base_url,
        model=_normalize_shim_model(explicit_model),
        transport="shim",
    )
