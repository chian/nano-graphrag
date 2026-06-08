import networkx as nx

from graph_enrichment import entity_merger
from graph_enrichment.graph_merger import add_entities_to_graph


def test_find_entity_matches_skips_full_ratio_when_upper_bound_is_below_threshold(monkeypatch):
    class SequenceMatcherStub:
        ratio_calls = 0

        def __init__(self, *_args):
            pass

        def real_quick_ratio(self):
            return 0.2

        def quick_ratio(self):
            raise AssertionError("quick_ratio should be skipped")

        def ratio(self):
            self.__class__.ratio_calls += 1
            raise AssertionError("ratio should be skipped")

    monkeypatch.setattr(entity_merger, "SequenceMatcher", SequenceMatcherStub)

    matches = entity_merger.find_entity_matches(
        {"entity_name": "compact", "entity_type": "MODEL"},
        {
            "a very long unrelated mechanism name": {"entity_type": "MODEL"},
        },
        similarity_threshold=0.85,
    )

    assert matches == []
    assert SequenceMatcherStub.ratio_calls == 0


def test_add_entities_only_scans_matching_entity_type(monkeypatch):
    scanned_candidate_counts = []

    def fake_find_entity_matches(new_entity, existing_entities, **_kwargs):
        scanned_candidate_counts.append(len(existing_entities))
        return []

    monkeypatch.setattr(
        "graph_enrichment.graph_merger.find_entity_matches",
        fake_find_entity_matches,
    )

    graph = nx.DiGraph()
    for i in range(100):
        graph.add_node(f"other_{i}", entity_name=f"other_{i}", entity_type="OTHER")
    graph.add_node("same", entity_name="same", entity_type="CLAIM")

    add_entities_to_graph(
        graph,
        {
            "new": {
                "entity_name": "new",
                "entity_type": "CLAIM",
                "description": "new claim",
            },
        },
        source_uuid="paper-1",
    )

    assert scanned_candidate_counts == [1]


def test_add_entities_uses_exact_index_before_fuzzy_scan(monkeypatch):
    def fail_find_entity_matches(*_args, **_kwargs):
        raise AssertionError("exact normalized matches should not scan")

    monkeypatch.setattr(
        "graph_enrichment.graph_merger.find_entity_matches",
        fail_find_entity_matches,
    )

    graph = nx.DiGraph()
    graph.add_node(
        "Exact Entity",
        entity_name="Exact Entity",
        entity_type="CLAIM",
        description="old",
    )

    _, name_mapping = add_entities_to_graph(
        graph,
        {
            "exact entity": {
                "entity_name": "exact entity",
                "entity_type": "CLAIM",
                "description": "new",
            },
        },
        source_uuid="paper-2",
    )

    assert name_mapping == {"exact entity": "Exact Entity"}
    assert "exact entity" not in graph
    assert graph.nodes["Exact Entity"]["description"] == "old | new"


def test_add_entities_threshold_one_skips_non_exact_fuzzy_scan(monkeypatch):
    def fail_find_entity_matches(*_args, **_kwargs):
        raise AssertionError("threshold 1.0 should use exact-only matching")

    monkeypatch.setattr(
        "graph_enrichment.graph_merger.find_entity_matches",
        fail_find_entity_matches,
    )

    graph = nx.DiGraph()
    graph.add_node(
        "Existing Entity",
        entity_name="Existing Entity",
        entity_type="CLAIM",
        description="old",
    )

    _, name_mapping = add_entities_to_graph(
        graph,
        {
            "New Entity": {
                "entity_name": "New Entity",
                "entity_type": "CLAIM",
                "description": "new",
            },
        },
        source_uuid="paper-3",
        similarity_threshold=1.0,
    )

    assert name_mapping == {"New Entity": "New Entity"}
    assert "Existing Entity" in graph
    assert "New Entity" in graph
