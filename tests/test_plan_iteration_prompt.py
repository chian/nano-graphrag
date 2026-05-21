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
                "reasons": [
                    {"command": "JOIN a with b on id AS joined", "status": "error", "error_message": "Variables a or b not found or empty"}
                ],
            },
        },
    )
    assert "Current Iteration Failure Summary:" in prompt
    assert "Variables a or b not found or empty" in prompt
    assert "Active Plan Symbol Table:" in prompt
    assert "\"name\": \"controls\"" in prompt
