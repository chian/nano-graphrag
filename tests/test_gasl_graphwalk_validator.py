import unittest

from gasl.validation import LLMJudgeValidator


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


class TestGraphwalkValidator(unittest.TestCase):
    def test_validate_graphwalk_semantics_returns_structured_json(self):
        llm = _StubLLM(
            """```json
            {
              "semantically_valid": true,
              "reason": "anchored to sources and relation semantics look correct",
              "anchor_strength": 0.9,
              "relation_match_strength": 0.8,
              "depth_match_strength": 0.9,
              "recommended_payload_kind": "edge_rows",
              "recommended_grain": "edge",
              "downstream_safe_for": ["PROCESS", "AGGREGATE", "SHOW"],
              "repair_hint": "",
              "confidence": 0.88
            }
            ```"""
        )
        validator = LLMJudgeValidator(llm)
        result = validator.validate_graphwalk_semantics(
            {"from_variable": "src_nodes", "relationship_types": "AFFECTS", "depth": "1"},
            [{"id": "s1", "data": {"entity_name": "SOURCE"}}],
            [{"id": "t1", "src_id": "s1", "tgt_id": "t1", "data": {"entity_name": "TARGET"}}],
            1,
            contract={"payload_kind": "walk_rows", "grain_type": "edge", "usable_by": ["PROCESS"]},
        )
        self.assertTrue(result["semantically_valid"])
        self.assertEqual(result["recommended_payload_kind"], "edge_rows")
        self.assertEqual(result["recommended_grain"], "edge")
        self.assertIn("AGGREGATE", result["downstream_safe_for"])


if __name__ == "__main__":
    unittest.main()
