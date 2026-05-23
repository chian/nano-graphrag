from gasl.state import ContextStore, StateStore
from gasl.state_manager import StateManager
from gasl.commands.debug import DebugHandler
from gasl.commands.process import ProcessHandler
from gasl.types import Command


def test_context_and_state_contract_storage(tmp_path):
    state = StateStore(tmp_path / "state.json")
    ctx = ContextStore()
    manager = StateManager(state, ctx)
    contract = {
        "payload_kind": "grouped_rows",
        "label_field": "group_name",
        "metric_field": "count",
        "ordered": False,
        "confidence": 0.9,
    }
    manager.store_variable_data("x", [{"group_name": "A", "count": 1}], contract=contract)
    assert manager.get_variable_contract("x")["payload_kind"] == "grouped_rows"
    assert state.get_variable_contract("x")["metric_field"] == "count"


def test_debug_show_uses_count_not_result_count(tmp_path):
    state = StateStore(tmp_path / "state.json")
    ctx = ContextStore()
    state.declare_variable("x", "LIST", "test")
    var = state.get_variable("x")
    var["items"] = [{"id": "a"}]
    state.set_variable_contract("x", {"payload_kind": "nodes"})
    state._save_state()
    handler = DebugHandler(state, ctx)
    command = Command(command_type="SHOW", args={"variable": "x", "limit": 1}, raw_text="SHOW x", line_number=1)
    result = handler.execute(command)
    assert result.status == "success"
    assert result.count == 1
    assert result.contract["payload_kind"] == "nodes"


def test_process_repair_response_parser():
    raw = """
    {
      "refined_instruction": "use only rows whose target entity_type equals AIRBORNE_PATHOGEN",
      "selector_hint": "lexical",
      "current_rows_sufficient": true,
      "confidence": 0.71,
      "reason": "probe positives are sparse but rows are sufficient"
    }
    """
    parsed = ProcessHandler._parse_repair_response(raw)
    assert parsed["selector_hint"] == "lexical"
    assert parsed["current_rows_sufficient"] is True
    assert parsed["confidence"] == 0.71


def test_store_variable_data_coerces_empty_dict_to_list(tmp_path):
    state = StateStore(tmp_path / "state.json")
    ctx = ContextStore()
    manager = StateManager(state, ctx)
    state.declare_variable("walk_rows", "DICT", "placeholder")
    manager.store_variable_data(
        "walk_rows",
        [{"id": "n1"}, {"id": "n2"}],
        contract={"payload_kind": "walk_rows", "grain_type": "edge"},
    )
    stored = state.get_variable("walk_rows")
    assert stored["_meta"]["type"] == "LIST"
    assert len(stored["items"]) == 2
    assert ctx.has("walk_rows") is True
