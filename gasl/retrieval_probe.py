from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence


@dataclass
class ProbeDecision:
    strategy: str
    sample: List[Dict[str, Any]]
    validation: Dict[str, Any] = field(default_factory=dict)
    adapted: bool = False
    reason: str = ""


class RetrievalProbePolicy:
    """Generic probe -> score -> adapt helper for broad retrieval/filter steps."""

    PROBE_SIZE = 20

    @classmethod
    def sample_rows(cls, rows: Sequence[Dict[str, Any]], *, seed_text: str, k: int | None = None) -> List[Dict[str, Any]]:
        items = list(rows or [])
        limit = min(k or cls.PROBE_SIZE, len(items))
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
    def should_adapt(validation: Dict[str, Any], total_count: int, *, min_count: int = 30) -> bool:
        if total_count < min_count:
            return False
        if not validation:
            return False
        if validation.get("valid") is False:
            return True
        if validation.get("semantically_valid") is False:
            return True
        confidence = float(validation.get("confidence", 1.0) or 1.0)
        return confidence < 0.55
