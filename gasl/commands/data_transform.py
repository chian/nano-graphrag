"""
Data Transformation command handlers.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class DataTransformHandler(CommandHandler):
    """Handles data transformation commands: TRANSFORM, RESHAPE, AGGREGATE, PIVOT."""
    
    def __init__(self, state_store, context_store, llm_func=None):
        super().__init__(state_store, context_store)
        self.llm_func = llm_func
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type in ["TRANSFORM", "RESHAPE", "AGGREGATE", "PIVOT"]
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute data transformation command."""
        try:
            if command.command_type == "TRANSFORM":
                return self._execute_transform(command)
            elif command.command_type == "RESHAPE":
                return self._execute_reshape(command)
            elif command.command_type == "AGGREGATE":
                return self._execute_aggregate(command)
            elif command.command_type == "PIVOT":
                return self._execute_pivot(command)
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown data transformation command: {command.command_type}"
                )
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _execute_transform(self, command: Command) -> ExecutionResult:
        """Execute TRANSFORM command using LLM."""
        args = command.args
        variable = args["variable"]
        instruction = args["instruction"]
        
        print(f"DEBUG: TRANSFORM - variable: {variable}, instruction: {instruction}")
        
        # Get data to transform
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        if not self.llm_func:
            return self._create_result(command=command, status="error",
                                     error_message="LLM function not available for TRANSFORM command")
        
        # Create prompt for LLM transformation
        prompt = self._create_transform_prompt(data, instruction)
        
        # Call LLM
        llm_response = self.llm_func.call(prompt)
        print(f"DEBUG: TRANSFORM - LLM Response:\n{llm_response}\n")
        
        # Parse LLM response
        try:
            import json
            transformed_result = json.loads(llm_response)
            transformed_data = transformed_result.get("transformed_data", [])
            
            # Update the state variable with transformed results
            if self.state_store.has_variable(variable):
                var_data = self.state_store.get_variable(variable)
                if isinstance(var_data, dict) and "items" in var_data:
                    var_data["items"] = transformed_data
                    self.state_store._save_state()
                    print(f"DEBUG: TRANSFORM - Updated {variable} with {len(transformed_data)} transformed items")
            
            return self._create_result(
                command=command,
                status="success",
                data=transformed_data,
                count=len(transformed_data),
                provenance=[self._create_provenance("transform", "transform",
                                                   variable=variable, instruction=instruction)]
            )
            
        except json.JSONDecodeError:
            return self._create_result(command=command, status="error",
                                     error_message="Failed to parse LLM response as JSON")
    
    def _execute_reshape(self, command: Command) -> ExecutionResult:
        """Execute RESHAPE command."""
        args = command.args
        variable = args["variable"]
        from_format = args["from_format"]
        to_format = args["to_format"]
        
        print(f"DEBUG: RESHAPE - variable: {variable}, from: {from_format}, to: {to_format}")
        
        # Get data to reshape
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        # Perform reshape operation
        reshaped_data = []
        
        if from_format == "list" and to_format == "dict":
            # Convert list to dictionary using ID as key
            reshaped_data = {}
            for item in data:
                key = item.get("id", f"item_{len(reshaped_data)}")
                reshaped_data[key] = item
        
        elif from_format == "dict" and to_format == "list":
            # Convert dictionary to list
            if isinstance(data, dict):
                reshaped_data = list(data.values())
            else:
                reshaped_data = data
        
        elif from_format == "flat" and to_format == "hierarchical":
            # Group items by a field to create hierarchy
            hierarchy = {}
            for item in data:
                group_key = item.get("entity_type", "unknown")
                if group_key not in hierarchy:
                    hierarchy[group_key] = []
                hierarchy[group_key].append(item)
            reshaped_data = hierarchy
        
        else:
            return self._create_result(command=command, status="error",
                                     error_message=f"Unsupported reshape from {from_format} to {to_format}")
        
        # Update the state variable
        if self.state_store.has_variable(variable):
            var_data = self.state_store.get_variable(variable)
            if to_format == "list" and isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = reshaped_data
            else:
                # Replace entire variable data
                var_data.clear()
                if isinstance(reshaped_data, dict):
                    var_data.update(reshaped_data)
                else:
                    var_data["items"] = reshaped_data
            self.state_store._save_state()
        
        count = len(reshaped_data) if isinstance(reshaped_data, (list, dict)) else 1
        print(f"DEBUG: RESHAPE - reshaped {len(data)} items to {count} items")
        
        return self._create_result(
            command=command,
            status="success",
            data=reshaped_data,
            count=count,
            provenance=[self._create_provenance("reshape", "reshape",
                                               variable=variable, from_format=from_format, to_format=to_format)]
        )
    
    def _execute_aggregate(self, command: Command) -> ExecutionResult:
        """Execute AGGREGATE command."""
        args = command.args
        variable = args["variable"]
        by_field = args["by_field"]
        operation = args["operation"]  # sum, count, avg, min, max
        
        print(f"DEBUG: AGGREGATE - variable: {variable}, by: {by_field}, operation: {operation}")
        
        # Get data to aggregate
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        # Perform aggregation
        aggregated_data = {}
        group_counter = 0
        
        for item in data:
            group_key = self._get_nested_field(item, by_field)
            if group_key is None:
                group_key = "unknown"
            
            if group_key not in aggregated_data:
                group_counter += 1
                aggregated_data[group_key] = {
                    "group_id": f"group_{group_counter}",
                    "group_name": str(group_key),
                    "group_key": group_key,
                    "items": [],
                    "item_ids": [],
                    "count": 0
                }
            
            # Add item ID to tracking
            item_id = item.get("id", f"item_{len(aggregated_data[group_key]['items'])}")
            aggregated_data[group_key]["item_ids"].append(item_id)
            aggregated_data[group_key]["items"].append(item)
            aggregated_data[group_key]["count"] += 1
        
        # Apply operation
        for group_key, group_data in aggregated_data.items():
            if operation == "count":
                group_data["result"] = group_data["count"]
            elif operation == "sum":
                # Sum numeric fields
                total = 0
                for item in group_data["items"]:
                    for key, value in item.items():
                        if isinstance(value, (int, float)):
                            total += value
                group_data["result"] = total
            elif operation == "avg":
                # Average of counts or numeric fields
                group_data["result"] = group_data["count"] / len(group_data["items"]) if group_data["items"] else 0
        
        # Convert to list format
        result_list = list(aggregated_data.values())
        
        # Store aggregated results
        if self.state_store.has_variable(variable):
            # Update existing state variable
            var_data = self.state_store.get_variable(variable)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = result_list
                self.state_store._save_state()
                print(f"DEBUG: AGGREGATE - Updated state variable {variable} with {len(result_list)} groups")
            else:
                # If it's not a LIST type, update it directly
                self.state_store.update_variable(variable, result_list)
                print(f"DEBUG: AGGREGATE - Updated state variable {variable} directly with {len(result_list)} groups")
        else:
            # Store in context store if source variable is in context
            self.context_store.set(variable, result_list)
            print(f"DEBUG: AGGREGATE - Stored {len(result_list)} groups in context as {variable}")
        
        # Also store as last_aggregate_result for consistency
        self.context_store.set("last_aggregate_result", result_list)
        print(f"DEBUG: AGGREGATE - Also stored as last_aggregate_result with {len(result_list)} groups")
        
        print(f"DEBUG: AGGREGATE - created {len(result_list)} aggregated groups")
        
        return self._create_result(
            command=command,
            status="success",
            data=result_list,
            count=len(result_list),
            provenance=[self._create_provenance("aggregate", "aggregate",
                                               variable=variable, by_field=by_field, operation=operation)]
        )
    
    def _execute_pivot(self, command: Command) -> ExecutionResult:
        """Execute PIVOT command."""
        args = command.args
        variable = args["variable"]
        pivot_field = args["pivot_field"]
        value_field = args["value_field"]
        
        print(f"DEBUG: PIVOT - variable: {variable}, pivot: {pivot_field}, value: {value_field}")
        
        # Get data to pivot
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        # Perform pivot operation
        pivot_result = {}
        pivot_columns = set()
        
        # First pass: collect all pivot values
        for item in data:
            pivot_value = self._get_nested_field(item, pivot_field)
            if pivot_value:
                pivot_columns.add(str(pivot_value))
        
        # Second pass: create pivoted structure
        for item in data:
            row_key = item.get("id", f"row_{len(pivot_result)}")
            if row_key not in pivot_result:
                pivot_result[row_key] = {**item}  # Copy original item
                # Initialize pivot columns
                for col in pivot_columns:
                    pivot_result[row_key][f"pivot_{col}"] = None
            
            pivot_value = str(self._get_nested_field(item, pivot_field))
            value = self._get_nested_field(item, value_field)
            if pivot_value and pivot_value in pivot_columns:
                pivot_result[row_key][f"pivot_{pivot_value}"] = value
        
        # Convert to list
        pivoted_list = list(pivot_result.values())
        
        # Update variable
        if self.state_store.has_variable(variable):
            var_data = self.state_store.get_variable(variable)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = pivoted_list
                self.state_store._save_state()
        
        print(f"DEBUG: PIVOT - created {len(pivoted_list)} pivoted rows with {len(pivot_columns)} pivot columns")
        
        return self._create_result(
            command=command,
            status="success",
            data=pivoted_list,
            count=len(pivoted_list),
            provenance=[self._create_provenance("pivot", "pivot",
                                               variable=variable, pivot_field=pivot_field, value_field=value_field)]
        )
    
    def _create_transform_prompt(self, data: Any, instruction: str) -> str:
        """Create prompt for LLM transformation."""
        prompt = f"""You are transforming data according to this instruction: {instruction}

Data to transform:
{self._format_data_for_llm(data)}

Instructions:
1. Transform the data according to the instruction
2. Maintain the original structure but modify/enhance as requested
3. Return your results as a JSON object with this structure:
{{
  "transformed_data": [
    // Array of transformed items
  ],
  "transformation_summary": {{
    "total_processed": 0,
    "changes_made": "description of changes",
    "new_fields_added": ["field1", "field2"]
  }}
}}

Apply the transformation consistently to all items.
"""
        return prompt
    
    def _format_data_for_llm(self, data: Any) -> str:
        """Format data for LLM consumption."""
        if not isinstance(data, list):
            return str(data)
        
        # Limit to first 10 items to avoid token limits
        sample_data = data[:10]
        formatted = []
        
        for i, item in enumerate(sample_data):
            formatted.append(f"Item {i+1}: {item}")
        
        if len(data) > 10:
            formatted.append(f"... and {len(data) - 10} more items")
        
        return "\n".join(formatted)
    
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
    
    def _get_nested_field(self, item: Dict, field_path: str) -> Any:
        """Get nested field value using dot notation."""
        if not field_path:
            return None
        
        fields = field_path.split(".")
        value = item
        for field in fields:
            if isinstance(value, dict) and field in value:
                value = value[field]
            else:
                return None
        return value
