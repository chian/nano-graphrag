from __future__ import annotations

from ..types import AnswerView
from ..utils import candidate_group_fields, top_evidence_refs


def build(view_id: str, variable_name: str, rows: list[dict], meta: dict) -> AnswerView:
    group_field = next(iter(candidate_group_fields(rows, meta)), None)
    if not group_field:
        return AnswerView(view_id=view_id, kind="evidence_lookup", source_variable=variable_name, sufficient=False, payload={})
    refs = top_evidence_refs(rows, group_field)
    return AnswerView(
        view_id=view_id,
        kind="evidence_lookup",
        source_variable=variable_name,
        sufficient=bool(refs),
        payload={"group_field": group_field, "refs": refs},
    )
