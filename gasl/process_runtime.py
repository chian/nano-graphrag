"""
Runtime helpers for PROCESS execution.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import os
import re
import httpx
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from openai import AsyncOpenAI
from .sampling import deterministic_sample
from .contracts import iter_scalar_fields
from .llm.runtime_config import resolve_runtime_llm_config


PROCESS_SUBTYPES = (
    "semantic_filter",
    "field_derivation",
    "classification",
    "cross_node_synthesis",
)


ROW_MATERIALIZATION_PATTERNS = (
    r"\btarget\s+table\s+variable\b",
    r"\brow[-\s]*shaped\b",
    r"\bmateriali[sz]e\b",
    r"\b(?:create|emit|produce|return)\b.{0,120}\brows?\b",
    r"\b(?:create|emit|produce|return)\b.{0,120}\bfields?\b",
    r"\bpopulate\b.{0,120}\bfields?\b",
    r"\bone\s+row\s+per\b",
    r"\bstable_row_key\b",
    r"\brow_key\b",
    r"\bdedup(?:lication)?[_\s-]*key\b",
    r"\bsource_refs\b",
    r"\bsource_chunks\b",
)

# `CARDINALITY <exactly_input|zero_to_n>` is part of the declared PROCESS
# contract surface (see docs/GASL_GUIDE.md); it serializes as
# `output_cardinality`. A bare token is required so the `<a|b>` placeholder in
# the planner-facing grammar is not mistaken for a declaration.
OUTPUT_CARDINALITY_EXACTLY_INPUT = "exactly_input"
OUTPUT_CARDINALITY_ZERO_TO_N = "zero_to_n"
DECLARED_CARDINALITIES = (
    OUTPUT_CARDINALITY_EXACTLY_INPUT,
    OUTPUT_CARDINALITY_ZERO_TO_N,
)
DECLARED_CARDINALITY_PATTERN = re.compile(
    r"\bCARDINALITY\s+(" + "|".join(DECLARED_CARDINALITIES) + r")\b",
    flags=re.IGNORECASE,
)

ROW_PRESERVATION_PATTERNS = (
    r"\bemit\s+exactly\s+one\b",
    r"\bemit\s+one\s+row\s+for\s+every\b",
    r"\bone\s+row\s+per\s+input\b",
    r"\bone\s+row\s+for\s+every\s+input\b",
    r"\bone\s+row\s+per\s+current\b",
    r"\bone\s+row\s+per\s+collapsed\b",
    r"\bone\s+row\s+per\s+projected\b",
    r"\bone\s+row\s+per\s+input\s+path\b",
    r"\bone\s+row\s+per\s+path\b",
    r"\bone\s+row\s+per\s+estimate\b",
    r"\bone\s+row\s+per\s+candidate\b",
    r"\bone\s+row\s+per\s+row\b",
    r"\bpreserve\s+(?:the\s+)?one\s+row\s+per\b",
    r"\bpreserve\s+multiplicity\b",
)

ROW_MATERIALIZE_EACH_PATTERN = re.compile(
    r"\b(?:for|from)\s+(?:each|every)\b.{0,160}"
    r"\b(?:create|emit|produce|return|materiali[sz]e)\b.{0,80}\brows?\b"
    r"|"
    r"\b(?:create|emit|produce|return|materiali[sz]e)\b.{0,160}"
    r"\b(?:for|from)\s+(?:each|every)\b"
    r"|"
    r"\b(?:normalize|standardi[sz]e|transform)\b.{0,80}"
    r"\b(?:each|every)\b.{0,160}\brows?\b",
    flags=re.IGNORECASE,
)

SELECTIVE_ROW_CRITERIA_PATTERN = re.compile(
    r"\b(?:filter|select)\b"
    r"|"
    r"\b(?:include|keep)\s+only\b"
    r"|"
    r"\bonly\s+(?:rows?|items?|records?|entries?)\s+"
    r"(?:with|where|when|if|that|having|matching)\b"
    r"|"
    r"\b(?:exclude|omit|skip|drop)\b"
    r"|"
    r"\b(?:eligible|ineligible|matching|matches|criteria)\b"
    r"|"
    r"\bwhere\b",
    flags=re.IGNORECASE,
)


def requires_row_materialization(
    instruction: str,
    target_variable: Optional[str] = None,
) -> bool:
    """Return True when PROCESS must emit row objects, not filter decisions."""
    text = (instruction or "").lower()
    if target_variable and str(target_variable).endswith("_table"):
        return True
    return any(re.search(pattern, text) for pattern in ROW_MATERIALIZATION_PATTERNS)


def declared_output_cardinality(
    instruction: str,
    source_contract: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return the explicitly declared PROCESS output cardinality, if any.

    In practice this reads the `CARDINALITY <token>` clause of the instruction,
    which is planner output being read back out of planner output. The
    `output_cardinality` branch below is forward-looking: nothing in the tree
    populates that key today, so do not assume a caller supplies it. Returns
    None when nothing was declared, leaving the caller free to infer.
    """
    declared = (source_contract or {}).get("output_cardinality")
    if isinstance(declared, str) and declared.strip().lower() in DECLARED_CARDINALITIES:
        return declared.strip().lower()

    match = DECLARED_CARDINALITY_PATTERN.search(instruction or "")
    return match.group(1).lower() if match else None


def requires_input_row_preservation(
    instruction: str,
    interpretation: Optional[Dict[str, Any]] = None,
    *,
    target_variable: Optional[str] = None,
    source_contract: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return True when PROCESS should emit one result for each input row."""
    # An explicit declaration outranks every prose heuristic below. Those
    # heuristics exist to guess a cardinality that was never stated; when the
    # planner has stated one, guessing against it forces exactly-input
    # cardinality onto a contract that declared zero_to_n and fails every batch
    # whose eligible rows are fewer than its inputs.
    declared = declared_output_cardinality(instruction, source_contract)
    if declared is not None:
        return declared == OUTPUT_CARDINALITY_EXACTLY_INPUT

    text = f"{instruction or ''}\n{(interpretation or {}).get('output_contract') or ''}"
    compact = re.sub(r"[\s_-]+", " ", text.lower())

    if _has_explicit_row_preservation(compact):
        return True

    if _group_rows_default_to_preserve(target_variable, source_contract or {}):
        return not _has_selective_row_criteria(compact)

    return False


def _has_explicit_row_preservation(text: str) -> bool:
    return (
        any(re.search(pattern, text) for pattern in ROW_PRESERVATION_PATTERNS)
        or bool(ROW_MATERIALIZE_EACH_PATTERN.search(text))
    )


def _group_rows_default_to_preserve(
    target_variable: Optional[str],
    source_contract: Dict[str, Any],
) -> bool:
    return bool(
        target_variable
        and str(target_variable).endswith("_table")
        and (
            source_contract.get("payload_kind") == "collapsed_rows"
            or source_contract.get("grain_type") == "group"
        )
    )


def _has_selective_row_criteria(text: str) -> bool:
    return bool(SELECTIVE_ROW_CRITERIA_PATTERN.search(text))


# Response-protocol keys that name rows the model has *rejected*. A container
# under one of these names must never be mistaken for the accepted-row payload,
# because doing so would invert the model's decision. These are response
# vocabulary, not graph schema.
REJECTED_PAYLOAD_KEYS = frozenset(
    {
        "excluded",
        "excluded_items",
        "excluded_rows",
        "rejected",
        "rejected_items",
        "rejected_rows",
        "dropped",
        "dropped_items",
        "dropped_rows",
        "ineligible",
        "ineligible_items",
        "ineligible_rows",
        "errors",
        "warnings",
    }
)


def recover_row_container(
    parsed_result: Any,
    target_variable: Optional[str] = None,
) -> Optional[List[Any]]:
    """Recover the accepted-row array from a PROCESS response of any shape.

    Models routinely name the row container after the output they were asked to
    produce — the target variable, the table, the mode, or the task — rather
    than after the engine's canonical key. Those rows are well formed, so the
    engine recovers them instead of discarding the batch.

    Selection is by shape (exactly one list-valued key) and by runtime state
    (`target_variable`, the command's own AS binding). Container names are
    matched only against the response-protocol denylist in
    `REJECTED_PAYLOAD_KEYS`, never against graph schema or any vocabulary of
    field names. That denylist is incomplete by construction, so an
    unrecognized rejection container can still be read as the accepted set;
    the row-shape guard below limits, but does not eliminate, that risk.

    Returns None when no unambiguous row container is present, leaving the
    caller to apply its own fallback.
    """
    if isinstance(parsed_result, list):
        return parsed_result
    if not isinstance(parsed_result, dict):
        return None

    if target_variable:
        value = parsed_result.get(str(target_variable))
        if isinstance(value, list) and _is_row_container(value):
            return value

    containers = [
        value
        for key, value in parsed_result.items()
        if isinstance(value, list)
        and str(key).strip().lower() not in REJECTED_PAYLOAD_KEYS
        and _is_row_container(value)
    ]
    if len(containers) == 1:
        return containers[0]
    return None


def _is_row_container(value: List[Any]) -> bool:
    """Rows are objects. An empty array is a valid zero-row answer."""
    return not value or any(isinstance(item, dict) for item in value)


def normalize_table_items(
    items: List[Dict[str, Any]],
    target_variable: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lift wrapped row payloads and remove sibling table rows."""
    if not target_variable or not str(target_variable).endswith("_table"):
        return items

    normalized: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        table_item = _lift_wrapped_table_item(item)
        table_name = table_item.get("table_name")
        if table_name and table_name != target_variable:
            continue
        normalized.append(table_item)
    return normalized


def _lift_wrapped_table_item(item: Dict[str, Any]) -> Dict[str, Any]:
    nested_key = _best_wrapped_row_key(item)
    if not nested_key:
        return item

    lifted = {
        key: value
        for key, value in item.items()
        if key not in {nested_key, "items"}
    }
    lifted.update(item[nested_key])
    return lifted


def _best_wrapped_row_key(item: Dict[str, Any]) -> str:
    best_key = ""
    best_score = 0
    for key, value in item.items():
        if not isinstance(value, dict):
            continue
        key_text = str(key).lower()
        if key_text not in {"row", "record"} and not (
            key_text.endswith("_row") or key_text.endswith("_record")
        ):
            continue
        score = sum(
            1
            for field in (
                "deduplication_key",
                "row_id",
                "source_refs",
                "source_chunks",
                "table_name",
                "entity_type",
                "relation_type",
            )
            if field in value
        )
        if score > best_score:
            best_key = key
            best_score = score
    return best_key


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
        r"\bcreate\b",
        r"\bderive\b",
        r"\bemit\b",
        r"\bextract\b",
        r"\bmateriali[sz]e\b",
        r"\bnormalize\b",
        r"\bpopulate\b",
        r"\bproduce\b",
        r"\breturn\b.{0,120}\brows?\b",
        r"\bstandardize\b",
        r"\badd field\b",
        r"\bmap\b",
    )

    def infer(self, instruction: str) -> str:
        text = (instruction or "").lower()
        if any(re.search(p, text) for p in self.CLASSIFY_PATTERNS):
            return "classification"
        if requires_row_materialization(instruction):
            return "field_derivation"
        if any(re.search(p, text) for p in self.DERIVE_PATTERNS):
            return "field_derivation"
        if any(re.search(p, text) for p in self.FILTER_PATTERNS):
            return "semantic_filter"
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
        mini_override = os.getenv("PROCESS_MINI_MODEL", "").strip()
        large_default = os.getenv("PROCESS_LARGE_MODEL", model or "gpt-5.5").strip()
        if subtype in {"semantic_filter", "field_derivation"}:
            return mini_override or model or large_default
        if subtype == "cross_node_synthesis" and "mini" in model.lower():
            return large_default
        return model or large_default


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
        runtime_cfg = resolve_runtime_llm_config(explicit_api_key=api_key)
        self.api_key = runtime_cfg.api_key
        self.base_url = runtime_cfg.base_url
        self.transport = runtime_cfg.transport
        self.shim_user = os.getenv("NANOGRAPHRAG_SHIM_USER", "chia")
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

        positive_ids = {self._stable_item_key(item) for item in positives if isinstance(item, dict)}
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
        exact_fields = []
        if isinstance(item, dict):
            for field_name, value in iter_scalar_fields(item, max_depth=2):
                if field_name.endswith(".id") or field_name == "id":
                    exact_fields.append(str(value).lower())
        for tok in tokens:
            if any(tok == v for v in exact_fields):
                score += 5
            elif any(tok in v for v in exact_fields):
                score += 2
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
        contents = [self._item_search_text(item)[:2000] for item in data]
        if self.transport == "shim":
            async with httpx.AsyncClient(headers={"x-api-key": self.api_key or ""}) as client:
                query_resp = await client.post(
                    self.base_url.rstrip("/") + "/embeddings",
                    json={"model": "text-embedding-3-small", "input": [text], "encoding_format": "float", "user": self.shim_user},
                )
                item_resp = await client.post(
                    self.base_url.rstrip("/") + "/embeddings",
                    json={"model": "text-embedding-3-small", "input": contents, "encoding_format": "float", "user": self.shim_user},
                )
            q_json = query_resp.json()
            i_json = item_resp.json()
            q = q_json["data"][0]["embedding"]
            sims = []
            for item, emb in zip(data, i_json["data"]):
                sims.append((item, self._cosine(q, emb["embedding"])))
            sims.sort(key=lambda pair: pair[1], reverse=True)
            return [item for item, _ in sims[:top_k]]
        if self._client is None:
            client_kwargs = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self._client = AsyncOpenAI(**client_kwargs)
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
        """The anti-rank-bias draw that rounds out the ranked slices above.

        The implementation moved to `gasl.sampling.deterministic_sample`, which
        is now the engine's only sampler: this one was correct and the other one
        -- a stratifier in the refinement agent that never executed -- is gone.
        One implementation, so a fix to sampling is a fix everywhere.
        """
        return deterministic_sample(
            data, seed_text=f"{query}|{instruction}|{subtype}", k=k
        )

    @staticmethod
    def _merge_unique(*groups: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen = set()
        for group in groups:
            for item in group:
                item_key = CandidateSelector._stable_item_key(item)
                if item_key in seen:
                    continue
                seen.add(item_key)
                merged.append(item)
        return merged

    @staticmethod
    def _item_search_text(item: Dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return str(item).lower()
        parts: list[str] = []
        for field_name, value in iter_scalar_fields(item, max_depth=2):
            if field_name.endswith(".id") or field_name == "id":
                parts.append(str(value))
                continue
            parts.append(str(value))
        return " ".join(parts).lower()

    @staticmethod
    def _stable_item_key(item: Any) -> str:
        if not isinstance(item, dict):
            return str(item)
        key_parts = []
        for field_name, value in iter_scalar_fields(item, max_depth=2):
            if isinstance(value, (str, int, float, bool)):
                key_parts.append((field_name, str(value)))
        if not key_parts:
            return str(id(item))
        encoded = json.dumps(sorted(key_parts), ensure_ascii=True)
        return hashlib.sha1(encoded.encode("utf-8")).hexdigest()

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
        node_id = self._stable_item_key(item)
        text = self._item_search_text(item)
        score = 0
        if node_id in positive_ids:
            score += 10
        score += sum(1 for tok in positive_terms if tok in text)
        return score
