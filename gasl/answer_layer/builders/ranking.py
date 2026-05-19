from __future__ import annotations

from collections import defaultdict

from ..types import AnswerView


def build(view_id: str, grouped_summary_view: AnswerView) -> AnswerView:
    rows = grouped_summary_view.payload.get("rows", [])
    if not rows:
        return AnswerView(view_id=view_id, kind="ranking", source_variable=grouped_summary_view.source_variable, sufficient=False, payload={})
    by_subject: dict[str, dict] = defaultdict(lambda: {"score": 0.0, "outcomes": set(), "support_n": 0})
    for row in rows:
        subject = row["subject"]
        by_subject[subject]["support_n"] += row.get("support_n", 0)
        if row.get("outcome"):
            by_subject[subject]["outcomes"].add(row["outcome"])
        if isinstance(row.get("measure_mean"), (int, float)):
            by_subject[subject]["score"] += abs(float(row["measure_mean"]))
        else:
            by_subject[subject]["score"] += row.get("evidence_n", 0)
    ranked = []
    for subject, bucket in by_subject.items():
        ranked.append(
            {
                "subject": subject,
                "score": bucket["score"],
                "outcome_count": len(bucket["outcomes"]),
                "support_n": bucket["support_n"],
            }
        )
    ranked.sort(key=lambda x: (-x["score"], -x["outcome_count"], -x["support_n"], x["subject"]))
    return AnswerView(
        view_id=view_id,
        kind="ranking",
        source_variable=grouped_summary_view.source_variable,
        sufficient=bool(ranked),
        payload={"ranked_subjects": ranked[:50], "row_count": len(ranked)},
    )
