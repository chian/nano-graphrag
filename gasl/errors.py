"""
Custom exceptions for GASL system.
"""
from __future__ import annotations


class GASLError(Exception):
    """Base exception for all GASL-related errors."""
    pass


class ParseError(GASLError):
    """Raised when GASL command parsing fails."""
    
    def __init__(self, message: str, command: str = None, line_number: int = None):
        super().__init__(message)
        self.command = command
        self.line_number = line_number


class ExecutionError(GASLError):
    """Raised when command execution fails."""
    
    def __init__(self, message: str, command: str = None, step_id: str = None):
        super().__init__(message)
        self.command = command
        self.step_id = step_id


class AdapterError(GASLError):
    """Raised when graph adapter operations fail."""
    
    def __init__(self, message: str, adapter_type: str = None, operation: str = None):
        super().__init__(message)
        self.adapter_type = adapter_type
        self.operation = operation


class AdapterCapabilityError(AdapterError):
    """Raised when a filter is well-formed but this backend cannot translate it.

    Distinct from `AdapterError` on purpose. A malformed filter is a caller
    error and rewriting the command can fix it; an untranslated filter is a
    property of the backend and no rewrite of the command will ever satisfy it.
    Collapsing the two sends the repair loop to rewrite a perfectly good command
    against an unrepairable condition, burning a call per attempt.
    """

    def __init__(
        self,
        message: str,
        adapter_type: str = None,
        operation: str = None,
        *,
        unsupported_keys: list[str] | None = None,
        surface: str = None,
    ):
        super().__init__(message, adapter_type, operation)
        self.unsupported_keys = list(unsupported_keys or [])
        self.surface = surface
        # Retrying the same command against the same adapter cannot succeed.
        self.retryable = False


class StateError(GASLError):
    """Raised when state operations fail."""
    
    def __init__(self, message: str, state_key: str = None, operation: str = None):
        super().__init__(message)
        self.state_key = state_key
        self.operation = operation


class LLMError(GASLError):
    """Raised when LLM interactions fail."""
    
    def __init__(
        self,
        message: str,
        provider: str = None,
        model: str = None,
        *,
        category: str = "unknown",
        status_code: int | None = None,
        original_type: str | None = None,
        fatal: bool = False,
    ):
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.category = category
        self.status_code = status_code
        self.original_type = original_type
        self.fatal = fatal
