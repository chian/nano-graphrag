"""
FIND command handler.
"""

from typing import Any, List
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..adapters.base import GraphAdapter


class FindHandler(CommandHandler):
    """Handles FIND commands for graph traversal."""
    
    def __init__(self, state_store, context_store, adapter: GraphAdapter):
        super().__init__(state_store, context_store)
        self.adapter = adapter
    
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
            
            # Store result in context
            result_key = f"find_{target}_{len(self.context_store.keys())}"
            self.context_store.set(result_key, result)
            # Also store as last_nodes_result for compatibility
            self.context_store.set("last_nodes_result", result)
            
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
            
            status = "success" if result else "empty"
            count = len(result) if isinstance(result, list) else (1 if result else 0)
            
            return self._create_result(
                command=command,
                status=status,
                data=result,
                count=count,
                provenance=provenance
            )
            
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
            # Match: entity_type=PERSON, entity_type="PERSON", entity_type='PERSON', entity_type = PERSON, etc.
            patterns = [
                r"entity_type\s*=\s*['\"]?([A-Z_]+)['\"]?",  # entity_type=PERSON or entity_type="PERSON"
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
