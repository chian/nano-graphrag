import networkx as nx

from gasl import GASLExecutor
from gasl.adapters import NetworkXAdapter
from gasl.commands.data_transform import DataTransformHandler
from gasl.state import ContextStore, StateStore
from gasl.state_manager import StateManager
from gasl.types import ExecutionResult


class DummyLLM:
    model = "dummy"

    def call(self, prompt: str) -> str:
        return ""


def test_on_condition_matches_treats_success_zero_count_as_empty():
    result = ExecutionResult(command="GRAPHWALK", status="success", data=[], count=0)
    assert GASLExecutor._on_condition_matches("empty", result) is True
    assert GASLExecutor._on_condition_matches("success", result) is False


def test_on_executes_nested_action_on_success():
    graph = nx.MultiDiGraph()
    executor = GASLExecutor(NetworkXAdapter(graph), DummyLLM(), state_file=None, job_id="test_on")
    plan = {
        "plan_id": "plan-on-success",
        "why": "test",
        "commands": [
            "SET seed = 1",
            "ON success do SET fired = true",
        ],
        "config": {"stop_on_error": True, "continue_on_empty": False},
    }
    result = executor.execute_plan(plan)
    assert result["status"] == "completed"
    assert executor.context_store.get("fired") is True


def test_aggregate_falls_back_to_contract_label_field_and_preserves_requested_alias():
    state_store = StateStore()
    context_store = ContextStore()
    state_manager = StateManager(state_store, context_store)
    handler = DataTransformHandler(state_store, context_store, llm_func=None, state_manager=state_manager)
    rows = [
        {"id": "n1", "data": {"entity_name": "NEGATIVE PRESSURE ROOM"}, "entity_name": "NEGATIVE PRESSURE ROOM"},
        {"id": "n2", "data": {"entity_name": "NEGATIVE PRESSURE ROOM"}, "entity_name": "NEGATIVE PRESSURE ROOM"},
        {"id": "n3", "data": {"entity_name": "ISOLATION ROOM"}, "entity_name": "ISOLATION ROOM"},
    ]
    context_store.set(
        "pattern_rows",
        rows,
        contract={
            "payload_kind": "filtered_rows",
            "label_field": "data.entity_name",
            "row_schema": ["id", "data.entity_name", "entity_name"],
        },
    )
    command = executor_command(
        "AGGREGATE pattern_rows by pattern_name with count AS pattern_counts"
    )
    result = handler.execute(command)
    assert result.status == "success"
    assert result.count == 2
    names = {row["group_name"] for row in result.data}
    assert names == {"NEGATIVE PRESSURE ROOM", "ISOLATION ROOM"}
    assert all("pattern_name" in row for row in result.data)


def executor_command(text: str):
    from gasl.parser import GASLParser

    return GASLParser().parse_command(text)
