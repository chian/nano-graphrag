"""
Generate Queries: Therapeutic Alternatives
Finds diseases/phenotypes and their treatments, generates queries to find MORE therapeutic options
"""

import argparse
import json
import networkx as nx
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from query_generation.graph_validator import validate_graph_has_types

def find_therapeutic_targets(graph: nx.Graph, domain_name: str) -> dict:
    """
    Find disease/phenotype nodes and their existing treatments.

    Args:
        graph: Domain-typed NetworkX graph
        domain_name: Domain schema name

    Returns:
        Dict with therapeutic targets and their treatments
    """

    print(f"\nAnalyzing for therapeutic targets...")

    # Define target node types (things we want to treat)
    target_types = ['DISEASE', 'PHENOTYPE', 'SYMPTOM', 'OUTCOME']

    # Define treatment node types
    treatment_types = ['DRUG', 'COMPOUND', 'TREATMENT', 'THERAPY', 'INTERVENTION']

    # Define therapeutic relationship types
    therapeutic_relations = ['TREATS', 'PREVENTS', 'INHIBITS', 'SUPPRESSES',
                             'REDUCES', 'DECREASES_RISK', 'PROTECTS_AGAINST']

    therapeutic_targets = []

    for node in graph.nodes():
        node_type = graph.nodes[node].get('entity_type', '')

        if node_type in target_types:
            node_data = graph.nodes[node]

            # Find all treatments for this target
            treatments = []

            # Check incoming edges for treatments
            for src, tgt, edge_data in graph.in_edges(node, data=True):
                src_type = graph.nodes[src].get('entity_type', '')
                relation = edge_data.get('relation_type', '')

                if src_type in treatment_types and relation in therapeutic_relations:
                    src_data = graph.nodes[src]
                    treatments.append({
                        'treatment_id': src,
                        'treatment_label': src_data.get('label', src),
                        'treatment_type': src_type,
                        'relation': relation
                    })

            # Also check if this target is affected by proteins/pathways that could be drug targets
            potential_targets = []
            for src, tgt, edge_data in graph.in_edges(node, data=True):
                src_type = graph.nodes[src].get('entity_type', '')
                relation = edge_data.get('relation_type', '')

                if src_type in ['PROTEIN', 'ENZYME', 'PATHWAY', 'GENE'] and \
                   relation in ['CAUSES', 'ACTIVATES', 'PRODUCES', 'LEADS_TO']:
                    src_data = graph.nodes[src]
                    potential_targets.append({
                        'target_id': src,
                        'target_label': src_data.get('label', src),
                        'target_type': src_type,
                        'relation': relation
                    })

            # Record this therapeutic target
            therapeutic_targets.append({
                'target_id': node,
                'target_label': node_data.get('label', node),
                'target_type': node_type,
                'num_known_treatments': len(treatments),
                'known_treatments': treatments,
                'num_potential_drug_targets': len(potential_targets),
                'potential_drug_targets': potential_targets[:5]  # Limit
            })

    # Sort by those with few/no treatments (high priority for finding alternatives)
    therapeutic_targets.sort(key=lambda x: x['num_known_treatments'])

    print(f"Found {len(therapeutic_targets)} therapeutic targets")
    print(f"  Targets with no known treatments: {sum(1 for t in therapeutic_targets if t['num_known_treatments'] == 0)}")
    print(f"  Targets with treatments: {sum(1 for t in therapeutic_targets if t['num_known_treatments'] > 0)}")

    return {'therapeutic_targets': therapeutic_targets}

def generate_queries(analysis_results: dict, max_queries: int = 20) -> list[dict]:
    """
    Generate search queries to find more therapeutic options.

    Args:
        analysis_results: Output from find_therapeutic_targets
        max_queries: Maximum number of queries

    Returns:
        List of query dicts
    """

    queries = []
    seen_queries = set()

    for target in analysis_results['therapeutic_targets']:
        target_label = target['target_label']
        known_treatments = target['known_treatments']
        potential_drug_targets = target['potential_drug_targets']

        # Query 1: Broad treatment search
        query_text = f"treatments for {target_label}"
        if query_text.lower() not in seen_queries:
            queries.append({
                'query': query_text,
                'type': 'broad_treatment_search',
                'target': target_label,
                'num_known_treatments': target['num_known_treatments'],
                'known_treatments': [t['treatment_label'] for t in known_treatments[:3]]
            })
            seen_queries.add(query_text.lower())

        # Query 2: Drug/compound search
        query_text = f"drugs for {target_label}"
        if query_text.lower() not in seen_queries:
            queries.append({
                'query': query_text,
                'type': 'drug_search',
                'target': target_label,
                'num_known_treatments': target['num_known_treatments']
            })
            seen_queries.add(query_text.lower())

        # Query 3: For targets with potential drug targets, search for drugs targeting them
        for pot_target in potential_drug_targets[:2]:  # Top 2
            pot_label = pot_target['target_label']
            pot_type = pot_target['target_type']

            query_text = f"drugs targeting {pot_label} for {target_label}"
            if query_text.lower() not in seen_queries:
                queries.append({
                    'query': query_text,
                    'type': 'target_specific_drug_search',
                    'disease': target_label,
                    'drug_target': pot_label,
                    'drug_target_type': pot_type
                })
                seen_queries.add(query_text.lower())

        # Query 4: Alternative therapeutic approaches
        if known_treatments:
            # Group by treatment type
            by_type = defaultdict(list)
            for t in known_treatments:
                by_type[t['treatment_type']].append(t)

            for treat_type, treats in by_type.items():
                query_text = f"alternative {treat_type.lower()}s for {target_label}"
                if query_text.lower() not in seen_queries and len(queries) < max_queries:
                    queries.append({
                        'query': query_text,
                        'type': 'alternative_treatment_class',
                        'target': target_label,
                        'treatment_class': treat_type,
                        'known_examples': [t['treatment_label'] for t in treats[:2]]
                    })
                    seen_queries.add(query_text.lower())

        # Query 5: Therapeutic mechanisms
        query_text = f"therapeutic approaches for {target_label}"
        if query_text.lower() not in seen_queries and len(queries) < max_queries:
            queries.append({
                'query': query_text,
                'type': 'therapeutic_mechanisms',
                'target': target_label
            })
            seen_queries.add(query_text.lower())

    # Limit total
    queries = queries[:max_queries]

    print(f"\nGenerated {len(queries)} search queries")

    return queries

def main(args):
    """Main function"""

    print(f"{'='*60}")
    print(f"Therapeutic Alternatives Query Generation")
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

    # Find therapeutic targets
    analysis_results = find_therapeutic_targets(graph, args.domain)

    if not analysis_results['therapeutic_targets']:
        print("\n⚠ No therapeutic targets found in graph.")
        sys.exit(0)

    # Generate queries
    queries = generate_queries(analysis_results, max_queries=args.max_queries)

    # Prepare output
    output = {
        'graph_file': str(args.graph_file),
        'domain': args.domain,
        'query_type': 'therapeutic_alternatives',
        'num_targets_found': len(analysis_results['therapeutic_targets']),
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
        description="Generate queries to find therapeutic alternatives"
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
        default="therapeutic_alternatives_queries.json",
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
