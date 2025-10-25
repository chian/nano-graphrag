"""
ADD_FIELD command handler for GASL system.
"""

from typing import Any, Dict, List
from .base import CommandHandler
from ..types import Command, ExecutionResult
from ..errors import ExecutionError


class AddFieldHandler(CommandHandler):
    """Handler for ADD_FIELD command."""
    
    def __init__(self, state_store, context_store, llm_func=None, state_manager=None):
        super().__init__(state_store, context_store, state_manager)
        self.llm_func = llm_func
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "ADD_FIELD"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute ADD_FIELD command."""
        args = command.args
        variable_name = args.get("variable")
        field_name = args.get("field_name")
        source_variable = args.get("source_variable")
        
        if not variable_name or not field_name or not source_variable:
            raise ExecutionError("ADD_FIELD requires variable, field_name, and source_variable")
        
        # Get the target variable
        target_var = self.state_store.get_variable(variable_name)
        if not target_var:
            raise ExecutionError(f"Variable {variable_name} not found")
        
        # Get the source data
        source_data = self.context_store.get(source_variable)
        if source_data is None:
            # Try state store
            source_data = self.state_store.get_variable(source_variable)
            if source_data:
                source_data = source_data.get("value")
        
        if source_data is None:
            raise ExecutionError(f"Source variable {source_variable} not found")
        
        # Add field to each item in the target variable
        target_value = target_var.get("value", [])
        if not isinstance(target_value, list):
            raise ExecutionError(f"ADD_FIELD can only be applied to LIST variables, got {type(target_value)}")
        
        source_list = source_data if isinstance(source_data, list) else [source_data]
        
        if len(target_value) != len(source_list):
            raise ExecutionError(f"Target variable has {len(target_value)} items but source has {len(source_list)} items")
        
        # Add field to each item
        for i, item in enumerate(target_value):
            if isinstance(item, dict):
                item[field_name] = source_list[i]
            else:
                # Convert to dict if needed
                target_value[i] = {"value": item, field_name: source_list[i]}
        
        # Update the variable
        self.state_store.set_variable(variable_name, target_value, target_var.get("type", "LIST"))
        
        # Add field metadata
        description = f"Field {field_name} added from {source_variable}"
        actual_field_name = self.state_store.add_field_metadata(
            variable_name, 
            field_name, 
            description, 
            f"ADD_FIELD from {source_variable}"
        )
        
        return self._create_result(
            command=command,
            status="success",
            data={"field_name": actual_field_name, "items_updated": len(target_value)},
            count=len(target_value)
        )
