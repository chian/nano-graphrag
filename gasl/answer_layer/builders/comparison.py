from __future__ import annotations

from ..types import AnswerView


def build(view_id: str, ranking_view: AnswerView, grouped_summary_view: AnswerView | None = None) -> AnswerView:
    ranked_items = ranking_view.payload.get("ranked_subjects", []) if ranking_view else []
    if len(ranked_items) < 2:
        return AnswerView(view_id=view_id, kind="comparison", source_variable=ranking_view.source_variable if ranking_view else "", sufficient=False, payload={})
    left, right = ranked_items[0], ranked_items[1]
    return AnswerView(
        view_id=view_id,
        kind="comparison",
        source_variable=ranking_view.source_variable,
        sufficient=True,
        payload={
            "comparands": [left["subject"], right["subject"]],
            "left_score": left.get("score", 0),
            "right_score": right.get("score", 0),
            "delta": left.get("score", 0) - right.get("score", 0),
        },
    )
