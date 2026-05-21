import unittest

from gasl.search_refinement_agent import LLMSearchRefinementAgent


class _StubLLM:
    def __init__(self, response: str):
        self.response = response
        self.model = "gpt-5.5"
        self.reasoning_effort = None

    def clone(self, model=None, reasoning_effort=None):
        child = _StubLLM(self.response)
        child.model = model or self.model
        child.reasoning_effort = reasoning_effort
        return child

    def call(self, prompt: str) -> str:
        return self.response


class TestGraphwalkRefiner(unittest.TestCase):
    def test_refine_graphwalk_sample_returns_structured_json(self):
        llm = _StubLLM(
            """```json
            {
              "refinement_hint": "keep",
              "refinement_reason": "anchored to sources and relation semantics look correct",
              "refinement_anchor_strength": 0.9,
              "refinement_relation_strength": 0.8,
              "refinement_depth_strength": 0.9,
              "refinement_payload_hint": "edge_rows",
              "refinement_grain_hint": "edge",
              "refinement_downstream_hint": ["PROCESS", "AGGREGATE", "SHOW"],
              "repair_hint": "",
              "refinement_confidence": 0.88
            }
            ```"""
        )
        refiner = LLMSearchRefinementAgent(llm)
        result = refiner.get_graphwalk_refinement(
            {"from_variable": "src_nodes", "relationship_types": "AFFECTS", "depth": "1"},
            [{"id": "s1", "data": {"entity_name": "SOURCE"}}],
            iter([{"id": "t1", "src_id": "s1", "tgt_id": "t1", "data": {"entity_name": "TARGET"}}]),
            contract={"payload_kind": "walk_rows", "grain_type": "edge", "usable_by": ["PROCESS"]},
        )
        self.assertEqual(result["refinement_hint"], "keep")
        self.assertEqual(result["refinement_payload_hint"], "edge_rows")
        self.assertEqual(result["refinement_grain_hint"], "edge")
        self.assertIn("AGGREGATE", result["refinement_downstream_hint"])


if __name__ == "__main__":
    unittest.main()
