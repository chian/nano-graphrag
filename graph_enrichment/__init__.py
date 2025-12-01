"""
Graph Enrichment Module
Utilities for enriching knowledge graphs with additional papers
"""

from .entity_merger import (
    find_entity_matches,
    merge_entities,
    calculate_similarity
)

from .graph_merger import (
    add_entities_to_graph,
    add_relationships_to_graph,
    merge_graphs
)

__all__ = [
    'find_entity_matches',
    'merge_entities',
    'calculate_similarity',
    'add_entities_to_graph',
    'add_relationships_to_graph',
    'merge_graphs'
]
