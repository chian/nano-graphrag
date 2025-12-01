"""
Graph Merger
Functions for merging entities and relationships into existing graphs
"""

import networkx as nx
from typing import Dict, List
from .entity_merger import find_entity_matches, merge_entities, get_canonical_name


def add_entities_to_graph(
    graph: nx.DiGraph,
    new_entities: Dict[str, Dict],
    source_uuid: str,
    similarity_threshold: float = 0.85,
    auto_merge: bool = True
) -> tuple[nx.DiGraph, Dict[str, str]]:
    """
    Add new entities to graph, merging with existing entities when appropriate.

    Args:
        graph: Existing NetworkX graph
        new_entities: Dict of new entities to add (name -> entity_dict)
        source_uuid: UUID of the paper these entities came from
        similarity_threshold: Threshold for entity matching
        auto_merge: Whether to automatically merge similar entities

    Returns:
        Tuple of (updated_graph, name_mapping)
        name_mapping: Maps new entity names to canonical names in graph
    """
    name_mapping = {}
    existing_entities = {
        node: graph.nodes[node]
        for node in graph.nodes()
    }

    for new_name, new_entity in new_entities.items():
        # Find potential matches
        matches = find_entity_matches(
            new_entity,
            existing_entities,
            entity_type_match=True,
            similarity_threshold=similarity_threshold
        )

        if matches and auto_merge:
            # Use the best match
            canonical_name, similarity = matches[0]
            name_mapping[new_name] = canonical_name

            # Merge entity data
            merged_entity = merge_entities(
                existing_entities[canonical_name],
                new_entity,
                source_uuid
            )

            # Update node attributes
            for key, value in merged_entity.items():
                graph.nodes[canonical_name][key] = value

        else:
            # Add as new entity
            canonical_name = new_name
            name_mapping[new_name] = canonical_name

            # Add source tracking
            new_entity_data = new_entity.copy()
            if 'source_papers' not in new_entity_data:
                new_entity_data['source_papers'] = [source_uuid]
            else:
                new_entity_data['source_papers'].append(source_uuid)

            graph.add_node(
                canonical_name,
                **new_entity_data
            )

            existing_entities[canonical_name] = new_entity_data

    return graph, name_mapping


def add_relationships_to_graph(
    graph: nx.DiGraph,
    new_relationships: List[Dict],
    name_mapping: Dict[str, str],
    source_uuid: str
) -> nx.DiGraph:
    """
    Add new relationships to graph using name mapping.

    Args:
        graph: Existing NetworkX graph
        new_relationships: List of relationship dicts
        name_mapping: Maps new entity names to canonical names
        source_uuid: UUID of the paper these relationships came from

    Returns:
        Updated graph
    """
    for rel in new_relationships:
        src = rel['src_id']
        tgt = rel['tgt_id']

        # Map to canonical names
        src_canonical = name_mapping.get(src, src)
        tgt_canonical = name_mapping.get(tgt, tgt)

        # Only add if both nodes exist
        if src_canonical not in graph.nodes or tgt_canonical not in graph.nodes:
            continue

        # Check if edge already exists
        if graph.has_edge(src_canonical, tgt_canonical):
            # Merge edge data
            existing_edge = graph[src_canonical][tgt_canonical]

            # Combine descriptions
            new_desc = rel.get('description', '')
            existing_desc = existing_edge.get('description', '')

            if new_desc and new_desc.lower() not in existing_desc.lower():
                if existing_desc:
                    existing_edge['description'] = f"{existing_desc} | {new_desc}"
                else:
                    existing_edge['description'] = new_desc

            # Update weight to maximum
            existing_edge['weight'] = max(
                existing_edge.get('weight', 0),
                rel.get('weight', 0)
            )

            # Track source papers
            if 'source_papers' not in existing_edge:
                existing_edge['source_papers'] = []

            if source_uuid not in existing_edge['source_papers']:
                existing_edge['source_papers'].append(source_uuid)

        else:
            # Add new edge
            edge_data = rel.copy()
            edge_data['source_papers'] = [source_uuid]

            graph.add_edge(
                src_canonical,
                tgt_canonical,
                **edge_data
            )

    return graph


def merge_graphs(
    base_graph: nx.DiGraph,
    new_graph: nx.DiGraph,
    source_uuid: str,
    similarity_threshold: float = 0.85,
    auto_merge: bool = True
) -> nx.DiGraph:
    """
    Merge a new graph into an existing base graph.

    Args:
        base_graph: Base graph to merge into
        new_graph: New graph to merge
        source_uuid: UUID of the paper the new graph came from
        similarity_threshold: Threshold for entity matching
        auto_merge: Whether to automatically merge similar entities

    Returns:
        Merged graph
    """
    # Extract entities from new graph
    new_entities = {}
    for node in new_graph.nodes():
        new_entities[node] = dict(new_graph.nodes[node])

    # Add entities with merging
    merged_graph, name_mapping = add_entities_to_graph(
        base_graph,
        new_entities,
        source_uuid,
        similarity_threshold=similarity_threshold,
        auto_merge=auto_merge
    )

    # Extract relationships from new graph
    new_relationships = []
    for src, tgt in new_graph.edges():
        edge_data = dict(new_graph[src][tgt])
        edge_data['src_id'] = src
        edge_data['tgt_id'] = tgt
        new_relationships.append(edge_data)

    # Add relationships
    merged_graph = add_relationships_to_graph(
        merged_graph,
        new_relationships,
        name_mapping,
        source_uuid
    )

    return merged_graph


def get_enrichment_statistics(
    original_graph: nx.DiGraph,
    enriched_graph: nx.DiGraph
) -> Dict:
    """
    Calculate statistics about graph enrichment.

    Args:
        original_graph: Graph before enrichment
        enriched_graph: Graph after enrichment

    Returns:
        Dict with enrichment statistics
    """
    stats = {
        'original_nodes': original_graph.number_of_nodes(),
        'original_edges': original_graph.number_of_edges(),
        'enriched_nodes': enriched_graph.number_of_nodes(),
        'enriched_edges': enriched_graph.number_of_edges(),
        'nodes_added': enriched_graph.number_of_nodes() - original_graph.number_of_nodes(),
        'edges_added': enriched_graph.number_of_edges() - original_graph.number_of_edges(),
    }

    # Calculate growth percentages
    if stats['original_nodes'] > 0:
        stats['node_growth_percent'] = (stats['nodes_added'] / stats['original_nodes']) * 100
    else:
        stats['node_growth_percent'] = 0

    if stats['original_edges'] > 0:
        stats['edge_growth_percent'] = (stats['edges_added'] / stats['original_edges']) * 100
    else:
        stats['edge_growth_percent'] = 0

    return stats
