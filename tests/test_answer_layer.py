from gasl.answer_layer import AnswerLayerCompiler, DeterministicAnswerFinalizer
from gasl.answer_layer.selector import AnswerViewSelector
from gasl.answer_layer.types import AnswerView


class _FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def call(self, prompt: str) -> str:
        self.calls += 1
        return self.response


def _runtime_view():
    return {
        "state_variables": {
            "grouped_relation_rows": {
                "_meta": {"type": "LIST", "contract": {"label_field": "item_label"}},
                "items": [
                    {"item_key": "alpha", "item_label": "Alpha", "dim_key": "x1", "row_id": "r1"},
                    {"item_key": "alpha", "item_label": "Alpha", "dim_key": "x2", "row_id": "r2"},
                    {"item_key": "beta", "item_label": "Beta", "dim_key": "x1", "row_id": "r3"},
                    {"item_key": "beta", "item_label": "Beta", "dim_key": "x1", "row_id": "r4"},
                ],
            },
            "numeric_fact_rows": {
                "_meta": {"type": "LIST", "contract": {"metric_field": "metric_a"}},
                "items": [
                    {"entity_key": "alpha", "measure_name": "m1", "metric_a": 7.0},
                    {"entity_key": "beta", "measure_name": "m1", "metric_a": 3.0},
                    {"entity_key": "alpha", "measure_name": "m2", "metric_a": 8.0},
                    {"entity_key": "beta", "measure_name": "m2", "metric_a": 4.0},
                ],
            },
        },
        "context_variables": {},
        "produced_artifacts": [
            {
                "variable": "grouped_relation_rows",
                "payload_kind": "filtered_rows",
                "item_count": 4,
                "label_field": "item_label",
                "grain_type": "edge",
                "safe_for": ["PROCESS", "AGGREGATE", "SHOW", "SELECT"],
            },
            {
                "variable": "numeric_fact_rows",
                "payload_kind": "projected_rows",
                "item_count": 4,
                "label_field": "entity_key",
                "metric_field": "metric_a",
                "grain_type": "row",
                "safe_for": ["PROCESS", "AGGREGATE", "SHOW", "SELECT"],
            },
        ],
        "history": [],
    }


def test_compiler_builds_generic_views():
    compiler = AnswerLayerCompiler()
    views = compiler.build_views(_runtime_view())
    kinds = {view.kind for view in views if view.sufficient}
    assert "evidence_table" in kinds
    assert "grouped_summary" in kinds
    assert "ranking" in kinds
    assert "distribution" in kinds
    assert "comparison" in kinds


def test_selector_prefers_ranking_for_top_query():
    compiler = AnswerLayerCompiler()
    views = compiler.build_views(_runtime_view())
    selection = compiler.select_view(
        "Return the top three item labels as a comma-separated list with no explanation.",
        views,
    )
    assert selection.view is not None
    assert selection.view.kind == "ranking"
    assert any(view.kind == "grouped_summary" for view in selection.supporting_views)
    answer = DeterministicAnswerFinalizer().finalize(
        "Return the top three item labels as a comma-separated list with no explanation.",
        selection,
    )
    assert answer == "Alpha, Beta"


def test_selector_prefers_distribution_for_distribution_query():
    compiler = AnswerLayerCompiler()
    views = compiler.build_views(_runtime_view())
    selection = compiler.select_view("Show the distribution as a histogram.", views)
    assert selection.view is not None
    assert selection.view.kind == "distribution"


def test_selector_prefers_grouped_summary_for_effect_style_query():
    compiler = AnswerLayerCompiler()
    views = compiler.build_views(_runtime_view())
    selection = compiler.select_view(
        "Which interventions have the strongest effects across outcomes and what measure is reported?",
        views,
    )
    assert selection.view is not None
    assert selection.view.kind == "grouped_summary"


def test_selector_uses_llm_adjudicator_only_on_ambiguous_case():
    selector = AnswerViewSelector()
    llm = _FakeLLM('{"selected_view_id":"v2","rationale":"question asks for table-like summary"}')
    views = [
        AnswerView("v1", "ranking", "rows_a", True, {"ranked_subjects": [{"subject": "A", "score": 2.0}]}, {}),
        AnswerView("v2", "grouped_summary", "rows_a", True, {"rows": [{"subject": "A", "outcome": "risk", "measure_mean": 0.5, "support_n": 2}]}, {}),
    ]
    selection = selector.select(
        "Which interventions have the strongest effects and what measure is reported?",
        views,
        llm_func=llm,
    )
    assert llm.calls == 1
    assert selection.view is not None
    assert selection.view.view_id == "v2"
    assert selection.rationale.startswith("llm_adjudicated:")


def test_selector_skips_llm_when_clear_winner_exists():
    selector = AnswerViewSelector()
    llm = _FakeLLM('{"selected_view_id":"v2","rationale":"ignored"}')
    views = [
        AnswerView("v1", "distribution", "rows_a", True, {"n": 10, "mean": 2.0, "median": 2.0}, {}),
        AnswerView("v2", "provenance", "rows_a", True, {"refs": [{"item_id": "A"}]}, {}),
    ]
    selection = selector.select("Show the distribution as a histogram.", views, llm_func=llm)
    assert llm.calls == 0
    assert selection.view is not None
    assert selection.view.view_id == "v1"
