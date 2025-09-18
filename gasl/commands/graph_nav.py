"""
Graph Navigation command handlers.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..adapters.base import GraphAdapter


class GraphNavHandler(CommandHandler):
    """Handles graph navigation commands: GRAPHWALK, GRAPHCONNECT, SUBGRAPH, GRAPHPATTERN."""
    
    def __init__(self, state_store, context_store, adapter: GraphAdapter):
        super().__init__(state_store, context_store)
        self.adapter = adapter
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type in ["GRAPHWALK", "GRAPHCONNECT", "SUBGRAPH", "GRAPHPATTERN"]
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute graph navigation command."""
        try:
            if command.command_type == "GRAPHWALK":
                return self._execute_graphwalk(command)
            elif command.command_type == "GRAPHCONNECT":
                return self._execute_graphconnect(command)
            elif command.command_type == "SUBGRAPH":
                return self._execute_subgraph(command)
            elif command.command_type == "GRAPHPATTERN":
                return self._execute_graphpattern(command)
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown graph navigation command: {command.command_type}"
                )
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _execute_graphwalk(self, command: Command) -> ExecutionResult:
        """Execute GRAPHWALK command."""
        args = command.args
        from_var = args["from_variable"]
        follow_types = args["relationship_types"]
        depth = int(args.get("depth", 1))
        
        print(f"DEBUG: GRAPHWALK - from: {from_var}, follow: {follow_types}, depth: {depth}")
        
        # Get source nodes
        source_nodes = self._get_variable_data(from_var)
        if not source_nodes:
            # If the specified variable is empty, try to use last_nodes_result
            if self.context_store.has("last_nodes_result"):
                source_nodes = self.context_store.get("last_nodes_result")
                print(f"DEBUG: GRAPHWALK - Using last_nodes_result as fallback: {len(source_nodes)} nodes")
            else:
                return self._create_result(command=command, status="error", 
                                         error_message=f"Variable {from_var} not found or empty, and no last_nodes_result available")
        
        # Perform graph walk with memory limit
        walked_data = []
        max_nodes = 10000  # Limit to prevent memory issues
        
        for node in source_nodes[:100]:  # Limit source nodes to first 100
            if len(walked_data) >= max_nodes:
                break
                
            node_id = node.get("id")
            if node_id:
                # Multi-hop traversal
                current_nodes = [node]
                for step in range(depth):
                    next_nodes = []
                    for current_node in current_nodes:
                        if len(walked_data) >= max_nodes:
                            break
                            
                        # Find edges from current node
                        edges = self.adapter.find_edges({"source_filter": f"id={current_node['id']}"})
                        for edge in edges[:50]:  # Limit edges per node to 50
                            if len(walked_data) >= max_nodes:
                                break
                                
                            # Since edges don't have relationship_name, follow all edges
                            # or check if the relationship type matches the edge description
                            should_follow = True
                            if follow_types not in ["*", "all", "any"]:
                                # Check if any of the follow types appear in the edge description
                                edge_desc = edge.get("data", {}).get("description", "").lower()
                                follow_types_list = [rt.strip().lower() for rt in follow_types.split(",")]
                                should_follow = any(rt in edge_desc for rt in follow_types_list)
                            
                            if should_follow:
                                # Get target node
                                target_node = self.adapter.find_nodes({"id_filter": edge["target"]})
                                if target_node:
                                    next_nodes.extend(target_node)
                    current_nodes = next_nodes
                walked_data.extend(current_nodes)
        
        # Store result in context
        self.context_store.set("last_walk_result", walked_data)
        print(f"DEBUG: GRAPHWALK - stored {len(walked_data)} nodes in last_walk_result")
        
        return self._create_result(
            command=command,
            status="success",
            data=walked_data,
            count=len(walked_data),
            provenance=[self._create_provenance("graph-walk", "graphwalk", 
                                               from_variable=from_var, depth=depth)]
        )
    
    def _execute_graphconnect(self, command: Command) -> ExecutionResult:
        """Execute GRAPHCONNECT command."""
        args = command.args
        var1 = args["variable1"]
        var2 = args["variable2"]
        via_pattern = args.get("via_pattern", "")
        
        print(f"DEBUG: GRAPHCONNECT - {var1} to {var2} via {via_pattern}")
        
        # Get source node sets
        nodes1 = self._get_variable_data(var1)
        nodes2 = self._get_variable_data(var2)
        
        if not nodes1 or not nodes2:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variables {var1} or {var2} not found or empty")
        
        # Find connections between node sets
        connections = []
        for node1 in nodes1:
            for node2 in nodes2:
                if node1.get("id") != node2.get("id"):  # Don't connect to self
                    # Find path between nodes
                    paths = self.adapter.find_paths({
                        "source_filter": f"id={node1['id']}",
                        "target_filter": f"id={node2['id']}"
                    })
                    if paths:
                        connections.append({
                            "source": node1,
                            "target": node2,
                            "paths": paths
                        })
        
        # Store result in context
        self.context_store.set("last_connect_result", connections)
        print(f"DEBUG: GRAPHCONNECT - found {len(connections)} connections")
        
        return self._create_result(
            command=command,
            status="success",
            data=connections,
            count=len(connections),
            provenance=[self._create_provenance("graph-connect", "graphconnect",
                                               variable1=var1, variable2=var2)]
        )
    
    def _execute_subgraph(self, command: Command) -> ExecutionResult:
        """Execute SUBGRAPH command."""
        args = command.args
        around_var = args["around_variable"]
        radius = int(args.get("radius", 1))
        include_types = args.get("include_types", "").split(",")
        
        print(f"DEBUG: SUBGRAPH - around: {around_var}, radius: {radius}, include: {include_types}")
        
        # Get center nodes
        center_nodes = self._get_variable_data(around_var)
        if not center_nodes:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {around_var} not found or empty")
        
        # Extract subgraph around center nodes
        subgraph_nodes = set()
        subgraph_edges = []
        
        for center_node in center_nodes:
            # Add center node
            subgraph_nodes.add(center_node["id"])
            
            # Find nodes within radius
            current_nodes = [center_node]
            for step in range(radius):
                next_nodes = []
                for node in current_nodes:
                    # Find all edges connected to this node
                    edges = self.adapter.find_edges({"source_filter": f"id={node['id']}"})
                    edges.extend(self.adapter.find_edges({"target_filter": f"id={node['id']}"}))
                    
                    for edge in edges:
                        # Check if target/source matches include types
                        target_node = self.adapter.find_nodes({"id_filter": edge["target"]})
                        source_node = self.adapter.find_nodes({"id_filter": edge["source"]})
                        
                        if target_node and (not include_types or any(t in target_node[0].get("entity_type", "") for t in include_types)):
                            subgraph_nodes.add(edge["target"])
                            next_nodes.extend(target_node)
                            subgraph_edges.append(edge)
                        
                        if source_node and (not include_types or any(t in source_node[0].get("entity_type", "") for t in include_types)):
                            subgraph_nodes.add(edge["source"])
                            next_nodes.extend(source_node)
                            subgraph_edges.append(edge)
                
                current_nodes = next_nodes
        
        # Get full node data for subgraph
        subgraph_node_data = []
        for node_id in subgraph_nodes:
            node_data = self.adapter.find_nodes({"id_filter": node_id})
            if node_data:
                subgraph_node_data.extend(node_data)
        
        subgraph_result = {
            "nodes": subgraph_node_data,
            "edges": subgraph_edges
        }
        
        # Store result in context
        self.context_store.set("last_subgraph_result", subgraph_result)
        print(f"DEBUG: SUBGRAPH - extracted {len(subgraph_node_data)} nodes, {len(subgraph_edges)} edges")
        
        return self._create_result(
            command=command,
            status="success",
            data=subgraph_result,
            count=len(subgraph_node_data),
            provenance=[self._create_provenance("subgraph", "subgraph",
                                               around_variable=around_var, radius=radius)]
        )
    
    def _execute_graphpattern(self, command: Command) -> ExecutionResult:
        """Execute GRAPHPATTERN command."""
        args = command.args
        pattern_desc = args["pattern_description"]
        in_var = args["in_variable"]
        
        print(f"DEBUG: GRAPHPATTERN - pattern: {pattern_desc}, in: {in_var}")
        
        # Get nodes to search in
        search_nodes = self._get_variable_data(in_var)
        if not search_nodes:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {in_var} not found or empty")
        
        # Simple pattern matching (can be enhanced later)
        pattern_matches = []
        
        # Example: "Author->Publication->Author chains"
        if "author->publication->author" in pattern_desc.lower():
            for node in search_nodes:
                if node.get("entity_type") == '"PERSON"':
                    # Find publications this author is connected to
                    pub_edges = self.adapter.find_edges({"source_filter": f"id={node['id']}"})
                    for pub_edge in pub_edges:
                        # Find other authors connected to this publication
                        other_author_edges = self.adapter.find_edges({"target_filter": pub_edge["target"]})
                        for other_edge in other_author_edges:
                            if other_edge["source"] != node["id"]:
                                other_author = self.adapter.find_nodes({"id_filter": other_edge["source"]})
                                if other_author and other_author[0].get("entity_type") == '"PERSON"':
                                    pattern_matches.append({
                                        "pattern": "Author->Publication->Author",
                                        "author1": node,
                                        "publication": pub_edge["target"],
                                        "author2": other_author[0]
                                    })
        
        # Store result in context
        self.context_store.set("last_pattern_result", pattern_matches)
        print(f"DEBUG: GRAPHPATTERN - found {len(pattern_matches)} pattern matches")
        
        return self._create_result(
            command=command,
            status="success",
            data=pattern_matches,
            count=len(pattern_matches),
            provenance=[self._create_provenance("graph-pattern", "graphpattern",
                                               pattern=pattern_desc, in_variable=in_var)]
        )
    
    def _get_variable_data(self, variable_name: str) -> List[Dict]:
        """Get data from state or context variable."""
        # Try context first
        if self.context_store.has(variable_name):
            return self.context_store.get(variable_name)
        
        # Try state
        if self.state_store.has_variable(variable_name):
            var_data = self.state_store.get_variable(variable_name)
            if isinstance(var_data, dict) and "items" in var_data:
                return var_data["items"]
            else:
                return var_data if isinstance(var_data, list) else [var_data]
        
        return []
