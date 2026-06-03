from __future__ import annotations

import json
from pathlib import Path

import hpc.build_vllm_prompts as module
from hpc.build_vllm_prompts import build_vllm_prompts


def test_build_vllm_prompts_emits_prompt_jsonl(tmp_path: Path):
    shard_path = tmp_path / "shard_000.jsonl"
    shard_row = {
        "chunk_id": "paper-1:0:0:24:abcd",
        "paper_id": "paper-1",
        "chunk_text": "Ionizing radiation perturbs DNA repair and increases gamma-H2AX foci.",
    }
    shard_path.write_text(json.dumps(shard_row) + "\n", encoding="utf-8")
    out_path = tmp_path / "prompts.jsonl"

    summary = build_vllm_prompts(
        shard_path=shard_path,
        out_path=out_path,
        schema_name="low_dose_radiation_dna_damage_repair",
        model="test-model",
        request_format="prompt-jsonl",
        max_tokens=1024,
        temperature=0.0,
        top_p=1.0,
    )

    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert summary["rows"] == 1
    assert rows[0]["custom_id"] == shard_row["chunk_id"]
    assert rows[0]["model"] == "test-model"
    assert "ENTITY TYPES" in rows[0]["prompt"]
    assert shard_row["chunk_text"] in rows[0]["prompt"]


def test_build_vllm_prompts_emits_openai_chat_requests(tmp_path: Path):
    shard_path = tmp_path / "shard_000.jsonl"
    shard_row = {
        "chunk_id": "paper-2:0:0:24:efgh",
        "paper_id": "paper-2",
        "chunk_text": "Buformin targets AMPK signaling and modifies radiosensitivity.",
    }
    shard_path.write_text(json.dumps(shard_row) + "\n", encoding="utf-8")
    out_path = tmp_path / "requests.jsonl"

    build_vllm_prompts(
        shard_path=shard_path,
        out_path=out_path,
        schema_name="low_dose_radiation_dna_damage_repair",
        model="test-model",
        request_format="openai-chat",
        max_tokens=1536,
        temperature=0.1,
        top_p=0.95,
    )

    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["custom_id"] == shard_row["chunk_id"]
    assert rows[0]["url"] == "/v1/chat/completions"
    assert rows[0]["body"]["model"] == "test-model"
    assert rows[0]["body"]["temperature"] == 0.1
    assert rows[0]["body"]["messages"][0]["role"] == "user"
    assert shard_row["chunk_text"] in rows[0]["body"]["messages"][0]["content"]


def test_build_vllm_prompts_formats_schema_once_per_shard(tmp_path: Path, monkeypatch):
    shard_path = tmp_path / "shard_000.jsonl"
    rows = [
        {
            "chunk_id": f"paper-3:{idx}:0:24:{idx}",
            "paper_id": "paper-3",
            "chunk_text": f"Chunk {idx} mentions ATM and DNA repair.",
        }
        for idx in range(3)
    ]
    shard_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    out_path = tmp_path / "requests.jsonl"

    calls = {"count": 0}
    real_components = module._schema_prompt_components

    def wrapped(schema_name: str):
        calls["count"] += 1
        return real_components(schema_name)

    monkeypatch.setattr(module, "_schema_prompt_components", wrapped)

    build_vllm_prompts(
        shard_path=shard_path,
        out_path=out_path,
        schema_name="low_dose_radiation_dna_damage_repair",
        model="test-model",
        request_format="prompt-jsonl",
        max_tokens=1024,
        temperature=0.0,
        top_p=1.0,
    )

    assert calls["count"] == 1
