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


def test_aggregate_count_uses_evidence_weight_for_deduped_rows():
    state_store = StateStore()
    context_store = ContextStore()
    state_manager = StateManager(state_store, context_store)
    handler = DataTransformHandler(state_store, context_store, llm_func=None, state_manager=state_manager)
    rows = [
        {
            "id": "n1",
            "entity_name": "SARS-COV-2",
            "data": {
                "entity_name": "SARS-COV-2",
                "source_papers": "p1,p2,p3",
            },
        },
        {
            "id": "n2",
            "entity_name": "INFLUENZA VIRUS",
            "data": {
                "entity_name": "INFLUENZA VIRUS",
                "source_papers": "p4",
            },
        },
    ]
    context_store.set(
        "pathogen_rows",
        rows,
        contract={
            "payload_kind": "filtered_rows",
            "label_field": "entity_name",
            "row_schema": ["id", "entity_name", "data.source_papers"],
        },
    )
    command = executor_command(
        "AGGREGATE pathogen_rows by entity_name with count AS pathogen_counts"
    )
    result = handler.execute(command)
    assert result.status == "success"
    counts = {row["group_name"]: row["count"] for row in result.data}
    assert counts["SARS-COV-2"] == 3
    assert counts["INFLUENZA VIRUS"] == 1


def test_aggregate_sum_prefers_contract_metric_field():
    state_store = StateStore()
    context_store = ContextStore()
    state_manager = StateManager(state_store, context_store)
    handler = DataTransformHandler(state_store, context_store, llm_func=None, state_manager=state_manager)
    rows = [
        {"id": "a", "entity_name": "X", "count_value": 2},
        {"id": "b", "entity_name": "X", "count_value": 5},
        {"id": "c", "entity_name": "Y", "count_value": 7},
    ]
    context_store.set(
        "dose_rows",
        rows,
        contract={
            "payload_kind": "filtered_rows",
            "label_field": "entity_name",
            "metric_field": "count_value",
            "row_schema": ["id", "entity_name", "count_value"],
        },
    )
    command = executor_command("AGGREGATE dose_rows by entity_name with sum AS dose_counts")
    result = handler.execute(command)
    assert result.status == "success"
    sums = {row["group_name"]: row["result"] for row in result.data}
    assert sums["X"] == 7
    assert sums["Y"] == 7


def test_project_paper_grain_explodes_source_papers():
    state_store = StateStore()
    context_store = ContextStore()
    state_manager = StateManager(state_store, context_store)
    handler = DataTransformHandler(state_store, context_store, llm_func=None, state_manager=state_manager)
    rows = [
        {"id": "n1", "data": {"entity_name": "SARS-COV-2", "source_papers": "p1,p2"}},
        {"id": "n2", "data": {"entity_name": "INFLUENZA VIRUS", "source_papers": "p3"}},
    ]
    context_store.set("walk_rows", rows, contract={"payload_kind": "walk_rows", "grain_type": "edge", "multiplicity_preserved": True})
    command = executor_command(
        "PROJECT walk_rows GRAIN paper FIELDS data.entity_name AS entity_name PRESERVE_MULTIPLICITY AS paper_rows"
    )
    result = handler.execute(command)
    assert result.status == "success"
    assert result.count == 3
    paper_ids = [row["paper_id"] for row in result.data]
    assert paper_ids == ["p1", "p2", "p3"]


def executor_command(text: str):
    from gasl.parser import GASLParser

    return GASLParser().parse_command(text)
