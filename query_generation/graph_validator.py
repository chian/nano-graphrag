"""
Graph Validator
Ensures graph has required domain schema attributes before query generation
"""

import networkx as nx
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from domain_schemas.schema_loader import load_domain_schema

def validate_graph_has_types(graph: nx.Graph, domain_name: str) -> bool:
    """
    Validate that graph has entity_type and relation_type attributes from domain schema.

    Args:
        graph: NetworkX graph to validate
        domain_name: Domain schema name (e.g., 'molecular_biology')

    Returns:
        True if valid, raises exception if not
    """

    # Load domain schema
    try:
        schema = load_domain_schema(domain_name)
    except Exception as e:
        raise ValueError(f"Could not load domain schema '{domain_name}': {e}")

    # Check that graph has nodes
    if graph.number_of_nodes() == 0:
        raise ValueError(
            f"Graph is empty (0 nodes, 0 edges). "
            f"Entity extraction may have failed in Stage 2. "
            f"Check the Stage 2 output - you should see '(X entities, Y relationships)' for each chunk. "
            f"If all chunks show '(0 entities, 0 relationships)', the LLM failed to extract anything. "
            f"This could be due to: (1) JSON parsing failures, (2) LLM returning empty responses, "
            f"or (3) paper content not matching the domain schema."
        )

    # Check that nodes have entity_type attribute
    nodes_without_type = []
    for node in list(graph.nodes())[:10]:  # Check first 10
        if 'entity_type' not in graph.nodes[node]:
            nodes_without_type.append(node)

    if nodes_without_type:
        # Show actual attributes that exist
        sample_attrs = dict(graph.nodes[nodes_without_type[0]])
        raise ValueError(
            f"Graph nodes are missing the 'entity_type' attribute required by domain schema. "
            f"This means the graph was not created using create_domain_typed_graph.py. "
            f"\n"
            f"Nodes missing 'entity_type': {nodes_without_type[:3]}\n"
            f"Sample node '{nodes_without_type[0]}' has attributes: {list(sample_attrs.keys())}\n"
            f"\n"
            f"Expected: Nodes should have 'entity_type' attribute (e.g., PROTEIN, COMPOUND, etc.)\n"
            f"Solution: Re-run Stage 2 (create_domain_typed_graph.py) to create a properly typed graph."
        )

    # Check that edges have relation_type attribute
    edges_without_type = []
    for edge in list(graph.edges())[:10]:  # Check first 10
        src, tgt = edge
        edge_data = graph.get_edge_data(src, tgt)
        if 'relation_type' not in edge_data:
            edges_without_type.append(edge)

    if edges_without_type:
        # Show actual attributes that exist
        sample_edge = edges_without_type[0]
        sample_edge_attrs = graph.get_edge_data(sample_edge[0], sample_edge[1])
        raise ValueError(
            f"Graph edges are missing the 'relation_type' attribute required by domain schema. "
            f"This means the graph was not created using create_domain_typed_graph.py. "
            f"\n"
            f"Edges missing 'relation_type': {edges_without_type[:3]}\n"
            f"Sample edge {sample_edge} has attributes: {list(sample_edge_attrs.keys())}\n"
            f"\n"
            f"Expected: Edges should have 'relation_type' attribute (e.g., INHIBITS, ACTIVATES, etc.)\n"
            f"Solution: Re-run Stage 2 (create_domain_typed_graph.py) to create a properly typed graph."
        )

    # Verify entity types match schema
    valid_entity_types = set(schema.entity_types.keys())
    graph_entity_types = set()

    for node in graph.nodes():
        entity_type = graph.nodes[node].get('entity_type')
        if entity_type:
            graph_entity_types.add(entity_type)

    invalid_types = graph_entity_types - valid_entity_types
    if invalid_types:
        raise ValueError(
            f"Graph contains entity types not in domain schema '{domain_name}': {invalid_types}. "
            f"Valid types: {valid_entity_types}"
        )

    # Verify relationship types match schema
    valid_relation_types = set(schema.relationship_types.keys())
    graph_relation_types = set()

    for src, tgt, data in graph.edges(data=True):
        relation_type = data.get('relation_type')
        if relation_type:
            graph_relation_types.add(relation_type)

    invalid_relations = graph_relation_types - valid_relation_types
    if invalid_relations:
        raise ValueError(
            f"Graph contains relation types not in domain schema '{domain_name}': {invalid_relations}. "
            f"Valid types: {valid_relation_types}"
        )

    print(f"✓ Graph validation passed for domain '{domain_name}'")
    print(f"  Entity types found: {len(graph_entity_types)}")
    print(f"  Relation types found: {len(graph_relation_types)}")

    return True

def get_causal_edge_types(domain_name: str) -> list[str]:
    """
    Get list of causal relationship types from domain schema.

    Causal relationships are those that indicate causation, activation, inhibition, etc.

    Args:
        domain_name: Domain schema name

    Returns:
        List of causal relationship type names
    """
    schema = load_domain_schema(domain_name)

    # Keywords that indicate causal relationships
    causal_keywords = [
        'cause', 'activate', 'inhibit', 'produce', 'lead', 'result',
        'induce', 'suppress', 'promote', 'trigger', 'block', 'prevent'
    ]

    causal_types = []

    for rel_name, rel_type in schema.relationship_types.items():
        description = rel_type.description.lower()

        # Check if description contains causal keywords
        if any(keyword in description for keyword in causal_keywords):
            causal_types.append(rel_name)

        # Also include specific known causal types
        if rel_name in ['CAUSES', 'ACTIVATES', 'INHIBITS', 'PRODUCES',
                        'LEADS_TO', 'RESULTS_IN', 'TRIGGERS', 'PREVENTS',
                        'SUPPRESSES', 'PROMOTES', 'INDUCES']:
            if rel_name not in causal_types:
                causal_types.append(rel_name)

    return causal_types

if __name__ == "__main__":
    # Test the validator
    import argparse

    parser = argparse.ArgumentParser(description="Validate graph schema")
    parser.add_argument("graph_file", help="Path to GraphML file")
    parser.add_argument("domain", help="Domain name")

    args = parser.parse_args()

    graph = nx.read_graphml(args.graph_file)

    try:
        validate_graph_has_types(graph, args.domain)
        print("\n✓ Graph is valid for query generation")

        causal_types = get_causal_edge_types(args.domain)
        print(f"\nCausal relationship types in {args.domain}:")
        for ct in causal_types:
            print(f"  - {ct}")
    except Exception as e:
        print(f"\n✗ Graph validation failed: {e}")
        sys.exit(1)
