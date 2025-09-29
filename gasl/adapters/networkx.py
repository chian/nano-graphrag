"""
NetworkX adapter for GASL system.
"""

import networkx as nx
from typing import Any, Dict, List, Set
from .base import GraphAdapter
from ..types import AdapterCapabilities
from ..errors import AdapterError


class NetworkXAdapter(GraphAdapter):
    """NetworkX implementation of GraphAdapter."""
    
    def _get_capabilities(self) -> AdapterCapabilities:
        """Get NetworkX adapter capabilities."""
        return AdapterCapabilities(
            supports_path_finding=True,
            supports_cypher=False,
            supports_networkx=True,
            max_path_length=10,
            max_results=1000,
            supported_node_properties=self._get_node_properties(),
            supported_edge_properties=self._get_edge_properties()
        )
    
    def get_schema(self) -> Dict[str, Any]:
        """Get graph schema information."""
        return {
            "node_labels": self._get_node_labels(),
            "edge_types": self._get_edge_types(),
            "node_properties": self._get_node_properties(),
            "edge_properties": self._get_edge_properties(),
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges()
        }
    
    def find_nodes(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find nodes matching filters."""
        try:
            nodes = []
            
            for node_id, data in self.graph.nodes(data=True):
                if self._node_matches_filters(node_id, data, filters):
                    node_info = {
                        "id": node_id,
                        "data": data,
                        "type": "node"
                    }
                    nodes.append(node_info)
            
            # Apply max_results limit
            max_results = self.capabilities.max_results
            if len(nodes) > max_results:
                nodes = nodes[:max_results]
            
            return nodes
            
        except Exception as e:
            raise AdapterError(f"Failed to find nodes: {e}", "networkx", "find_nodes")
    
    def find_edges(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find edges matching filters."""
        try:
            edges = []
            
            for source, target, data in self.graph.edges(data=True):
                if self._edge_matches_filters(source, target, data, filters):
                    edge_info = {
                        "source": source,
                        "target": target,
                        "data": data,
                        "type": "edge"
                    }
                    edges.append(edge_info)
            
            # Apply max_results limit
            max_results = self.capabilities.max_results
            if len(edges) > max_results:
                edges = edges[:max_results]
            
            return edges
            
        except Exception as e:
            raise AdapterError(f"Failed to find edges: {e}", "networkx", "find_edges")
    
    def find_paths(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find paths matching filters."""
        try:
            paths = []
            max_path_length = self.capabilities.max_path_length
            
            # Extract source and target from filters
            source_nodes = self._get_nodes_by_filter(filters.get("source_filter", {}))
            target_nodes = self._get_nodes_by_filter(filters.get("target_filter", {}))
            
            if not source_nodes or not target_nodes:
                return paths
            
            # Find paths between source and target nodes
            for source in source_nodes:
                for target in target_nodes:
                    if source != target:
                        try:
                            # Use NetworkX shortest path
                            path = nx.shortest_path(self.graph, source, target)
                            
                            if len(path) <= max_path_length:
                                path_info = {
                                    "source": source,
                                    "target": target,
                                    "path": path,
                                    "length": len(path) - 1,
                                    "type": "path"
                                }
                                paths.append(path_info)
                        except nx.NetworkXNoPath:
                            # No path exists
                            continue
            
            # Apply max_results limit
            max_results = self.capabilities.max_results
            if len(paths) > max_results:
                paths = paths[:max_results]
            
            return paths
            
        except Exception as e:
            raise AdapterError(f"Failed to find paths: {e}", "networkx", "find_paths")
    
    def _node_matches_filters(self, node_id: Any, data: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if node matches filters."""
        # Check entity_type filter
        if "entity_type" in filters:
            entity_type = filters["entity_type"]
            node_entity_type = data.get("entity_type")
            if node_entity_type == f'"{entity_type}"':
                pass  # Match found with quotes
            elif node_entity_type == entity_type:
                pass  # Match found without quotes
            else:
                return False  # No match found
        
        # Check relationship_name filter (for nodes, this might be in data)
        if "relationship_name" in filters:
            relationship_name = filters["relationship_name"]
            node_relationship_name = data.get("relationship_name")
            if node_relationship_name == f'"{relationship_name}"':
                pass  # Match found with quotes
            elif node_relationship_name == relationship_name:
                pass  # Match found without quotes
            else:
                return False  # No match found
        
        # Check description contains filter
        if "description_contains" in filters:
            description = data.get("description", "")
            if filters["description_contains"].lower() not in description.lower():
                return False
        
        # Check raw criteria (bulletproof keyword matching)
        if "raw_criteria" in filters:
            criteria = filters["raw_criteria"].lower()
            node_text = f"{node_id} {str(data)}".lower()
            
            # For entity_type criteria, extract and check the entity type value
            if "entity_type" in criteria:
                import re
                # Extract entity type from various formats
                patterns = [
                    r"entity_type\s*[=:]\s*['\"]?([a-z_]+)['\"]?",
                    r"entity_type\s+['\"]?([a-z_]+)['\"]?",
                ]
                
                entity_type_found = False
                for pattern in patterns:
                    match = re.search(pattern, criteria)
                    if match:
                        entity_type_value = match.group(1).strip()
                        # Check if this entity type appears in the node data
                        if entity_type_value in node_text:
                            entity_type_found = True
                            break
                
                if not entity_type_found:
                    return False
            else:
                # For other criteria, do simple keyword matching
                if criteria not in node_text:
                    return False
        
        return True
    
    def _edge_matches_filters(self, source: Any, target: Any, data: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if edge matches filters."""
        # Check relationship_name filter
        if "relationship_name" in filters:
            relationship_name = filters["relationship_name"]
            edge_relationship_name = data.get("relationship_name")
            if edge_relationship_name == f'"{relationship_name}"':
                pass  # Match found with quotes
            elif edge_relationship_name == relationship_name:
                pass  # Match found without quotes
            else:
                return False  # No match found
        
        # Check description contains filter
        if "description_contains" in filters:
            description = data.get("description", "")
            if filters["description_contains"].lower() not in description.lower():
                return False
        
        # Check raw criteria
        if "raw_criteria" in filters:
            criteria = filters["raw_criteria"].lower()
            edge_text = f"{source} {target} {str(data)}".lower()
            if criteria not in edge_text:
                return False
        
        return True
    
    def _get_nodes_by_filter(self, filters: Dict[str, Any]) -> List[Any]:
        """Get nodes matching specific filters."""
        nodes = []
        for node_id, data in self.graph.nodes(data=True):
            if self._node_matches_filters(node_id, data, filters):
                nodes.append(node_id)
        return nodes
    
    def _get_node_labels(self) -> List[str]:
        """Get available node labels (entity types)."""
        labels = set()
        for _, data in self.graph.nodes(data=True):
            # Try direct entity_type first
            entity_type = data.get("entity_type")
            if not entity_type and "data" in data:
                # Try nested data structure
                entity_type = data.get("data", {}).get("entity_type")
            if entity_type:
                # Remove quotes if present
                clean_type = entity_type.strip('"')
                labels.add(clean_type)
        return list(labels)
    
    def _get_edge_types(self) -> List[str]:
        """Get available edge types (relationship names)."""
        types = set()
        for _, _, data in self.graph.edges(data=True):
            relationship_name = data.get("relationship_name")
            if relationship_name:
                # Remove quotes if present
                clean_type = relationship_name.strip('"')
                types.add(clean_type)
        return list(types)
    
    def _get_node_properties(self) -> List[str]:
        """Get available node properties."""
        properties = set()
        for _, data in self.graph.nodes(data=True):
            properties.update(data.keys())
        return list(properties)
    
    def _get_edge_properties(self) -> List[str]:
        """Get available edge properties."""
        properties = set()
        for _, _, data in self.graph.edges(data=True):
            properties.update(data.keys())
        return list(properties)
