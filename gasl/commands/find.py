"""
FIND command handler.
"""

from typing import Any, List
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..adapters.base import GraphAdapter
from ..validation import LLMJudgeValidator
from ..state_manager import StateManager


class FindHandler(CommandHandler):
    """Handles FIND commands for graph traversal."""
    
    def __init__(self, state_store, context_store, adapter: GraphAdapter, llm_func=None, state_manager=None):
        super().__init__(state_store, context_store)
        self.adapter = adapter
        self.validator = LLMJudgeValidator(llm_func) if llm_func else None
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
            
            # Execute based on target type
            if target == "nodes":
                result = self.adapter.find_nodes(filters)
            elif target == "edges":
                result = self.adapter.find_edges(filters)
            elif target == "paths":
                result = self.adapter.find_paths(filters)
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown target type: {target}"
                )
            
            # Store result using centralized state manager
            result_key = f"find_{target}_{len(self.context_store.keys())}"
            self.state_manager.store_variable_data(result_key, result, store_in_state=False, store_in_context=True)
            
            # Also store as last_nodes_result for compatibility
            self.state_manager.store_variable_data("last_nodes_result", result, store_in_state=False, store_in_context=True)
            
            # Store with user-specified variable name if AS clause was used
            if "result_var" in args and args["result_var"]:
                self.state_manager.store_variable_data(
                    args["result_var"], 
                    result, 
                    store_in_state=True,  # Store in state for persistence
                    store_in_context=True,
                    description=f"Nodes found with criteria: {criteria}"
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
                provenance=provenance
            )
            
            # Validate with LLM judge if available
            if self.validator and status == "success":
                validation = self.validator.validate_command_success(
                    command.command_type, command.args, result, count
                )
                
                if not validation.get("valid", True):
                    # Override status if LLM judge says it failed
                    result_obj.status = "error"
                    result_obj.error_message = f"LLM Judge Validation Failed: {validation.get('reason', 'Unknown validation failure')}"
                    print(f"DEBUG: FIND - LLM Judge validation failed: {validation}")
                else:
                    print(f"DEBUG: FIND - LLM Judge validation passed: {validation.get('reason', 'Valid')}")
            
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
        
        # Entity type parsing - handle any variation of quotes, spaces, etc.
        if "entity_type" in criteria.lower():
            import re
            # Handle OR conditions by splitting on OR and processing each part
            if " OR " in criteria.upper():
                # Split on OR and process each part
                parts = re.split(r'\s+OR\s+', criteria, flags=re.IGNORECASE)
                entity_types = []
                for part in parts:
                    # Match: entity_type=PERSON, entity_type="PERSON", entity_type='PERSON', entity_type = PERSON, etc.
                    patterns = [
                        r"entity_type\s*=\s*['\"]?([A-Z_\s]+)['\"]?",  # entity_type=PERSON or entity_type="PERSON" or entity_type="RESISTANCE MECHANISM"
                        r"entity_type\s*:\s*['\"]?([A-Z_\s]+)['\"]?",  # entity_type: PERSON
                        r"entity_type\s+['\"]?([A-Z_\s]+)['\"]?",      # entity_type PERSON
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
                    r"entity_type\s*=\s*['\"]?([A-Z_\s]+)['\"]?",  # entity_type=PERSON or entity_type="PERSON" or entity_type="RESISTANCE MECHANISM"
                    r"entity_type\s*:\s*['\"]?([A-Z_\s]+)['\"]?",  # entity_type: PERSON
                    r"entity_type\s+['\"]?([A-Z_\s]+)['\"]?",      # entity_type PERSON
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
            import re
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
            import re
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
