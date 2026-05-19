from __future__ import annotations

from ..types import AnswerView
from ..utils import distribution_summary, numeric_fields


def build(view_id: str, variable_name: str, rows: list[dict], meta: dict) -> AnswerView:
    measure_field = next(iter(numeric_fields(rows, meta.get("metric_field"))), None)
    if not measure_field:
        return AnswerView(view_id=view_id, kind="distribution", source_variable=variable_name, sufficient=False, payload={})
    values = [float(row.get(measure_field)) for row in rows if isinstance(row.get(measure_field), (int, float))]
    summary = distribution_summary(values)
    return AnswerView(
        view_id=view_id,
        kind="distribution",
        source_variable=variable_name,
        sufficient=bool(summary),
        payload={"measure_field": measure_field, **summary},
    )
