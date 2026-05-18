"""
Runtime helpers for PROCESS execution.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from openai import AsyncOpenAI


PROCESS_SUBTYPES = (
    "semantic_filter",
    "field_derivation",
    "classification",
    "cross_node_synthesis",
)


@dataclass
class CandidateSelection:
    probe_items: List[Dict[str, Any]]
    final_items: List[Dict[str, Any]]
    diagnostics: Dict[str, Any] = field(default_factory=dict)


class ProcessSubtypeRouter:
    """Infer and route PROCESS subtypes without changing GASL surface syntax."""

    FILTER_PATTERNS = (
        r"\bfilter\b",
        r"\bselect\b",
        r"\bkeep only\b",
        r"\binclude\b",
        r"\bexclude\b",
        r"\bwhere\b",
        r"\bin\s+\w+",
        r"\bpreserve\s+(?:tgt_id|src_id|id|node_id)\b",
    )
    CLASSIFY_PATTERNS = (r"\bclassif", r"\bcategory\b", r"\blabel\b", r"\bbucket\b")
    DERIVE_PATTERNS = (
        r"\bcalculate\b",
        r"\bcompute\b",
        r"\bderive\b",
        r"\bextract\b",
        r"\bnormalize\b",
        r"\bstandardize\b",
        r"\badd field\b",
        r"\bmap\b",
    )

    def infer(self, instruction: str) -> str:
        text = (instruction or "").lower()
        if any(re.search(p, text) for p in self.CLASSIFY_PATTERNS):
            return "classification"
        if any(re.search(p, text) for p in self.FILTER_PATTERNS):
            return "semantic_filter"
        if any(re.search(p, text) for p in self.DERIVE_PATTERNS):
            return "field_derivation"
        return "cross_node_synthesis"

    def confirm_from_result(self, initial_subtype: str, result: Dict[str, Any]) -> str:
        if result.get("processing_method") == "filter":
            return "semantic_filter"
        processed = result.get("processed_items") or []
        if not processed:
            return initial_subtype
        keys = {k for item in processed if isinstance(item, dict) for k in item.keys()}
        if "category" in keys:
            return "classification"
        if len(keys - {"id", "name", "reason"}) > 0:
            return "field_derivation"
        return initial_subtype

    def routed_model(self, current_model: str, subtype: str) -> str:
        model = (current_model or "").strip()
        mini_default = os.getenv("PROCESS_MINI_MODEL", "gpt-5-mini")
        large_default = os.getenv("PROCESS_LARGE_MODEL", model or "gpt-5.5")
        if subtype in {"semantic_filter", "field_derivation"}:
            return mini_default
        if subtype == "cross_node_synthesis" and "mini" in model:
            return large_default
        return model


class DerivedArtifactRegistry:
    """Append-only artifact candidate log for later consolidation."""

    def __init__(self, state_file: Optional[Path] = None):
        base_dir = state_file.parent if state_file else Path.cwd()
        self.artifacts_dir = base_dir / "gasl_artifacts"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_path = self.artifacts_dir / "process_candidates.jsonl"

    def record_candidate(self, record: Dict[str, Any]) -> None:
        payload = dict(record)
        with self.candidates_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")


class CandidateSelector:
    """Build bounded candidate sets before PROCESS calls."""

    PROBE_SIZE = 20
    FINAL_BUDGET = 72
    RANDOM_TAIL = 8

    def __init__(self, graph=None, api_key: Optional[str] = None):
        self.graph = graph
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("VIZ_API_KEY")
        self._client: Optional[AsyncOpenAI] = None

    def select(
        self,
        data: List[Dict[str, Any]],
        *,
        query: str,
        instruction: str,
        subtype: str,
        strategy_hint: str = "stratified",
    ) -> CandidateSelection:
        if not isinstance(data, list) or len(data) <= self.PROBE_SIZE:
            return CandidateSelection(probe_items=list(data), final_items=list(data), diagnostics={"strategy": "all"})

        lexical = self._lexical_rank(data, query, instruction)
        central = self._central_rank(data)
        vector = self._vector_rank(data, f"{query} {instruction}".strip(), top_k=6)

        probe = self._stratified_probe(
            data,
            lexical=lexical,
            vector=vector,
            central=central,
            query=query,
            instruction=instruction,
            subtype=subtype,
            strategy_hint=strategy_hint,
        )
        final_budget = self.FINAL_BUDGET + (24 if strategy_hint == "broaden" else (-24 if strategy_hint == "narrow" else 0))
        final_budget = max(self.PROBE_SIZE, final_budget)
        lexical_slice = lexical[: final_budget]
        vector_slice = vector[:12 if strategy_hint != "vector" else 20]
        central_slice = central[:12 if strategy_hint != "central" else 20]
        random_slice = self._deterministic_random_tail(data, query, instruction, subtype, k=self.RANDOM_TAIL + (4 if strategy_hint == "broaden" else 0))
        final_items = self._merge_unique(
            lexical_slice,
            vector_slice,
            central_slice,
            random_slice,
        )[: final_budget + self.RANDOM_TAIL]

        return CandidateSelection(
            probe_items=probe,
            final_items=final_items,
            diagnostics={
                "strategy": strategy_hint or "stratified",
                "lexical_count": len(lexical),
                "vector_count": len(vector),
                "central_count": len(central),
                "probe_size": len(probe),
                "final_size": len(final_items),
            },
        )

    def widen(
        self,
        full_data: List[Dict[str, Any]],
        probe_result: Dict[str, Any],
        selection: CandidateSelection,
        *,
        query: str,
        instruction: str,
        subtype: str,
    ) -> List[Dict[str, Any]]:
        positives = probe_result.get("filtered_items") or probe_result.get("processed_items") or []
        if not positives:
            return selection.final_items

        positive_ids = {str(item.get("id", "")) for item in positives if isinstance(item, dict)}
        positive_terms = self._positive_terms(positives)
        ranked = sorted(
            full_data,
            key=lambda item: self._positive_similarity(item, positive_ids, positive_terms),
            reverse=True,
        )
        widened = self._merge_unique(
            selection.final_items,
            ranked[: self.FINAL_BUDGET],
            self._deterministic_random_tail(full_data, query, instruction, subtype, k=self.RANDOM_TAIL),
        )
        return widened[: self.FINAL_BUDGET + self.RANDOM_TAIL]

    def refine_instruction(self, instruction: str, probe_result: Dict[str, Any], subtype: str) -> str:
        positives = probe_result.get("filtered_items") or probe_result.get("processed_items") or []
        if not positives:
            return instruction
        example_ids = [str(item.get("id") or item.get("name") or "") for item in positives[:5] if isinstance(item, dict)]
        if subtype == "semantic_filter":
            return (
                f"{instruction}\n"
                f"Positive probe examples: {', '.join(example_ids)}.\n"
                "Prefer items similar in role and evidence to those examples; preserve the same inclusion criteria."
            )
        if subtype == "field_derivation":
            fields = sorted({k for item in positives if isinstance(item, dict) for k in item.keys() if k not in {'id', 'name', 'reason'}})
            if fields:
                return f"{instruction}\nPreserve a stable output schema using fields: {', '.join(fields)}."
        return instruction

    def _lexical_rank(self, data: List[Dict[str, Any]], query: str, instruction: str) -> List[Dict[str, Any]]:
        needle_text = f"{query} {instruction}".strip()
        return sorted(data, key=lambda item: self._lexical_score(item, needle_text), reverse=True)

    def _lexical_score(self, item: Dict[str, Any], needle_text: str) -> int:
        tokens = {tok for tok in re.findall(r"[a-z0-9]+", needle_text.lower()) if len(tok) > 2}
        item_text = self._item_search_text(item)
        score = 0
        for tok in tokens:
            if tok in item_text:
                score += 1
        item_id = str(item.get("id", "")).lower() if isinstance(item, dict) else ""
        entity = str(item.get("data", {}).get("entity_type", "")).lower() if isinstance(item, dict) else ""
        alt_names = str(item.get("data", {}).get("alternative_names", "")).lower() if isinstance(item, dict) else ""
        for tok in tokens:
            if tok == item_id:
                score += 5
            elif tok in item_id:
                score += 2
            if tok in entity:
                score += 2
            if tok in alt_names:
                score += 1
        return score

    def _central_rank(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self.graph is None or not hasattr(self.graph, "degree"):
            return []
        scored = []
        for item in data:
            node_id = item.get("id") if isinstance(item, dict) else None
            if node_id is None or node_id not in self.graph:
                continue
            scored.append((item, int(self.graph.degree(node_id))))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [item for item, _ in scored]

    def _vector_rank(self, data: List[Dict[str, Any]], text: str, top_k: int) -> List[Dict[str, Any]]:
        if not self.api_key or len(data) < 10:
            return []
        try:
            try:
                asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self._vector_rank_async(data, text, top_k=top_k))
                    return future.result()
            except RuntimeError:
                return asyncio.run(self._vector_rank_async(data, text, top_k=top_k))
        except Exception:
            return []

    async def _vector_rank_async(self, data: List[Dict[str, Any]], text: str, top_k: int) -> List[Dict[str, Any]]:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.api_key)
        contents = [self._item_search_text(item)[:2000] for item in data]
        query_resp = await self._client.embeddings.create(model="text-embedding-3-small", input=[text], encoding_format="float")
        item_resp = await self._client.embeddings.create(model="text-embedding-3-small", input=contents, encoding_format="float")
        q = query_resp.data[0].embedding
        sims = []
        for item, emb in zip(data, item_resp.data):
            sims.append((item, self._cosine(q, emb.embedding)))
        sims.sort(key=lambda pair: pair[1], reverse=True)
        return [item for item, _ in sims[:top_k]]

    @staticmethod
    def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
        num = sum(x * y for x, y in zip(a, b))
        denom_a = sum(x * x for x in a) ** 0.5
        denom_b = sum(y * y for y in b) ** 0.5
        if denom_a == 0 or denom_b == 0:
            return 0.0
        return num / (denom_a * denom_b)

    def _stratified_probe(
        self,
        data: List[Dict[str, Any]],
        *,
        lexical: List[Dict[str, Any]],
        vector: List[Dict[str, Any]],
        central: List[Dict[str, Any]],
        query: str,
        instruction: str,
        subtype: str,
        strategy_hint: str,
    ) -> List[Dict[str, Any]]:
        random_tail = self._deterministic_random_tail(data, query, instruction, subtype, k=6)
        if strategy_hint == "lexical":
            return self._merge_unique(lexical[:12], vector[:2], central[:2], random_tail)[: self.PROBE_SIZE]
        if strategy_hint == "vector":
            return self._merge_unique(vector[:10], lexical[:4], central[:2], random_tail)[: self.PROBE_SIZE]
        if strategy_hint == "central":
            return self._merge_unique(central[:10], lexical[:4], vector[:2], random_tail)[: self.PROBE_SIZE]
        return self._merge_unique(
            lexical[:8],
            vector[:4],
            central[:4],
            random_tail,
        )[: self.PROBE_SIZE]

    def _deterministic_random_tail(self, data: List[Dict[str, Any]], query: str, instruction: str, subtype: str, *, k: int) -> List[Dict[str, Any]]:
        seed_material = f"{query}|{instruction}|{subtype}|{len(data)}"
        seed = int(hashlib.sha1(seed_material.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed)
        if k >= len(data):
            return list(data)
        idxs = list(range(len(data)))
        rng.shuffle(idxs)
        return [data[i] for i in idxs[:k]]

    @staticmethod
    def _merge_unique(*groups: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen = set()
        for group in groups:
            for item in group:
                if isinstance(item, dict):
                    node_id = (
                        item.get("id")
                        or item.get("group_id")
                        or item.get("group_key")
                        or item.get("name")
                        or id(item)
                    )
                else:
                    node_id = id(item)
                if node_id in seen:
                    continue
                seen.add(node_id)
                merged.append(item)
        return merged

    @staticmethod
    def _item_search_text(item: Dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return str(item).lower()
        parts = [str(item.get("id", ""))]
        parts.extend([
            str(item.get("group_id", "")),
            str(item.get("group_name", "")),
            str(item.get("group_key", "")),
            str(item.get("count", "")),
            str(item.get("result", "")),
            str(item.get("name", "")),
        ])
        if isinstance(item.get("data"), dict):
            data = item["data"]
            parts.extend([
                str(data.get("entity_type", "")),
                str(data.get("entity_name", "")),
                str(data.get("alternative_names", "")),
                str(data.get("description", "")),
            ])
        else:
            parts.extend([
                str(item.get("entity_type", "")),
                str(item.get("name", "")),
                str(item.get("description", "")),
            ])
        return " ".join(parts).lower()

    @staticmethod
    def _positive_terms(items: List[Dict[str, Any]]) -> set[str]:
        terms: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            text = CandidateSelector._item_search_text(item)
            terms.update(tok for tok in re.findall(r"[a-z0-9]+", text) if len(tok) > 3)
        return terms

    def _positive_similarity(self, item: Dict[str, Any], positive_ids: set[str], positive_terms: set[str]) -> int:
        node_id = str(item.get("id", "")) if isinstance(item, dict) else ""
        text = self._item_search_text(item)
        score = 0
        if node_id in positive_ids:
            score += 10
        score += sum(1 for tok in positive_terms if tok in text)
        return score
