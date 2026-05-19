from gasl.answer_layer import AnswerLayerCompiler, DeterministicAnswerFinalizer


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
    assert "ranked_subjects" in kinds
    assert "subject_measure" in kinds
    assert "distribution" in kinds
    assert "comparison" in kinds


def test_selector_prefers_ranked_subjects_for_top_query():
    compiler = AnswerLayerCompiler()
    views = compiler.build_views(_runtime_view())
    selection = compiler.select_view(
        "Return the top three item labels as a comma-separated list with no explanation.",
        views,
    )
    assert selection.view is not None
    assert selection.view.kind == "ranked_subjects"
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
