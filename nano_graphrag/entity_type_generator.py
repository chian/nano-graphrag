from __future__ import annotations

from typing import Iterable, List, Dict, Any
import json
import os
import re

from .prompt_system import PROMPTS


def _normalize_type_name(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"\s+", " ", name)
    # simple plural -> singular heuristic for common cases
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("ses"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def _parse_entity_types(raw: str) -> List[str]:
    raw = raw.strip()
    # try JSON
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "entity_types" in data and isinstance(data["entity_types"], list):
            items = [str(x) for x in data["entity_types"]]
            return [_normalize_type_name(x) for x in items if x and str(x).strip()]
        if isinstance(data, list):
            items = [str(x) for x in data]
            return [_normalize_type_name(x) for x in items if x and str(x).strip()]
    except Exception:
        pass

    # try comma-separated
    if "," in raw:
        parts = [p for p in [x.strip() for x in raw.split(",")] if p]
        return [_normalize_type_name(x) for x in parts]

    # single token fallback
    return [_normalize_type_name(raw)] if raw else []


async def generate_entity_types_for_chunks(
    task: str,
    chunks: Dict[str, Any],
    llm_func,
    max_chars_per_prompt: int = 4000,
    per_chunk: bool = True,
) -> List[str]:
    prompt_template = PROMPTS["entity_type_generation"]

    def build_input_text(text: str) -> str:
        if len(text) <= max_chars_per_prompt:
            return text
        return text[:max_chars_per_prompt]

    if not per_chunk:
        concatenated = []
        for _, chunk in chunks.items():
            concatenated.append(chunk["content"])  # do not rename keys
        input_text = build_input_text("\n\n".join(concatenated))
        prompt = prompt_template.format(task=task, input_text=input_text)
        raw = await llm_func(prompt)
        if isinstance(raw, list):
            raw = raw[0]["text"]
        return list(dict.fromkeys(_parse_entity_types(raw)))

    # per-chunk generation and merge
    freq: Dict[str, int] = {}
    for _, chunk in chunks.items():
        input_text = build_input_text(chunk["content"])  # do not rename keys
        prompt = prompt_template.format(task=task, input_text=input_text)
        raw = await llm_func(prompt)
        if isinstance(raw, list):
            raw = raw[0]["text"]
        types = _parse_entity_types(raw)
        for t in types:
            if not t:
                continue
            freq[t] = freq.get(t, 0) + 1

    # frequency filter: keep those appearing >=2, else keep top-N fallback
    filtered = [t for t, c in freq.items() if c >= 2]
    if not filtered:
        # keep top 12 distinct by frequency
        filtered = [t for t, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:12]]

    # final de-dup preserving order
    return list(dict.fromkeys(filtered))


