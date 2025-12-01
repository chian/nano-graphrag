"""
Generate Queries: Contrastive Alternatives
Finds outcomes with multiple causal inputs, generates queries to find MORE alternative mechanisms
"""

import argparse
import json
import networkx as nx
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from query_generation.graph_validator import validate_graph_has_types, get_causal_edge_types

def analyze_graph_for_alternatives(graph: nx.Graph, domain_name: str) -> dict:
    """
    Find nodes with multiple incoming causal edges - these are outcomes with alternative mechanisms.

    Args:
        graph: Domain-typed NetworkX graph
        domain_name: Domain schema name

    Returns:
        Dict with 'alternatives' list containing targets with multiple causal sources
    """

    # Get causal relationship types from domain schema
    causal_types = get_causal_edge_types(domain_name)

    print(f"\nAnalyzing for contrastive alternatives...")
    print(f"Causal relationship types: {causal_types}")

    # Find nodes with multiple incoming causal edges
    convergent_nodes = []

    for node in graph.nodes():
        # Get incoming edges
        incoming_edges = list(graph.in_edges(node, data=True))

        # Filter to causal edges only
        causal_incoming = [
            (src, tgt, data)
            for src, tgt, data in incoming_edges
            if data.get('relation_type') in causal_types
        ]

        # Need at least 2 different causal sources
        if len(causal_incoming) >= 2:
            # Get unique sources
            unique_sources = set(src for src, _, _ in causal_incoming)

            if len(unique_sources) >= 2:
                node_data = graph.nodes[node]

                sources_info = []
                for src, tgt, edge_data in causal_incoming:
                    src_data = graph.nodes[src]
                    sources_info.append({
                        'node_id': src,
                        'label': src_data.get('label', src),
                        'entity_type': src_data.get('entity_type', 'UNKNOWN'),
                        'relation_type': edge_data.get('relation_type', 'UNKNOWN'),
                        'description': edge_data.get('description', '')[:100]
                    })

                convergent_nodes.append({
                    'target_node_id': node,
                    'target_label': node_data.get('label', node),
                    'target_type': node_data.get('entity_type', 'UNKNOWN'),
                    'num_alternatives': len(unique_sources),
                    'sources': sources_info
                })

    # Sort by number of alternatives (most first)
    convergent_nodes.sort(key=lambda x: x['num_alternatives'], reverse=True)

    print(f"Found {len(convergent_nodes)} nodes with multiple causal inputs")

    return {'alternatives': convergent_nodes}

def generate_queries(analysis_results: dict, max_queries: int = 20) -> list[dict]:
    """
    Generate search queries to find MORE alternative mechanisms from literature.

    Args:
        analysis_results: Output from analyze_graph_for_alternatives
        max_queries: Maximum number of queries to generate

    Returns:
        List of query dicts
    """

    queries = []
    seen_queries = set()

    for item in analysis_results['alternatives']:
        target_label = item['target_label']
        target_type = item['target_type']
        sources = item['sources']

        # Query 1: Broad search for alternative mechanisms
        query_text = f"alternative mechanisms for {target_label}"
        if query_text.lower() not in seen_queries:
            queries.append({
                'query': query_text,
                'type': 'broad_alternatives',
                'target': target_label,
                'target_type': target_type,
                'num_known_alternatives': item['num_alternatives'],
                'known_mechanisms': [s['label'] for s in sources[:3]]
            })
            seen_queries.add(query_text.lower())

        # Query 2: Type-specific search for more of same type
        # Group sources by entity type
        sources_by_type = defaultdict(list)
        for src in sources:
            sources_by_type[src['entity_type']].append(src)

        for entity_type, type_sources in sources_by_type.items():
            if entity_type != 'UNKNOWN' and len(type_sources) >= 1:
                # Make plural and lowercase
                type_plural = entity_type.lower()
                if not type_plural.endswith('s'):
                    type_plural += 's'

                query_text = f"alternative {type_plural} affecting {target_label}"
                if query_text.lower() not in seen_queries:
                    queries.append({
                        'query': query_text,
                        'type': 'type_specific_alternatives',
                        'target': target_label,
                        'target_type': target_type,
                        'source_entity_type': entity_type,
                        'known_examples': [s['label'] for s in type_sources[:2]]
                    })
                    seen_queries.add(query_text.lower())

        # Query 3: Relation-specific search
        # Group by relation type
        sources_by_relation = defaultdict(list)
        for src in sources:
            sources_by_relation[src['relation_type']].append(src)

        for relation_type, rel_sources in sources_by_relation.items():
            if relation_type != 'UNKNOWN' and len(rel_sources) >= 1:
                # Convert relation type to readable text
                relation_text = relation_type.lower().replace('_', ' ')

                query_text = f"what {relation_text} {target_label}"
                if query_text.lower() not in seen_queries:
                    queries.append({
                        'query': query_text,
                        'type': 'relation_specific_alternatives',
                        'target': target_label,
                        'target_type': target_type,
                        'relation_type': relation_type,
                        'known_examples': [s['label'] for s in rel_sources[:2]]
                    })
                    seen_queries.add(query_text.lower())

    # Limit total queries
    queries = queries[:max_queries]

    print(f"\nGenerated {len(queries)} search queries")

    return queries

def main(args):
    """Main function"""

    print(f"{'='*60}")
    print(f"Contrastive Alternatives Query Generation")
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
        print("Please use create_domain_typed_graph.py to create a properly typed graph.")
        sys.exit(1)

    # Analyze graph
    analysis_results = analyze_graph_for_alternatives(graph, args.domain)

    if not analysis_results['alternatives']:
        print("\n⚠ No alternative mechanisms found in graph.")
        print("Graph may be too sparse or not contain convergent causal patterns.")
        sys.exit(0)

    # Generate queries
    queries = generate_queries(analysis_results, max_queries=args.max_queries)

    # Prepare output
    output = {
        'graph_file': str(args.graph_file),
        'domain': args.domain,
        'query_type': 'contrastive_alternatives',
        'num_patterns_found': len(analysis_results['alternatives']),
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
        description="Generate queries to find alternative mechanisms from literature"
    )
    parser.add_argument(
        "graph_file",
        type=str,
        help="Path to domain-typed GraphML file"
    )
    parser.add_argument(
        "domain",
        type=str,
        help="Domain name (e.g., molecular_biology, microbial_biology)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="contrastive_alternatives_queries.json",
        help="Output file path (default: contrastive_alternatives_queries.json)"
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=20,
        help="Maximum number of queries to generate (default: 20)"
    )

    args = parser.parse_args()
    main(args)
