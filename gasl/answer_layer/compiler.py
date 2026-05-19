from __future__ import annotations

from .builders import comparison, distribution, evidence_table, frontier, grouped_summary, provenance, ranking
from .selector import AnswerViewSelector
from .types import AnswerSelection, AnswerView
from .utils import enumerate_row_variables


class AnswerLayerCompiler:
    def build_views(self, runtime_view: dict) -> list[AnswerView]:
        views: list[AnswerView] = []
        evidence_views: list[AnswerView] = []
        grouped_views: list[AnswerView] = []
        row_vars = enumerate_row_variables(runtime_view)
        for candidate in row_vars:
            name, rows, meta = candidate["name"], candidate["rows"], candidate["meta"]
            if not rows:
                continue
            eview = evidence_table.build(f"{name}:evidence_table", name, rows, meta)
            views.append(eview)
            evidence_views.append(eview)
        for eview in evidence_views:
            if not eview.sufficient:
                continue
            gview = grouped_summary.build(f"{eview.source_variable}:grouped_summary", eview)
            pview = provenance.build(f"{eview.source_variable}:provenance", eview)
            views.extend([gview, pview])
            grouped_views.append(gview)
        ranking_view = None
        for gview in grouped_views:
            if not gview.sufficient:
                continue
            rview = ranking.build(f"{gview.source_variable}:ranking", gview)
            dview = distribution.build(f"{gview.source_variable}:distribution", gview)
            fview = frontier.build(f"{gview.source_variable}:frontier", gview)
            views.extend([rview, dview, fview])
            if ranking_view is None and rview.sufficient:
                ranking_view = rview
        if ranking_view:
            best_grouped = next((v for v in grouped_views if v.sufficient and v.source_variable == ranking_view.source_variable), None)
            views.append(comparison.build("comparison:primary", ranking_view, best_grouped))
        return views

    def select_view(self, query: str, views: list[AnswerView], llm_func=None) -> AnswerSelection:
        return AnswerViewSelector().select(query, views, llm_func=llm_func)
