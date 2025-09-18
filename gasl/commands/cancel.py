"""
CANCEL command handler.
"""

from typing import Any
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class CancelHandler(CommandHandler):
    """Handles CANCEL commands for plan cancellation."""
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "CANCEL"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute CANCEL command."""
        try:
            args = command.args
            plan_id = args["plan_id"]
            
            # This is a placeholder - in a real implementation,
            # this would signal the executor to cancel the specified plan
            
            # Create provenance
            provenance = [
                self._create_provenance(
                    source_id="gasl-cancel",
                    method="cancel_plan",
                    plan_id=plan_id
                )
            ]
            
            return self._create_result(
                command=command,
                status="success",
                data={"plan_id": plan_id, "cancelled": True},
                count=1,
                provenance=provenance
            )
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )