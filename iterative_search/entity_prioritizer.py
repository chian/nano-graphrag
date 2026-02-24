"""
Entity Priority Queue

Ranks entities for iterative search by novelty, importance,
connectivity, and domain relevance.
"""

from dataclasses import dataclass
from typing import List, Optional
import networkx as nx

from .search_state import IterativeSearchState
from .config import HAIQUPipelineConfig


@dataclass
class EntityPriority:
    """Priority score for an entity."""
    entity_name: str
    entity_type: str
    importance_score: float      # From extraction (0-1)
    novelty_score: float         # Higher for newly discovered entities (0-1)
    connectivity_score: float    # Based on graph centrality (0-1)
    domain_relevance_score: float  # Based on priority entity types (0-1)
    combined_score: float        # Weighted combination

    def __lt__(self, other: 'EntityPriority') -> bool:
        """For sorting - higher scores first."""
        return self.combined_score > other.combined_score


class EntityPriorityQueue:
    """
    Prioritizes entities for iterative search.

    Entities are ranked by a weighted combination of:
    - Novelty: Recently discovered entities score higher
    - Importance: Extraction-time importance scores
    - Connectivity: Graph centrality metrics
    - Domain relevance: Priority entity types score higher
    """

    # Weights for combining scores (must sum to 1.0)
    WEIGHT_NOVELTY = 0.35
    WEIGHT_IMPORTANCE = 0.25
    WEIGHT_CONNECTIVITY = 0.15
    WEIGHT_DOMAIN_RELEVANCE = 0.25

    def __init__(
        self,
        graph: nx.DiGraph,
        state: IterativeSearchState,
        config: Optional[HAIQUPipelineConfig] = None
    ):
        self.graph = graph
        self.state = state
        self.config = config or HAIQUPipelineConfig()
        self.priorities: List[EntityPriority] = []

        # Pre-compute centrality
        self._degree_centrality = {}
        if graph.number_of_nodes() > 0:
            try:
                self._degree_centrality = nx.degree_centrality(graph)
            except Exception:
                # Fallback for problematic graphs
                self._degree_centrality = {n: 0.0 for n in graph.nodes()}

    def compute_priorities(self) -> List[EntityPriority]:
        """Compute priority scores for all unsearched entities."""
        self.priorities = []

        unsearched = self.state.get_unsearched_entities(self.graph)

        for entity_name in unsearched:
            if entity_name not in self.graph.nodes:
                continue

            node_data = self.graph.nodes[entity_name]
            entity_type = node_data.get('entity_type', 'UNKNOWN')

            # Compute individual scores
            importance = self._get_importance_score(entity_name, node_data)
            novelty = self._compute_novelty_score(entity_name)
            connectivity = self._compute_connectivity_score(entity_name)
            domain_relevance = self._compute_domain_relevance(entity_type)

            # Weighted combination
            combined = (
                self.WEIGHT_NOVELTY * novelty +
                self.WEIGHT_IMPORTANCE * importance +
                self.WEIGHT_CONNECTIVITY * connectivity +
                self.WEIGHT_DOMAIN_RELEVANCE * domain_relevance
            )

            priority = EntityPriority(
                entity_name=entity_name,
                entity_type=entity_type,
                importance_score=importance,
                novelty_score=novelty,
                connectivity_score=connectivity,
                domain_relevance_score=domain_relevance,
                combined_score=combined
            )

            self.priorities.append(priority)

        # Sort by combined score (highest first)
        self.priorities.sort()

        return self.priorities

    def get_top_entities(self, n: int = 10) -> List[str]:
        """Get top N entity names for next search round."""
        if not self.priorities:
            self.compute_priorities()

        return [p.entity_name for p in self.priorities[:n]]

    def get_top_priorities(self, n: int = 10) -> List[EntityPriority]:
        """Get top N EntityPriority objects with full scoring details."""
        if not self.priorities:
            self.compute_priorities()

        return self.priorities[:n]

    def _get_importance_score(self, entity_name: str, node_data: dict) -> float:
        """Get importance score from node data, normalized to 0-1."""
        score = node_data.get('importance_score', 0.5)
        try:
            score = float(score)
        except (ValueError, TypeError):
            score = 0.5
        return max(0.0, min(1.0, score))

    def _compute_novelty_score(self, entity_name: str) -> float:
        """
        Higher score for entities discovered in recent rounds.

        - Entities from the most recent round: 1.0
        - Entities from 1 round ago: 0.8
        - Entities from 2 rounds ago: 0.6
        - Seed entities (round 0): 0.4
        """
        current_round = self.state.current_round

        # Find which round this entity was discovered
        discovery_round = None
        for round_num in sorted(self.state.entities_by_round.keys()):
            if entity_name in self.state.entities_by_round[round_num]:
                discovery_round = round_num
                break

        if discovery_round is None:
            # Entity not tracked - assume it's new
            return 1.0

        # Calculate recency
        rounds_ago = current_round - discovery_round

        if rounds_ago <= 0:
            return 1.0
        elif rounds_ago == 1:
            return 0.8
        elif rounds_ago == 2:
            return 0.6
        elif rounds_ago == 3:
            return 0.4
        else:
            return 0.2  # Older entities get minimum novelty

    def _compute_connectivity_score(self, entity_name: str) -> float:
        """
        Based on degree centrality in the graph.

        Higher connectivity suggests the entity is more central
        to the knowledge domain.
        """
        return self._degree_centrality.get(entity_name, 0.0)

    def _compute_domain_relevance(self, entity_type: str) -> float:
        """
        Higher score for priority entity types.

        Priority types are defined in config and represent the most
        important entity types for the domain.
        """
        priority_types = self.config.priority_entity_types

        if not priority_types:
            return 0.5  # Default

        if entity_type in priority_types:
            # Score based on position in priority list
            # First in list = 1.0, last = 0.6
            position = priority_types.index(entity_type)
            return 1.0 - (position * 0.05)  # 0.05 decay per position

        return 0.3  # Non-priority types

    def get_entities_by_type(self, entity_type: str, n: int = 10) -> List[str]:
        """Get top N unsearched entities of a specific type."""
        if not self.priorities:
            self.compute_priorities()

        matching = [
            p.entity_name for p in self.priorities
            if p.entity_type == entity_type
        ]

        return matching[:n]

    def get_type_distribution(self) -> dict:
        """Get distribution of entity types among unsearched entities."""
        if not self.priorities:
            self.compute_priorities()

        distribution = {}
        for p in self.priorities:
            t = p.entity_type
            distribution[t] = distribution.get(t, 0) + 1

        return distribution

    def __repr__(self) -> str:
        return (
            f"EntityPriorityQueue(\n"
            f"  total_entities={len(self.priorities)},\n"
            f"  type_distribution={self.get_type_distribution()}\n"
            f")"
        )
