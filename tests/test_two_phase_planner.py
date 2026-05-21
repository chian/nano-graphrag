import json

from gasl.parser import GASLParser
from gasl.two_phase_planner import TwoPhasePlanner


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.model = "test-model"

    def create_plan_symbols_prompt(self, query, schema, state, history):
        return f"symbols::{query}"

    def create_plan_prompt(self, query, schema, state, history, symbol_table=None, validation_defects=None):
        return f"plan::{query}"

    def call(self, prompt: str) -> str:
        return self.responses.pop(0)


def test_two_phase_planner_generates_valid_plan():
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "symbols": [
                        {"name": "controls", "role": "seed nodes", "shape": "nodes", "producer": "input", "rationale": "seed"},
                        {"name": "zone_links", "role": "zone links", "shape": "paths", "producer": "GRAPHWALK", "rationale": "walk"},
                        {"name": "zone_counts", "role": "counts", "shape": "rows", "producer": "AGGREGATE", "rationale": "agg"},
                    ]
                }
            ),
            json.dumps(
                {
                    "plan_id": "p1",
                    "why": "test",
                    "commands": [
                        "GRAPHWALK from controls follow APPLIED_TO depth 1 AS zone_links",
                        "AGGREGATE zone_links by id with count AS zone_counts",
                    ],
                    "config": {},
                }
            ),
        ]
    )
    planner = TwoPhasePlanner(llm, GASLParser())
    result = planner.generate_plan(
        query="Which controls have broad zone coverage?",
        schema={"node_labels": [], "edge_types": [], "node_properties": [], "edge_properties": []},
        state={"variables": {}, "produced_artifacts": []},
        history=[],
        iteration=1,
    )
    assert result.validation["ok"] is True
    assert result.plan_json["commands"][0].startswith("GRAPHWALK from controls")
    assert len(result.symbol_table) == 3


def test_two_phase_planner_retries_when_symbols_are_violated():
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "symbols": [
                        {"name": "controls", "role": "seed nodes", "shape": "nodes", "producer": "input", "rationale": "seed"},
                        {"name": "zone_links", "role": "zone links", "shape": "paths", "producer": "GRAPHWALK", "rationale": "walk"},
                    ]
                }
            ),
            json.dumps(
                {
                    "plan_id": "bad",
                    "why": "bad",
                    "commands": [
                        "GRAPHWALK from controls follow APPLIED_TO depth 1 AS wrong_name",
                    ],
                    "config": {},
                }
            ),
            json.dumps(
                {
                    "plan_id": "good",
                    "why": "good",
                    "commands": [
                        "GRAPHWALK from controls follow APPLIED_TO depth 1 AS zone_links",
                    ],
                    "config": {},
                }
            ),
        ]
    )
    planner = TwoPhasePlanner(llm, GASLParser())
    result = planner.generate_plan(
        query="Which controls have broad zone coverage?",
        schema={"node_labels": [], "edge_types": [], "node_properties": [], "edge_properties": []},
        state={"variables": {}, "produced_artifacts": []},
        history=[],
        iteration=1,
    )
    assert result.validation["ok"] is True
    assert result.plan_json["plan_id"] == "good"
    assert len(llm.responses) == 0


def test_two_phase_planner_reuses_existing_symbol_table():
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "plan_id": "reuse",
                    "why": "reuse",
                    "commands": [
                        "GRAPHWALK from controls follow APPLIED_TO depth 1 AS zone_links",
                    ],
                    "config": {},
                }
            ),
        ]
    )
    planner = TwoPhasePlanner(llm, GASLParser())
    result = planner.generate_plan(
        query="Which controls have broad zone coverage?",
        schema={"node_labels": [], "edge_types": [], "node_properties": [], "edge_properties": []},
        state={"variables": {}, "produced_artifacts": []},
        history=[],
        iteration=2,
        existing_symbol_table=[
            {"name": "controls", "role": "seed nodes", "shape": "nodes", "producer": "input", "rationale": "seed"},
            {"name": "zone_links", "role": "zone links", "shape": "paths", "producer": "GRAPHWALK", "rationale": "walk"},
        ],
    )
    assert result.validation["ok"] is True
    assert result.symbol_prompt == ""
    assert result.symbol_response == ""
