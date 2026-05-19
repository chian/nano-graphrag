from __future__ import annotations

from ..types import AnswerView


def build(view_id: str, ranked_view: AnswerView, measure_view: AnswerView | None = None) -> AnswerView:
    ranked_items = ranked_view.payload.get("ranked_items", []) if ranked_view else []
    if len(ranked_items) < 2:
        return AnswerView(view_id=view_id, kind="comparison", source_variable=ranked_view.source_variable if ranked_view else "", sufficient=False, payload={})
    left, right = ranked_items[0], ranked_items[1]
    measure_field = ""
    delta = left.get("count", 0) - right.get("count", 0)
    if measure_view and measure_view.payload.get("rows"):
        measure_field = measure_view.payload.get("measure_field", "")
    return AnswerView(
        view_id=view_id,
        kind="comparison",
        source_variable=ranked_view.source_variable,
        sufficient=True,
        payload={
            "comparands": [left["item"], right["item"]],
            "measure_field": measure_field,
            "left_score": left.get("count", 0),
            "right_score": right.get("count", 0),
            "delta": delta,
        },
    )
