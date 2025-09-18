"""
ON command handler.
"""

from typing import Any
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class OnHandler(CommandHandler):
    """Handles ON commands for conditional execution."""
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "ON"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute ON command."""
        try:
            args = command.args
            status = args["status"]  # success, error, empty
            action = args["action"]
            
            # This is a placeholder - in a real implementation,
            # this would be handled by the executor to set up
            # conditional execution based on previous command status
            
            # Create provenance
            provenance = [
                self._create_provenance(
                    source_id="gasl-on",
                    method="on_condition",
                    status=status,
                    action=action
                )
            ]
            
            return self._create_result(
                command=command,
                status="success",
                data={"status": status, "action": action, "registered": True},
                count=1,
                provenance=provenance
            )
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )