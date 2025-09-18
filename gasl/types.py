"""
Core data structures for GASL system.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, Literal
from datetime import datetime
import json


@dataclass
class Provenance:
    """Tracks the source and method of data extraction."""
    source_id: str
    doc_id: Optional[str] = None
    offset_start: Optional[int] = None
    offset_end: Optional[int] = None
    snippet: Optional[str] = None
    extraction: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HistoryEntry:
    """Single entry in execution history."""
    step_id: str
    command: str
    status: Literal["success", "error", "empty", "partial"]
    result_count: int
    duration_ms: int
    timestamp: datetime
    error_message: Optional[str] = None
    provenance: List[Provenance] = field(default_factory=list)


@dataclass
class StateSnapshot:
    """Snapshot of state at a decision point for MCTS future-proofing."""
    snapshot_id: str
    timestamp: datetime
    variables: Dict[str, Any]
    history: List[HistoryEntry]
    next_actions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Command:
    """Parsed GASL command."""
    command_type: str
    args: Dict[str, Any]
    raw_text: str
    line_number: int


@dataclass
class PlanObject:
    """JSON plan object emitted by LLM."""
    plan_id: str
    why: str
    commands: List[str]
    config: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "why": self.why,
            "commands": self.commands,
            "config": self.config
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanObject":
        return cls(
            plan_id=data["plan_id"],
            why=data["why"],
            commands=data["commands"],
            config=data.get("config", {})
        )


@dataclass
class ExecutionResult:
    """Result of executing a single command."""
    command: str
    status: Literal["success", "error", "empty", "partial"]
    data: Any = None
    count: int = 0
    error_message: Optional[str] = None
    provenance: List[Provenance] = field(default_factory=list)
    duration_ms: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AdapterCapabilities:
    """Describes what a graph adapter can do."""
    supports_path_finding: bool = True
    supports_cypher: bool = False
    supports_networkx: bool = False
    max_path_length: int = 10
    max_results: int = 1000
    supported_node_properties: List[str] = field(default_factory=list)
    supported_edge_properties: List[str] = field(default_factory=list)


@dataclass
class LLMConfig:
    """Configuration for LLM interactions."""
    provider: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 4000
    timeout: int = 300
    retry_attempts: int = 3
