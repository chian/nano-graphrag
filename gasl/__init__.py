"""
GASL - Graph Analysis & State Language

A flexible, LLM-driven system for graph traversal and stateful accumulation.
"""

from .types import (
    PlanObject,
    Command,
    StateSnapshot,
    ExecutionResult,
    Provenance,
    HistoryEntry
)
from .executor import GASLExecutor
from .state import StateStore, ContextStore
from .parser import GASLParser
from .adapters import NetworkXAdapter, Neo4jAdapter
from .llm import ArgoBridgeLLM
from .errors import GASLError, ParseError, ExecutionError, AdapterError, StateError, LLMError

__version__ = "0.1.0"
__all__ = [
    "PlanObject",
    "Command", 
    "StateSnapshot",
    "ExecutionResult",
    "Provenance",
    "HistoryEntry",
    "GASLExecutor",
    "StateStore",
    "ContextStore", 
    "GASLParser",
    "NetworkXAdapter",
    "Neo4jAdapter",
    "ArgoBridgeLLM",
    "GASLError",
    "ParseError",
    "ExecutionError",
    "AdapterError",
    "StateError",
    "LLMError"
]
