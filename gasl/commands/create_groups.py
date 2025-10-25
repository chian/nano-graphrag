"""
CREATE_GROUPS command handler for GASL system.
"""

from typing import Any, Dict, List
from .base import CommandHandler
from ..types import Command, ExecutionResult
from ..errors import ExecutionError


class CreateGroupsHandler(CommandHandler):
    """Handler for CREATE_GROUPS command."""
    
    def __init__(self, state_store, context_store, adapter, llm_func=None, state_manager=None):
        super().__init__(state_store, context_store, state_manager)
        self.adapter = adapter
        self.llm_func = llm_func
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "CREATE_GROUPS"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute CREATE_GROUPS command."""
        args = command.args
        source_variable = args.get("source_variable")
        spec = args.get("spec")
        
        if not source_variable:
            raise ExecutionError("CREATE_GROUPS requires source_variable")
        
        # Get the source data
        source_data = self.context_store.get(source_variable)
        if source_data is None:
            # Try state store
            source_var = self.state_store.get_variable(source_variable)
            if source_var:
                source_data = source_var.get("value")
        
        if source_data is None:
            raise ExecutionError(f"Source variable {source_variable} not found")
        
        # Parse spec to determine group properties
        group_type = "GROUP"
        properties = {}
        
        if spec:
            # Parse spec like "type: AUTHOR_GROUP with properties: count, members"
            if "type:" in spec:
                type_part = spec.split("type:")[1].split("with")[0].strip()
                group_type = type_part
            
            if "properties:" in spec:
                props_part = spec.split("properties:")[1].strip()
                properties = {prop.strip(): None for prop in props_part.split(",")}
        
        # Create group nodes from source data
        created_groups = []
        
        if isinstance(source_data, list):
            for i, group in enumerate(source_data):
                group_id = f"created_group_{i}"
                group_data = {
                    "id": group_id,
                    "type": group_type,
                    "properties": properties.copy()
                }
                
                # Map group data to group properties
                if isinstance(group, dict):
                    # Handle different group formats
                    if "group_key" in group:
                        # AGGREGATE result format
                        group_data["properties"]["group_key"] = group.get("group_key")
                        group_data["properties"]["count"] = group.get("count", 0)
                        group_data["properties"]["items"] = group.get("items", [])
                    elif "key" in group:
                        # Simple group format
                        group_data["properties"]["key"] = group.get("key")
                        group_data["properties"]["value"] = group.get("value")
                    else:
                        # Generic dict mapping
                        for key, value in group.items():
                            if key in properties:
                                group_data["properties"][key] = value
                            else:
                                group_data["properties"][key] = value
                else:
                    # If group is not a dict, store as 'value' property
                    group_data["properties"]["value"] = group
                
                # Add to graph via adapter
                if self.adapter:
                    self.adapter.add_node(group_id, group_data)
                
                created_groups.append(group_data)
        
        else:
            # Single group
            group_id = "created_group_0"
            group_data = {
                "id": group_id,
                "type": group_type,
                "properties": properties.copy()
            }
            
            if isinstance(source_data, dict):
                if "group_key" in source_data:
                    group_data["properties"]["group_key"] = source_data.get("group_key")
                    group_data["properties"]["count"] = source_data.get("count", 0)
                    group_data["properties"]["items"] = source_data.get("items", [])
                else:
                    for key, value in source_data.items():
                        if key in properties:
                            group_data["properties"][key] = value
                        else:
                            group_data["properties"][key] = value
            else:
                group_data["properties"]["value"] = source_data
            
            if self.adapter:
                self.adapter.add_node(group_id, group_data)
            
            created_groups.append(group_data)
        
        # Store created groups in context
        result_var = f"created_groups_{source_variable}"
        self.context_store.set(result_var, created_groups)
        
        return self._create_result(
            command=command,
            status="success",
            data={"groups_created": len(created_groups), "result_variable": result_var, "group_type": group_type},
            count=len(created_groups)
        )
