from __future__ import annotations

from .builders import comparison, distribution, evidence_lookup, ranked_subjects, subject_measure
from .selector import AnswerViewSelector
from .types import AnswerSelection, AnswerView
from .utils import enumerate_row_variables


class AnswerLayerCompiler:
    def build_views(self, runtime_view: dict) -> list[AnswerView]:
        views: list[AnswerView] = []
        row_vars = enumerate_row_variables(runtime_view)
        for idx, candidate in enumerate(row_vars):
            name, rows, meta = candidate["name"], candidate["rows"], candidate["meta"]
            if not rows:
                continue
            views.append(ranked_subjects.build(f"{name}:ranked_subjects", name, rows, meta))
            views.append(subject_measure.build(f"{name}:subject_measure", name, rows, meta))
            views.append(distribution.build(f"{name}:distribution", name, rows, meta))
            views.append(evidence_lookup.build(f"{name}:evidence_lookup", name, rows, meta))

        ranked = next((v for v in views if v.kind == "ranked_subjects" and v.sufficient), None)
        measure = next((v for v in views if v.kind == "subject_measure" and v.sufficient), None)
        if ranked:
            views.append(comparison.build("comparison:primary", ranked, measure))
        return views

    def select_view(self, query: str, views: list[AnswerView]) -> AnswerSelection:
        return AnswerViewSelector().select(query, views)
