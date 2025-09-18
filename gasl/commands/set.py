"""
SET command handler.
"""

from typing import Any
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class SetHandler(CommandHandler):
    """Handles SET commands for variable assignment."""
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "SET"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute SET command."""
        try:
            args = command.args
            variable = args["variable"]
            value_str = args["value"]
            
            # Parse value
            value = self._parse_value(value_str)
            
            # Set in context
            self.context_store.set(variable, value)
            
            # Create provenance
            provenance = [
                self._create_provenance(
                    source_id="gasl-set",
                    method="set_variable",
                    variable=variable,
                    value=value
                )
            ]
            
            return self._create_result(
                command=command,
                status="success",
                data={"variable": variable, "value": value},
                count=1,
                provenance=provenance
            )
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _parse_value(self, value_str: str) -> Any:
        """Parse value string into appropriate type."""
        value_str = value_str.strip()
        
        # Try to parse as JSON first
        try:
            import json
            return json.loads(value_str)
        except json.JSONDecodeError:
            pass
        
        # Try to parse as number
        try:
            if "." in value_str:
                return float(value_str)
            else:
                return int(value_str)
        except ValueError:
            pass
        
        # Try to parse as boolean
        if value_str.lower() in ["true", "false"]:
            return value_str.lower() == "true"
        
        # Return as string
        return value_str