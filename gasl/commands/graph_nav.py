"""
Graph Navigation command handlers.
"""

import re
from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..validation import LLMJudgeValidator
from ..adapters.base import GraphAdapter
from ..contracts import make_contract
from ..retrieval_probe import RetrievalProbePolicy


class GraphNavHandler(CommandHandler):
    """Handles graph navigation commands: GRAPHWALK, GRAPHCONNECT, SUBGRAPH, GRAPHPATTERN."""
    
    def __init__(self, state_store, context_store, adapter: GraphAdapter, llm_func=None, state_manager=None):
        super().__init__(state_store, context_store, state_manager)
        self.adapter = adapter
        self.validator = LLMJudgeValidator(llm_func) if llm_func else None
        self.probe_policy = RetrievalProbePolicy()
    
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
        result_var = args.get("result_var")
        
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
        effective_depth = depth
        source_cap = 100
        follow_filters = self._normalize_follow_types(follow_types)

        if self.validator and (len(source_nodes) > 10 or depth > 1):
            pilot = self._walk(source_nodes, follow_filters, depth, source_cap=10, max_nodes=60, edge_cap=15)
            pilot_contract = make_contract(
                payload_kind="walk_rows",
                data=pilot,
                label_field="data.entity_name",
                scope="current_rows_only",
                usable_by=["PROCESS", "AGGREGATE", "SHOW", "SELECT"],
                confidence=0.9,
                grain_type="edge",
                grain_keys=["src_id", "tgt_id", "relation_type", "path_depth"],
                multiplicity_preserved=True,
            )
            pilot_validation = self.validator.validate_graphwalk_semantics(
                command.args,
                source_nodes[:10],
                pilot,
                len(pilot),
                contract=pilot_contract,
            )
            if depth > 1 and (not pilot or self.probe_policy.should_adapt(pilot_validation, len(pilot), min_count=25)):
                effective_depth = 1
                source_cap = min(25, len(source_nodes))

        walked_data = self._walk(source_nodes, follow_filters, effective_depth, source_cap=source_cap, max_nodes=10000, edge_cap=50)
        
        if result_var:
            walk_contract = make_contract(
                payload_kind="walk_rows",
                data=walked_data,
                label_field="data.entity_name",
                scope="current_rows_only",
                usable_by=["PROCESS", "AGGREGATE", "SHOW", "SELECT"],
                confidence=0.9,
                grain_type="edge",
                grain_keys=["src_id", "tgt_id", "relation_type", "path_depth"],
                multiplicity_preserved=True,
            )
            self.context_store.set(result_var, walked_data, contract=walk_contract)
            if self.state_store.has_variable(result_var):
                self.state_store.update_variable(result_var, walked_data)
                self.state_store.set_variable_contract(result_var, walk_contract)

        # Store result in context
        walk_contract = make_contract(
            payload_kind="walk_rows",
            data=walked_data,
            label_field="data.entity_name",
            scope="current_rows_only",
            usable_by=["PROCESS", "AGGREGATE", "SHOW", "SELECT"],
            confidence=0.9,
            grain_type="edge",
            grain_keys=["src_id", "tgt_id", "relation_type", "path_depth"],
            multiplicity_preserved=True,
        )
        self.context_store.set("last_walk_result", walked_data, contract=walk_contract)
        # Compatibility: many plans expect the most recent graph navigation result
        # to be accessible via last_nodes_result for downstream PROCESS/AGGREGATE.
        self.context_store.set("last_nodes_result", walked_data, contract=walk_contract)
        print(f"DEBUG: GRAPHWALK - stored {len(walked_data)} nodes in last_walk_result")
        
        # Create initial result
        result_obj = self._create_result(
            command=command,
            status="success",
            data=walked_data,
            count=len(walked_data),
            contract=walk_contract,
            provenance=[self._create_provenance("graph-walk", "graphwalk", 
                                               from_variable=from_var, depth=depth)]
        )
        
        # Dedicated path-semantics validation with source-set context.
        if self.validator and len(walked_data) > 0:
            validation = self.validator.validate_graphwalk_semantics(
                command.args,
                source_nodes,
                walked_data,
                len(walked_data),
                contract=walk_contract,
            )
            walk_contract["confidence"] = min(
                float(walk_contract.get("confidence", 0.9)),
                float(validation.get("confidence", walk_contract.get("confidence", 0.9)) or 0.9),
            )
            if validation.get("recommended_payload_kind"):
                walk_contract["payload_kind"] = validation["recommended_payload_kind"]
            if validation.get("recommended_grain"):
                walk_contract["grain_type"] = validation["recommended_grain"]
            if validation.get("downstream_safe_for"):
                walk_contract["usable_by"] = list(validation["downstream_safe_for"])
            notes = list(walk_contract.get("notes", []))
            notes.append(f"path_semantics: {validation.get('reason', '')}".strip())
            if effective_depth != depth:
                notes.append(f"retrieval_probe: adapted GRAPHWALK depth {depth} -> {effective_depth}")
            walk_contract["notes"] = notes
            walk_contract["semantic_validation"] = validation

            if result_var:
                self.context_store.set(result_var, walked_data, contract=walk_contract)
                if self.state_store.has_variable(result_var):
                    self.state_store.set_variable_contract(result_var, walk_contract)
            self.context_store.set("last_walk_result", walked_data, contract=walk_contract)
            self.context_store.set("last_nodes_result", walked_data, contract=walk_contract)
            result_obj.contract = walk_contract

            if not validation.get("semantically_valid", True):
                result_obj.error_message = (
                    f"Path semantics warning: {validation.get('reason', 'Unknown path semantics warning')}"
                )
                print(f"DEBUG: GRAPHWALK - path semantics warning: {validation}")
            else:
                print(f"DEBUG: GRAPHWALK - path semantics passed: {validation.get('reason', 'Valid')}")
        
        return result_obj

    def _walk(
        self,
        source_nodes: list[dict],
        follow_filters: list[str],
        depth: int,
        *,
        source_cap: int,
        max_nodes: int,
        edge_cap: int,
    ) -> list[dict]:
        walked_data: list[dict] = []
        visited_hops = set()
        for node in source_nodes[:source_cap]:
            if len(walked_data) >= max_nodes:
                break
            node_id = node.get("id")
            if not node_id:
                continue
            current_nodes = [node]
            for step in range(depth):
                next_nodes = []
                for current_node in current_nodes:
                    if len(walked_data) >= max_nodes:
                        break
                    edges = self.adapter.find_edges({"source": current_node["id"]})
                    for edge in edges[:edge_cap]:
                        if len(walked_data) >= max_nodes:
                            break
                        edge_rel = (
                            edge.get("data", {}).get("relation_type")
                            or edge.get("data", {}).get("relationship_name")
                            or ""
                        )
                        canonical_edge_rel = self._canonicalize_relation_token(edge_rel)
                        if follow_filters and canonical_edge_rel not in follow_filters:
                            continue
                        target_nodes = self.adapter.find_nodes({"id_filter": edge["target"]})
                        if not target_nodes:
                            continue
                        target_node = target_nodes[0]
                        target_id = target_node["id"]
                        hop_key = (current_node["id"], target_id, step + 1, canonical_edge_rel)
                        if hop_key in visited_hops:
                            continue
                        visited_hops.add(hop_key)
                        enriched_target = {
                            **target_node,
                            "src_id": current_node["id"],
                            "tgt_id": target_id,
                            "data": {
                                **target_node.get("data", {}),
                                "src_id": current_node["id"],
                                "tgt_id": target_id,
                                "relation_type": edge_rel,
                                "path_depth": step + 1,
                            },
                        }
                        next_nodes.append(enriched_target)
                current_nodes = next_nodes
            walked_data.extend(current_nodes)
        return walked_data

    @staticmethod
    def _normalize_follow_types(follow_types: str) -> list[str]:
        text = (follow_types or "").strip()
        if not text or text.lower() in {"*", "all", "any"}:
            return []
        if "=" in text:
            key, value = text.split("=", 1)
            if key.strip().lower() in {"relation_type", "relationship_name"}:
                text = value
        return [
            GraphNavHandler._canonicalize_relation_token(part)
            for part in text.split(",")
            if part.strip()
        ]

    @staticmethod
    def _canonicalize_relation_token(text: str) -> str:
        raw = str(text or "").strip().strip('"').strip("'").lower()
        raw = re.sub(r"[\s\-\/]+", "_", raw)
        raw = re.sub(r"__+", "_", raw)
        return raw
    
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
