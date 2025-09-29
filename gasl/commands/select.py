"""
SELECT command handler.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class SelectHandler(CommandHandler):
    """Handles SELECT commands for data manipulation."""
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "SELECT"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute SELECT command."""
        try:
            args = command.args
            source = args["source"]
            fields = args["fields"]
            target = args["target"]
            
            # Get source data from context or state
            data = None
            if self.context_store.has(source):
                data = self.context_store.get(source)
            elif self.state_store.has_variable(source):
                var_data = self.state_store.get_variable(source)
                # Handle state store variable structure (with _meta and items)
                if isinstance(var_data, dict) and "items" in var_data:
                    data = var_data["items"]
                else:
                    data = var_data
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Source variable {source} not found"
                )
            
            # Parse fields
            field_list = [f.strip() for f in fields.split(",")]
            
            # Select fields from data
            result = self._select_fields(data, field_list)
            
            # Store result in context
            self.context_store.set(target, result)
            
            # Create provenance
            provenance = [
                self._create_provenance(
                    source_id="gasl-select",
                    method="select_fields",
                    source=source,
                    fields=field_list,
                    target=target
                )
            ]
            
            return self._create_result(
                command=command,
                status="success",
                data=result,
                count=len(result) if isinstance(result, list) else 1,
                provenance=provenance
            )
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _select_fields(self, data: Any, fields: List[str]) -> Any:
        """Select specified fields from data."""
        if isinstance(data, list):
            # Handle list of items
            result = []
            for item in data:
                if isinstance(item, dict):
                    selected = {}
                    for field in fields:
                        # Handle nested field access (e.g., "data.description")
                        if '.' in field:
                            parts = field.split('.')
                            value = item
                            for part in parts:
                                if isinstance(value, dict):
                                    value = value.get(part)
                                else:
                                    value = None
                                    break
                            selected[field] = value
                        else:
                            # Direct field access
                            selected[field] = item.get(field)
                    result.append(selected)
                else:
                    result.append(item)
            return result
        elif isinstance(data, dict):
            # Handle single dict
            result = {}
            for field in fields:
                # Handle nested field access (e.g., "data.description")
                if '.' in field:
                    parts = field.split('.')
                    value = data
                    for part in parts:
                        if isinstance(value, dict):
                            value = value.get(part)
                        else:
                            value = None
                            break
                    result[field] = value
                else:
                    # Direct field access
                    result[field] = data.get(field)
            return result
        else:
            # Return as-is for other types
            return data