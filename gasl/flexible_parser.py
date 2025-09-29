"""
Flexible parser for GASL commands using hybrid approach.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from .types import Command
from .errors import ParseError


class FlexibleParser:
    """Flexible parser using hybrid approach."""
    
    def __init__(self):
        # Command keywords for classification
        self.command_keywords = [
            "DECLARE", "FIND", "PROCESS", "CLASSIFY", "UPDATE", "COUNT",
            "SELECT", "SET", "REQUIRE", "ASSERT", "ON", "TRY", "CATCH", "CANCEL",
            "GRAPHWALK", "GRAPHCONNECT", "SUBGRAPH", "GRAPHPATTERN",
            "JOIN", "MERGE", "COMPARE", "TRANSFORM", "RESHAPE", "AGGREGATE",
            "PIVOT", "CALCULATE", "SCORE", "RANK", "WEIGHT", "CREATE", "GENERATE",
            "CLUSTER", "DETECT", "GROUP", "ANALYZE"
        ]
        
        # Keywords for different command types
        self.command_patterns = {
            "DECLARE": ["AS", "WITH_DESCRIPTION"],
            "FIND": ["with", "AS"],
            "PROCESS": ["with", "instruction", "AS"],
            "CLASSIFY": ["with", "instruction"],
            "UPDATE": ["with", "operation", "where"],
            "COUNT": ["where", "AS"],
            "SELECT": ["FIELDS", "AS"],
            "SET": ["=", "to"],
            "REQUIRE": ["condition"],
            "ASSERT": ["condition"],
            "ON": ["do", "then"],
            "TRY": ["CATCH"],
            "CANCEL": [],
            "GRAPHWALK": ["from", "follow", "depth"],
            "GRAPHCONNECT": ["to", "via"],
            "SUBGRAPH": ["around", "radius", "include"],
            "GRAPHPATTERN": ["find", "in"],
            "JOIN": ["with", "on", "AS"],
            "MERGE": ["with", "AS"],
            "COMPARE": ["with", "AS"],
            "TRANSFORM": ["with", "AS"],
            "RESHAPE": ["from", "to", "AS"],
            "AGGREGATE": ["by", "with", "AS"],
            "PIVOT": ["by", "AS"],
            "CALCULATE": ["with", "AS"],
            "SCORE": ["with", "AS"],
            "RANK": ["by", "AS"],
            "WEIGHT": ["by", "AS"],
            "CREATE": ["with", "AS"],
            "GENERATE": ["from", "with", "format", "AS"],
            "CLUSTER": ["with", "AS"],
            "DETECT": ["with", "AS"],
            "GROUP": ["by", "AS"],
            "ANALYZE": ["with", "AS"]
        }
    
    def parse_command(self, command_text: str, line_number: int = 1) -> Command:
        """Parse a command using flexible approach."""
        command_text = command_text.strip()
        
        # Step 1: Classify command type
        command_type = self._classify_command(command_text)
        if not command_type:
            raise ParseError(f"Unknown command: {command_text}", command_text, line_number)
        
        # Step 2: Extract arguments based on command type
        args = self._extract_arguments(command_type, command_text)
        
        return Command(
            command_type=command_type,
            args=args,
            raw_text=command_text,
            line_number=line_number
        )
    
    def _classify_command(self, text: str) -> Optional[str]:
        """Classify command type by looking for keywords."""
        text_upper = text.upper()
        
        for command in self.command_keywords:
            if text_upper.startswith(command):
                return command
        
        return None
    
    def _extract_arguments(self, command_type: str, text: str) -> Dict[str, Any]:
        """Extract arguments based on command type."""
        if command_type == "COUNT":
            return self._parse_count_flexible(text)
        elif command_type == "FIND":
            return self._parse_find_flexible(text)
        elif command_type == "DECLARE":
            return self._parse_declare_flexible(text)
        elif command_type == "PROCESS":
            return self._parse_process_flexible(text)
        elif command_type == "UPDATE":
            return self._parse_update_flexible(text)
        elif command_type == "CLASSIFY":
            return self._parse_classify_flexible(text)
        else:
            # Fallback to basic parsing for other commands
            return self._parse_basic_command(command_type, text)
    
    def _parse_count_flexible(self, text: str) -> Dict[str, Any]:
        """Flexible COUNT command parser."""
        args = {}
        
        # Remove COUNT keyword
        text = text.replace("COUNT", "").strip()
        
        # Extract components by looking for keywords
        components = self._extract_components(text, [
            "FIND nodes with", "field", "where", "group by", "unique", "AS"
        ])
        
        # Handle FIND syntax
        if "FIND nodes with" in components:
            args["source"] = "FIND"
            args["criteria"] = components["FIND nodes with"]
        else:
            # Look for source variable
            source = self._extract_source_variable(text)
            if source:
                args["source"] = source
        
        # Extract field name
        if "field" in components:
            args["field_name"] = components["field"]
        
        # Extract where condition
        if "where" in components:
            args["condition"] = components["where"]
        else:
            args["condition"] = "all"
        
        # Extract group by
        if "group by" in components:
            args["group_by"] = components["group by"]
        
        # Extract unique flag
        args["unique"] = "unique" in text
        
        # Extract result variable
        if "AS" in components:
            args["result_var"] = components["AS"]
        
        return args
    
    def _parse_find_flexible(self, text: str) -> Dict[str, Any]:
        """Flexible FIND command parser."""
        args = {}
        
        # Remove FIND keyword
        text = text.replace("FIND", "").strip()
        
        # Extract target (nodes, edges, paths)
        target_match = re.match(r'^(nodes|edges|paths)', text, re.IGNORECASE)
        if target_match:
            args["target"] = target_match.group(1).lower()
            text = text[target_match.end():].strip()
        
        # Extract criteria
        if text.startswith("with"):
            criteria = text[4:].strip()
            args["criteria"] = criteria
        else:
            args["criteria"] = text
        
        return args
    
    def _parse_declare_flexible(self, text: str) -> Dict[str, Any]:
        """Flexible DECLARE command parser."""
        args = {}
        
        # Remove DECLARE keyword
        text = text.replace("DECLARE", "").strip()
        
        # Extract variable name
        var_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_.]*)', text)
        if var_match:
            args["variable"] = var_match.group(1)
            text = text[var_match.end():].strip()
        
        # Extract type
        type_match = re.search(r'AS\s+(DICT|LIST|COUNTER)', text, re.IGNORECASE)
        if type_match:
            args["type"] = type_match.group(1).upper()
            text = text[:type_match.start()] + text[type_match.end():]
        
        # Extract description
        desc_match = re.search(r'WITH_DESCRIPTION\s+"([^"]*)"', text)
        if desc_match:
            args["description"] = desc_match.group(1)
        
        return args
    
    def _parse_process_flexible(self, text: str) -> Dict[str, Any]:
        """Flexible PROCESS command parser."""
        args = {}
        
        # Remove PROCESS keyword
        text = text.replace("PROCESS", "").strip()
        
        # Extract variable name
        var_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_.]*)', text)
        if var_match:
            args["variable"] = var_match.group(1)
            text = text[var_match.end():].strip()
        
        # Extract instruction
        if text.startswith("with"):
            instruction = text[4:].strip()
            args["instruction"] = instruction
        else:
            args["instruction"] = text
        
        # Extract target variable (AS clause)
        as_match = re.search(r'AS\s+([a-zA-Z_][a-zA-Z0-9_.]*)', text)
        if as_match:
            args["target_variable"] = as_match.group(1)
        
        return args
    
    def _parse_update_flexible(self, text: str) -> Dict[str, Any]:
        """Flexible UPDATE command parser."""
        args = {}
        
        # Remove UPDATE keyword
        text = text.replace("UPDATE", "").strip()
        
        # Extract variable name
        var_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_.]*)', text)
        if var_match:
            args["variable"] = var_match.group(1)
            text = text[var_match.end():].strip()
        
        # Extract instruction
        if text.startswith("with"):
            instruction = text[4:].strip()
            args["instruction"] = instruction
        else:
            args["instruction"] = text
        
        return args
    
    def _parse_classify_flexible(self, text: str) -> Dict[str, Any]:
        """Flexible CLASSIFY command parser."""
        args = {}
        
        # Remove CLASSIFY keyword
        text = text.replace("CLASSIFY", "").strip()
        
        # Extract variable name
        var_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_.]*)', text)
        if var_match:
            args["variable"] = var_match.group(1)
            text = text[var_match.end():].strip()
        
        # Extract instruction
        if text.startswith("with"):
            instruction = text[4:].strip()
            args["instruction"] = instruction
        else:
            args["instruction"] = text
        
        return args
    
    def _extract_components(self, text: str, keywords: List[str]) -> Dict[str, str]:
        """Extract text between keywords."""
        components = {}
        positions = []
        
        # Find all keyword positions
        for keyword in keywords:
            pos = text.find(keyword)
            if pos >= 0:
                positions.append((pos, keyword))
        
        # Sort by position
        positions.sort()
        
        # Extract text between keywords
        for i, (pos, keyword) in enumerate(positions):
            if i + 1 < len(positions):
                next_pos = positions[i + 1][0]
                components[keyword] = text[pos + len(keyword):next_pos].strip()
            else:
                components[keyword] = text[pos + len(keyword):].strip()
        
        return components
    
    def _extract_source_variable(self, text: str) -> Optional[str]:
        """Extract source variable from text."""
        # Look for [variable] syntax
        bracket_match = re.search(r'\[([a-zA-Z_][a-zA-Z0-9_.]*)\]', text)
        if bracket_match:
            return f"[{bracket_match.group(1)}]"
        
        # Look for variable before "field"
        field_pos = text.find("field")
        if field_pos > 0:
            var_text = text[:field_pos].strip()
            var_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_.]*)', var_text)
            if var_match:
                return var_match.group(1)
        
        return None
    
    def _parse_basic_command(self, command_type: str, text: str) -> Dict[str, Any]:
        """Basic parsing for commands not yet implemented."""
        # This is a fallback for commands that don't have flexible parsers yet
        return {"raw_text": text}
    
    def validate_command(self, command: Command) -> bool:
        """Validate a parsed command."""
        # Basic validation - can be enhanced per command type
        if command.command_type == "COUNT":
            return self._validate_count_command(command)
        elif command.command_type == "FIND":
            return self._validate_find_command(command)
        elif command.command_type == "DECLARE":
            return self._validate_declare_command(command)
        elif command.command_type == "PROCESS":
            return self._validate_process_command(command)
        elif command.command_type == "UPDATE":
            return self._validate_update_command(command)
        elif command.command_type == "CLASSIFY":
            return self._validate_classify_command(command)
        
        return True  # Default to valid for unimplemented commands
    
    def _validate_count_command(self, command: Command) -> bool:
        """Validate COUNT command."""
        args = command.args
        return (
            "field_name" in args and args["field_name"] and
            "result_var" in args and args["result_var"] and
            ("source" in args or "criteria" in args)
        )
    
    def _validate_find_command(self, command: Command) -> bool:
        """Validate FIND command."""
        args = command.args
        return "target" in args and "criteria" in args
    
    def _validate_declare_command(self, command: Command) -> bool:
        """Validate DECLARE command."""
        args = command.args
        return "variable" in args and "type" in args
    
    def _validate_process_command(self, command: Command) -> bool:
        """Validate PROCESS command."""
        args = command.args
        return "variable" in args and "instruction" in args
    
    def _validate_update_command(self, command: Command) -> bool:
        """Validate UPDATE command."""
        args = command.args
        return "variable" in args and "instruction" in args
    
    def _validate_classify_command(self, command: Command) -> bool:
        """Validate CLASSIFY command."""
        args = command.args
        return "variable" in args and "instruction" in args
