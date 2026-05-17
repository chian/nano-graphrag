import unittest

from gasl.parser import GASLParser


class TestGASLParser(unittest.TestCase):
    def setUp(self):
        self.parser = GASLParser()

    def test_graphwalk_parses_relation_depth_and_result_var(self):
        cmd = self.parser.parse_command(
            "GRAPHWALK from respiratory_infections follow relation_type=AFFECTS depth 1 AS ri_cd_links"
        )
        self.assertEqual(cmd.command_type, "GRAPHWALK")
        self.assertEqual(cmd.args["from_variable"], "respiratory_infections")
        self.assertEqual(cmd.args["relationship_types"], "relation_type=AFFECTS")
        self.assertEqual(cmd.args["depth"], "1")
        self.assertEqual(cmd.args["result_var"], "ri_cd_links")

    def test_aggregate_parses_result_var(self):
        cmd = self.parser.parse_command(
            "AGGREGATE ri_cd_links by entity_name with count AS cognitive_domain_frequency"
        )
        self.assertEqual(cmd.command_type, "AGGREGATE")
        self.assertEqual(cmd.args["variable"], "ri_cd_links")
        self.assertEqual(cmd.args["by_field"], "entity_name")
        self.assertEqual(cmd.args["operation"], "count")
        self.assertEqual(cmd.args["result_variable"], "cognitive_domain_frequency")


if __name__ == "__main__":
    unittest.main()
