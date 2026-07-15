"""
NetworkX adapter for GASL system.
"""

import re

import networkx as nx
from typing import Any, Dict, Iterator, List, Set
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
            max_results = int(filters.get("_max_results", self.capabilities.max_results) or self.capabilities.max_results)
            paths = []
            for row in self.iter_paths(filters):
                paths.append(row)
                if len(paths) >= max_results:
                    break
            return paths
            
        except Exception as e:
            raise AdapterError(f"Failed to find paths: {e}", "networkx", "find_paths")

    def iter_paths(self, filters: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """Yield paths incrementally so callers can probe early results before widening."""
        max_path_length = self.capabilities.max_path_length
        max_pair_budget = int(filters.get("_max_pairs", 0) or 0)
        relation_type = str(filters.get("relation_type", "") or "").strip('"').strip("'")

        source_nodes = self._get_nodes_by_filter(filters.get("source_filter", {}))
        target_nodes = self._get_nodes_by_filter(filters.get("target_filter", {}))
        if not source_nodes or not target_nodes:
            return

        search_graph = self._relation_filtered_graph(relation_type) if relation_type else self.graph
        scanned_pairs = 0
        emitted = 0
        max_results = int(filters.get("_max_results", self.capabilities.max_results) or self.capabilities.max_results)

        for source in source_nodes:
            for target in target_nodes:
                if source == target:
                    continue
                scanned_pairs += 1
                if max_pair_budget and scanned_pairs > max_pair_budget:
                    return
                try:
                    path = nx.shortest_path(search_graph, source, target)
                except nx.NetworkXNoPath:
                    continue
                if len(path) > max_path_length:
                    continue
                edge_types = self._path_edge_types(path)
                source_entity = str((self.graph.nodes.get(source) or {}).get("entity_type") or "").strip('"').strip("'")
                target_entity = str((self.graph.nodes.get(target) or {}).get("entity_type") or "").strip('"').strip("'")
                yield {
                    "source": source,
                    "target": target,
                    "path": path,
                    "length": len(path) - 1,
                    "type": "path",
                    "edge_types": edge_types,
                    "source_entity_type": source_entity,
                    "target_entity_type": target_entity,
                }
                emitted += 1
                if emitted >= max_results:
                    return

    def _relation_filtered_graph(self, relation_type: str):
        """Return a graph view restricted to a specific relation type."""
        if not relation_type:
            return self.graph
        relation_type = str(relation_type).strip('"').strip("'").lower()
        if isinstance(self.graph, nx.MultiDiGraph):
            g = nx.MultiDiGraph()
            g.add_nodes_from(self.graph.nodes(data=True))
            for u, v, k, data in self.graph.edges(data=True, keys=True):
                edge_rel = str(data.get("relation_type") or data.get("relationship_name") or "").strip('"').strip("'").lower()
                if edge_rel == relation_type:
                    g.add_edge(u, v, key=k, **data)
            return g
        else:
            g = type(self.graph)()
            g.add_nodes_from(self.graph.nodes(data=True))
            for u, v, data in self.graph.edges(data=True):
                edge_rel = str(data.get("relation_type") or data.get("relationship_name") or "").strip('"').strip("'").lower()
                if edge_rel == relation_type:
                    g.add_edge(u, v, **data)
            return g

    def _path_edge_types(self, path: List[Any]) -> List[str]:
        """Return relation types along a path to make path semantics inspectable."""
        edge_types: List[str] = []
        if len(path) < 2:
            return edge_types
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if isinstance(self.graph, nx.MultiDiGraph):
                edge_data = self.graph.get_edge_data(u, v) or {}
                rel = None
                for _, data in edge_data.items():
                    rel = data.get("relation_type") or data.get("relationship_name")
                    if rel:
                        break
            else:
                data = self.graph.get_edge_data(u, v) or {}
                rel = data.get("relation_type") or data.get("relationship_name")
            edge_types.append(str(rel or ""))
        return edge_types
    
    def _node_matches_filters(self, node_id: Any, data: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if node matches filters."""
        if "id_filter" in filters and str(node_id) != str(filters["id_filter"]):
            return False

        # Check entity_type filter
        if "entity_type" in filters:
            entity_type = filters["entity_type"]
            node_entity_type = data.get("entity_type")
            
            # Handle multiple entity types (list)
            if isinstance(entity_type, list):
                clean_node = (node_entity_type or "").strip('"').strip("'")
                if not any(clean_node == et.strip('"').strip("'") for et in entity_type):
                    return False
            else:
                # Handle single entity type — compare with and without surrounding quotes
                clean_filter = entity_type.strip('"').strip("'")
                clean_node = (node_entity_type or "").strip('"').strip("'")
                if clean_node != clean_filter:
                    return False
        
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
            description_filters = filters["description_contains"]
            if isinstance(description_filters, str):
                description_filters = [description_filters]
            if not any(
                str(term).lower() in description.lower()
                for term in description_filters
            ):
                return False
        
        # Check raw criteria (bulletproof keyword matching)
        if "raw_criteria" in filters:
            criteria = filters["raw_criteria"].lower()
            node_text = f"{node_id} {str(data)}".lower()
            
            raw_entity_types = self._entity_types_from_raw_criteria(criteria)
            if raw_entity_types:
                clean_node = str(data.get("entity_type") or "").strip('"').strip("'").lower()
                if clean_node not in raw_entity_types:
                    return False
            elif not self._has_structured_filter(
                filters,
                {"id_filter", "entity_type", "relationship_name", "description_contains"},
            ):
                if criteria not in node_text:
                    return False
        
        return True

    @staticmethod
    def _entity_types_from_raw_criteria(criteria: str) -> Set[str]:
        entity_list_match = re.search(
            r"(?:entity_type|label)\s+in\s*\[([^\]]+)\]", criteria, re.IGNORECASE
        )
        if entity_list_match:
            return {
                match.group(1).strip().lower()
                for match in re.finditer(
                    r"['\"]?([a-z0-9_]+)['\"]?",
                    entity_list_match.group(1),
                    re.IGNORECASE,
                )
            }

        patterns = [
            r"(?:entity_type|label)\s*[=:]\s*['\"]?([a-z0-9_|]+)['\"]?",
            r"(?:entity_type|label)\s+['\"]?([a-z0-9_|]+)['\"]?",
        ]
        for pattern in patterns:
            match = re.search(pattern, criteria, re.IGNORECASE)
            if match:
                return {
                    entity_type.strip().lower()
                    for entity_type in match.group(1).replace("|", ",").split(",")
                    if entity_type.strip()
                }
        return set()
    
    def _edge_matches_filters(self, source: Any, target: Any, data: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if edge matches filters."""
        # Check relationship_name filter (check both relationship_name and relation_type)
        if "relationship_name" in filters:
            relationship_name = filters["relationship_name"]
            edge_relationship_name = data.get("relationship_name") or data.get("relation_type")
            clean_edge = str(edge_relationship_name or "").strip('"').strip("'").lower()
            clean_filter = str(relationship_name).strip('"').strip("'").lower()
            if clean_edge != clean_filter:
                return False  # No match found

        if "relation_type" in filters:
            edge_relation_type = data.get("relation_type") or data.get("relationship_name")
            clean_edge = str(edge_relation_type or "").strip('"').strip("'").lower()
            clean_filter = str(filters["relation_type"]).strip('"').strip("'").lower()
            if clean_edge != clean_filter:
                return False

        # Check source filter
        if "source" in filters:
            if source != filters["source"]:
                return False

        # Check target filter
        if "target" in filters:
            if target != filters["target"]:
                return False

        # Check description contains filter
        if "description_contains" in filters:
            description = data.get("description", "")
            description_filters = filters["description_contains"]
            if isinstance(description_filters, str):
                description_filters = [description_filters]
            if not any(
                str(term).lower() in description.lower()
                for term in description_filters
            ):
                return False

        # Check raw criteria
        if "raw_criteria" in filters:
            criteria = filters["raw_criteria"].lower()
            edge_text = f"{source} {target} {str(data)}".lower()
            if (
                not self._has_structured_filter(
                    filters,
                    {
                        "source",
                        "target",
                        "relationship_name",
                        "relation_type",
                        "description_contains",
                    },
                )
                and criteria not in edge_text
            ):
                return False

        return True

    @staticmethod
    def _has_structured_filter(filters: Dict[str, Any], keys: Set[str]) -> bool:
        return any(key in filters for key in keys)
    
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
            relationship_name = data.get("relationship_name") or data.get("relation_type")
            if relationship_name:
                clean_type = str(relationship_name).strip('"').strip("'")
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
