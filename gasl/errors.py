"""
Custom exceptions for GASL system.
"""


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


class StateError(GASLError):
    """Raised when state operations fail."""
    
    def __init__(self, message: str, state_key: str = None, operation: str = None):
        super().__init__(message)
        self.state_key = state_key
        self.operation = operation


class LLMError(GASLError):
    """Raised when LLM interactions fail."""
    
    def __init__(self, message: str, provider: str = None, model: str = None):
        super().__init__(message)
        self.provider = provider
        self.model = model
