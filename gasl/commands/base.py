"""
Base command handler.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List
from ..types import Command, ExecutionResult, Provenance
from ..state import StateStore, ContextStore


class CommandHandler(ABC):
    """Base class for all command handlers."""
    
    def __init__(self, state_store: StateStore, context_store: ContextStore):
        self.state_store = state_store
        self.context_store = context_store
    
    @abstractmethod
    def can_handle(self, command: Command) -> bool:
        """Check if this handler can process the command."""
        pass
    
    @abstractmethod
    def execute(self, command: Command) -> ExecutionResult:
        """Execute the command and return result."""
        pass
    
    def _create_provenance(self, source_id: str, method: str, **kwargs) -> Provenance:
        """Create provenance entry."""
        return Provenance(
            source_id=source_id,
            extraction={
                "method": method,
                **kwargs
            }
        )
    
    def _create_result(self, command: Command, status: str, data: Any = None, 
                      count: int = 0, error_message: str = None, 
                      provenance: List[Provenance] = None) -> ExecutionResult:
        """Create execution result."""
        return ExecutionResult(
            command=command.raw_text,
            status=status,
            data=data,
            count=count,
            error_message=error_message,
            provenance=provenance or []
        )
