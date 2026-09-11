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
    produced_artifact: Optional[Dict[str, Any]] = None


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
    contract: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AdapterCapabilities:
    """Describes what a graph adapter can do.

    This used to carry a single `max_results` field that did two incompatible
    jobs: it capped how many rows a retrieval was allowed to *return*, and it
    bounded how much work path generation was allowed to *do*. The first job is
    positional truncation — it silently discarded matching rows by iteration
    order, so a FIND over a graph larger than the cap answered a different
    question than the one asked — and it is gone. The second job is real and is
    kept, under a name that says what it bounds.

    Neither field carries a default value here, and neither may acquire one
    without a cited measurement: an adapter that wants a bound declares it and
    says in words what justifies the number.
    """
    supports_path_finding: bool = True
    supports_cypher: bool = False
    supports_networkx: bool = False
    max_path_length: int = 10
    # Work bound on path generation, counted in SOURCES EXPANDED. Paths only.
    # None means the backend generates paths without a standing work bound
    # unless a caller supplies one per call.
    #
    # This counted (source, target) pairs until path generation stopped running
    # one graph search per pair. A single-source traversal reaches every target
    # in one pass, so the cost of a path query scales with |sources|, not with
    # |sources| x |targets|, and a budget denominated in pairs measured
    # something no longer performed.
    path_source_budget: Optional[int] = None
    # Work bound on GRAPHWALK, counted in SEEDS EXPANDED. None means the backend
    # expands every seed it is given.
    #
    # Unlike the path budget this one is kept, because there is no algorithmic
    # fix behind it: walking costs a per-node adapter query per hop, and that
    # cost is irreducible in a way a single-source traversal made the path cost
    # reducible. It is a real bound, so it is declared and it discloses.
    walk_seed_budget: Optional[int] = None
    # Server-side page size. This is a TRANSPORT concern, not a result bound:
    # a paging adapter still delivers every matching row, it just fetches them
    # in windows. None means the backend needs no paging.
    transport_window: Optional[int] = None
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
