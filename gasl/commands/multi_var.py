"""
Multi-Variable Access command handlers.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class MultiVarHandler(CommandHandler):
    """Handles multi-variable commands: JOIN, MERGE, COMPARE."""
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type in ["JOIN", "MERGE", "COMPARE"]
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute multi-variable command."""
        try:
            if command.command_type == "JOIN":
                return self._execute_join(command)
            elif command.command_type == "MERGE":
                return self._execute_merge(command)
            elif command.command_type == "COMPARE":
                return self._execute_compare(command)
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown multi-variable command: {command.command_type}"
                )
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _execute_join(self, command: Command) -> ExecutionResult:
        """Execute JOIN command."""
        args = command.args
        var1 = args["variable1"]
        var2 = args["variable2"]
        join_field = args["join_field"]
        target_var = args["target_variable"]
        
        print(f"DEBUG: JOIN - {var1} with {var2} on {join_field} as {target_var}")
        
        # Get data from both variables
        data1 = self._get_variable_data(var1)
        data2 = self._get_variable_data(var2)
        
        if not data1 or not data2:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variables {var1} or {var2} not found or empty")
        
        # Perform join operation
        joined_data = []
        for item1 in data1:
            for item2 in data2:
                # Check if join field matches
                if self._fields_match(item1, item2, join_field):
                    # Merge the items
                    joined_item = {**item1}  # Start with item1
                    # Add fields from item2 (with prefix to avoid conflicts)
                    for key, value in item2.items():
                        if key not in joined_item:
                            joined_item[key] = value
                        else:
                            joined_item[f"{var2}_{key}"] = value
                    joined_data.append(joined_item)
        
        # Create or update target variable
        if not self.state_store.has_variable(target_var):
            self.state_store.declare_variable(target_var, "LIST", f"Join result of {var1} and {var2}")
        
        var_data = self.state_store.get_variable(target_var)
        var_data["items"] = joined_data
        self.state_store._save_state()
        
        print(f"DEBUG: JOIN - created {len(joined_data)} joined items in {target_var}")
        
        return self._create_result(
            command=command,
            status="success",
            data=joined_data,
            count=len(joined_data),
            provenance=[self._create_provenance("join", "join",
                                               variable1=var1, variable2=var2, join_field=join_field)]
        )
    
    def _execute_merge(self, command: Command) -> ExecutionResult:
        """Execute MERGE command."""
        args = command.args
        variables = args["variables"]  # List of variable names
        target_var = args["target_variable"]
        
        print(f"DEBUG: MERGE - variables: {variables} as {target_var}")
        
        # Get data from all variables
        all_data = []
        for var_name in variables:
            var_data = self._get_variable_data(var_name)
            if var_data:
                all_data.extend(var_data)
        
        if not all_data:
            return self._create_result(command=command, status="error",
                                     error_message="No data found in specified variables")
        
        # Remove duplicates based on ID if present
        seen_ids = set()
        merged_data = []
        for item in all_data:
            item_id = item.get("id")
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                merged_data.append(item)
            elif not item_id:
                merged_data.append(item)
        
        # Create or update target variable
        if not self.state_store.has_variable(target_var):
            self.state_store.declare_variable(target_var, "LIST", f"Merged data from {', '.join(variables)}")
        
        var_data = self.state_store.get_variable(target_var)
        var_data["items"] = merged_data
        self.state_store._save_state()
        
        print(f"DEBUG: MERGE - merged {len(merged_data)} items from {len(variables)} variables")
        
        return self._create_result(
            command=command,
            status="success",
            data=merged_data,
            count=len(merged_data),
            provenance=[self._create_provenance("merge", "merge", variables=variables)]
        )
    
    def _execute_compare(self, command: Command) -> ExecutionResult:
        """Execute COMPARE command."""
        args = command.args
        var1 = args["variable1"]
        var2 = args["variable2"]
        criteria = args["criteria"]
        target_var = args["target_variable"]
        
        print(f"DEBUG: COMPARE - {var1} with {var2} on {criteria} as {target_var}")
        
        # Get data from both variables
        data1 = self._get_variable_data(var1)
        data2 = self._get_variable_data(var2)
        
        if not data1 or not data2:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variables {var1} or {var2} not found or empty")
        
        # Perform comparison
        comparison_result = {
            "variable1_name": var1,
            "variable2_name": var2,
            "variable1_count": len(data1),
            "variable2_count": len(data2),
            "common_items": [],
            "only_in_var1": [],
            "only_in_var2": [],
            "comparison_criteria": criteria
        }
        
        # Find common items and differences
        ids1 = {item.get("id") for item in data1 if item.get("id")}
        ids2 = {item.get("id") for item in data2 if item.get("id")}
        
        common_ids = ids1.intersection(ids2)
        only_in_1 = ids1 - ids2
        only_in_2 = ids2 - ids1
        
        # Get full data for each category
        for item in data1:
            if item.get("id") in common_ids:
                comparison_result["common_items"].append(item)
            elif item.get("id") in only_in_1:
                comparison_result["only_in_var1"].append(item)
        
        for item in data2:
            if item.get("id") in only_in_2:
                comparison_result["only_in_var2"].append(item)
        
        # Create or update target variable
        if not self.state_store.has_variable(target_var):
            self.state_store.declare_variable(target_var, "DICT", f"Comparison result of {var1} and {var2}")
        
        var_data = self.state_store.get_variable(target_var)
        var_data.update(comparison_result)
        self.state_store._save_state()
        
        print(f"DEBUG: COMPARE - found {len(common_ids)} common, {len(only_in_1)} only in {var1}, {len(only_in_2)} only in {var2}")
        
        return self._create_result(
            command=command,
            status="success",
            data=comparison_result,
            count=len(common_ids) + len(only_in_1) + len(only_in_2),
            provenance=[self._create_provenance("compare", "compare",
                                               variable1=var1, variable2=var2, criteria=criteria)]
        )
    
    def _get_variable_data(self, variable_name: str) -> List[Dict]:
        """Get data from state or context variable."""
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
    
    def _fields_match(self, item1: Dict, item2: Dict, join_field: str) -> bool:
        """Check if join field values match between two items."""
        # Simple field matching - can be enhanced for complex joins
        if join_field == "id":
            return item1.get("id") == item2.get("id")
        elif join_field in item1 and join_field in item2:
            return item1[join_field] == item2[join_field]
        else:
            # Try nested field access
            val1 = self._get_nested_field(item1, join_field)
            val2 = self._get_nested_field(item2, join_field)
            return val1 == val2
    
    def _get_nested_field(self, item: Dict, field_path: str) -> Any:
        """Get nested field value using dot notation."""
        fields = field_path.split(".")
        value = item
        for field in fields:
            if isinstance(value, dict) and field in value:
                value = value[field]
            else:
                return None
        return value
