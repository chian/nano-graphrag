"""
Graph loading and conversion utilities for visualization.

Loads GraphML files and converts them to formats suitable for vis.js visualization.
"""

import json
import networkx as nx
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field


# Color scheme for different entity types
ENTITY_COLORS = {
    'PATHOGEN': '#e74c3c',           # Red
    'ANTIMICROBIAL': '#3498db',      # Blue
    'RESISTANCE_MECHANISM': '#e67e22', # Orange
    'DIAGNOSTIC_TEST': '#9b59b6',    # Purple
    'BIOMARKER': '#1abc9c',          # Teal
    'SPECIMEN': '#95a5a6',           # Gray
    'METHOD': '#f39c12',             # Yellow
    'DISEASE': '#c0392b',            # Dark red
    'GENE': '#27ae60',               # Green
    'PROTEIN': '#2980b9',            # Dark blue
    'COMPOUND': '#8e44ad',           # Dark purple
    'ORGANISM': '#d35400',           # Dark orange
    'CLINICAL_OUTCOME': '#16a085',   # Dark teal
    'TREATMENT': '#2ecc71',          # Light green
    'DEFAULT': '#7f8c8d'             # Default gray
}

# Shape for different entity types
ENTITY_SHAPES = {
    'PATHOGEN': 'hexagon',
    'ANTIMICROBIAL': 'diamond',
    'RESISTANCE_MECHANISM': 'triangle',
    'DIAGNOSTIC_TEST': 'square',
    'BIOMARKER': 'star',
    'SPECIMEN': 'dot',
    'METHOD': 'box',
    'DEFAULT': 'ellipse'
}


@dataclass
class GraphStats:
    """Statistics about a loaded graph."""
    num_nodes: int = 0
    num_edges: int = 0
    entity_types: Dict[str, int] = field(default_factory=dict)
    relation_types: Dict[str, int] = field(default_factory=dict)
    avg_importance: float = 0.0
    connected_components: int = 0


class GraphLoader:
    """Load and convert GraphML files for visualization."""

    def __init__(self, graphml_path: Optional[str] = None):
        """
        Initialize the graph loader.

        Args:
            graphml_path: Optional path to a GraphML file to load immediately
        """
        self.graph: Optional[nx.Graph] = None
        self.graphml_path: Optional[str] = None
        self.stats: Optional[GraphStats] = None

        if graphml_path:
            self.load(graphml_path)

    def load(self, graphml_path: str) -> nx.Graph:
        """
        Load a GraphML file.

        Args:
            graphml_path: Path to the GraphML file

        Returns:
            NetworkX graph object
        """
        path = Path(graphml_path)
        if not path.exists():
            raise FileNotFoundError(f"GraphML file not found: {graphml_path}")

        self.graphml_path = str(path.absolute())
        self.graph = nx.read_graphml(graphml_path)
        self._compute_stats()
        return self.graph

    def _compute_stats(self) -> None:
        """Compute statistics about the loaded graph."""
        if self.graph is None:
            return

        stats = GraphStats()
        stats.num_nodes = self.graph.number_of_nodes()
        stats.num_edges = self.graph.number_of_edges()

        # Count entity types
        importance_sum = 0.0
        for node_id, data in self.graph.nodes(data=True):
            entity_type = data.get('entity_type', 'UNKNOWN')
            stats.entity_types[entity_type] = stats.entity_types.get(entity_type, 0) + 1
            importance_sum += float(data.get('importance_score', 0.5))

        if stats.num_nodes > 0:
            stats.avg_importance = importance_sum / stats.num_nodes

        # Count relation types
        for source, target, data in self.graph.edges(data=True):
            rel_type = data.get('relation_type', 'UNKNOWN')
            stats.relation_types[rel_type] = stats.relation_types.get(rel_type, 0) + 1

        # Count connected components
        if self.graph.is_directed():
            stats.connected_components = nx.number_weakly_connected_components(self.graph)
        else:
            stats.connected_components = nx.number_connected_components(self.graph)

        self.stats = stats

    def to_vis_format(self,
                      highlight_nodes: Optional[List[str]] = None,
                      highlight_edges: Optional[List[Tuple[str, str]]] = None,
                      filter_entity_types: Optional[List[str]] = None,
                      min_importance: float = 0.0) -> Dict[str, Any]:
        """
        Convert the graph to vis.js format.

        Args:
            highlight_nodes: List of node IDs to highlight
            highlight_edges: List of (source, target) tuples to highlight
            filter_entity_types: Only include nodes of these entity types
            min_importance: Minimum importance score for nodes

        Returns:
            Dictionary with 'nodes' and 'edges' lists for vis.js
        """
        if self.graph is None:
            raise ValueError("No graph loaded. Call load() first.")

        highlight_nodes = set(highlight_nodes or [])
        highlight_edges = set(highlight_edges or [])

        nodes = []
        edges = []
        included_nodes = set()

        # Process nodes
        for node_id, data in self.graph.nodes(data=True):
            entity_type = data.get('entity_type', 'DEFAULT')
            importance = float(data.get('importance_score', 0.5))

            # Apply filters
            if filter_entity_types and entity_type not in filter_entity_types:
                continue
            if importance < min_importance:
                continue

            included_nodes.add(node_id)

            # Get color and shape
            color = ENTITY_COLORS.get(entity_type, ENTITY_COLORS['DEFAULT'])
            shape = ENTITY_SHAPES.get(entity_type, ENTITY_SHAPES['DEFAULT'])

            # Calculate size based on importance
            size = 15 + (importance * 25)

            # Check if highlighted
            is_highlighted = node_id in highlight_nodes

            node_vis = {
                'id': node_id,
                'label': self._truncate_label(node_id),
                'title': self._create_tooltip(node_id, data),
                'color': {
                    'background': color,
                    'border': '#ffffff' if is_highlighted else self._darken_color(color),
                    'highlight': {
                        'background': self._lighten_color(color),
                        'border': '#ffffff'
                    }
                },
                'shape': shape,
                'size': size,
                'borderWidth': 4 if is_highlighted else 2,
                'font': {
                    'size': 12,
                    'color': '#333333'
                },
                # Store original data for inspection
                'data': {
                    'entity_type': entity_type,
                    'description': data.get('description', ''),
                    'importance_score': importance,
                    'source_chunks': data.get('source_chunks', '')
                }
            }

            nodes.append(node_vis)

        # Process edges
        for source, target, data in self.graph.edges(data=True):
            if source not in included_nodes or target not in included_nodes:
                continue

            relation_type = data.get('relation_type', 'RELATED')
            weight = float(data.get('weight', 0.5))

            # Check if highlighted
            is_highlighted = (source, target) in highlight_edges

            edge_vis = {
                'from': source,
                'to': target,
                'label': relation_type,
                'title': self._create_edge_tooltip(source, target, data),
                'arrows': 'to',
                'color': {
                    'color': '#ff0000' if is_highlighted else '#848484',
                    'highlight': '#ff6600',
                    'opacity': 0.8 if is_highlighted else 0.6
                },
                'width': 3 if is_highlighted else max(1, weight * 3),
                'smooth': {
                    'type': 'curvedCW',
                    'roundness': 0.2
                },
                'font': {
                    'size': 10,
                    'align': 'middle',
                    'background': 'white'
                },
                # Store original data
                'data': {
                    'relation_type': relation_type,
                    'description': data.get('description', ''),
                    'weight': weight,
                    'order': data.get('order', 0),
                    'source_chunk': data.get('source_chunk', '')
                }
            }

            edges.append(edge_vis)

        return {
            'nodes': nodes,
            'edges': edges,
            'stats': {
                'num_nodes': len(nodes),
                'num_edges': len(edges),
                'entity_types': dict(self.stats.entity_types) if self.stats else {},
                'relation_types': dict(self.stats.relation_types) if self.stats else {}
            }
        }

    def get_subgraph(self,
                     center_node: str,
                     depth: int = 2,
                     max_nodes: int = 100) -> Dict[str, Any]:
        """
        Get a subgraph centered on a specific node.

        Args:
            center_node: The node to center the subgraph on
            depth: How many hops from the center node
            max_nodes: Maximum number of nodes to include

        Returns:
            vis.js formatted subgraph data
        """
        if self.graph is None:
            raise ValueError("No graph loaded. Call load() first.")

        if center_node not in self.graph:
            raise ValueError(f"Node '{center_node}' not found in graph")

        # BFS to find nodes within depth
        nodes_to_include = {center_node}
        current_frontier = {center_node}

        for _ in range(depth):
            next_frontier = set()
            for node in current_frontier:
                # Get neighbors (both in and out for directed graphs)
                if self.graph.is_directed():
                    neighbors = set(self.graph.predecessors(node)) | set(self.graph.successors(node))
                else:
                    neighbors = set(self.graph.neighbors(node))
                next_frontier |= neighbors

            nodes_to_include |= next_frontier
            current_frontier = next_frontier

            if len(nodes_to_include) >= max_nodes:
                break

        # Create subgraph
        subgraph = self.graph.subgraph(list(nodes_to_include)[:max_nodes])

        # Convert to vis format with center node highlighted
        original_graph = self.graph
        self.graph = subgraph
        result = self.to_vis_format(highlight_nodes=[center_node])
        self.graph = original_graph

        return result

    def search_nodes(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Search for nodes matching a query.

        Args:
            query: Search string (matches node ID or description)
            limit: Maximum results to return

        Returns:
            List of matching nodes with their data
        """
        if self.graph is None:
            return []

        query_lower = query.lower()
        results = []

        for node_id, data in self.graph.nodes(data=True):
            score = 0

            # Check node ID
            if query_lower in node_id.lower():
                score = 2 if node_id.lower().startswith(query_lower) else 1

            # Check description
            description = data.get('description', '').lower()
            if query_lower in description:
                score += 0.5

            if score > 0:
                results.append({
                    'id': node_id,
                    'entity_type': data.get('entity_type', 'UNKNOWN'),
                    'description': data.get('description', '')[:200],
                    'importance': float(data.get('importance_score', 0.5)),
                    'score': score
                })

        # Sort by score and importance
        results.sort(key=lambda x: (-x['score'], -x['importance']))
        return results[:limit]

    def get_node_details(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific node."""
        if self.graph is None or node_id not in self.graph:
            return None

        data = dict(self.graph.nodes[node_id])

        # Get connected edges
        incoming = []
        outgoing = []

        if self.graph.is_directed():
            for pred in self.graph.predecessors(node_id):
                edge_data = self.graph.edges[pred, node_id]
                incoming.append({
                    'from': pred,
                    'relation': edge_data.get('relation_type', 'RELATED'),
                    'description': edge_data.get('description', '')
                })

            for succ in self.graph.successors(node_id):
                edge_data = self.graph.edges[node_id, succ]
                outgoing.append({
                    'to': succ,
                    'relation': edge_data.get('relation_type', 'RELATED'),
                    'description': edge_data.get('description', '')
                })
        else:
            for neighbor in self.graph.neighbors(node_id):
                edge_data = self.graph.edges[node_id, neighbor]
                outgoing.append({
                    'to': neighbor,
                    'relation': edge_data.get('relation_type', 'RELATED'),
                    'description': edge_data.get('description', '')
                })

        return {
            'id': node_id,
            'entity_type': data.get('entity_type', 'UNKNOWN'),
            'description': data.get('description', ''),
            'importance_score': float(data.get('importance_score', 0.5)),
            'source_chunks': data.get('source_chunks', ''),
            'incoming_edges': incoming,
            'outgoing_edges': outgoing,
            'degree': len(incoming) + len(outgoing)
        }

    def _truncate_label(self, label: str, max_length: int = 25) -> str:
        """Truncate a label for display."""
        if len(label) <= max_length:
            return label
        return label[:max_length-3] + '...'

    def _create_tooltip(self, node_id: str, data: Dict[str, Any]) -> str:
        """Create an HTML tooltip for a node."""
        entity_type = data.get('entity_type', 'UNKNOWN')
        description = data.get('description', 'No description')[:300]
        importance = float(data.get('importance_score', 0.5))

        return f"""
        <div style="max-width: 300px; padding: 8px;">
            <strong>{node_id}</strong><br>
            <span style="color: {ENTITY_COLORS.get(entity_type, '#666')};">
                [{entity_type}]
            </span><br>
            <hr style="margin: 4px 0;">
            <p style="font-size: 12px; margin: 4px 0;">{description}</p>
            <small>Importance: {importance:.2f}</small>
        </div>
        """

    def _create_edge_tooltip(self, source: str, target: str, data: Dict[str, Any]) -> str:
        """Create an HTML tooltip for an edge."""
        relation = data.get('relation_type', 'RELATED')
        description = data.get('description', 'No description')[:200]
        weight = float(data.get('weight', 0.5))

        return f"""
        <div style="max-width: 250px; padding: 8px;">
            <strong>{relation}</strong><br>
            <small>{source} → {target}</small>
            <hr style="margin: 4px 0;">
            <p style="font-size: 11px; margin: 4px 0;">{description}</p>
            <small>Weight: {weight:.2f}</small>
        </div>
        """

    def _darken_color(self, hex_color: str, factor: float = 0.7) -> str:
        """Darken a hex color."""
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        darkened = tuple(int(c * factor) for c in rgb)
        return '#{:02x}{:02x}{:02x}'.format(*darkened)

    def _lighten_color(self, hex_color: str, factor: float = 1.3) -> str:
        """Lighten a hex color."""
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        lightened = tuple(min(255, int(c * factor)) for c in rgb)
        return '#{:02x}{:02x}{:02x}'.format(*lightened)


def find_graphs_in_directory(base_path: str, pattern: str = "**/*graph.graphml") -> List[str]:
    """
    Find all GraphML files in a directory.

    Args:
        base_path: Base directory to search
        pattern: Glob pattern for matching files

    Returns:
        List of absolute paths to GraphML files
    """
    base = Path(base_path)
    return [str(p.absolute()) for p in base.glob(pattern)]
