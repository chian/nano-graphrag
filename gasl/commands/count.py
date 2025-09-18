"""
COUNT command handler.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class CountHandler(CommandHandler):
    """Handles COUNT commands for counting field values."""
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "COUNT"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute COUNT command."""
        try:
            args = command.args
            source = args.get("source")  # Could be a variable or "FIND"
            field_name = args["field_name"]
            condition = args.get("condition", "all")
            group_by = args.get("group_by")
            unique = args.get("unique", False)
            result_var = args["result_var"]
            
            print(f"DEBUG: COUNT - source: {source}, field: {field_name}, condition: {condition}, group_by: {group_by}, unique: {unique}")
            
            # Get data to count
            if source == "FIND":
                # This is a direct graph query
                find_criteria = args.get("criteria", "")
                data = self._execute_find_query(find_criteria)
            else:
                # This is counting from existing variable
                data = self._get_variable_data(source)
            
            if not data:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"No data found for counting"
                )
            
            # Apply condition filter if specified
            if condition != "all":
                data = self._apply_condition_filter(data, condition)
            
            # Perform counting
            if group_by:
                result = self._count_with_grouping(data, field_name, group_by, unique)
            else:
                result = self._count_field_values(data, field_name, unique)
            
            # Store result
            self._store_count_result(result_var, result)
            
            print(f"DEBUG: COUNT - created {len(result)} count entries")
            
            return self._create_result(
                command=command,
                status="success",
                data=result,
                count=len(result),
                provenance=[self._create_provenance("count", "count",
                                                 field=field_name, condition=condition,
                                                 group_by=group_by, unique=unique)]
            )
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _execute_find_query(self, criteria: str) -> List[Dict]:
        """Execute a FIND query and return results."""
        # This would integrate with the graph adapter
        # For now, return empty list - this would need to be implemented
        return []
    
    def _get_variable_data(self, variable_name: str) -> List[Dict]:
        """Get data from state or context variable."""
        # Handle special context variables like [last_nodes_result]
        if variable_name.startswith('[') and variable_name.endswith(']'):
            context_var = variable_name[1:-1]  # Remove brackets
            if self.context_store.has(context_var):
                data = self.context_store.get(context_var)
                return data if isinstance(data, list) else [data]
        
        # Try context first
        if self.context_store.has(variable_name):
            data = self.context_store.get(variable_name)
            return data if isinstance(data, list) else [data]
        
        # Try state
        if self.state_store.has_variable(variable_name):
            var_data = self.state_store.get_variable(variable_name)
            if isinstance(var_data, dict) and "items" in var_data:
                return var_data["items"]
            else:
                return var_data if isinstance(var_data, list) else [var_data]
        
        return []
    
    def _apply_condition_filter(self, data: List[Dict], condition: str) -> List[Dict]:
        """Apply condition filter to data."""
        if condition == "all":
            return data
        
        filtered = []
        for item in data:
            if self._item_matches_condition(item, condition):
                filtered.append(item)
        
        return filtered
    
    def _item_matches_condition(self, item: Dict, condition: str) -> bool:
        """Check if item matches condition."""
        # Simple condition parsing - can be enhanced
        if " contains " in condition:
            field, value = condition.split(" contains ", 1)
            field_value = self._get_nested_field(item, field.strip())
            return value.strip().lower() in str(field_value).lower()
        elif " = " in condition:
            field, value = condition.split(" = ", 1)
            field_value = self._get_nested_field(item, field.strip())
            return str(field_value) == value.strip()
        elif " != " in condition:
            field, value = condition.split(" != ", 1)
            field_value = self._get_nested_field(item, field.strip())
            return str(field_value) != value.strip()
        
        return True
    
    def _count_field_values(self, data: List[Dict], field_name: str, unique: bool) -> List[Dict]:
        """Count occurrences of field values."""
        counts = {}
        
        for item in data:
            value = self._get_nested_field(item, field_name)
            if value is not None:
                value_str = str(value)
                if unique:
                    # Count unique items with this field value
                    counts[value_str] = counts.get(value_str, 0) + 1
                else:
                    # Count all occurrences
                    counts[value_str] = counts.get(value_str, 0) + 1
        
        # Convert to list format
        result = []
        for value, count in counts.items():
            result.append({
                "value": value,
                "count": count,
                "field": field_name
            })
        
        return sorted(result, key=lambda x: x["count"], reverse=True)
    
    def _count_with_grouping(self, data: List[Dict], field_name: str, group_by: str, unique: bool) -> List[Dict]:
        """Count field values grouped by another field."""
        groups = {}
        
        for item in data:
            group_value = self._get_nested_field(item, group_by)
            field_value = self._get_nested_field(item, field_name)
            
            if group_value is not None and field_value is not None:
                group_key = str(group_value)
                field_key = str(field_value)
                
                if group_key not in groups:
                    groups[group_key] = {}
                
                if unique:
                    groups[group_key][field_key] = groups[group_key].get(field_key, 0) + 1
                else:
                    groups[group_key][field_key] = groups[group_key].get(field_key, 0) + 1
        
        # Convert to list format
        result = []
        for group_value, field_counts in groups.items():
            for field_value, count in field_counts.items():
                result.append({
                    "group": group_value,
                    "value": field_value,
                    "count": count,
                    "field": field_name,
                    "group_by": group_by
                })
        
        return sorted(result, key=lambda x: (x["group"], x["count"]), reverse=True)
    
    def _get_nested_field(self, item: Dict, field_path: str) -> Any:
        """Get nested field value using dot notation."""
        if not field_path:
            return None
        
        keys = field_path.split('.')
        value = item
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        
        return value
    
    def _store_count_result(self, result_var: str, result: List[Dict]) -> None:
        """Store count result in variable."""
        # Check if target variable exists in state store
        if self.state_store.has_variable(result_var):
            var_data = self.state_store.get_variable(result_var)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = result
                self.state_store._save_state()
            else:
                self.state_store.update_variable(result_var, result)
        else:
            # Store in context store if not in state
            self.context_store.set(result_var, result)
