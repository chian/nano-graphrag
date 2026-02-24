"""
Iterative Query Generator

Generates search queries from prioritized entities, combining entity names
with domain context and graph neighbors for comprehensive paper discovery.
"""

from typing import Dict, List, Set, Optional
import networkx as nx
import random

from .search_state import IterativeSearchState
from .config import HAIQUPipelineConfig


class IterativeQueryGenerator:
    """
    Generates search queries from graph entities for iterative discovery.

    Query strategies:
    1. Entity + domain context terms
    2. Entity + neighboring entities (from graph)
    3. Entity type-specific templates
    4. Knowledge gap filling queries
    """

    # Query templates by entity type
    QUERY_TEMPLATES = {
        'RESPIRATORY_DISEASE': [
            "{entity} cognitive effects",
            "{entity} neuropsychological impairment",
            "{entity} brain function",
            "{entity} cognitive assessment healthcare workers",
            "{entity} memory attention study",
        ],
        'COGNITIVE_FUNCTION': [
            "{entity} respiratory infection",
            "{entity} COVID-19 impairment",
            "{entity} acute illness effects",
            "{entity} measurement assessment",
            "{entity} healthcare workers study",
        ],
        'NEUROPSYCH_TEST': [
            "{entity} validation respiratory illness",
            "{entity} sensitivity cognitive impairment",
            "{entity} COVID assessment study",
            "{entity} reliability healthcare population",
        ],
        'CLAIM': [
            "evidence {entity}",
            "study findings {entity}",
            "research {entity}",
        ],
        'EFFECT_ESTIMATE': [
            "meta-analysis {entity}",
            "systematic review {entity}",
            "effect size {entity}",
        ],
        'COHORT': [
            "{entity} cognitive outcomes",
            "{entity} neuropsychological assessment",
            "{entity} respiratory infection study",
        ],
        'STUDY': [
            "{entity} findings",
            "{entity} methodology",
            "{entity} replication",
        ],
        'KNOWLEDGE_GAP': [
            "{entity} research needed",
            "{entity} understudied",
            "{entity} future research",
        ],
        'COVARIATE': [
            "{entity} cognitive outcomes",
            "{entity} confounding factor cognition",
            "{entity} respiratory disease cognition",
        ],
        'DISEASE_PHASE': [
            "{entity} cognitive assessment",
            "{entity} neuropsychological testing",
            "{entity} recovery cognition",
        ],
        'DEFAULT': [
            "{entity} cognition",
            "{entity} respiratory illness",
            "{entity} study",
        ]
    }

    def __init__(
        self,
        graph: nx.DiGraph,
        state: IterativeSearchState,
        config: Optional[HAIQUPipelineConfig] = None
    ):
        self.graph = graph
        self.state = state
        self.config = config or HAIQUPipelineConfig()
        self.generated_queries: Set[str] = set()

        # Load previously generated queries to avoid duplicates
        for record in self.state.searched_entities.values():
            for q in record.queries_generated:
                self.generated_queries.add(q.lower().strip())

    def generate_queries_for_entity(
        self,
        entity_name: str,
        max_queries: int = 5
    ) -> List[Dict]:
        """
        Generate search queries based on an entity and its graph context.

        Args:
            entity_name: The entity to generate queries for
            max_queries: Maximum number of queries to generate

        Returns:
            List of query dicts with 'query', 'entity', 'strategy' keys
        """
        if entity_name not in self.graph.nodes:
            return []

        entity_data = self.graph.nodes[entity_name]
        entity_type = entity_data.get('entity_type', 'UNKNOWN')

        queries = []

        # Strategy 1: Entity + domain context terms
        domain_queries = self._generate_domain_queries(entity_name, entity_type)
        queries.extend(domain_queries)

        # Strategy 2: Entity + graph neighbors
        neighbor_queries = self._generate_neighbor_queries(entity_name)
        queries.extend(neighbor_queries)

        # Strategy 3: Type-specific template queries
        template_queries = self._generate_template_queries(entity_name, entity_type)
        queries.extend(template_queries)

        # Deduplicate and filter
        filtered = self._filter_queries(queries, max_queries)

        return filtered

    def _generate_domain_queries(
        self,
        entity_name: str,
        entity_type: str
    ) -> List[Dict]:
        """Generate queries combining entity with domain context terms."""
        queries = []
        context_terms = self.config.domain_context_terms

        # Select a subset of context terms
        sample_size = min(3, len(context_terms))
        selected_terms = random.sample(context_terms, sample_size)

        for term in selected_terms:
            query = f"{entity_name} {term}"
            queries.append({
                'query': query,
                'entity': entity_name,
                'entity_type': entity_type,
                'strategy': 'domain_context'
            })

        return queries

    def _generate_neighbor_queries(self, entity_name: str) -> List[Dict]:
        """Generate queries based on graph relationships."""
        queries = []

        # Get neighbors (both in and out edges)
        try:
            successors = list(self.graph.successors(entity_name))
            predecessors = list(self.graph.predecessors(entity_name))
            neighbors = successors + predecessors
        except nx.NetworkXError:
            return queries

        # Limit to avoid too many queries
        neighbors = neighbors[:5]

        for neighbor in neighbors:
            # Skip if neighbor was already searched
            if self.state.is_entity_searched(neighbor):
                continue

            # Get edge data for context
            edge_data = {}
            if self.graph.has_edge(entity_name, neighbor):
                edge_data = self.graph.edges[entity_name, neighbor]
            elif self.graph.has_edge(neighbor, entity_name):
                edge_data = self.graph.edges[neighbor, entity_name]

            relation_type = edge_data.get('relation_type', 'related to')

            # Create relationship-aware query
            query = f"{entity_name} {neighbor}"
            queries.append({
                'query': query,
                'entity': entity_name,
                'entity_type': self.graph.nodes[entity_name].get('entity_type', 'UNKNOWN'),
                'strategy': 'neighbor',
                'related_entity': neighbor,
                'relation_type': relation_type
            })

        return queries

    def _generate_template_queries(
        self,
        entity_name: str,
        entity_type: str
    ) -> List[Dict]:
        """Generate queries using type-specific templates."""
        queries = []

        # Get templates for this entity type
        templates = self.QUERY_TEMPLATES.get(
            entity_type,
            self.QUERY_TEMPLATES['DEFAULT']
        )

        # Select a subset of templates
        sample_size = min(2, len(templates))
        selected = random.sample(templates, sample_size)

        for template in selected:
            query = template.format(entity=entity_name)
            queries.append({
                'query': query,
                'entity': entity_name,
                'entity_type': entity_type,
                'strategy': 'template',
                'template': template
            })

        return queries

    def _filter_queries(
        self,
        queries: List[Dict],
        max_queries: int
    ) -> List[Dict]:
        """Remove duplicate and previously-used queries."""
        filtered = []
        seen = set()

        for q in queries:
            query_text = q['query'].lower().strip()

            # Skip if already generated in this session
            if query_text in self.generated_queries:
                continue

            # Skip if duplicate within this batch
            if query_text in seen:
                continue

            # Skip very short queries
            if len(query_text) < 10:
                continue

            seen.add(query_text)
            self.generated_queries.add(query_text)
            filtered.append(q)

            if len(filtered) >= max_queries:
                break

        return filtered

    def generate_batch_queries(
        self,
        entities: List[str],
        queries_per_entity: int = 3
    ) -> List[Dict]:
        """Generate queries for a batch of entities."""
        all_queries = []

        for entity in entities:
            entity_queries = self.generate_queries_for_entity(
                entity,
                max_queries=queries_per_entity
            )
            all_queries.extend(entity_queries)

        return all_queries

    def get_query_stats(self) -> Dict:
        """Get statistics about generated queries."""
        return {
            'total_generated': len(self.generated_queries),
            'unique_entities_queried': len(set(
                q.split()[0] for q in self.generated_queries
            )) if self.generated_queries else 0
        }

    def __repr__(self) -> str:
        stats = self.get_query_stats()
        return (
            f"IterativeQueryGenerator(\n"
            f"  total_queries={stats['total_generated']},\n"
            f"  entities_queried={stats['unique_entities_queried']}\n"
            f")"
        )
