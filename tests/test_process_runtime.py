from gasl.process_runtime import CandidateSelector, ProcessSubtypeRouter


def _mock_items(n=100):
    items = []
    for i in range(n):
        items.append(
            {
                "id": f"node-{i}",
                "data": {
                    "entity_type": "TEST_TYPE" if i % 2 == 0 else "OTHER_TYPE",
                    "entity_name": f"Entity {i}",
                    "alternative_names": f"Alias {i}",
                    "description": f"Description for entity {i} mentioning ventilation and room {i}",
                },
            }
        )
    return items


def test_process_subtype_inference():
    router = ProcessSubtypeRouter()
    assert router.infer("filter where entity_type = 'X'") == "semantic_filter"
    assert router.infer("normalize rows with country in the output") == "field_derivation"
    assert router.infer("classify nodes into categories") == "classification"
    assert router.infer("compute combined_count = a + b") == "field_derivation"
    assert router.infer("summarize cross-node implications") == "cross_node_synthesis"


def test_candidate_selector_probe_is_deterministic():
    selector = CandidateSelector()
    items = _mock_items(120)
    first = selector.select(
        items,
        query="Which nodes mention ventilation in rooms?",
        instruction="filter where entity_type = 'TEST_TYPE'",
        subtype="semantic_filter",
    )
    second = selector.select(
        items,
        query="Which nodes mention ventilation in rooms?",
        instruction="filter where entity_type = 'TEST_TYPE'",
        subtype="semantic_filter",
    )
    assert [item["id"] for item in first.probe_items] == [item["id"] for item in second.probe_items]
    assert len(first.probe_items) <= selector.PROBE_SIZE
    assert len(first.final_items) <= selector.FINAL_BUDGET + selector.RANDOM_TAIL
