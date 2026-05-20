import tempfile
import unittest

from gasl.commands.multi_var import MultiVarHandler
from gasl.parser import GASLParser
from gasl.state import ContextStore, StateStore


class TestGASLMultiVarCompatibility(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        import os
        os.unlink(self.tmp.name)
        self.state = StateStore(self.tmp.name)
        self.context = ContextStore()
        self.handler = MultiVarHandler(self.state, self.context)
        self.parser = GASLParser()

    def tearDown(self):
        import os

        try:
            os.unlink(self.tmp.name)
        except FileNotFoundError:
            pass

    def test_join_accepts_parser_result_variable(self):
        self.state.declare_variable("left_rows", "LIST", "left")
        self.state.update_variable("left_rows", [{"id": "a", "left_value": 1}, {"id": "b", "left_value": 2}])
        self.state.declare_variable("right_rows", "LIST", "right")
        self.state.update_variable("right_rows", [{"id": "a", "right_value": 10}, {"id": "c", "right_value": 30}])

        cmd = self.parser.parse_command("JOIN left_rows with right_rows on id AS joined_rows")
        result = self.handler.execute(cmd)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.count, 1)
        joined = self.state.get_variable("joined_rows")
        self.assertEqual(len(joined["items"]), 1)
        self.assertEqual(joined["items"][0]["id"], "a")
        self.assertEqual(joined["items"][0]["left_value"], 1)
        self.assertEqual(joined["items"][0]["right_value"], 10)

    def test_compare_accepts_parser_result_variable_and_field(self):
        self.state.declare_variable("left_rows", "LIST", "left")
        self.state.update_variable("left_rows", [{"id": "a"}, {"id": "b"}])
        self.state.declare_variable("right_rows", "LIST", "right")
        self.state.update_variable("right_rows", [{"id": "b"}, {"id": "c"}])

        cmd = self.parser.parse_command("COMPARE left_rows with right_rows on id AS comparison_rows")
        result = self.handler.execute(cmd)

        self.assertEqual(result.status, "success")
        compared = self.state.get_variable("comparison_rows")
        self.assertEqual({row["id"] for row in compared["common_items"]}, {"b"})
        self.assertEqual({row["id"] for row in compared["only_in_var1"]}, {"a"})
        self.assertEqual({row["id"] for row in compared["only_in_var2"]}, {"c"})


if __name__ == "__main__":
    unittest.main()
