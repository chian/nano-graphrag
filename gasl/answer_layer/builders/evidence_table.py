from __future__ import annotations

from ..types import AnswerView
from ..utils import candidate_group_fields, distinct_dimension_fields, infer_support_field, numeric_fields


def build(view_id: str, variable_name: str, rows: list[dict], meta: dict) -> AnswerView:
    subject_field = next(iter(candidate_group_fields(rows, meta)), None)
    measure_field = next(iter(numeric_fields(rows, meta.get("metric_field"))), None)
    outcome_field = next(iter(distinct_dimension_fields(rows, meta, exclude={*( {subject_field} if subject_field else set() ), *( {measure_field} if measure_field else set() )})), None)
    support_field = infer_support_field(rows, exclude={*( {subject_field} if subject_field else set() ), *( {measure_field} if measure_field else set() ), *( {outcome_field} if outcome_field else set() )})

    if not subject_field:
        return AnswerView(view_id=view_id, kind="evidence_table", source_variable=variable_name, sufficient=False, payload={})

    evidence_rows = []
    for row in rows:
        subject = row.get(subject_field)
        if subject is None:
            continue
        evidence_rows.append(
            {
                "subject": str(subject),
                "outcome": str(row.get(outcome_field)) if outcome_field and row.get(outcome_field) is not None else "",
                "measure": float(row.get(measure_field)) if measure_field and isinstance(row.get(measure_field), (int, float)) else None,
                "unit": "",
                "uncertainty": None,
                "support": str(row.get(support_field)) if support_field and row.get(support_field) is not None else "",
                "raw": row,
            }
        )
    return AnswerView(
        view_id=view_id,
        kind="evidence_table",
        source_variable=variable_name,
        sufficient=bool(evidence_rows),
        payload={
            "subject_field": subject_field,
            "outcome_field": outcome_field or "",
            "measure_field": measure_field or "",
            "support_field": support_field or "",
            "rows": evidence_rows[:200],
            "row_count": len(evidence_rows),
        },
    )
