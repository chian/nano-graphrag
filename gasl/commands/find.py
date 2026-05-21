"""
FIND command handler.
"""

import re
from typing import Any, List
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..adapters.base import GraphAdapter
from ..search_refinement_agent import LLMSearchRefinementAgent
from ..state_manager import StateManager
from ..contracts import make_contract


class FindHandler(CommandHandler):
    """Handles FIND commands for graph traversal."""
    PATH_PROBE_PAIR_BUDGET = 120
    PATH_POST_PROBE_SIZE = 20
    
    def __init__(self, state_store, context_store, adapter: GraphAdapter, llm_func=None, state_manager=None):
        super().__init__(state_store, context_store)
        self.adapter = adapter
        self.search_refinement_agent = LLMSearchRefinementAgent(llm_func)
        self.state_manager = state_manager or StateManager(state_store, context_store)
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "FIND"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute FIND command."""
        try:
            args = command.args
            target = args["target"]  # nodes, edges, paths
            criteria = args["criteria"]
            
            # Parse criteria to extract filters
            filters = self._parse_criteria(criteria)
            
            strategy = "default"
            diagnostics = {}
            # Execute based on target type
            if target == "nodes":
                result = self.adapter.find_nodes(filters)
            elif target == "edges":
                result = self.adapter.find_edges(filters)
            elif target == "paths":
                result = self._find_paths_with_refinement(command, filters)
                strategy = filters.get("_strategy", "adapter_find_paths")
                diagnostics = filters.get("_refinement", {})
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown target type: {target}"
                )
            
            result_contract = make_contract(
                payload_kind=target,
                data=result,
                label_field="data.entity_name" if target == "nodes" else "id",
                scope="current_rows_only",
                usable_by=["PROCESS", "GRAPHWALK", "AGGREGATE", "SHOW", "SELECT"],
                confidence=0.95,
                grain_type="node" if target == "nodes" else ("edge" if target == "edges" else "path"),
                grain_keys=["id"] if target == "nodes" else (["src_id", "tgt_id", "relation_type"] if target == "edges" else ["path"]),
                multiplicity_preserved=True,
            )
            if strategy != "default":
                result_contract["notes"] = [f"retrieval_strategy: {strategy}"]
            if diagnostics:
                result_contract["refinement"] = diagnostics
            # Store result using centralized state manager
            result_key = f"find_{target}_{len(self.context_store.keys())}"
            self.state_manager.store_variable_data(result_key, result, store_in_state=False, store_in_context=True, contract=result_contract)
            
            # Also store as last_nodes_result for compatibility
            self.state_manager.store_variable_data("last_nodes_result", result, store_in_state=False, store_in_context=True, contract=result_contract)
            
            # Store with user-specified variable name if AS clause was used
            if "result_var" in args and args["result_var"]:
                self.state_manager.store_variable_data(
                    args["result_var"], 
                    result, 
                    store_in_state=True,  # Store in state for persistence
                    store_in_context=True,
                    description=f"Nodes found with criteria: {criteria}",
                    contract=result_contract,
                )
                print(f"DEBUG: FIND - Saved result to variable: {args['result_var']}")
            
            # Create provenance
            provenance = [
                self._create_provenance(
                    source_id="graph-adapter",
                    method="find",
                    target=target,
                    criteria=criteria,
                    filters=filters
                )
            ]
            
            # More meaningful status based on actual results
            if not result:
                status = "empty"
                count = 0
            elif isinstance(result, list) and len(result) == 0:
                status = "empty" 
                count = 0
            else:
                status = "success"
                count = len(result) if isinstance(result, list) else (1 if result else 0)
            
            # Create initial result
            result_obj = self._create_result(
                command=command,
                status=status,
                data=result,
                count=count,
                provenance=provenance,
                contract=result_contract,
            )
            
            return result_obj
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _parse_criteria(self, criteria: str) -> dict:
        """Parse criteria string into filter dictionary - bulletproof version."""
        print(f"DEBUG: Parsing criteria: '{criteria}'")
        filters = {}
        
        # Clean up the criteria string
        criteria = criteria.strip().rstrip(';')
        
        # Path-style semantics: source entity_type=X edge relation_type=R target entity_type=Y
        source_match = re.search(r"source\s+entity_type\s*=\s*['\"]?([A-Z_]+)['\"]?", criteria, re.IGNORECASE)
        target_match = re.search(r"target\s+entity_type\s*=\s*['\"]?([A-Z_]+)['\"]?", criteria, re.IGNORECASE)
        relation_match = re.search(r"edge\s+relation_type\s*=\s*['\"]?([A-Z_]+)['\"]?", criteria, re.IGNORECASE)
        if source_match:
            filters["source_filter"] = {"entity_type": f"\"{source_match.group(1).strip()}\""}
        if target_match:
            filters["target_filter"] = {"entity_type": f"\"{target_match.group(1).strip()}\""}
        if relation_match:
            filters["relation_type"] = relation_match.group(1).strip()

        # Entity type parsing - handle any variation of quotes, spaces, etc.
        if "entity_type" in criteria.lower():
            # Handle OR conditions by splitting on OR and processing each part
            if " OR " in criteria.upper():
                # Split on OR and process each part
                parts = re.split(r'\s+OR\s+', criteria, flags=re.IGNORECASE)
                entity_types = []
                for part in parts:
                    # Match: entity_type=PERSON, entity_type="PERSON", entity_type='PERSON', entity_type = PERSON, etc.
                    patterns = [
                        r"entity_type\s*=\s*['\"]?([A-Z_]+)['\"]?",  # entity_type=PERSON or entity_type="PERSON" or entity_type="RESISTANCE MECHANISM"
                        r"entity_type\s*:\s*['\"]?([A-Z_]+)['\"]?",  # entity_type: PERSON
                        r"entity_type\s+['\"]?([A-Z_]+)['\"]?",      # entity_type PERSON
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, part, re.IGNORECASE)
                        if match:
                            entity_type = match.group(1).strip()
                            entity_types.append(f'"{entity_type}"')
                            print(f"DEBUG: Extracted entity_type from OR part: '{entity_type}' -> '\"{entity_type}\"'")
                            break
                
                if entity_types:
                    filters["entity_type"] = entity_types
                    print(f"DEBUG: Final entity_types: {entity_types}")
            else:
                # Single entity type (no OR)
                patterns = [
                    r"entity_type\s*=\s*['\"]?([A-Z_]+)['\"]?",  # entity_type=PERSON or entity_type="PERSON" or entity_type="RESISTANCE MECHANISM"
                    r"entity_type\s*:\s*['\"]?([A-Z_]+)['\"]?",  # entity_type: PERSON
                    r"entity_type\s+['\"]?([A-Z_]+)['\"]?",      # entity_type PERSON
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, criteria, re.IGNORECASE)
                    if match:
                        entity_type = match.group(1).strip()
                        # Always store with double quotes to match data format
                        filters["entity_type"] = f'"{entity_type}"'
                        print(f"DEBUG: Extracted entity_type: '{entity_type}' -> '{filters['entity_type']}'")
                        break
        
        # Relationship name parsing
        if "relationship_name" in criteria.lower():
            patterns = [
                r"relationship_name\s*=\s*['\"]?([A-Z_]+)['\"]?",
                r"relationship_name\s*:\s*['\"]?([A-Z_]+)['\"]?",
                r"relationship_name\s+['\"]?([A-Z_]+)['\"]?",
            ]
            
            for pattern in patterns:
                match = re.search(pattern, criteria, re.IGNORECASE)
                if match:
                    rel_name = match.group(1).strip()
                    filters["relationship_name"] = f'"{rel_name}"'
                    print(f"DEBUG: Extracted relationship_name: '{rel_name}' -> '{filters['relationship_name']}'")
                    break
        
        # Description contains parsing
        if "description" in criteria.lower() and "contains" in criteria.lower():
            patterns = [
                r"description\s+contains\s+['\"]([^'\"]*)['\"]",
                r"description\s*:\s*contains\s+['\"]([^'\"]*)['\"]",
                r"description\s*=\s*contains\s+['\"]([^'\"]*)['\"]",
            ]
            
            for pattern in patterns:
                match = re.search(pattern, criteria, re.IGNORECASE)
                if match:
                    desc_text = match.group(1).strip()
                    filters["description_contains"] = desc_text
                    print(f"DEBUG: Extracted description_contains: '{desc_text}'")
                    break
        
        # Store raw criteria for fallback matching
        filters["raw_criteria"] = criteria
        
        print(f"DEBUG: Final filters: {filters}")
        return filters

    def _clean_type(self, value: str | None) -> str:
        return str(value or "").strip('"').strip("'").strip()

    def _find_paths_with_refinement(self, command: Command, filters: dict) -> list[dict]:
        initial_filters = dict(filters)
        initial_filters["_max_results"] = self.PATH_POST_PROBE_SIZE
        initial_filters["_max_pairs"] = self.PATH_PROBE_PAIR_BUDGET
        initial_rows = list(self.adapter.iter_paths(initial_filters))
        refinement = self.search_refinement_agent.get_find_refinement(command.args, iter(initial_rows))
        filters["_refinement"] = {"refinement": refinement, "sample_size": len(initial_rows)}

        if refinement.get("refinement_hint", "keep") == "keep":
            filters["_strategy"] = "refinement_keep"
            full_filters = dict(filters)
            full_filters["_max_results"] = self.adapter.capabilities.max_results
            return self.adapter.find_paths(full_filters)

        if filters.get("source_filter") and filters.get("target_filter") and filters.get("relation_type"):
            filters["_strategy"] = "refinement_tighten_strict_relation"
            full_filters = dict(filters)
            full_filters["_max_results"] = self.adapter.capabilities.max_results
            full_filters["_max_pairs"] = 0
            return self._strict_relation_paths(full_filters, source_limit=None, max_results=self.adapter.capabilities.max_results)

        filters["_strategy"] = "refinement_no_tightening_available"
        return initial_rows

    def _strict_relation_paths(self, filters: dict, *, source_limit: int | None, max_results: int) -> list[dict]:
        source_nodes = self.adapter.find_nodes(filters["source_filter"])
        target_nodes = self.adapter.find_nodes(filters["target_filter"])
        target_ids = {row["id"] for row in target_nodes}
        selected_sources = source_nodes[:source_limit] if source_limit else source_nodes
        source_ids = {row["id"] for row in selected_sources}
        relation_type = filters.get("relation_type", "")
        if not source_ids or not target_ids or not relation_type:
            return []
        matched = []
        for edge in self.adapter.find_edges({"relation_type": relation_type}):
            if edge["source"] in source_ids and edge["target"] in target_ids:
                matched.append(
                    {
                        "source": edge["source"],
                        "target": edge["target"],
                        "path": [edge["source"], edge["target"]],
                        "length": 1,
                        "type": "path",
                        "relation_type": relation_type,
                    }
                )
                if len(matched) >= max_results:
                    break
        return matched
