import networkx as nx

from gasl.commands.find import FindHandler
from gasl.commands.graph_nav import GraphNavHandler
from gasl.adapters.networkx import NetworkXAdapter
from gasl.state import StateStore, ContextStore
from gasl.state_manager import StateManager
from gasl.types import Command


class _InvalidGraphwalkLLM:
    model = "gpt-5.5"

    def clone(self, model=None, reasoning_effort=None):
        return self

    def call(self, prompt: str) -> str:
        if "refining a GRAPHWALK retrieval strategy" in prompt:
            return """
            {
              "refinement_hint": "tighten_depth",
              "refinement_reason": "pilot sample is too broad",
              "refinement_anchor_strength": 0.2,
              "refinement_relation_strength": 0.2,
              "refinement_depth_strength": 0.2,
              "refinement_payload_hint": "walk_rows",
              "refinement_grain_hint": "edge",
              "refinement_downstream_hint": ["PROCESS", "SHOW", "SELECT"],
              "refinement_confidence": 0.2
            }
            """
        return '{"refinement_hint": "keep", "refinement_reason": "ok", "refinement_confidence": 0.9}'


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


def test_find_parse_entity_types_and_relations_with_digits():
    g = nx.DiGraph()
    g.add_node("country", entity_type="COUNTRY_R0_RECORD", entity_name="Country record")
    g.add_node("comparison", entity_type="ID50_R0_COMPARISON", entity_name="Comparison")
    g.add_node("method", entity_type="ANALYTICAL_METHOD", entity_name="Method")
    g.add_edge("country", "comparison", relation_type="HAS_ID50_R0_COMPARISON")
    handler = FindHandler(StateStore(), ContextStore(), NetworkXAdapter(g))

    node_filters = handler._parse_criteria("entity_type=COUNTRY_R0_RECORD")
    node_rows = handler.adapter.find_nodes(node_filters)
    listed_filters = handler._parse_criteria(
        'entity_type in ["COUNTRY_R0_RECORD", "ID50_R0_COMPARISON"]'
    )
    listed_rows = handler.adapter.find_nodes(listed_filters)
    pipe_filters = handler._parse_criteria(
        "entity_type=COUNTRY_R0_RECORD|ID50_R0_COMPARISON"
    )
    pipe_rows = handler.adapter.find_nodes(pipe_filters)
    label_filters = handler._parse_criteria(
        'label in ["COUNTRY_R0_RECORD", "ID50_R0_COMPARISON"]'
    )
    label_rows = handler.adapter.find_nodes(label_filters)
    path_filters = handler._parse_criteria(
        "source entity_type=COUNTRY_R0_RECORD "
        "edge relation_type=HAS_ID50_R0_COMPARISON "
        "target entity_type=ID50_R0_COMPARISON"
    )

    assert node_filters["entity_type"] == '"COUNTRY_R0_RECORD"'
    assert len(node_rows) == 1
    assert listed_filters["entity_type"] == ['"COUNTRY_R0_RECORD"', '"ID50_R0_COMPARISON"']
    assert {row["id"] for row in listed_rows} == {"country", "comparison"}
    assert pipe_filters["entity_type"] == ['"COUNTRY_R0_RECORD"', '"ID50_R0_COMPARISON"']
    assert {row["id"] for row in pipe_rows} == {"country", "comparison"}
    assert label_filters["entity_type"] == ['"COUNTRY_R0_RECORD"', '"ID50_R0_COMPARISON"']
    assert {row["id"] for row in label_rows} == {"country", "comparison"}
    assert path_filters["source_filter"]["entity_type"] == '"COUNTRY_R0_RECORD"'
    assert path_filters["target_filter"]["entity_type"] == '"ID50_R0_COMPARISON"'
    assert path_filters["relation_type"] == "HAS_ID50_R0_COMPARISON"


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


def test_find_paths_refinement_keeps_unanchored_query_when_no_semantics_are_parsed():
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
    assert result.status == "success"
    assert "retrieval_strategy: refinement_keep" in (result.contract.get("notes") or [])
    probe = result.contract.get("refinement") or {}
    assert probe.get("sample_size", 0) >= 0
    assert probe.get("refinement", {}).get("refinement_hint") == "keep"


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


def test_graphwalk_accepts_pipe_separated_relationships():
    graph = _make_graph()
    adapter = NetworkXAdapter(graph)
    context = ContextStore()
    state = StateStore()
    context.set("seed_nodes", [{"id": "ec1", "data": graph.nodes["ec1"]}])
    handler = GraphNavHandler(
        state,
        context,
        adapter,
        state_manager=StateManager(state, context),
    )
    command = Command(
        command_type="GRAPHWALK",
        args={
            "from_variable": "seed_nodes",
            "relationship_types": "VALIDATED_BY|REDUCES",
            "depth": "1",
            "result_var": "walk_rows",
        },
        raw_text="GRAPHWALK from seed_nodes follow VALIDATED_BY|REDUCES depth 1 AS walk_rows",
        line_number=1,
    )

    result = handler.execute(command)

    assert result.status == "success"
    assert {item["id"] for item in result.data} == {"vs1", "vs2", "other"}


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
