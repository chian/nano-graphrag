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


def test_plan_generation_prompt_uses_planner_constraints_not_strategy_prose():
    llm = ArgoBridgeLLM(api_key="test-key", base_url="http://localhost:9999")
    prompt = llm.create_plan_prompt(
        query="Which controls have the broadest validation footprint?",
        schema={
            "node_labels": ["ENGINEERING_CONTROL"],
            "edge_types": ["VALIDATED_BY"],
            "node_properties": [],
            "edge_properties": [],
        },
        state={
            "variables": {},
            "produced_artifacts": [],
            "planner_constraints": ["Use only declared symbols", "Do not add INSPECT steps"],
            "strategy_insights": "If fields are unclear, INSPECT the rows before joining.",
        },
        history=[],
        symbol_table=[],
        validation_defects=[],
    )
    assert "Previous planner constraints:" in prompt
    assert "- Use only declared symbols" in prompt
    assert "- Do not add INSPECT steps" in prompt
    assert "If fields are unclear, INSPECT the rows before joining." not in prompt


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


def test_plan_prompt_state_uses_contract_row_schema_and_grain_keys():
    llm = ArgoBridgeLLM(api_key="test-key", base_url="http://localhost:9999")
    prompt = llm.create_plan_prompt(
        query="Which controls have the broadest validation footprint?",
        schema={
            "node_labels": ["ENGINEERING_CONTROL"],
            "edge_types": ["VALIDATED_IN"],
            "node_properties": [],
            "edge_properties": [],
        },
        state={
            "variables": {
                "control_zone_validations": {
                    "_meta": {
                        "type": "LIST",
                        "description": "validation walk rows",
                        "contract": {
                            "grain_type": "edge",
                            "grain_keys": ["data.src_id", "data.tgt_id", "data.relation_type"],
                            "row_schema": [
                                "id",
                                "type",
                                "data",
                                "data.src_id",
                                "data.tgt_id",
                                "data.relation_type",
                                "data.path_depth",
                            ],
                        },
                    },
                    "items": [
                        {
                            "id": "n1",
                            "type": "node",
                            "data": {
                                "src_id": "c1",
                                "tgt_id": "z1",
                                "relation_type": "VALIDATED_IN",
                                "path_depth": 1,
                            },
                        }
                    ],
                }
            },
            "produced_artifacts": [],
        },
        history=[],
        symbol_table=[],
        validation_defects=[],
    )
    assert "GRAIN: edge" in prompt
    assert "GRAIN KEYS: data.src_id, data.tgt_id, data.relation_type" in prompt
    assert "- data.src_id: string" in prompt
    assert "- data.tgt_id: string" in prompt
    assert "- data.path_depth: number" in prompt


def test_plan_prompt_produced_artifacts_do_not_truncate_shape():
    llm = ArgoBridgeLLM(api_key="test-key", base_url="http://localhost:9999")
    prompt = llm.create_plan_prompt(
        query="Which controls have the broadest validation footprint?",
        schema={
            "node_labels": ["ENGINEERING_CONTROL"],
            "edge_types": ["VALIDATED_IN"],
            "node_properties": [],
            "edge_properties": [],
        },
        state={
            "variables": {},
            "produced_artifacts": [
                {
                    "variable": "control_zone_validations",
                    "command_type": "GRAPHWALK",
                    "payload_kind": "walk_rows",
                    "item_count": 12,
                    "grain_type": "edge",
                    "grain_keys": ["data.src_id", "data.tgt_id", "data.relation_type"],
                    "row_schema": [
                        "id",
                        "type",
                        "data",
                        "data.src_id",
                        "data.tgt_id",
                        "data.relation_type",
                        "data.path_depth",
                        "data.weight",
                        "data.source_id",
                    ],
                }
            ],
        },
        history=[],
        symbol_table=[],
        validation_defects=[],
    )
    assert "grain_keys=['data.src_id', 'data.tgt_id', 'data.relation_type']" in prompt
    assert "data.source_id" in prompt
