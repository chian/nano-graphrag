"""
Generate Queries: Pathway Expansion
Finds incomplete pathways and gaps, generates queries to find missing connections
"""

import argparse
import json
import networkx as nx
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from query_generation.graph_validator import validate_graph_has_types, get_causal_edge_types

def find_pathway_gaps(graph: nx.Graph, domain_name: str, max_path_length: int = 4) -> dict:
    """
    Find potential pathway gaps where indirect paths exist but direct connections are missing.

    Args:
        graph: Domain-typed NetworkX graph
        domain_name: Domain schema name
        max_path_length: Maximum path length to consider (default: 4)

    Returns:
        Dict with 'gaps' list containing potential missing connections
    """

    causal_types = get_causal_edge_types(domain_name)

    print(f"\nAnalyzing for pathway gaps...")
    print(f"Causal relationship types: {causal_types}")

    gaps = []

    # Get all nodes as potential start/end points
    nodes = list(graph.nodes())

    # Limit analysis to avoid combinatorial explosion
    max_pairs = 1000
    pairs_analyzed = 0

    for i, start_node in enumerate(nodes):
        if pairs_analyzed >= max_pairs:
            break

        # Only consider paths from certain entity types (not all nodes)
        start_type = graph.nodes[start_node].get('entity_type', '')
        if start_type in ['UNKNOWN', '']:
            continue

        for end_node in nodes[i+1:]:
            if pairs_analyzed >= max_pairs:
                break

            end_type = graph.nodes[end_node].get('entity_type', '')
            if end_type in ['UNKNOWN', '']:
                continue

            # Skip if direct edge exists
            if graph.has_edge(start_node, end_node):
                continue

            # Check if there's an indirect path via causal edges
            try:
                # Try to find path using only causal edges
                path_exists = False
                path_length = 0

                for path in nx.all_simple_paths(graph, start_node, end_node, cutoff=max_path_length):
                    # Check if path uses causal edges
                    is_causal_path = True
                    for j in range(len(path) - 1):
                        edge_data = graph.get_edge_data(path[j], path[j+1])
                        if edge_data.get('relation_type') not in causal_types:
                            is_causal_path = False
                            break

                    if is_causal_path and len(path) >= 3:  # At least 2 hops
                        path_exists = True
                        path_length = len(path) - 1
                        break

                if path_exists:
                    # Found indirect path but no direct connection - potential gap
                    start_data = graph.nodes[start_node]
                    end_data = graph.nodes[end_node]

                    gaps.append({
                        'start_node_id': start_node,
                        'start_label': start_data.get('label', start_node),
                        'start_type': start_type,
                        'end_node_id': end_node,
                        'end_label': end_data.get('label', end_node),
                        'end_type': end_type,
                        'path_length': path_length,
                        'gap_type': 'missing_direct_connection'
                    })

                    pairs_analyzed += 1

            except nx.NetworkXNoPath:
                continue
            except Exception as e:
                continue

    # Also find nodes that seem like they should connect but don't
    # (e.g., a DRUG and a DISEASE with no connection)
    for start_node in nodes[:500]:  # Limit
        start_type = graph.nodes[start_node].get('entity_type', '')

        # Look for specific disconnection patterns
        if start_type in ['DRUG', 'COMPOUND', 'TREATMENT']:
            for end_node in nodes:
                end_type = graph.nodes[end_node].get('entity_type', '')

                if end_type in ['DISEASE', 'PHENOTYPE', 'SYMPTOM']:
                    # Check if drug and disease are disconnected
                    if not nx.has_path(graph, start_node, end_node) and \
                       not nx.has_path(graph, end_node, start_node):

                        start_data = graph.nodes[start_node]
                        end_data = graph.nodes[end_node]

                        gaps.append({
                            'start_node_id': start_node,
                            'start_label': start_data.get('label', start_node),
                            'start_type': start_type,
                            'end_node_id': end_node,
                            'end_label': end_data.get('label', end_node),
                            'end_type': end_type,
                            'path_length': None,
                            'gap_type': 'disconnected_entities'
                        })

    print(f"Found {len(gaps)} potential pathway gaps")

    return {'gaps': gaps[:50]}  # Limit to top 50

def generate_queries(analysis_results: dict, max_queries: int = 20) -> list[dict]:
    """
    Generate search queries to find missing pathway connections.

    Args:
        analysis_results: Output from find_pathway_gaps
        max_queries: Maximum number of queries to generate

    Returns:
        List of query dicts
    """

    queries = []
    seen_queries = set()

    for gap in analysis_results['gaps']:
        start_label = gap['start_label']
        end_label = gap['end_label']
        start_type = gap['start_type']
        end_type = gap['end_type']

        # Query 1: Direct connection search
        query_text = f"{start_label} connection to {end_label}"
        if query_text.lower() not in seen_queries:
            queries.append({
                'query': query_text,
                'type': 'direct_connection',
                'start_entity': start_label,
                'end_entity': end_label,
                'gap_type': gap['gap_type']
            })
            seen_queries.add(query_text.lower())

        # Query 2: Intermediate/mediator search
        query_text = f"intermediates between {start_label} and {end_label}"
        if query_text.lower() not in seen_queries:
            queries.append({
                'query': query_text,
                'type': 'find_intermediates',
                'start_entity': start_label,
                'end_entity': end_label,
                'gap_type': gap['gap_type']
            })
            seen_queries.add(query_text.lower())

        # Query 3: Mechanism search
        query_text = f"how {start_label} affects {end_label}"
        if query_text.lower() not in seen_queries:
            queries.append({
                'query': query_text,
                'type': 'mechanism_search',
                'start_entity': start_label,
                'end_entity': end_label,
                'gap_type': gap['gap_type']
            })
            seen_queries.add(query_text.lower())

        # Query 4: Type-based pathway search
        if start_type != 'UNKNOWN' and end_type != 'UNKNOWN':
            query_text = f"{start_type.lower()} to {end_type.lower()} pathway"
            if query_text.lower() not in seen_queries and len(queries) < max_queries:
                queries.append({
                    'query': query_text,
                    'type': 'pathway_by_types',
                    'start_type': start_type,
                    'end_type': end_type,
                    'example_start': start_label,
                    'example_end': end_label
                })
                seen_queries.add(query_text.lower())

    # Limit total queries
    queries = queries[:max_queries]

    print(f"\nGenerated {len(queries)} search queries")

    return queries

def main(args):
    """Main function"""

    print(f"{'='*60}")
    print(f"Pathway Expansion Query Generation")
    print(f"{'='*60}\n")

    # Load graph
    print(f"Loading graph: {args.graph_file}")
    graph = nx.read_graphml(args.graph_file)
    print(f"Loaded graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

    # Validate graph has domain types
    try:
        validate_graph_has_types(graph, args.domain)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        print("\nThis graph was not created with domain schema typing.")
        sys.exit(1)

    # Find pathway gaps
    analysis_results = find_pathway_gaps(graph, args.domain, max_path_length=args.max_path_length)

    if not analysis_results['gaps']:
        print("\n⚠ No pathway gaps found in graph.")
        sys.exit(0)

    # Generate queries
    queries = generate_queries(analysis_results, max_queries=args.max_queries)

    # Prepare output
    output = {
        'graph_file': str(args.graph_file),
        'domain': args.domain,
        'query_type': 'pathway_expansion',
        'num_gaps_found': len(analysis_results['gaps']),
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
        description="Generate queries to find missing pathway connections"
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
        default="pathway_expansion_queries.json",
        help="Output file path"
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=20,
        help="Maximum number of queries"
    )
    parser.add_argument(
        "--max-path-length",
        type=int,
        default=4,
        help="Maximum path length to consider for gaps"
    )

    args = parser.parse_args()
    main(args)
