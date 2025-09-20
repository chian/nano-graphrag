"""
ITERATE command handler for explicit micro-action control.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..micro_actions import MicroActionFramework


class IterateHandler(CommandHandler):
    """Handles ITERATE commands for explicit micro-action control."""
    
    def __init__(self, state_store, context_store, micro_framework: MicroActionFramework):
        super().__init__(state_store, context_store)
        self.micro_framework = micro_framework
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "ITERATE"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute ITERATE command with explicit batching control."""
        try:
            args = command.args
            source_var = args["source_var"]
            batch_size = args["batch_size"]
            sub_command = args["sub_command"]
            instruction = args["instruction"]
            
            # Get source data
            data = self._get_data(source_var)
            if not data:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Source variable {source_var} not found or empty"
                )
            
            if not isinstance(data, list):
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Source variable {source_var} is not a list"
                )
            
            print(f"DEBUG: ITERATE - Processing {len(data)} items with {sub_command} in batches of {batch_size}")
            
            # Use the shared micro-action framework
            result = self.micro_framework.execute_command_with_batching(
                data, sub_command, instruction, batch_size
            )
            
            if result.status == "success":
                # Store results in a new variable
                target_var = f"{source_var}_{sub_command.lower()}_processed"
                self._store_results(target_var, result.data.get("processed_items", []))
                
                print(f"DEBUG: ITERATE - Stored {len(result.data.get('processed_items', []))} results in {target_var}")
                
                # Create provenance
                provenance = [
                    self._create_provenance(
                        source_id="micro-action-framework",
                        method="iterate",
                        source_variable=source_var,
                        sub_command=sub_command,
                        batch_size=batch_size,
                        instruction=instruction
                    )
                ]
                
                return self._create_result(
                    command=command,
                    status="success",
                    data=result.data,
                    count=result.count,
                    provenance=provenance
                )
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"ITERATE failed: {result.error_message}"
                )
                
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _get_data(self, variable: str) -> Any:
        """Get data from context or state store."""
        if self.context_store.has(variable):
            return self.context_store.get(variable)
        elif self.state_store.has_variable(variable):
            return self.state_store.get_variable(variable)
        else:
            return None
    
    def _store_results(self, target_var: str, results: List[Dict]) -> None:
        """Store results in target variable."""
        # Store in context for immediate access
        self.context_store.set(target_var, results)
        
        # Also store in state if it exists
        if self.state_store.has_variable(target_var):
            var_data = self.state_store.get_variable(target_var)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = results
                self.state_store._save_state()
            else:
                self.state_store.update_variable(target_var, results)
        else:
            # Create new state variable
            self.state_store.declare_variable(target_var, "LIST", f"Results from ITERATE command")
            var_data = self.state_store.get_variable(target_var)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = results
                self.state_store._save_state()
