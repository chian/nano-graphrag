"""
GASL command parser.
"""

import re
from typing import List, Dict, Any, Optional
from .types import Command
from .errors import ParseError
from .flexible_parser import FlexibleParser


class GASLParser:
    """Parses GASL commands into structured Command objects."""
    
    def __init__(self):
        self.flexible_parser = FlexibleParser()
        # Command patterns
        self.patterns = {
            # Core commands
            "DECLARE": r"DECLARE\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+AS\s+(DICT|LIST|COUNTER)(?:\s+WITH_DESCRIPTION\s+\"([^\"]*)\")?",
            "FIND": r"FIND\s+(nodes|edges|paths)\s+(?:with\s+)?([^;]+)",
            "CLASSIFY": r"CLASSIFY\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:with\s+)?([^;]+)",
            "PROCESS": r"PROCESS\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:with\s+)?([^;]+)(?:\s+AS\s+([a-zA-Z_][a-zA-Z0-9_.]*))?",
            "UPDATE": r"UPDATE\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:with\s+)?([^;]+)",
            "COUNT": r"COUNT.*AS.*",
            "SHOW": r"SHOW\s+([a-zA-Z_][a-zA-Z0-9_.]*)(?:\s+limit\s+(\d+))?",
            "INSPECT": r"INSPECT\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
            "ITERATE": r"ITERATE\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+BATCH_SIZE\s+(\d+)\s+WITH\s+(\w+)\s+instruction:\s*([^;]+)",
            
            # Graph navigation commands
            "GRAPHWALK": r"GRAPHWALK\s+from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+follow\s+([^;]+?)(?:\s+depth\s+(\d+))?",
            "GRAPHCONNECT": r"GRAPHCONNECT\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+to\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+via\s+([^;]+)",
            "SUBGRAPH": r"SUBGRAPH\s+around\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+radius\s+(\d+)(?:\s+include\s+([^;]+))?",
            "GRAPHPATTERN": r"GRAPHPATTERN\s+find\s+([^;]+?)\s+in\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
            
            # Multi-variable commands
            "JOIN": r"JOIN\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+with\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+on\s+([^;]+?)\s+AS\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
            "MERGE": r"MERGE\s+([^;]+?)\s+AS\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
            "COMPARE": r"COMPARE\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+with\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+on\s+([^;]+?)\s+AS\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
            
            # Data transformation commands
            "TRANSFORM": r"TRANSFORM\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:with\s+)?([^;]+)",
            "RESHAPE": r"RESHAPE\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+from\s+([^;]+?)\s+to\s+([^;]+)",
            "AGGREGATE": r"AGGREGATE\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+by\s+([^;]+?)\s+with\s+([^;]+)",
            "PIVOT": r"PIVOT\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+on\s+([^;]+?)\s+by\s+([^;]+)",
            
            # Field calculation commands
            "CALCULATE": r"CALCULATE\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+add\s+field:\s*([^;]+)",
            "SCORE": r"SCORE\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:with\s+)?([^;]+)",
            "RANK": r"RANK\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+by\s+([^;]+?)(?:\s+order\s+(desc|asc))?",
            "WEIGHT": r"WEIGHT\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:with\s+)?([^;]+)",
            
            # Object creation commands
            "CREATE": r"CREATE\s+(nodes|edges|summary)\s+from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:with\s+)?([^;]+)",
            "GENERATE": r"GENERATE\s+([^;]+?)\s+from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:with\s+)?([^;]+)",
            
            # Pattern analysis commands
            "CLUSTER": r"CLUSTER\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:with\s+)?([^;]+)",
            "DETECT": r"DETECT\s+patterns\s+in\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:with\s+)?([^;]+)",
            "GROUP": r"GROUP\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+by\s+([^;]+?)(?:\s+with\s+([^;]+))?",
            "ANALYZE": r"ANALYZE\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+for\s+([^;]+)",
            
            # Control flow commands
            "SELECT": r"SELECT\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+FIELDS\s+([^;]+)\s+AS\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
            "SET": r"SET\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s*=\s*([^;]+)",
            "REQUIRE": r"REQUIRE\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:is\s+)?([^;]+)",
            "ASSERT": r"ASSERT\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+(?:is\s+)?([^;]+)",
            "ON": r"ON\s+(success|error|empty)\s+(?:do\s+)?([^;]+)",
            "TRY": r"TRY\s+([^;]+)",
            "CATCH": r"CATCH\s+([^;]+)",
            "FINALLY": r"FINALLY\s+([^;]+)",
            "CANCEL": r"CANCEL\s+PLAN\s+\"([^\"]*)\""
        }
    
    def parse_plan(self, plan_json: Dict[str, Any]) -> List[Command]:
        """Parse a plan object into a list of commands."""
        commands = []
        for i, command_text in enumerate(plan_json.get("commands", [])):
            try:
                command = self.parse_command(command_text.strip(), i + 1)
                commands.append(command)
            except ParseError as e:
                e.line_number = i + 1
                raise e
        return commands
    
    def parse_command(self, command_text: str, line_number: int = 1) -> Command:
        """Parse a single GASL command."""
        command_text = command_text.strip()
        if not command_text:
            raise ParseError("Empty command", command_text, line_number)
        
        # Try each command pattern
        for command_type, pattern in self.patterns.items():
            match = re.match(pattern, command_text, re.IGNORECASE)
            if match:
                args = self._extract_args(command_type, match.groups(), command_text)
                return Command(
                    command_type=command_type,
                    args=args,
                    raw_text=command_text,
                    line_number=line_number
                )
        
        # Fallback to flexible parser
        try:
            return self.flexible_parser.parse_command(command_text, line_number)
        except ParseError:
            raise ParseError(f"Unknown command: {command_text}", command_text, line_number)
    
    def _extract_args(self, command_type: str, groups: tuple, command_text: str) -> Dict[str, Any]:
        """Extract arguments based on command type."""
        args = {}
        
        if command_type == "DECLARE":
            args["variable"] = groups[0]
            args["type"] = groups[1]
            args["description"] = groups[2] if len(groups) > 2 and groups[2] else None
        
        elif command_type == "FIND":
            args["target"] = groups[0]  # nodes, edges, paths
            args["criteria"] = groups[1].strip()
        
        elif command_type in ["PROCESS", "UPDATE", "ANALYZE", "CLASSIFY"]:
            args["variable"] = groups[0]
            args["instruction"] = groups[1].strip()
            if command_type == "PROCESS" and len(groups) > 2 and groups[2]:
                args["target_variable"] = groups[2]
        
        elif command_type == "ITERATE":
            args["source_var"] = groups[0]
            args["batch_size"] = int(groups[1])
            args["sub_command"] = groups[2]
            args["instruction"] = groups[3].strip()
        
        elif command_type == "COUNT":
            # More flexible COUNT parsing
            args = self._parse_count_command(command_text)
        
        elif command_type == "SHOW":
            args["variable"] = groups[0]
            if len(groups) > 1 and groups[1]:
                args["limit"] = int(groups[1])
        
        elif command_type == "INSPECT":
            args["variable"] = groups[0]
        
        elif command_type == "SELECT":
            args["source"] = groups[0]
            args["fields"] = groups[1].strip()
            args["target"] = groups[2]
        
        elif command_type == "SET":
            args["variable"] = groups[0]
            args["value"] = groups[1].strip()
        
        elif command_type in ["REQUIRE", "ASSERT"]:
            args["variable"] = groups[0]
            args["condition"] = groups[1].strip()
        
        elif command_type == "ON":
            args["status"] = groups[0]
            args["action"] = groups[1].strip()
        
        elif command_type in ["TRY", "CATCH", "FINALLY"]:
            args["action"] = groups[0].strip()
        
        elif command_type == "CANCEL":
            args["plan_id"] = groups[0]
        
        # Graph Navigation commands
        elif command_type == "GRAPHWALK":
            args["from_variable"] = groups[0]
            # Handle case where relationship_types might include "depth X"
            relationship_text = groups[1].strip()
            if " depth " in relationship_text:
                parts = relationship_text.split(" depth ")
                args["relationship_types"] = parts[0].strip()
                args["depth"] = parts[1].strip() if len(parts) > 1 else "1"
            else:
                args["relationship_types"] = relationship_text
                args["depth"] = groups[2] if len(groups) > 2 and groups[2] else "1"
            
            # Special handling for common relationship types
            if args["relationship_types"] in ["a", "an", "any"]:
                args["relationship_types"] = "any"
        
        elif command_type == "GRAPHCONNECT":
            args["variable1"] = groups[0]
            args["variable2"] = groups[1]
            args["via_pattern"] = groups[2].strip()
        
        elif command_type == "SUBGRAPH":
            args["around_variable"] = groups[0]
            args["radius"] = groups[1]
            args["include_types"] = groups[2] if len(groups) > 2 and groups[2] else ""
        
        elif command_type == "GRAPHPATTERN":
            args["pattern_description"] = groups[0].strip()
            args["in_variable"] = groups[1]
        
        # Multi-variable commands
        elif command_type == "JOIN":
            args["variable1"] = groups[0]
            args["variable2"] = groups[1]
            args["join_field"] = groups[2].strip()
            args["result_variable"] = groups[3]
        
        elif command_type == "MERGE":
            args["variables"] = groups[0].strip()
            args["result_variable"] = groups[1]
        
        elif command_type == "COMPARE":
            args["variable1"] = groups[0]
            args["variable2"] = groups[1]
            args["comparison_field"] = groups[2].strip()
            args["result_variable"] = groups[3]
        
        # Data transformation commands
        elif command_type == "TRANSFORM":
            args["variable"] = groups[0]
            args["instruction"] = groups[1].strip()
        
        elif command_type == "RESHAPE":
            args["variable"] = groups[0]
            args["from_format"] = groups[1].strip()
            args["to_format"] = groups[2].strip()
        
        elif command_type == "AGGREGATE":
            args["variable"] = groups[0]
            args["by_field"] = groups[1].strip()
            args["operation"] = groups[2].strip()
        
        elif command_type == "PIVOT":
            args["variable"] = groups[0]
            args["pivot_field"] = groups[1].strip()
            args["value_field"] = groups[2].strip()
        
        # Field calculation commands
        elif command_type == "CALCULATE":
            args["variable"] = groups[0]
            args["field_name"] = groups[1].strip()
            args["computation"] = groups[2].strip()
        
        elif command_type == "SCORE":
            args["variable"] = groups[0]
            args["scoring_criteria"] = groups[1].strip()
        
        elif command_type == "RANK":
            args["variable"] = groups[0]
            args["rank_field"] = groups[1].strip()
            args["order"] = groups[2] if len(groups) > 2 and groups[2] else "desc"
        
        elif command_type == "WEIGHT":
            args["variable"] = groups[0]
            args["weighting_criteria"] = groups[1].strip()
        
        # Object creation commands
        elif command_type == "CREATE":
            args["object_type"] = groups[0]
            args["source_variable"] = groups[1]
            args["specification"] = groups[2] if len(groups) > 2 and groups[2] else ""
        
        elif command_type == "GENERATE":
            args["content_type"] = groups[0].strip()
            args["source_variable"] = groups[1]
            args["specification"] = groups[2] if len(groups) > 2 and groups[2] else ""
        
        # Pattern analysis commands
        elif command_type == "CLUSTER":
            args["variable"] = groups[0]
            args["clustering_criteria"] = groups[1].strip()
        
        elif command_type == "DETECT":
            args["variable"] = groups[0]
            args["pattern_type"] = groups[1].strip()
        
        elif command_type == "GROUP":
            args["variable"] = groups[0]
            args["group_field"] = groups[1].strip()
            args["aggregation"] = groups[2] if len(groups) > 2 and groups[2] else ""
        
        elif command_type == "ANALYZE":
            args["variable"] = groups[0]
            args["analysis_type"] = groups[1].strip()
        
        return args
    
    def validate_command(self, command: Command) -> bool:
        """Validate a parsed command."""
        if command.command_type == "DECLARE":
            return self._validate_declare(command)
        elif command.command_type == "FIND":
            return self._validate_find(command)
        elif command.command_type in ["PROCESS", "UPDATE", "ANALYZE"]:
            return self._validate_process_update_analyze(command)
        elif command.command_type == "COUNT":
            return self._validate_count(command)
        elif command.command_type == "SELECT":
            return self._validate_select(command)
        elif command.command_type == "SET":
            return self._validate_set(command)
        elif command.command_type in ["REQUIRE", "ASSERT"]:
            return self._validate_require_assert(command)
        elif command.command_type == "ON":
            return self._validate_on(command)
        elif command.command_type in ["TRY", "CATCH", "FINALLY"]:
            return self._validate_try_catch_finally(command)
        elif command.command_type == "CANCEL":
            return self._validate_cancel(command)
        # New command validations
        elif command.command_type in ["GRAPHWALK", "GRAPHCONNECT", "SUBGRAPH", "GRAPHPATTERN"]:
            return self._validate_graph_nav(command)
        elif command.command_type in ["JOIN", "MERGE", "COMPARE"]:
            return self._validate_multi_var(command)
        elif command.command_type in ["TRANSFORM", "RESHAPE", "AGGREGATE", "PIVOT"]:
            return self._validate_data_transform(command)
        elif command.command_type in ["CALCULATE", "SCORE", "RANK", "WEIGHT"]:
            return self._validate_field_calc(command)
        elif command.command_type in ["CREATE", "GENERATE"]:
            return self._validate_object_create(command)
        elif command.command_type in ["CLUSTER", "DETECT", "GROUP", "ANALYZE"]:
            return self._validate_pattern_analysis(command)
        
        return False
    
    def _validate_declare(self, command: Command) -> bool:
        """Validate DECLARE command."""
        args = command.args
        return (
            "variable" in args and 
            "type" in args and 
            args["type"] in ["DICT", "LIST", "COUNTER"]
        )
    
    def _validate_find(self, command: Command) -> bool:
        """Validate FIND command."""
        args = command.args
        return (
            "target" in args and 
            "criteria" in args and
            args["target"] in ["nodes", "edges", "paths"]
        )
    
    def _validate_process_update_analyze(self, command: Command) -> bool:
        """Validate PROCESS/UPDATE/ANALYZE commands."""
        args = command.args
        return "variable" in args and "instruction" in args
    
    def _parse_count_command(self, command_string: str) -> Dict[str, Any]:
        """Flexible COUNT command parser."""
        args = {}
        
        # Remove COUNT and clean up
        text = command_string.replace("COUNT", "").strip()
        
        # Check for FIND syntax
        if text.startswith("FIND nodes with"):
            # Extract criteria
            criteria_start = text.find("with") + 4
            criteria_end = text.find("field")
            if criteria_end > criteria_start:
                args["source"] = "FIND"
                args["criteria"] = text[criteria_start:criteria_end].strip()
                text = text[criteria_end:].strip()
        
        # Extract source variable if not FIND
        if "source" not in args:
            # Look for [variable] or variable syntax
            if text.startswith("["):
                end_bracket = text.find("]")
                if end_bracket > 0:
                    args["source"] = f"[{text[1:end_bracket]}]"
                    text = text[end_bracket + 1:].strip()
            else:
                # Find first word as variable name
                space_pos = text.find(" ")
                if space_pos > 0:
                    args["source"] = text[:space_pos]
                    text = text[space_pos:].strip()
        
        # Extract field name
        if text.startswith("field"):
            field_start = text.find("field") + 5
            # Find next keyword
            next_keyword = None
            for keyword in ["where", "group by", "AS"]:
                pos = text.find(keyword, field_start)
                if pos > field_start and (next_keyword is None or pos < next_keyword):
                    next_keyword = pos
            
            if next_keyword:
                field_text = text[field_start:next_keyword].strip()
                text = text[next_keyword:].strip()
            else:
                field_text = text[field_start:].strip()
                text = ""
            
            # Handle "unique" keyword in field name
            if field_text.endswith(" unique"):
                args["field_name"] = field_text[:-7].strip()  # Remove " unique"
                args["unique"] = True
            else:
                args["field_name"] = field_text
        
        # Extract where condition
        if text.startswith("where"):
            where_start = text.find("where") + 5
            group_pos = text.find("group by")
            as_pos = text.find("AS")
            
            next_pos = len(text)
            if group_pos > where_start:
                next_pos = min(next_pos, group_pos)
            if as_pos > where_start:
                next_pos = min(next_pos, as_pos)
            
            if next_pos < len(text):
                args["condition"] = text[where_start:next_pos].strip()
                text = text[next_pos:].strip()
            else:
                args["condition"] = text[where_start:].strip()
                text = ""
        
        # Extract group by
        if text.startswith("group by"):
            group_start = text.find("group by") + 8
            as_pos = text.find("AS")
            
            if as_pos > group_start:
                args["group_by"] = text[group_start:as_pos].strip()
                text = text[as_pos:].strip()
            else:
                args["group_by"] = text[group_start:].strip()
                text = ""
        
        # Extract unique flag
        args["unique"] = "unique" in command_string
        
        # Extract AS result variable
        if text.startswith("AS"):
            as_start = text.find("AS") + 2
            args["result_var"] = text[as_start:].strip()
        
        # Set defaults
        args.setdefault("condition", "all")
        
        return args
    
    def _validate_count(self, command: Command) -> bool:
        """Validate COUNT commands."""
        args = command.args
        
        # Check required fields
        if "field_name" not in args or not args["field_name"]:
            return False
        
        if "result_var" not in args or not args["result_var"]:
            return False
        
        # Either source variable or FIND criteria must be provided
        if not args.get("source") and not args.get("criteria"):
            return False
        
        return True
    
    def _validate_select(self, command: Command) -> bool:
        """Validate SELECT command."""
        args = command.args
        return (
            "source" in args and 
            "fields" in args and 
            "target" in args
        )
    
    def _validate_set(self, command: Command) -> bool:
        """Validate SET command."""
        args = command.args
        return "variable" in args and "value" in args
    
    def _validate_require_assert(self, command: Command) -> bool:
        """Validate REQUIRE/ASSERT commands."""
        args = command.args
        return "variable" in args and "condition" in args
    
    def _validate_on(self, command: Command) -> bool:
        """Validate ON command."""
        args = command.args
        return (
            "status" in args and 
            "action" in args and
            args["status"] in ["success", "error", "empty"]
        )
    
    def _validate_try_catch_finally(self, command: Command) -> bool:
        """Validate TRY/CATCH/FINALLY commands."""
        args = command.args
        return "action" in args
    
    def _validate_cancel(self, command: Command) -> bool:
        """Validate CANCEL command."""
        args = command.args
        return "plan_id" in args
    
    def _validate_graph_nav(self, command: Command) -> bool:
        """Validate graph navigation commands."""
        args = command.args
        if command.command_type == "GRAPHWALK":
            return "from_variable" in args and "relationship_types" in args
        elif command.command_type == "GRAPHCONNECT":
            return "variable1" in args and "variable2" in args and "via_pattern" in args
        elif command.command_type == "SUBGRAPH":
            return "around_variable" in args and "radius" in args
        elif command.command_type == "GRAPHPATTERN":
            return "pattern_description" in args and "in_variable" in args
        return False
    
    def _validate_multi_var(self, command: Command) -> bool:
        """Validate multi-variable commands."""
        args = command.args
        if command.command_type == "JOIN":
            return "variable1" in args and "variable2" in args and "join_field" in args and "result_variable" in args
        elif command.command_type == "MERGE":
            return "variables" in args and "result_variable" in args
        elif command.command_type == "COMPARE":
            return "variable1" in args and "variable2" in args and "comparison_field" in args and "result_variable" in args
        return False
    
    def _validate_data_transform(self, command: Command) -> bool:
        """Validate data transformation commands."""
        args = command.args
        if command.command_type == "TRANSFORM":
            return "variable" in args and "instruction" in args
        elif command.command_type == "RESHAPE":
            return "variable" in args and "from_format" in args and "to_format" in args
        elif command.command_type == "AGGREGATE":
            return "variable" in args and "by_field" in args and "operation" in args
        elif command.command_type == "PIVOT":
            return "variable" in args and "pivot_field" in args and "value_field" in args
        return False
    
    def _validate_field_calc(self, command: Command) -> bool:
        """Validate field calculation commands."""
        args = command.args
        if command.command_type == "CALCULATE":
            return "variable" in args and "field_name" in args and "computation" in args
        elif command.command_type in ["SCORE", "WEIGHT"]:
            return "variable" in args and "scoring_criteria" in args or "weighting_criteria" in args
        elif command.command_type == "RANK":
            return "variable" in args and "rank_field" in args
        return False
    
    def _validate_object_create(self, command: Command) -> bool:
        """Validate object creation commands."""
        args = command.args
        return "object_type" in args and "source_variable" in args
    
    def _validate_pattern_analysis(self, command: Command) -> bool:
        """Validate pattern analysis commands."""
        args = command.args
        if command.command_type in ["CLUSTER", "DETECT", "ANALYZE"]:
            return "variable" in args and ("clustering_criteria" in args or "pattern_type" in args or "analysis_type" in args)
        elif command.command_type == "GROUP":
            return "variable" in args and "group_field" in args
        return False
