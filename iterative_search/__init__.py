"""
Iterative Search Package

Components for iterative graph-guided paper discovery.
"""

from .config import HAIQUPipelineConfig
from .search_state import (
    IterativeSearchState,
    EntitySearchRecord,
    PaperRecord
)
from .entity_prioritizer import (
    EntityPriorityQueue,
    EntityPriority
)
from .iterative_query_generator import IterativeQueryGenerator
from .convergence import (
    ConvergenceChecker,
    StopReason
)


__all__ = [
    # Configuration
    'HAIQUPipelineConfig',

    # State management
    'IterativeSearchState',
    'EntitySearchRecord',
    'PaperRecord',

    # Entity prioritization
    'EntityPriorityQueue',
    'EntityPriority',

    # Query generation
    'IterativeQueryGenerator',

    # Convergence
    'ConvergenceChecker',
    'StopReason',
]
