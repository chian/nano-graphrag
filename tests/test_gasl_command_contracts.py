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
