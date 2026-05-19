from __future__ import annotations

from ..types import AnswerView
from ..utils import top_evidence_refs


def build(view_id: str, evidence_view: AnswerView) -> AnswerView:
    rows = evidence_view.payload.get("rows", [])
    if not rows:
        return AnswerView(view_id=view_id, kind="provenance", source_variable=evidence_view.source_variable, sufficient=False, payload={})
    raw_rows = [row.get("raw", {}) for row in rows if row.get("raw")]
    refs = top_evidence_refs(raw_rows, evidence_view.payload.get("subject_field", "subject"))
    return AnswerView(
        view_id=view_id,
        kind="provenance",
        source_variable=evidence_view.source_variable,
        sufficient=bool(refs),
        payload={"refs": refs},
    )
