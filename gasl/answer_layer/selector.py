from __future__ import annotations

from .adjudicator import AnswerViewAdjudicator
from .types import AnswerSelection, AnswerView
from .utils import tokenize_query


class AnswerViewSelector:
    def select(self, query: str, views: list[AnswerView], llm_func=None) -> AnswerSelection:
        if not views:
            return AnswerSelection(view=None, rationale="no views built")
        tokens = tokenize_query(query)
        views_by_id = {view.view_id: view for view in views}
        scored: list[tuple[tuple[int, int, int], AnswerView, str]] = []
        grouped_candidates: list[AnswerView] = []
        provenance_candidates: list[AnswerView] = []
        for view in views:
            if not view.sufficient:
                continue
            intent_score = 0
            rationale = "highest sufficiency"
            if view.kind == "answer_bundle" and tokens & {"table", "tables", "view", "views"}:
                intent_score += 8
                rationale = "multi-view table intent"
            if view.kind == "grouped_summary":
                grouped_candidates.append(view)
            if view.kind == "provenance":
                provenance_candidates.append(view)
            if view.kind == "distribution" and tokens & {"distribution", "histogram", "normal", "lognormal", "power", "gumbel"}:
                intent_score += 4
                rationale = "distribution intent"
            if view.kind == "comparison" and tokens & {"compare", "comparison", "versus", "vs", "balance"}:
                intent_score += 4
                rationale = "comparison intent"
            if view.kind == "frontier" and tokens & {"tradeoff", "trade-off", "pareto", "balance"}:
                intent_score += 5
                rationale = "frontier intent"
            if view.kind == "ranking" and tokens & {"top", "most", "main", "highest", "strongest", "widest", "broadest"}:
                intent_score += 4
                rationale = "ranking intent"
            if view.kind == "provenance" and tokens & {"evidence", "study", "source", "support"}:
                intent_score += 3
                rationale = "evidence intent"
            if view.kind == "grouped_summary" and tokens & {"effect", "outcome", "measure", "morbidity", "mortality", "rate", "risk"}:
                intent_score += 4
                rationale = "summary-by-outcome intent"
            compactness = 100 - min(len(str(view.payload)), 100)
            support = int(bool(view.metadata))
            scored.append(((intent_score, support, compactness), view, rationale))
        if not scored:
            return AnswerSelection(view=None, rationale="no sufficient view")
        scored.sort(key=lambda x: x[0], reverse=True)
        top_score = scored[0][0]
        ambiguous = [
            (score, view, rationale)
            for score, view, rationale in scored
            if score[0] >= top_score[0] - 1 and score[1] >= top_score[1] - 1
        ]
        _, view, rationale = scored[0]
        if llm_func and len(ambiguous) > 1:
            candidate_views = [candidate_view for _, candidate_view, _ in ambiguous if candidate_view.kind != view.kind or candidate_view.source_variable != view.source_variable]
            # Keep only meaningfully different alternatives plus the deterministic winner.
            candidate_views = [view] + candidate_views[:3]
            adj = AnswerViewAdjudicator(llm_func).adjudicate(query, candidate_views)
            if adj.selected_view_id:
                chosen = next((candidate for candidate in candidate_views if candidate.view_id == adj.selected_view_id), None)
                if chosen is not None:
                    view = chosen
                    rationale = f"llm_adjudicated: {adj.rationale}"
        supporting: list[AnswerView] = []
        if view.kind == "ranking":
            supporting.extend(v for v in grouped_candidates if v.source_variable == view.source_variable)
            supporting.extend(v for v in provenance_candidates if v.source_variable == view.source_variable)
        elif view.kind == "grouped_summary":
            supporting.extend(v for v in provenance_candidates if v.source_variable == view.source_variable)
        elif view.kind == "frontier":
            supporting.extend(v for v in grouped_candidates if v.source_variable == view.source_variable)
            supporting.extend(v for v in provenance_candidates if v.source_variable == view.source_variable)
        elif view.kind == "answer_bundle":
            for view_id in [
                *view.payload.get("primary_view_ids", []),
                *view.payload.get("diagnostic_view_ids", []),
            ]:
                supporting_view = views_by_id.get(view_id)
                if supporting_view is not None and supporting_view.sufficient:
                    supporting.append(supporting_view)
        support_limit = 8 if view.kind == "answer_bundle" else 3
        return AnswerSelection(
            view=view,
            supporting_views=supporting[:support_limit],
            rationale=rationale,
        )
