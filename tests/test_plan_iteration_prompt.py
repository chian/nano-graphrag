import json

from gasl.llm.argo_bridge import ArgoBridgeLLM


def test_plan_iteration_prompt_includes_structured_failure_summary():
    llm = ArgoBridgeLLM(api_key="test-key", base_url="http://localhost:9999")
    prompt = llm.create_plan_iteration_prompt(
        query="Which controls have the broadest validation footprint?",
        previous_plan={"plan_id": "p1", "why": "test", "commands": ["SHOW rows"], "config": {}},
        results={"some_var": {"items": []}},
        iteration=2,
        state={
            "history": [],
            "produced_artifacts": [],
            "strategy_insights": json.dumps([{"command": "JOIN", "status": "error"}]),
            "plan_symbol_table": [
                {"name": "controls", "role": "seed nodes", "shape": "nodes", "producer": "input", "rationale": "seed"},
                {"name": "zone_links", "role": "paths", "shape": "paths", "producer": "GRAPHWALK", "rationale": "walk"},
            ],
            "last_failure_summary": {
                "needs_repair": True,
                "errors": [
                    {"command": "JOIN a with b on id AS joined", "status": "error", "error_message": "Variables a or b not found or empty"}
                ],
                "empties": [
                    {"command": "FIND edges with relation_type = \"TARGETS\" AS edges", "status": "empty", "error_message": ""}
                ],
                "expertise_context": {
                    "kg_schema": {"edge_types_count": 12},
                    "source_coverage": {"artifacts_with_source_papers": 2},
                    "operator_path": {"direct_graph_ops": 1, "transform_ops": 0},
                },
                "reasons": [
                    {"command": "JOIN a with b on id AS joined", "status": "error", "error_message": "Variables a or b not found or empty"}
                ],
            },
        },
    )
    assert "Current Iteration Failure Summary:" in prompt
    assert "Variables a or b not found or empty" in prompt
    assert "\"empties\"" in prompt
    assert "\"expertise_context\"" in prompt
    assert "Active Plan Symbol Table:" in prompt
    assert "\"name\": \"controls\"" in prompt


def test_strategy_adaptation_prompt_uses_state_history_and_expertise_context():
    llm = ArgoBridgeLLM(api_key="test-key", base_url="http://localhost:9999")
    prompt = llm.create_strategy_adaptation_prompt(
        query="Which controls have the broadest validation footprint?",
        results={"controls": ["A", "B"]},
        iteration=3,
        schema={"node_labels": ["ENGINEERING_CONTROL"], "edge_types": ["VALIDATED_IN"], "node_properties": [], "edge_properties": []},
        state={
            "history": [
                {"status": "empty", "command": "FIND edges with relation_type = \"TARGETS\" AS edges", "result_count": 0},
                {"status": "error", "command": "JOIN a with b on id AS joined", "result_count": 0},
            ],
            "last_failure_summary": {
                "needs_repair": True,
                "errors": [{"command": "JOIN a with b on id AS joined", "status": "error", "error_message": "Variables a or b not found or empty"}],
                "empties": [{"command": "FIND edges with relation_type = \"TARGETS\" AS edges", "status": "empty", "error_message": ""}],
                "expertise_context": {
                    "kg_schema": {"edge_types_count": 12},
                    "source_coverage": {"artifacts_with_source_papers": 2},
                    "operator_path": {"direct_graph_ops": 1, "transform_ops": 1},
                },
            },
        },
    )
    assert "FIND edges with relation_type = \"TARGETS\" AS edges" in prompt
    assert "\"expertise_context\"" in prompt or "\"kg_schema\"" in prompt
