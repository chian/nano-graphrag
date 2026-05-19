from __future__ import annotations

from collections import defaultdict

from ..types import AnswerView
from ..utils import candidate_group_fields, distinct_dimension_fields, infer_support_field, top_evidence_refs


def build(view_id: str, variable_name: str, rows: list[dict], meta: dict) -> AnswerView:
    group_field = next(iter(candidate_group_fields(rows, meta)), None)
    if not group_field:
        return AnswerView(view_id=view_id, kind="ranked_subjects", source_variable=variable_name, sufficient=False, payload={})
    dimension_field = next(iter(distinct_dimension_fields(rows, meta, exclude={group_field})), None)
    support_field = infer_support_field(rows, exclude={group_field, *( {dimension_field} if dimension_field else set() )})
    grouped: dict[str, dict] = defaultdict(lambda: {"rows": 0, "dimensions": set(), "support": set()})
    for row in rows:
        subject = row.get(group_field)
        if subject is None:
            continue
        bucket = grouped[str(subject)]
        bucket["rows"] += 1
        if dimension_field and row.get(dimension_field) is not None:
            bucket["dimensions"].add(str(row.get(dimension_field)))
        if support_field and row.get(support_field) is not None:
            bucket["support"].add(str(row.get(support_field)))
    ranked = []
    for subject, bucket in grouped.items():
        count = len(bucket["dimensions"]) if bucket["dimensions"] else bucket["rows"]
        ranked.append({"item": subject, "count": count, "support_n": len(bucket["support"])})
    ranked.sort(key=lambda x: (-x["count"], -x["support_n"], x["item"]))
    payload = {
        "group_field": group_field,
        "dimension_field": dimension_field or "",
        "support_field": support_field or "",
        "ranked_items": ranked[:10],
        "row_count": len(rows),
    }
    return AnswerView(
        view_id=view_id,
        kind="ranked_subjects",
        source_variable=variable_name,
        sufficient=bool(ranked),
        payload=payload,
        metadata={"evidence_refs": top_evidence_refs(rows, group_field)},
    )
