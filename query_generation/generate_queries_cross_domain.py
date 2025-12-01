"""
Generate Queries: Cross-Domain
Finds entities that bridge multiple contexts, generates queries to explore cross-domain connections
"""

import argparse
import json
import networkx as nx
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from query_generation.graph_validator import validate_graph_has_types

def find_cross_domain_entities(graph: nx.Graph, domain_name: str) -> dict:
    """
    Find entities that connect diverse entity types or contexts.

    Args:
        graph: Domain-typed NetworkX graph
        domain_name: Domain schema name

    Returns:
        Dict with cross-domain bridge entities
    """

    print(f"\nAnalyzing for cross-domain entities...")

    cross_domain_entities = []

    for node in graph.nodes():
        node_data = graph.nodes[node]
        node_type = node_data.get('entity_type', 'UNKNOWN')

        # Get all neighbors
        neighbors = list(graph.neighbors(node)) + list(graph.predecessors(node))

        if len(neighbors) < 3:  # Need at least 3 connections to be interesting
            continue

        # Analyze neighbor diversity
        neighbor_types = []
        neighbor_labels = []

        for neighbor in neighbors:
            neighbor_data = graph.nodes[neighbor]
            neighbor_types.append(neighbor_data.get('entity_type', 'UNKNOWN'))
            neighbor_labels.append(neighbor_data.get('label', neighbor))

        # Count unique entity types among neighbors
        type_counts = Counter(neighbor_types)
        unique_types = len([t for t in type_counts.keys() if t != 'UNKNOWN'])

        # Entity is cross-domain if it connects 3+ different entity types
        if unique_types >= 3:
            # Get edge types too
            edge_types = []
            for neighbor in neighbors:
                if graph.has_edge(node, neighbor):
                    edge_data = graph.get_edge_data(node, neighbor)
                    edge_types.append(edge_data.get('relation_type', 'UNKNOWN'))
                if graph.has_edge(neighbor, node):
                    edge_data = graph.get_edge_data(neighbor, node)
                    edge_types.append(edge_data.get('relation_type', 'UNKNOWN'))

            unique_edge_types = len(set(edge_types))

            cross_domain_entities.append({
                'entity_id': node,
                'entity_label': node_data.get('label', node),
                'entity_type': node_type,
                'num_connections': len(neighbors),
                'num_unique_neighbor_types': unique_types,
                'num_unique_edge_types': unique_edge_types,
                'neighbor_type_distribution': dict(type_counts),
                'sample_neighbors': neighbor_labels[:5]
            })

    # Sort by diversity (most diverse first)
    cross_domain_entities.sort(
        key=lambda x: (x['num_unique_neighbor_types'], x['num_connections']),
        reverse=True
    )

    # Also find hub nodes (high degree)
    degree_centrality = nx.degree_centrality(graph)
    top_hubs = sorted(degree_centrality.items(), key=lambda x: x[1], reverse=True)[:20]

    hub_entities = []
    for node, centrality in top_hubs:
        node_data = graph.nodes[node]
        neighbors = list(graph.neighbors(node)) + list(graph.predecessors(node))

        if len(neighbors) >= 5:  # Must be highly connected
            neighbor_types = [graph.nodes[n].get('entity_type', '') for n in neighbors]
            unique_types = len(set(neighbor_types))

            hub_entities.append({
                'entity_id': node,
                'entity_label': node_data.get('label', node),
                'entity_type': node_data.get('entity_type', 'UNKNOWN'),
                'degree_centrality': centrality,
                'num_connections': len(neighbors),
                'num_unique_neighbor_types': unique_types
            })

    print(f"Found {len(cross_domain_entities)} cross-domain entities")
    print(f"Found {len(hub_entities)} hub entities")

    return {
        'cross_domain_entities': cross_domain_entities[:30],
        'hub_entities': hub_entities[:20]
    }

def generate_queries(analysis_results: dict, max_queries: int = 20) -> list[dict]:
    """
    Generate search queries to explore cross-domain connections.

    Args:
        analysis_results: Output from find_cross_domain_entities
        max_queries: Maximum number of queries

    Returns:
        List of query dicts
    """

    queries = []
    seen_queries = set()

    # Queries for cross-domain entities
    for entity in analysis_results['cross_domain_entities']:
        entity_label = entity['entity_label']
        entity_type = entity['entity_type']
        neighbor_types = entity['neighbor_type_distribution']

        # Query 1: Explore entity in multiple contexts
        contexts = [t.lower() for t in neighbor_types.keys() if t != 'UNKNOWN'][:2]
        if len(contexts) >= 2:
            query_text = f"{entity_label} role in {contexts[0]} and {contexts[1]}"
            if query_text.lower() not in seen_queries:
                queries.append({
                    'query': query_text,
                    'type': 'cross_context_role',
                    'entity': entity_label,
                    'entity_type': entity_type,
                    'contexts': contexts
                })
                seen_queries.add(query_text.lower())

        # Query 2: Broad cross-domain exploration
        query_text = f"{entity_label} interactions and functions"
        if query_text.lower() not in seen_queries and len(queries) < max_queries:
            queries.append({
                'query': query_text,
                'type': 'broad_interactions',
                'entity': entity_label,
                'num_known_connections': entity['num_connections']
            })
            seen_queries.add(query_text.lower())

        # Query 3: Specific neighbor type exploration
        for neighbor_type, count in list(neighbor_types.items())[:2]:
            if neighbor_type != 'UNKNOWN':
                query_text = f"{entity_label} and {neighbor_type.lower()}"
                if query_text.lower() not in seen_queries and len(queries) < max_queries:
                    queries.append({
                        'query': query_text,
                        'type': 'entity_type_interaction',
                        'entity': entity_label,
                        'interacting_type': neighbor_type,
                        'num_known': count
                    })
                    seen_queries.add(query_text.lower())

    # Queries for hub entities
    for hub in analysis_results['hub_entities'][:10]:
        entity_label = hub['entity_label']
        entity_type = hub['entity_type']

        # Query for hub network exploration
        query_text = f"{entity_label} network and interactions"
        if query_text.lower() not in seen_queries and len(queries) < max_queries:
            queries.append({
                'query': query_text,
                'type': 'hub_network_exploration',
                'entity': entity_label,
                'entity_type': entity_type,
                'centrality': hub['degree_centrality']
            })
            seen_queries.add(query_text.lower())

        # Query for regulatory role (hubs often regulate)
        query_text = f"{entity_label} regulatory role"
        if query_text.lower() not in seen_queries and len(queries) < max_queries:
            queries.append({
                'query': query_text,
                'type': 'regulatory_role',
                'entity': entity_label
            })
            seen_queries.add(query_text.lower())

    # Limit total
    queries = queries[:max_queries]

    print(f"\nGenerated {len(queries)} search queries")

    return queries

def main(args):
    """Main function"""

    print(f"{'='*60}")
    print(f"Cross-Domain Query Generation")
    print(f"{'='*60}\n")

    # Load graph
    print(f"Loading graph: {args.graph_file}")
    graph = nx.read_graphml(args.graph_file)
    print(f"Loaded graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

    # Validate graph
    try:
        validate_graph_has_types(graph, args.domain)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        print("\nThis graph was not created with domain schema typing.")
        sys.exit(1)

    # Find cross-domain entities
    analysis_results = find_cross_domain_entities(graph, args.domain)

    if not analysis_results['cross_domain_entities'] and not analysis_results['hub_entities']:
        print("\n⚠ No cross-domain entities found in graph.")
        sys.exit(0)

    # Generate queries
    queries = generate_queries(analysis_results, max_queries=args.max_queries)

    # Prepare output
    output = {
        'graph_file': str(args.graph_file),
        'domain': args.domain,
        'query_type': 'cross_domain',
        'num_cross_domain_entities': len(analysis_results['cross_domain_entities']),
        'num_hub_entities': len(analysis_results['hub_entities']),
        'num_queries': len(queries),
        'queries': queries
    }

    # Save output
    output_path = Path(args.output)
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n✓ Saved {len(queries)} queries to: {output_path}")

    # Print sample queries
    print("\nSample queries:")
    for q in queries[:5]:
        print(f"  - {q['query']}")

    print(f"\n{'='*60}")
    print(f"Query generation complete")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate queries to explore cross-domain connections"
    )
    parser.add_argument(
        "graph_file",
        type=str,
        help="Path to domain-typed GraphML file"
    )
    parser.add_argument(
        "domain",
        type=str,
        help="Domain name"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="cross_domain_queries.json",
        help="Output file path"
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=20,
        help="Maximum number of queries"
    )

    args = parser.parse_args()
    main(args)
