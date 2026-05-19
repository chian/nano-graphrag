from __future__ import annotations

from collections import defaultdict

from ..types import AnswerView


def build(view_id: str, grouped_summary_view: AnswerView) -> AnswerView:
    rows = grouped_summary_view.payload.get("rows", [])
    if not rows:
        return AnswerView(view_id=view_id, kind="frontier", source_variable=grouped_summary_view.source_variable, sufficient=False, payload={})
    metrics_by_subject: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        if isinstance(row.get("measure_mean"), (int, float)) and row.get("outcome"):
            metrics_by_subject[row["subject"]][row["outcome"]] = abs(float(row["measure_mean"]))
    outcomes = sorted({outcome for metrics in metrics_by_subject.values() for outcome in metrics.keys()})
    if len(outcomes) < 2:
        return AnswerView(view_id=view_id, kind="frontier", source_variable=grouped_summary_view.source_variable, sufficient=False, payload={})
    points = []
    for subject, metrics in metrics_by_subject.items():
        points.append({"subject": subject, "metrics": metrics})

    frontier_subjects = []
    for candidate in points:
        dominated = False
        for other in points:
            if other is candidate:
                continue
            other_ge = all(other["metrics"].get(o, float("-inf")) >= candidate["metrics"].get(o, float("-inf")) for o in outcomes)
            other_gt = any(other["metrics"].get(o, float("-inf")) > candidate["metrics"].get(o, float("-inf")) for o in outcomes)
            if other_ge and other_gt:
                dominated = True
                break
        if not dominated:
            frontier_subjects.append(candidate)
    frontier_subjects.sort(key=lambda x: x["subject"])
    return AnswerView(
        view_id=view_id,
        kind="frontier",
        source_variable=grouped_summary_view.source_variable,
        sufficient=bool(frontier_subjects),
        payload={"outcomes": outcomes, "subjects": frontier_subjects},
    )
