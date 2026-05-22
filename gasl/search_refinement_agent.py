from __future__ import annotations
"""
LLM-guided search refinement for GASL runtime probes.

This module does not validate execution truth. It looks at sampled output and
recommends a next-step search refinement for retrieval/filter stages.
"""

import hashlib
import json
import os
import random
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional


@dataclass
class SearchRefinementRequest:
    search_name: str
    prompt_builder: Callable[[list[Dict[str, Any]], int], str]
    row_iterator: Iterable[Dict[str, Any]]
    seed_text: str
    default_payload: Dict[str, Any]
    sample_limit: int = 20
    model: str | None = None
    reasoning_effort: str | None = None
    prompt_name: str | None = None
    prompt_logger: Any = None
    prompt_metadata: Optional[Dict[str, Any]] = None
    label_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None


class LLMSearchRefinementAgent:
    """Use an LLM to inspect sampled output and recommend the next search move."""

    def __init__(self, llm_func):
        self.llm_func = llm_func

    def _llm_for_refinement(self, request: SearchRefinementRequest):
        if hasattr(self.llm_func, "clone"):
            current_model = getattr(self.llm_func, "model", "") or ""
            model = request.model or current_model
            reasoning_effort = request.reasoning_effort
            if not model and "mini" in current_model.lower():
                model = os.getenv("PROCESS_LARGE_MODEL", "gpt-5.5")
            return self.llm_func.clone(model=model, reasoning_effort=reasoning_effort)
        return self.llm_func

    @staticmethod
    def sample_rows(rows: Iterable[Dict[str, Any]], *, seed_text: str, k: int = 20) -> list[Dict[str, Any]]:
        items = list(rows or [])
        limit = min(k, len(items))
        if len(items) <= limit:
            return items
        head_n = max(1, limit // 3)
        tail_n = max(1, limit // 4)
        body_n = max(0, limit - head_n - tail_n)
        body = items[head_n : max(head_n, len(items) - tail_n)]
        rng = random.Random(int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:8], 16))
        picked = []
        if body and body_n > 0:
            indices = list(range(len(body)))
            rng.shuffle(indices)
            picked = [body[i] for i in sorted(indices[:body_n])]
        return items[:head_n] + picked + items[-tail_n:]

    @staticmethod
    def should_apply_refinement(search_refinement: Dict[str, Any], total_count: int, *, min_count: int = 30) -> bool:
        if total_count < min_count or not search_refinement:
            return False
        if search_refinement.get("refinement_hint") in {"tighten", "tighten_depth", "narrow", "broaden"}:
            return True
        confidence = float(search_refinement.get("refinement_confidence", 1.0) or 1.0)
        return confidence < 0.55

    def run_search_refinement(self, request: SearchRefinementRequest) -> Dict[str, Any]:
        initial_rows: list[Dict[str, Any]] = []
        for row in request.row_iterator:
            initial_rows.append(row)
            if len(initial_rows) >= request.sample_limit:
                break
        sampled_rows = self.sample_rows(initial_rows, seed_text=request.seed_text, k=request.sample_limit)
        prompt_text = request.prompt_builder(sampled_rows, len(sampled_rows))
        observation_id = None
        try:
            llm = self._llm_for_refinement(request)
            if request.prompt_logger and request.prompt_name:
                observation_id = request.prompt_logger.record_invocation(
                    prompt_name=request.prompt_name,
                    prompt_text=prompt_text,
                    model=getattr(llm, "model", None),
                    metadata=request.prompt_metadata or {},
                )
            response = llm.call(prompt_text)
            parsed = json.loads(self._extract_json(response))
            if request.prompt_logger and request.prompt_name and observation_id:
                request.prompt_logger.record_outcome(
                    observation_id,
                    prompt_name=request.prompt_name,
                    response_text=response,
                    parsed=parsed,
                    labels=request.label_builder(parsed) if request.label_builder else {},
                )
            return parsed
        except Exception:
            if request.prompt_logger and request.prompt_name and observation_id:
                request.prompt_logger.record_outcome(
                    observation_id,
                    prompt_name=request.prompt_name,
                    response_text=None,
                    parsed=request.default_payload,
                    labels={"parse_success": False},
                )
            return request.default_payload

    def get_find_refinement(
        self,
        command_args: Dict[str, Any],
        row_iterator: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        criteria = command_args.get("criteria", "")
        target = command_args.get("target", "nodes")
        return self.run_search_refinement(
            SearchRefinementRequest(
                search_name="find",
                row_iterator=row_iterator,
                seed_text=criteria,
                prompt_builder=lambda sampled_rows, sampled_count: f"""You are refining a FIND command strategy.

Command intent:
- target: {target}
- criteria: {criteria}

Observed output sample:
- sample_count: {sampled_count}
- sample_data: {self._format_sample_data(sampled_rows)}

Decide the next move based only on the sample:
1. keep current strategy if the sample already matches the requested semantics closely enough
2. tighten the strategy if the sample is too broad, weakly matched, or structurally off-target

Return strict JSON:
{{
  "refinement_hint": "keep|tighten",
  "refinement_reason": "short reason",
  "refinement_issues": ["optional issues"],
  "refinement_confidence": 0.0
}}""",
                default_payload={"refinement_hint": "keep", "refinement_reason": "refinement agent unavailable", "refinement_issues": [], "refinement_confidence": 0.5},
                prompt_name="find_refinement",
            )
        )

    def get_graphwalk_refinement(
        self,
        args: Dict[str, Any],
        source_nodes: Any,
        row_iterator: Iterable[Dict[str, Any]],
        contract: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from_variable = args.get("from_variable", "")
        relationship_types = args.get("relationship_types", "")
        depth = args.get("depth", "1")
        default = {
            "refinement_hint": "keep",
            "refinement_reason": "graphwalk refinement agent unavailable",
            "refinement_anchor_strength": 0.5,
            "refinement_relation_strength": 0.5,
            "refinement_depth_strength": 0.5,
            "refinement_payload_hint": (contract or {}).get("payload_kind", "walk_rows"),
            "refinement_grain_hint": (contract or {}).get("grain_type", "edge"),
            "refinement_downstream_hint": (contract or {}).get("usable_by", ["PROCESS", "SHOW", "SELECT"]),
            "refinement_confidence": 0.5,
        }
        return self.run_search_refinement(
            SearchRefinementRequest(
                search_name="graphwalk",
                row_iterator=row_iterator,
                seed_text=f"{from_variable}:{relationship_types}:{depth}",
                prompt_builder=lambda sampled_rows, sampled_count: f"""You are refining a GRAPHWALK retrieval strategy.

Goal:
- walk from source variable '{from_variable}'
- follow relationship filter '{relationship_types}'
- depth {depth}

Source sample:
{self._format_path_sample(source_nodes)}

Walk result sample:
{self._format_path_sample(sampled_rows)}

Current contract:
{contract or {}}

Decide the next move based on the sample:
1. keep current depth/strategy if the sample is good enough
2. tighten depth/strategy if the sample is too broad or weakly anchored

Return strict JSON:
{{
  "refinement_hint": "keep|tighten_depth",
  "refinement_reason": "short reason",
  "refinement_anchor_strength": 0.0,
  "refinement_relation_strength": 0.0,
  "refinement_depth_strength": 0.0,
  "refinement_payload_hint": "walk_rows|edge_rows|path_rows|node_rows",
  "refinement_grain_hint": "edge|path|node|chunk|paper",
  "refinement_downstream_hint": ["PROCESS", "SHOW", "SELECT"],
  "refinement_confidence": 0.0
}}""",
                default_payload=default,
                model=os.getenv("PATH_SEMANTICS_MODEL", "") or None,
                reasoning_effort=os.getenv("PATH_SEMANTICS_REASONING", "high"),
                prompt_name="graphwalk_refinement",
            )
        )

    @staticmethod
    def _format_sample_data(data: Any) -> str:
        if not data:
            return "No data"
        if isinstance(data, list):
            if len(data) == 0:
                return "Empty list"
            return f"List with {len(data)} items, sample: {data[:3]}"
        return str(data)

    @staticmethod
    def _format_path_sample(data: Any) -> str:
        if not data:
            return "No data"
        if isinstance(data, list):
            return json.dumps(data[:10], ensure_ascii=False, default=str)
        return json.dumps(data, ensure_ascii=False, default=str)

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end >= start:
            return text[start : end + 1]
        return text
