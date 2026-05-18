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

    def test_rank_parses_full_field_name_and_order(self):
        cmd = self.parser.parse_command(
            "RANK confounding_factors by count order desc"
        )
        self.assertEqual(cmd.command_type, "RANK")
        self.assertEqual(cmd.args["variable"], "confounding_factors")
        self.assertEqual(cmd.args["field"], "count")
        self.assertEqual(cmd.args["order"], "desc")

    def test_on_parses_status_and_action(self):
        cmd = self.parser.parse_command(
            "ON empty do GRAPHWALK from occupancy_load_nodes follow ADJACENT_TO depth 6 AS occupancy_reachable_graph"
        )
        self.assertEqual(cmd.command_type, "ON")
        self.assertEqual(cmd.args["status"], "empty")
        self.assertEqual(
            cmd.args["action"],
            "GRAPHWALK from occupancy_load_nodes follow ADJACENT_TO depth 6 AS occupancy_reachable_graph",
        )

    def test_project_parses_grain_fields_and_result_var(self):
        cmd = self.parser.parse_command(
            "PROJECT contains_targets GRAIN edge FIELDS src_id,tgt_id,data.entity_name AS entity_name KEYS src_id,tgt_id PRESERVE_MULTIPLICITY AS pathogen_links"
        )
        self.assertEqual(cmd.command_type, "PROJECT")
        self.assertEqual(cmd.args["variable"], "contains_targets")
        self.assertEqual(cmd.args["grain"], "edge")
        self.assertEqual(cmd.args["fields"], "src_id,tgt_id,data.entity_name AS entity_name")
        self.assertEqual(cmd.args["keys"], "src_id,tgt_id")
        self.assertTrue(cmd.args["preserve_multiplicity"])
        self.assertEqual(cmd.args["result_variable"], "pathogen_links")

    def test_collapse_parses_weight_and_result_var(self):
        cmd = self.parser.parse_command(
            "COLLAPSE pathogen_links BY entity_name COUNT AS occurrence_count AS unique_pathogens"
        )
        self.assertEqual(cmd.command_type, "COLLAPSE")
        self.assertEqual(cmd.args["variable"], "pathogen_links")
        self.assertEqual(cmd.args["by_field"], "entity_name")
        self.assertEqual(cmd.args["weight_field"], "occurrence_count")
        self.assertEqual(cmd.args["result_variable"], "unique_pathogens")


if __name__ == "__main__":
    unittest.main()
