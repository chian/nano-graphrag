"""
COUNT command handler.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..validation import LLMJudgeValidator
from ..utils import normalize_string


class CountHandler(CommandHandler):
    """Handles COUNT commands for counting field values."""
    
    def __init__(self, state_store, context_store, llm_func=None):
        super().__init__(state_store, context_store)
        self.validator = LLMJudgeValidator(llm_func) if llm_func else None
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "COUNT"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute COUNT command - count items matching condition."""
        try:
            args = command.args
            source = args["source"]
            condition = args.get("condition", "all")
            result_var = args["result_var"]
            
            print(f"DEBUG: COUNT - source: {source}, condition: {condition}")
            
            # Get data to count
            if source == "FIND":
                find_criteria = args.get("criteria", "")
                data = self._execute_find_query(find_criteria)
            else:
                data = self._get_variable_data(source)
            
            if not data:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"No data found for counting"
                )
            
            # Apply condition filter if specified
            if condition != "all":
                print(f"DEBUG: COUNT - Before filtering: {len(data)} items")
                if data and len(data) > 0:
                    print(f"DEBUG: COUNT - Sample item keys: {list(data[0].keys()) if isinstance(data[0], dict) else 'not a dict'}")
                data = self._apply_condition_filter(data, condition)
                print(f"DEBUG: COUNT - After filtering: {len(data)} items")
            
            # Count items
            count = len(data)
            
            # Store result
            result = {"count": count, "condition": condition, "source": source}
            self._store_count_result(result_var, result)
            
            print(f"DEBUG: COUNT - counted {count} items")
            
            return self._create_result(
                command=command,
                status="success",
                data=result,
                count=1,
                provenance=[self._create_provenance("count", "count_items",
                                                 source=source, condition=condition)]
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
            if isinstance(var_data, dict) and "value" in var_data:
                return var_data["value"]
            elif isinstance(var_data, dict) and "items" in var_data:
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
        elif " matches " in condition:
            field, pattern = condition.split(" matches ", 1)
            field_value = self._get_nested_field(item, field.strip())
            if field_value is None:
                return False
            
            # Handle regex pattern (remove / delimiters if present)
            pattern = pattern.strip()
            if pattern.startswith('/') and pattern.endswith('/'):
                pattern = pattern[1:-1]
            
            import re
            try:
                return bool(re.match(pattern, str(field_value), re.IGNORECASE))
            except re.error:
                # If regex is invalid, fall back to simple string matching
                return False
        elif " = " in condition:
            field, value = condition.split(" = ", 1)
            field_value = self._get_nested_field(item, field.strip())
            result = normalize_string(str(field_value)) == normalize_string(value.strip())
            print(f"DEBUG: COUNT - Item {item.get('id', 'unknown')}: field '{field.strip()}' = '{field_value}' vs '{value.strip()}' -> {result}")
            return result
        elif " != " in condition:
            field, value = condition.split(" != ", 1)
            field_value = self._get_nested_field(item, field.strip())
            return normalize_string(str(field_value)) != normalize_string(value.strip())
        
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
        """Get nested field value using dot notation with automatic path resolution."""
        if not field_path:
            return None
        
        # First try the exact field path
        keys = field_path.split('.')
        value = item
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                break
        else:
            # If we successfully traversed all keys, return the value
            return value
        
        # If exact path failed, try to find the field in common nested locations
        if '.' not in field_path:
            # Try common nested locations for single field names
            common_paths = [
                f"data.{field_path}",
                f"properties.{field_path}",
                f"attributes.{field_path}",
                field_path  # Try the original path again
            ]
            
            for path in common_paths:
                keys = path.split('.')
                value = item
                
                for key in keys:
                    if isinstance(value, dict) and key in value:
                        value = value[key]
                    else:
                        break
                else:
                    # Found the field, return it
                    return value
        
        return None
    
    def _store_count_result(self, result_var: str, result: List[Dict]) -> None:
        """Store count result in variable."""
        # Create state variable if it doesn't exist
        if not self.state_store.has_variable(result_var):
            self.state_store.declare_variable(result_var, "LIST", f"Count results for {result_var}")
        
        # Store in state
        var_data = self.state_store.get_variable(result_var)
        if isinstance(var_data, dict) and "items" in var_data:
            var_data["items"] = result
            self.state_store._save_state()
        else:
            self.state_store.update_variable(result_var, result)
        
        # Also store in context for immediate access
        self.context_store.set(result_var, result)
        
        print(f"DEBUG: COUNT - stored {len(result)} count entries in {result_var}")
