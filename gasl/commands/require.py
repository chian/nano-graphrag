"""
REQUIRE command handler.
"""

from typing import Any
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class RequireHandler(CommandHandler):
    """Handles REQUIRE commands for preconditions."""
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "REQUIRE"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute REQUIRE command."""
        try:
            args = command.args
            variable = args["variable"]
            condition = args["condition"]
            
            # Check if variable exists
            exists = False
            if self.context_store.has(variable):
                exists = True
            elif self.state_store.has_variable(variable):
                exists = True
            
            if not exists:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"REQUIRE failed: Variable {variable} does not exist"
                )
            
            # Get variable value
            value = None
            if self.context_store.has(variable):
                value = self.context_store.get(variable)
            elif self.state_store.has_variable(variable):
                value = self.state_store.get_variable(variable)
            
            # Check condition
            condition_met = self._check_condition(value, condition)
            
            if not condition_met:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"REQUIRE failed: Condition '{condition}' not met for {variable}"
                )
            
            # Create provenance
            provenance = [
                self._create_provenance(
                    source_id="gasl-require",
                    method="require_check",
                    variable=variable,
                    condition=condition,
                    result=True
                )
            ]
            
            return self._create_result(
                command=command,
                status="success",
                data={"variable": variable, "condition": condition, "met": True},
                count=1,
                provenance=provenance
            )
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _check_condition(self, value: Any, condition: str) -> bool:
        """Check if value meets condition."""
        condition = condition.strip().lower()
        
        if condition == "exists":
            return value is not None
        elif condition == "not empty":
            if isinstance(value, (list, dict)):
                return len(value) > 0
            elif isinstance(value, str):
                return len(value.strip()) > 0
            else:
                return value is not None
        elif condition.startswith("count >"):
            # Extract number
            try:
                threshold = int(condition.split(">")[1].strip())
                if isinstance(value, (list, dict)):
                    return len(value) > threshold
                else:
                    return False
            except (ValueError, IndexError):
                return False
        elif condition.startswith("count >="):
            # Extract number
            try:
                threshold = int(condition.split(">=")[1].strip())
                if isinstance(value, (list, dict)):
                    return len(value) >= threshold
                else:
                    return False
            except (ValueError, IndexError):
                return False
        
        # Default: assume condition is met if we can't parse it
        return True