"""Small helpers for calling an LLM and getting structured JSON back."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nano_graphrag._utils import extract_first_complete_json


class LLMJSONError(RuntimeError):
    """Raised when the model never returns parseable JSON."""


async def _call_llm(llm, prompt: str, *, system_prompt: str | None = None) -> str:
    try:
        return await llm.call_async(prompt, system_prompt=system_prompt)
    except TypeError as exc:
        if system_prompt is None or "system_prompt" not in str(exc):
            raise
        return await llm.call_async(
            f"SYSTEM:\n{system_prompt}\n\nUSER:\n{prompt}"
        )


async def ask_text(llm, prompt: str, *, system_prompt: str | None = None) -> str:
    """Call the LLM asynchronously and return the raw string response."""
    return await _call_llm(llm, prompt, system_prompt=system_prompt)


async def ask_json(
    llm,
    prompt: str,
    *,
    system_prompt: str | None = None,
    retries: int = 2,
) -> Any:
    """Call the LLM and parse a JSON object/array from its response.

    Reuses nano_graphrag's tolerant extractor (handles ```json fences and
    surrounding prose). On a parse failure it re-asks with an explicit
    "valid JSON only" nudge before giving up.
    """
    last_raw = ""
    current_prompt = prompt
    for attempt in range(retries + 1):
        last_raw = await _call_llm(llm, current_prompt, system_prompt=system_prompt)
        parsed = extract_first_complete_json(last_raw)
        if isinstance(parsed, (dict, list)):
            return parsed
        current_prompt = (
            prompt
            + "\n\nIMPORTANT: Your previous reply could not be parsed as JSON. "
            "Reply with a single valid JSON value and nothing else."
        )
    raise LLMJSONError(
        f"Model did not return parseable JSON after {retries + 1} attempts. "
        f"Last response started: {last_raw[:200]!r}"
    )
