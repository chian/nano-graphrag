from __future__ import annotations

from ..types import AnswerView
from ..utils import distribution_summary


def build(view_id: str, grouped_summary_view: AnswerView) -> AnswerView:
    rows = grouped_summary_view.payload.get("rows", [])
    values = [float(row.get("measure_mean")) for row in rows if isinstance(row.get("measure_mean"), (int, float))]
    if not values:
        return AnswerView(view_id=view_id, kind="distribution", source_variable=grouped_summary_view.source_variable, sufficient=False, payload={})
    summary = distribution_summary(values)
    return AnswerView(
        view_id=view_id,
        kind="distribution",
        source_variable=grouped_summary_view.source_variable,
        sufficient=bool(summary),
        payload={"measure_field": "measure_mean", **summary},
    )
