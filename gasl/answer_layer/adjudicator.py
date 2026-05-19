from __future__ import annotations

import json
from dataclasses import dataclass

from .types import AnswerView


@dataclass
class AdjudicationResult:
    selected_view_id: str | None
    rationale: str


class AnswerViewAdjudicator:
    """Optional semantic tie-breaker for ambiguous answer-view selection."""

    def __init__(self, llm_func):
        self.llm_func = llm_func

    def adjudicate(self, query: str, candidates: list[AnswerView]) -> AdjudicationResult:
        if not candidates:
            return AdjudicationResult(selected_view_id=None, rationale="no candidates")
        prompt = self._build_prompt(query, candidates)
        raw = self.llm_func.call(prompt)
        try:
            parsed = json.loads(raw)
        except Exception:
            return AdjudicationResult(selected_view_id=None, rationale="adjudicator parse failure")
        view_id = parsed.get("selected_view_id")
        rationale = parsed.get("rationale", "")
        if not any(view.view_id == view_id for view in candidates):
            return AdjudicationResult(selected_view_id=None, rationale="adjudicator selected unknown view")
        return AdjudicationResult(selected_view_id=view_id, rationale=rationale)

    @staticmethod
    def _build_prompt(query: str, candidates: list[AnswerView]) -> str:
        compact = []
        for view in candidates:
            compact.append(
                {
                    "view_id": view.view_id,
                    "kind": view.kind,
                    "source_variable": view.source_variable,
                    "payload_preview": _payload_preview(view.payload),
                }
            )
        return (
            "You are choosing the best answer view for a question. "
            "The views are already structurally valid. Choose the one whose framing best matches the question intent. "
            "Do not invent data. Return strict JSON only.\n\n"
            f"Question:\n{query}\n\n"
            f"Candidate views:\n{json.dumps(compact, ensure_ascii=False, indent=2)}\n\n"
            'Return JSON: {"selected_view_id": "<one candidate view_id>", "rationale": "<short reason>"}'
        )


def _payload_preview(payload: dict) -> dict:
    preview = {}
    for key, value in payload.items():
        if isinstance(value, list):
            preview[key] = value[:3]
        else:
            preview[key] = value
    return preview
