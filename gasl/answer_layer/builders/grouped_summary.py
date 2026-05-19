from __future__ import annotations

from collections import defaultdict
from statistics import mean

from ..types import AnswerView


def build(view_id: str, evidence_view: AnswerView) -> AnswerView:
    rows = evidence_view.payload.get("rows", [])
    if not rows:
        return AnswerView(view_id=view_id, kind="grouped_summary", source_variable=evidence_view.source_variable, sufficient=False, payload={})
    grouped: dict[tuple[str, str], dict] = defaultdict(lambda: {"measures": [], "supports": set(), "count": 0})
    for row in rows:
        subject = row.get("subject", "")
        outcome = row.get("outcome", "")
        key = (subject, outcome)
        grouped[key]["count"] += 1
        if isinstance(row.get("measure"), (int, float)):
            grouped[key]["measures"].append(float(row["measure"]))
        if row.get("support"):
            grouped[key]["supports"].add(str(row["support"]))

    summary_rows = []
    for (subject, outcome), bucket in grouped.items():
        summary_rows.append(
            {
                "subject": subject,
                "outcome": outcome,
                "measure_mean": mean(bucket["measures"]) if bucket["measures"] else None,
                "measure_n": len(bucket["measures"]),
                "support_n": len(bucket["supports"]),
                "evidence_n": bucket["count"],
            }
        )
    summary_rows.sort(
        key=lambda x: (
            -(x["support_n"] or 0),
            -(abs(x["measure_mean"]) if isinstance(x["measure_mean"], (int, float)) else 0.0),
            -(x["evidence_n"] or 0),
            x["subject"],
            x["outcome"],
        )
    )
    return AnswerView(
        view_id=view_id,
        kind="grouped_summary",
        source_variable=evidence_view.source_variable,
        sufficient=bool(summary_rows),
        payload={"rows": summary_rows[:200], "row_count": len(summary_rows)},
    )
