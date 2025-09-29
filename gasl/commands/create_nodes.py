"""
CREATE_NODES command handler for GASL system.
"""

from typing import Any, Dict, List
from .base import CommandHandler
from ..types import Command, ExecutionResult
from ..errors import ExecutionError


class CreateNodesHandler(CommandHandler):
    """Handler for CREATE_NODES command."""
    
    def __init__(self, state_store, context_store, adapter, llm_func=None):
        super().__init__(state_store, context_store)
        self.adapter = adapter
        self.llm_func = llm_func
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "CREATE_NODES"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute CREATE_NODES command."""
        args = command.args
        source_variable = args.get("source_variable")
        spec = args.get("spec")
        
        if not source_variable:
            raise ExecutionError("CREATE_NODES requires source_variable")
        
        # Get the source data
        source_data = self.context_store.get(source_variable)
        if source_data is None:
            # Try state store
            source_var = self.state_store.get_variable(source_variable)
            if source_var:
                source_data = source_var.get("value")
        
        if source_data is None:
            raise ExecutionError(f"Source variable {source_variable} not found")
        
        # Parse spec to determine node properties
        node_type = "NODE"
        properties = {}
        
        if spec:
            # Parse spec like "type: AUTHOR with properties: name, frequency"
            if "type:" in spec:
                type_part = spec.split("type:")[1].split("with")[0].strip()
                node_type = type_part
            
            if "properties:" in spec:
                props_part = spec.split("properties:")[1].strip()
                properties = {prop.strip(): None for prop in props_part.split(",")}
        
        # Create nodes from source data
        created_nodes = []
        
        if isinstance(source_data, list):
            for i, item in enumerate(source_data):
                node_id = f"created_node_{i}"
                node_data = {
                    "id": node_id,
                    "type": node_type,
                    "properties": properties.copy()
                }
                
                # Map item data to node properties
                if isinstance(item, dict):
                    for key, value in item.items():
                        if key in properties:
                            node_data["properties"][key] = value
                        else:
                            # Add as additional property
                            node_data["properties"][key] = value
                else:
                    # If item is not a dict, store as 'value' property
                    node_data["properties"]["value"] = item
                
                # Add to graph via adapter
                if self.adapter:
                    self.adapter.add_node(node_id, node_data)
                
                created_nodes.append(node_data)
        
        else:
            # Single item
            node_id = "created_node_0"
            node_data = {
                "id": node_id,
                "type": node_type,
                "properties": properties.copy()
            }
            
            if isinstance(source_data, dict):
                for key, value in source_data.items():
                    if key in properties:
                        node_data["properties"][key] = value
                    else:
                        node_data["properties"][key] = value
            else:
                node_data["properties"]["value"] = source_data
            
            if self.adapter:
                self.adapter.add_node(node_id, node_data)
            
            created_nodes.append(node_data)
        
        # Store created nodes in context
        result_var = f"created_nodes_{source_variable}"
        self.context_store.set(result_var, created_nodes)
        
        return self._create_result(
            command=command,
            status="success",
            data={"nodes_created": len(created_nodes), "result_variable": result_var, "node_type": node_type},
            count=len(created_nodes)
        )
