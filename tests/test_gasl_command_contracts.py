from gasl.commands.debug import DebugHandler
from gasl.commands.process import ProcessHandler
from gasl.state import ContextStore, StateStore
from gasl.types import Command


def test_debug_handler_can_handle_show_command_object():
    handler = DebugHandler(StateStore(), ContextStore(), None)
    command = Command(command_type="SHOW", args={"variable": "x"}, raw_text="SHOW x", line_number=1)
    assert handler.can_handle(command) is True


def test_process_normalized_items_returns_rows_for_filter_and_process():
    filter_result = {
        "filtered_items": [{"id": "n1"}],
        "excluded_items": [{"id": "n2"}],
        "processing_method": "filter",
    }
    process_result = {
        "processed_items": [{"id": "n3", "value": 1}],
        "processing_method": "process",
    }
    assert ProcessHandler._normalized_items(filter_result) == [{"id": "n1"}]
    assert ProcessHandler._normalized_items(process_result) == [{"id": "n3", "value": 1}]


def test_process_requested_top_k_parses_words_and_numbers():
    assert ProcessHandler._requested_top_k("select the top three entity_name values") == 3
    assert ProcessHandler._requested_top_k("return the top 5 items as csv") == 5
    assert ProcessHandler._requested_top_k("select leading values") is None


def test_process_stops_after_probe_for_ranked_top_k_materialization():
    ranked_rows = [
        {"group_id": "group_1", "group_name": "SYSTEMATIC REVIEW", "count": 18, "rank": 1},
        {"group_id": "group_2", "group_name": "TRACER GAS RELEASE EXPERIMENTS", "count": 16, "rank": 2},
        {"group_id": "group_3", "group_name": "TABLE 2", "count": 10, "rank": 3},
        {"group_id": "group_4", "group_name": "CASE REPORT", "count": 7, "rank": 4},
    ]
    probe_result = {
        "filtered_items": [
            {"id": "group_1", "name": "SYSTEMATIC REVIEW"},
            {"id": "group_2", "name": "TRACER GAS RELEASE EXPERIMENTS"},
            {"id": "group_3", "name": "TABLE 2"},
        ],
        "processing_method": "filter",
    }
    interpretation = {
        "label_field": "group_name",
        "metric_field": "count",
        "ordered": True,
        "order_basis": "rows already sorted by count descending",
        "order_field": "count",
        "order_direction": "desc",
        "scope": "current_rows_only",
        "output_contract": "Materialize exactly the top 3 rows in current order.",
        "confidence": 0.9,
    }
    assert ProcessHandler._should_stop_after_probe(
        ranked_rows,
        "select the top three entity_name values and format as a comma-separated list",
        probe_result,
        interpretation,
    ) is True


def test_parse_interpretation_response_returns_structured_contract():
    raw = """
    {
      "label_field": "data.entity_name",
      "metric_field": "count",
      "ordered": true,
      "order_basis": "rows are already sorted by descending count",
      "order_field": "count",
      "order_direction": "desc",
      "scope": "current_rows_only",
      "output_contract": "Use the current rows only and preserve order.",
      "confidence": 0.82
    }
    """
    parsed = ProcessHandler._parse_interpretation_response(raw)
    assert parsed["label_field"] == "data.entity_name"
    assert parsed["order_field"] == "count"
    assert parsed["ordered"] is True
    assert parsed["confidence"] == 0.82
