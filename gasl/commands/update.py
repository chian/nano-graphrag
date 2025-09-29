"""
UPDATE command handler.
"""

from typing import Any, List
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class UpdateHandler(CommandHandler):
    """Handles UPDATE commands for state variable updates."""
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "UPDATE"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute UPDATE command."""
        try:
            args = command.args
            variable = args["variable"]
            instruction = args["instruction"]
            
            print(f"DEBUG: UPDATE - variable: {variable}, instruction: {instruction}")
            
            # Parse instruction to get source data and filter
            # Format: "UPDATE var with source_var where condition"
            # or "UPDATE var with source_var operation: replace"
            import re
            
            # Extract source variable and condition/operation
            # Try format: "source_var operation: replace"
            match = re.search(r"(\w+)\s+operation:\s*(\w+)", instruction, re.IGNORECASE)
            if match:
                source_var = match.group(1)
                operation = match.group(2).lower()
                condition = "all"  # For replace operation, include all items
            else:
                # Try format: "with source_var operation: replace"
                match = re.search(r"with\s+(\w+)\s+operation:\s*(\w+)", instruction, re.IGNORECASE)
                if match:
                    source_var = match.group(1)
                    operation = match.group(2).lower()
                    condition = "all"  # For replace operation, include all items
                else:
                    # Try format: "with source_var where condition"
                    match = re.search(r"with\s+(\w+)\s+where\s+(.+)", instruction, re.IGNORECASE)
                    if not match:
                        # Try format: "source_var where condition" (without "with")
                        match = re.search(r"(\w+)\s+where\s+(.+)", instruction, re.IGNORECASE)
                    
                    if not match:
                        # Try format: "with source_var" or "source_var" (no where clause)
                        match = re.search(r"(?:with\s+)?(\w+)", instruction, re.IGNORECASE)
                        if match:
                            source_var = match.group(1)
                            condition = "all"  # Default to include all items
                            operation = "replace"
                        else:
                            return self._create_result(
                                command=command,
                                status="error",
                                error_message=f"Invalid UPDATE instruction format: {instruction}"
                            )
                    else:
                        source_var = match.group(1)
                        condition = match.group(2).strip()
                        operation = "filter"
            
            print(f"DEBUG: UPDATE - source_var: {source_var}, condition: {condition}, operation: {operation}")
            
            # Get source data from context or state
            source_data = None
            if self.context_store.has(source_var):
                source_data = self.context_store.get(source_var)
                print(f"DEBUG: UPDATE - found source data in context: {len(source_data) if isinstance(source_data, list) else 'not a list'}")
            elif self.state_store.has_variable(source_var):
                var_data = self.state_store.get_variable(source_var)
                if isinstance(var_data, dict) and "items" in var_data:
                    source_data = var_data["items"]
                    print(f"DEBUG: UPDATE - found source data in state: {len(source_data)}")
                else:
                    source_data = var_data
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Source variable {source_var} not found in context or state"
                )
            
            if not isinstance(source_data, list):
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Source data {source_var} is not a list"
                )
            
            # Apply operation based on type
            if operation == "replace":
                # For replace operation, use all data
                filtered_data = source_data
                print(f"DEBUG: UPDATE - replace operation: using all {len(filtered_data)} items")
            else:
                # Apply filter based on condition
                filtered_data = self._apply_filter(source_data, condition)
                print(f"DEBUG: UPDATE - filter operation: filtered {len(source_data)} items to {len(filtered_data)} items")
            
            # Update state variable with filtered data
            # For LIST variables, we need to replace the items, not extend
            if self.state_store.has_variable(variable):
                var_data = self.state_store.get_variable(variable)
                if isinstance(var_data, dict) and "items" in var_data:
                    # Replace the items list
                    var_data["items"] = filtered_data
                    self.state_store._save_state()
                    print(f"DEBUG: UPDATE - replaced items in {variable} with {len(filtered_data)} items")
                else:
                    # Fallback to update_variable
                    self.state_store.update_variable(variable, filtered_data, [])
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Target variable {variable} not found in state"
                )
            
            # Create provenance for update
            update_provenance = [
                self._create_provenance(
                    source_id="gasl-update",
                    method="update_variable",
                    variable=variable,
                    instruction=instruction,
                    source_variable=source_var,
                    condition=condition,
                    filtered_count=len(filtered_data)
                )
            ]
            
            return self._create_result(
                command=command,
                status="success",
                data={"variable": variable, "updated": True, "filtered_count": len(filtered_data)},
                count=len(filtered_data),
                provenance=update_provenance
            )
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _apply_filter(self, data: List[Any], condition: str) -> List[Any]:
        """Apply filter condition to data. UPDATE only supports basic filtering for data modification."""
        import re
        
        # Handle "description contains" condition
        if "description contains" in condition.lower():
            match = re.search(r"description contains ['\"]([^'\"]*)['\"]", condition, re.IGNORECASE)
            if match:
                search_text = match.group(1).lower()
                filtered = []
                for item in data:
                    if isinstance(item, dict):
                        description = item.get("description", "").lower()
                        if search_text in description:
                            filtered.append(item)
                return filtered
        
        # Handle "entity_type contains" condition  
        elif "entity_type contains" in condition.lower():
            match = re.search(r"entity_type contains ['\"]([^'\"]*)['\"]", condition, re.IGNORECASE)
            if match:
                search_text = match.group(1).lower()
                filtered = []
                for item in data:
                    if isinstance(item, dict):
                        entity_type = item.get("entity_type", "").lower()
                        if search_text in entity_type:
                            filtered.append(item)
                return filtered
        
        # Handle "id equals" condition for precise updates
        elif "id equals" in condition.lower():
            match = re.search(r"id equals ['\"]([^'\"]*)['\"]", condition, re.IGNORECASE)
            if match:
                target_id = match.group(1)
                filtered = []
                for item in data:
                    if isinstance(item, dict) and item.get("id") == target_id:
                        filtered.append(item)
                return filtered
        
        # For complex filtering, return error - use PROCESS instead
        else:
            raise ValueError(f"UPDATE command does not support complex filtering: '{condition}'. Use PROCESS command for complex filtering tasks.")
        
        # Default: return all data if no recognized condition
        return data
    
    def _apply_delete(self, data: list, condition: str) -> list:
        """Apply delete operation based on condition."""
        if not isinstance(data, list):
            return data
        
        filtered_data = []
        for item in data:
            if not self._item_matches_condition(item, condition):
                filtered_data.append(item)
        
        return filtered_data
    
    def _apply_merge(self, data: list, condition: str) -> list:
        """Apply merge operation based on condition."""
        # For now, just return the data as-is
        # This could be enhanced to merge items based on criteria
        return data
    
    def _apply_append(self, data: list, condition: str) -> list:
        """Apply append operation based on condition."""
        # For now, just return the data as-is
        # This could be enhanced to append items based on criteria
        return data