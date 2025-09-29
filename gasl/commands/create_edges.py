"""
CREATE_EDGES command handler for GASL system.
"""

from typing import Any, Dict, List
from .base import CommandHandler
from ..types import Command, ExecutionResult
from ..errors import ExecutionError


class CreateEdgesHandler(CommandHandler):
    """Handler for CREATE_EDGES command."""
    
    def __init__(self, state_store, context_store, adapter, llm_func=None):
        super().__init__(state_store, context_store)
        self.adapter = adapter
        self.llm_func = llm_func
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "CREATE_EDGES"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute CREATE_EDGES command."""
        args = command.args
        source_variable = args.get("source_variable")
        spec = args.get("spec")
        
        if not source_variable:
            raise ExecutionError("CREATE_EDGES requires source_variable")
        
        # Get the source data
        source_data = self.context_store.get(source_variable)
        if source_data is None:
            # Try state store
            source_var = self.state_store.get_variable(source_variable)
            if source_var:
                source_data = source_var.get("value")
        
        if source_data is None:
            raise ExecutionError(f"Source variable {source_variable} not found")
        
        # Parse spec to determine edge properties
        edge_type = "RELATIONSHIP"
        properties = {}
        
        if spec:
            # Parse spec like "type: BELONGS_TO with properties: weight, created_at"
            if "type:" in spec:
                type_part = spec.split("type:")[1].split("with")[0].strip()
                edge_type = type_part
            
            if "properties:" in spec:
                props_part = spec.split("properties:")[1].strip()
                properties = {prop.strip(): None for prop in props_part.split(",")}
        
        # Create edges from source data
        created_edges = []
        
        if isinstance(source_data, list):
            for i, item in enumerate(source_data):
                edge_id = f"created_edge_{i}"
                
                # Extract source and target from item
                source = None
                target = None
                
                if isinstance(item, dict):
                    source = item.get("source") or item.get("from") or item.get("source_id")
                    target = item.get("target") or item.get("to") or item.get("target_id")
                    
                    # If no explicit source/target, try to infer from item structure
                    if not source or not target:
                        keys = list(item.keys())
                        if len(keys) >= 2:
                            source = item.get(keys[0])
                            target = item.get(keys[1])
                else:
                    # If item is not a dict, we can't create an edge
                    continue
                
                if not source or not target:
                    continue
                
                edge_data = {
                    "id": edge_id,
                    "source": source,
                    "target": target,
                    "type": edge_type,
                    "properties": properties.copy()
                }
                
                # Map item data to edge properties
                if isinstance(item, dict):
                    for key, value in item.items():
                        if key not in ["source", "target", "from", "to", "source_id", "target_id"]:
                            if key in properties:
                                edge_data["properties"][key] = value
                            else:
                                edge_data["properties"][key] = value
                
                # Add to graph via adapter
                if self.adapter:
                    self.adapter.add_edge(source, target, edge_data)
                
                created_edges.append(edge_data)
        
        else:
            # Single item
            if isinstance(source_data, dict):
                source = source_data.get("source") or source_data.get("from") or source_data.get("source_id")
                target = source_data.get("target") or source_data.get("to") or source_data.get("target_id")
                
                if source and target:
                    edge_id = "created_edge_0"
                    edge_data = {
                        "id": edge_id,
                        "source": source,
                        "target": target,
                        "type": edge_type,
                        "properties": properties.copy()
                    }
                    
                    # Map item data to edge properties
                    for key, value in source_data.items():
                        if key not in ["source", "target", "from", "to", "source_id", "target_id"]:
                            if key in properties:
                                edge_data["properties"][key] = value
                            else:
                                edge_data["properties"][key] = value
                    
                    if self.adapter:
                        self.adapter.add_edge(source, target, edge_data)
                    
                    created_edges.append(edge_data)
        
        # Store created edges in context
        result_var = f"created_edges_{source_variable}"
        self.context_store.set(result_var, created_edges)
        
        return self._create_result(
            command=command,
            status="success",
            data={"edges_created": len(created_edges), "result_variable": result_var, "edge_type": edge_type},
            count=len(created_edges)
        )
