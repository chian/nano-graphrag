"""
Neo4j adapter for GASL system.
"""

from typing import Any, Dict, List
from .base import GraphAdapter
from ..types import AdapterCapabilities
from ..errors import AdapterError


class Neo4jAdapter(GraphAdapter):
    """Neo4j implementation of GraphAdapter."""
    
    def _get_capabilities(self) -> AdapterCapabilities:
        """Get Neo4j adapter capabilities."""
        return AdapterCapabilities(
            supports_path_finding=True,
            supports_cypher=True,
            supports_networkx=False,
            max_path_length=10,
            max_results=1000,
            supported_node_properties=self._get_node_properties(),
            supported_edge_properties=self._get_edge_properties()
        )
    
    def find_nodes(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find nodes matching filters using Cypher."""
        try:
            # Build Cypher query
            cypher = self._build_node_query(filters)
            
            # Execute query
            result = self.graph.run(cypher)
            
            nodes = []
            for record in result:
                node_info = {
                    "id": record["n"].id,
                    "data": dict(record["n"]),
                    "type": "node"
                }
                nodes.append(node_info)
            
            # Apply max_results limit
            max_results = self.capabilities.max_results
            if len(nodes) > max_results:
                nodes = nodes[:max_results]
            
            return nodes
            
        except Exception as e:
            raise AdapterError(f"Failed to find nodes: {e}", "neo4j", "find_nodes")
    
    def find_edges(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find edges matching filters using Cypher."""
        try:
            # Build Cypher query
            cypher = self._build_edge_query(filters)
            
            # Execute query
            result = self.graph.run(cypher)
            
            edges = []
            for record in result:
                edge_info = {
                    "source": record["s"].id,
                    "target": record["e"].id,
                    "data": dict(record["r"]),
                    "type": "edge"
                }
                edges.append(edge_info)
            
            # Apply max_results limit
            max_results = self.capabilities.max_results
            if len(edges) > max_results:
                edges = edges[:max_results]
            
            return edges
            
        except Exception as e:
            raise AdapterError(f"Failed to find edges: {e}", "neo4j", "find_edges")
    
    def find_paths(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find paths matching filters using Cypher."""
        try:
            # Build Cypher query
            cypher = self._build_path_query(filters)
            
            # Execute query
            result = self.graph.run(cypher)
            
            paths = []
            for record in result:
                path_info = {
                    "source": record["p"].start_node.id,
                    "target": record["p"].end_node.id,
                    "path": [node.id for node in record["p"].nodes],
                    "length": len(record["p"].relationships),
                    "type": "path"
                }
                paths.append(path_info)
            
            # Apply max_results limit
            max_results = self.capabilities.max_results
            if len(paths) > max_results:
                paths = paths[:max_results]
            
            return paths
            
        except Exception as e:
            raise AdapterError(f"Failed to find paths: {e}", "neo4j", "find_paths")
    
    def _build_node_query(self, filters: Dict[str, Any]) -> str:
        """Build Cypher query for finding nodes."""
        query = "MATCH (n)"
        conditions = []
        
        # Add entity_type filter
        if "entity_type" in filters:
            entity_type = filters["entity_type"]
            conditions.append(f"n.entity_type = '{entity_type}'")
        
        # Add description filter
        if "description_contains" in filters:
            description = filters["description_contains"]
            conditions.append(f"n.description CONTAINS '{description}'")
        
        # Add raw criteria (simple property matching)
        if "raw_criteria" in filters:
            criteria = filters["raw_criteria"]
            # Simple keyword matching in description
            conditions.append(f"n.description CONTAINS '{criteria}'")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += f" RETURN n LIMIT {self.capabilities.max_results}"
        
        return query
    
    def _build_edge_query(self, filters: Dict[str, Any]) -> str:
        """Build Cypher query for finding edges."""
        query = "MATCH (s)-[r]->(e)"
        conditions = []
        
        # Add relationship_name filter
        if "relationship_name" in filters:
            relationship_name = filters["relationship_name"]
            conditions.append(f"r.relationship_name = '{relationship_name}'")
        
        # Add description filter
        if "description_contains" in filters:
            description = filters["description_contains"]
            conditions.append(f"r.description CONTAINS '{description}'")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += f" RETURN s, r, e LIMIT {self.capabilities.max_results}"
        
        return query
    
    def _build_path_query(self, filters: Dict[str, Any]) -> str:
        """Build Cypher query for finding paths."""
        max_length = self.capabilities.max_path_length
        
        query = f"MATCH p = (start)-[*1..{max_length}]->(end)"
        conditions = []
        
        # Add source filter
        if "source_filter" in filters:
            source_filter = filters["source_filter"]
            if "entity_type" in source_filter:
                entity_type = source_filter["entity_type"]
                conditions.append(f"start.entity_type = '{entity_type}'")
        
        # Add target filter
        if "target_filter" in filters:
            target_filter = filters["target_filter"]
            if "entity_type" in target_filter:
                entity_type = target_filter["entity_type"]
                conditions.append(f"end.entity_type = '{entity_type}'")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += f" RETURN p LIMIT {self.capabilities.max_results}"
        
        return query
    
    def _get_node_labels(self) -> List[str]:
        """Get available node labels."""
        try:
            result = self.graph.run("CALL db.labels()")
            return [record["label"] for record in result]
        except Exception:
            return []
    
    def _get_edge_types(self) -> List[str]:
        """Get available edge types."""
        try:
            result = self.graph.run("CALL db.relationshipTypes()")
            return [record["relationshipType"] for record in result]
        except Exception:
            return []
    
    def _get_node_properties(self) -> List[str]:
        """Get available node properties."""
        try:
            result = self.graph.run("CALL db.propertyKeys()")
            return [record["propertyKey"] for record in result]
        except Exception:
            return []
    
    def _get_edge_properties(self) -> List[str]:
        """Get available edge properties."""
        # For Neo4j, edge properties are the same as node properties
        return self._get_node_properties()
