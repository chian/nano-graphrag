import networkx as nx

from gasl.commands.find import FindHandler
from gasl.commands.graph_nav import GraphNavHandler
from gasl.adapters.networkx import NetworkXAdapter
from gasl.state import StateStore, ContextStore
from gasl.types import Command


class _InvalidGraphwalkLLM:
    model = "gpt-5.5"

    def clone(self, model=None, reasoning_effort=None):
        return self

    def call(self, prompt: str) -> str:
        if "judging GRAPHWALK path semantics" in prompt:
            return """
            {
              "semantically_valid": false,
              "reason": "pilot sample is too broad",
              "anchor_strength": 0.2,
              "relation_match_strength": 0.2,
              "depth_match_strength": 0.2,
              "recommended_payload_kind": "walk_rows",
              "recommended_grain": "edge",
              "downstream_safe_for": ["PROCESS", "SHOW", "SELECT"],
              "repair_hint": "narrow depth",
              "confidence": 0.2
            }
            """
        return '{"valid": true, "reason": "ok", "issues": [], "confidence": 0.9}'


def _make_graph():
    g = nx.DiGraph()
    g.add_node("ec1", entity_type='"ENGINEERING_CONTROL"', entity_name="EC1")
    g.add_node("vs1", entity_type='"VALIDATION_STUDY"', entity_name="VS1")
    g.add_node("vs2", entity_type='"VALIDATION_STUDY"', entity_name="VS2")
    g.add_node("other", entity_type='"ADVERSE_EFFECT"', entity_name="OTHER")
    g.add_edge("ec1", "vs1", relation_type="VALIDATED_BY")
    g.add_edge("ec1", "vs2", relation_type="VALIDATED_BY")
    g.add_edge("ec1", "other", relation_type="REDUCES")
    g.add_edge("vs1", "other", relation_type="REDUCES")
    return g


def test_find_parse_path_criteria_extracts_source_target_relation():
    handler = FindHandler(StateStore(), ContextStore(), NetworkXAdapter(_make_graph()))
    filters = handler._parse_criteria(
        "source entity_type=ENGINEERING_CONTROL edge relation_type=VALIDATED_BY target entity_type=VALIDATION_STUDY"
    )
    assert filters["source_filter"]["entity_type"] == '"ENGINEERING_CONTROL"'
    assert filters["target_filter"]["entity_type"] == '"VALIDATION_STUDY"'
    assert filters["relation_type"] == "VALIDATED_BY"


def test_find_strict_relation_paths_prefers_exact_relation():
    handler = FindHandler(StateStore(), ContextStore(), NetworkXAdapter(_make_graph()))
    filters = {
        "source_filter": {"entity_type": '"ENGINEERING_CONTROL"'},
        "target_filter": {"entity_type": '"VALIDATION_STUDY"'},
        "relation_type": "VALIDATED_BY",
    }
    rows = handler.adapter.find_paths(filters)
    pairs = {(row["source"], row["target"]) for row in rows}
    assert ("ec1", "vs1") in pairs
    assert ("ec1", "vs2") in pairs
    assert ("ec1", "other") not in pairs
    assert all("VALIDATED_BY" in row.get("edge_types", []) for row in rows)


def test_find_paths_gate_blocks_unanchored_path_query():
    handler = FindHandler(StateStore(), ContextStore(), NetworkXAdapter(_make_graph()))
    command = Command(
        command_type="FIND",
        args={
            "target": "paths",
            "criteria": "entity_type=ENGINEERING_CONTROL and relation_type in [TARGETS,REDUCES] and entity_type=AIRBORNE_PATHOGEN",
            "result_var": "control_pathogen_paths",
        },
        raw_text="FIND paths with entity_type=ENGINEERING_CONTROL and relation_type in [TARGETS,REDUCES] and entity_type=AIRBORNE_PATHOGEN AS control_pathogen_paths",
        line_number=1,
    )
    result = handler.execute(command)
    assert result.status == "error"
    assert "source/edge/target anchored" in (result.error_message or "")


def test_networkx_find_paths_respects_pair_budget():
    graph = _make_graph()
    adapter = NetworkXAdapter(graph)
    filters = {
        "source_filter": {"entity_type": '"ENGINEERING_CONTROL"'},
        "target_filter": {"entity_type": '"VALIDATION_STUDY"'},
        "relation_type": "VALIDATED_BY",
        "_max_pairs": 1,
    }
    rows = adapter.find_paths(filters)
    assert len(rows) == 1


def test_graphwalk_probe_can_reduce_depth_on_invalid_pilot():
    graph = _make_graph()
    adapter = NetworkXAdapter(graph)
    context = ContextStore()
    state = StateStore()
    context.set("seed_nodes", [{"id": "ec1", "data": graph.nodes["ec1"]}])
    handler = GraphNavHandler(state, context, adapter, _InvalidGraphwalkLLM())
    command = Command(
        command_type="GRAPHWALK",
        args={"from_variable": "seed_nodes", "relationship_types": "VALIDATED_BY", "depth": "3", "result_var": "walk_rows"},
        raw_text="GRAPHWALK from seed_nodes follow VALIDATED_BY depth 3 AS walk_rows",
        line_number=1,
    )
    result = handler.execute(command)
    assert result.status == "success"
    notes = result.contract.get("notes", [])
    assert any("adapted GRAPHWALK depth 3 -> 1" in note for note in notes)
    assert all(item["data"]["path_depth"] == 1 for item in result.data)
