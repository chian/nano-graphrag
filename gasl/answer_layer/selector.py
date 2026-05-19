from __future__ import annotations

from .types import AnswerSelection, AnswerView
from .utils import tokenize_query


class AnswerViewSelector:
    def select(self, query: str, views: list[AnswerView]) -> AnswerSelection:
        if not views:
            return AnswerSelection(view=None, rationale="no views built")
        tokens = tokenize_query(query)
        scored: list[tuple[tuple[int, int, int], AnswerView, str]] = []
        for view in views:
            if not view.sufficient:
                continue
            intent_score = 0
            rationale = "highest sufficiency"
            if view.kind == "distribution" and tokens & {"distribution", "histogram", "normal", "lognormal", "power", "gumbel"}:
                intent_score += 4
                rationale = "distribution intent"
            if view.kind == "comparison" and tokens & {"compare", "comparison", "versus", "vs", "balance"}:
                intent_score += 4
                rationale = "comparison intent"
            if view.kind == "ranked_subjects" and tokens & {"top", "most", "main", "highest", "strongest", "widest", "broadest"}:
                intent_score += 4
                rationale = "ranking intent"
            if view.kind == "evidence_lookup" and tokens & {"evidence", "study", "source", "support"}:
                intent_score += 3
                rationale = "evidence intent"
            compactness = 100 - min(len(str(view.payload)), 100)
            support = int(bool(view.metadata))
            scored.append(((intent_score, support, compactness), view, rationale))
        if not scored:
            return AnswerSelection(view=None, rationale="no sufficient view")
        scored.sort(key=lambda x: x[0], reverse=True)
        _, view, rationale = scored[0]
        return AnswerSelection(view=view, rationale=rationale)
