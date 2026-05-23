import json
from types import SimpleNamespace

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


class RepairingLLM:
    model = "dummy-repair"

    def call(self, prompt: str) -> str:
        if "You are repairing exactly one GASL command in isolation." in prompt:
            return '{"retry": true, "replacement_command": "SET repaired_flag = true", "reason": "create the missing local variable", "confidence": 0.72}'
        return ""


class TwoStepCompileLLM:
    model = "dummy-compile-patch"

    def call(self, prompt: str) -> str:
        if "You are compiling exactly one GASL command under step-local constraints." in prompt:
            return (
                '{"action":"patch_two","commands":['
                '"SELECT controls FIELDS id AS temp_controls",'
                '"SELECT temp_controls FIELDS id AS top_controls"'
                '],"reason":"repair missing source through temp symbol"}'
            )
        return ""


def test_on_condition_matches_treats_success_zero_count_as_empty():
    result = ExecutionResult(command="GRAPHWALK", status="success", data=[], count=0)
    assert GASLExecutor._on_condition_matches("empty", result) is True
    assert GASLExecutor._on_condition_matches("success", result) is False


def test_iteration_summary_separates_errors_empties_and_expertise_context():
    graph = nx.MultiDiGraph()
    executor = GASLExecutor(NetworkXAdapter(graph), DummyLLM(), state_file=None, job_id="test_iteration_summary")
    executor.state_store.append_produced_artifact({
        "variable": "evidence_rows",
        "command_type": "FIND",
        "status": "success",
        "item_count": 2,
        "row_schema": ["entity_name", "source_papers", "source_chunks"],
    })
    summary = executor._summarize_iteration_outcomes([
        ExecutionResult(command='FIND edges with relation_type = "TARGETS" AS edges', status="empty", count=0),
        ExecutionResult(command="JOIN a with b on id AS joined", status="error", count=0, error_message="Variables a or b not found or empty"),
    ])
    assert summary["needs_repair"] is True
    assert len(summary["errors"]) == 1
    assert len(summary["empties"]) == 1
    assert summary["errors"][0]["status"] == "error"
    assert summary["empties"][0]["status"] == "empty"
    assert summary["expertise_context"]["kg_schema"]["edge_types_count"] >= 0
    assert summary["expertise_context"]["source_coverage"]["artifacts_with_source_papers"] == 1


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


def test_execute_plan_attempts_generic_command_repair_before_break():
    graph = nx.MultiDiGraph()
    executor = GASLExecutor(NetworkXAdapter(graph), RepairingLLM(), state_file=None, job_id="test_command_repair")
    plan = {
        "plan_id": "plan-command-repair",
        "why": "test generic command repair",
        "commands": [
            "SHOW missing_rows",
            "SHOW repaired_flag",
        ],
        "query": "repair a single failed command",
        "config": {"stop_on_error": True, "continue_on_empty": False},
    }
    result = executor.execute_plan(plan)
    statuses = [r.status for r in result["results"]]
    commands = [r.command for r in result["results"]]
    assert result["status"] == "completed"
    assert statuses[:3] == ["error", "success", "success"]
    assert commands[1] == "SET repaired_flag = true"
    assert executor.context_store.get("repaired_flag") is True


def test_execute_plan_runs_two_command_compile_patch_inline():
    graph = nx.MultiDiGraph()
    executor = GASLExecutor(NetworkXAdapter(graph), TwoStepCompileLLM(), state_file=None, job_id="test_compile_patch")
    executor.state_store.declare_variable("controls", "LIST")
    executor.state_store.update_variable("controls", [{"id": "c1"}, {"id": "c2"}])
    executor.state_store.set_variable_contract("controls", {"row_schema": ["id"], "grain_type": "node"})
    plan = {
        "plan_id": "plan-compile-patch",
        "why": "test compiler mini-patch",
        "commands": [
            "SELECT future_controls FIELDS id AS top_controls",
        ],
        "query": "repair one unavailable source by using a temp symbol",
        "config": {"stop_on_error": True, "continue_on_empty": False},
    }
    result = executor.execute_plan(plan)
    statuses = [r.status for r in result["results"]]
    commands = [r.command for r in result["results"]]
    assert result["status"] == "completed"
    assert statuses == ["success", "success"]
    assert commands == [
        "SELECT controls FIELDS id AS temp_controls",
        "SELECT temp_controls FIELDS id AS top_controls",
    ]
    top_controls = executor.context_store.get("top_controls")
    assert isinstance(top_controls, list)
    assert len(top_controls) == 2


def test_generate_final_answer_persists_deterministic_answer(tmp_path, monkeypatch):
    import gasl.executor as executor_module

    graph = nx.MultiDiGraph()
    state_path = tmp_path / "gasl_state.json"
    executor = GASLExecutor(
        NetworkXAdapter(graph),
        DummyLLM(),
        state_file=str(state_path),
        job_id="test_final_answer_persist",
    )
    executor.state_store.set_query("Which control ranks highest?")

    class _Selection:
        view = None
        supporting_views = []
        rationale = "analysis test"

    class _Compiler:
        def build_views(self, runtime_view):
            return []

        def select_view(self, query, views, llm_func=None):
            return _Selection()

    monkeypatch.setattr(executor_module, "AnswerLayerCompiler", lambda: _Compiler())
    monkeypatch.setattr(executor.llm_func, "create_analysis_prompt", lambda query, results: f"Q={query}\nR={results}", raising=False)
    monkeypatch.setattr(executor.llm_func, "call", lambda prompt: "SAFE ANSWER")

    answer = executor._generate_final_answer(
        "Which control ranks highest?",
        executor.state_store.get_state(),
    )

    persisted = json.loads(state_path.read_text())
    assert answer == "SAFE ANSWER"
    assert persisted["final_answer"] == "SAFE ANSWER"
    assert persisted["query_answered"] is True
    assert persisted["final_answer_mode"] == "llm_analysis"


def test_hdt_persists_defect_summary_and_returns_refreshed_state(tmp_path, monkeypatch):
    graph = nx.MultiDiGraph()
    state_path = tmp_path / "gasl_state.json"
    executor = GASLExecutor(
        NetworkXAdapter(graph),
        DummyLLM(),
        state_file=str(state_path),
        job_id="test_defect_summary_persist",
    )

    planner_result = SimpleNamespace(
        symbol_table=[],
        plan_prompt="",
        plan_response='{"plan_id":"p1","why":"test","commands":[],"config":{"stop_on_error":true,"continue_on_empty":false}}',
        plan_json={"plan_id": "p1", "why": "test", "commands": [], "config": {"stop_on_error": True, "continue_on_empty": False}},
        validation={},
    )
    monkeypatch.setattr(executor.two_phase_planner, "generate_plan", lambda **kwargs: planner_result)
    monkeypatch.setattr(
        executor,
        "execute_plan",
        lambda plan_json: {
            "status": "completed",
            "final_state": {"variables": {}},
            "results": [],
        },
    )

    result = executor.run_hypothesis_driven_traversal("Unanswerable query", max_iterations=1)

    persisted = json.loads(state_path.read_text())
    assert result["query_answered"] is False
    assert result["final_answer"].startswith("Query could not be answered cleanly")
    assert result["final_state"]["final_answer"] == result["final_answer"]
    assert persisted["final_answer"] == result["final_answer"]
    assert persisted["final_answer_mode"] == "defect_summary"


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


def test_apply_plan_patch_replaces_single_bad_line():
    plan = {
        "plan_id": "p1",
        "why": "orig",
        "commands": [
            "FIND paths with source entity_type=ENGINEERING_CONTROL edge relation_type=VALIDATED_BY target entity_type=VALIDATION_STUDY AS engineering_validation_paths",
            "PROCESS engineering_validation_paths with instruction: extract validation study names AS validation_rows",
        ],
        "config": {"stop_on_error": True, "continue_on_empty": False},
    }
    patch = {
        "mode": "patch",
        "reason": "narrow to graphwalk",
        "replace_command": "FIND paths with source entity_type=ENGINEERING_CONTROL edge relation_type=VALIDATED_BY target entity_type=VALIDATION_STUDY AS engineering_validation_paths",
        "replacement_command": "FIND nodes with entity_type=ENGINEERING_CONTROL AS engineering_controls",
        "insert_after_command": "FIND nodes with entity_type=ENGINEERING_CONTROL AS engineering_controls",
        "insert_command": "GRAPHWALK from engineering_controls follow VALIDATED_BY depth 1 AS engineering_validation_paths",
    }
    repaired = GASLExecutor._apply_plan_patch(plan, patch)
    assert repaired is not None
    assert repaired["commands"][0] == "FIND nodes with entity_type=ENGINEERING_CONTROL AS engineering_controls"
    assert repaired["commands"][1] == "GRAPHWALK from engineering_controls follow VALIDATED_BY depth 1 AS engineering_validation_paths"
    assert repaired["commands"][2].startswith("PROCESS engineering_validation_paths")


def executor_command(text: str):
    from gasl.parser import GASLParser

    return GASLParser().parse_command(text)
