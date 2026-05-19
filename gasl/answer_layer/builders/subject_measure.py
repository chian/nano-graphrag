from __future__ import annotations

from collections import defaultdict
from statistics import mean

from ..types import AnswerView
from ..utils import candidate_group_fields, distinct_dimension_fields, numeric_fields


def build(view_id: str, variable_name: str, rows: list[dict], meta: dict) -> AnswerView:
    subject_field = next(iter(candidate_group_fields(rows, meta)), None)
    if not subject_field:
        return AnswerView(view_id=view_id, kind="subject_measure", source_variable=variable_name, sufficient=False, payload={})
    measure_field = next(iter(numeric_fields(rows, meta.get("metric_field"))), None)
    if not measure_field:
        return AnswerView(view_id=view_id, kind="subject_measure", source_variable=variable_name, sufficient=False, payload={})
    dimension_field = next(iter(distinct_dimension_fields(rows, meta, exclude={subject_field, measure_field})), None)
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        subject = row.get(subject_field)
        measure = row.get(measure_field)
        if subject is None or not isinstance(measure, (int, float)):
            continue
        dimension = str(row.get(dimension_field)) if dimension_field and row.get(dimension_field) is not None else "__all__"
        grouped[(str(subject), dimension)].append(float(measure))
    matrix = []
    for (subject, dimension), values in grouped.items():
        matrix.append({"subject": subject, "dimension": dimension, "measure": mean(values), "n": len(values)})
    matrix.sort(key=lambda x: (-abs(x["measure"]), -x["n"], x["subject"], x["dimension"]))
    return AnswerView(
        view_id=view_id,
        kind="subject_measure",
        source_variable=variable_name,
        sufficient=bool(matrix),
        payload={
            "subject_field": subject_field,
            "dimension_field": dimension_field or "",
            "measure_field": measure_field,
            "rows": matrix[:50],
            "row_count": len(rows),
        },
    )
