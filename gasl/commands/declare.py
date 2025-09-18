"""
DECLARE command handler.
"""

from typing import Any
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..errors import StateError


class DeclareHandler(CommandHandler):
    """Handles DECLARE commands for state variable declaration."""
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "DECLARE"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute DECLARE command."""
        try:
            args = command.args
            variable = args["variable"]
            var_type = args["type"]
            description = args.get("description")
            
            print(f"DEBUG: DECLARE - variable: {variable}, type: {var_type}, description: {description}")
            
            # Check if variable already exists
            if self.state_store.has_variable(variable):
                print(f"DEBUG: Variable {variable} already exists - reusing it")
                
                # Check if this is a reset (same type) or reuse (different type)
                existing_var = self.state_store.get_variable(variable)
                existing_type = None
                if isinstance(existing_var, dict) and "_meta" in existing_var:
                    existing_type = existing_var["_meta"].get("type")
                
                if existing_type == var_type:
                    # Same type - just update description and clear data
                    if description:
                        existing_var["_meta"]["description"] = description
                    
                    # Clear existing data based on type
                    if var_type == "LIST":
                        existing_var["items"] = []
                    elif var_type == "DICT":
                        # Clear all non-meta keys
                        keys_to_remove = [k for k in existing_var.keys() if k != "_meta"]
                        for key in keys_to_remove:
                            del existing_var[key]
                    elif var_type == "COUNTER":
                        existing_var["value"] = 0
                    
                    self.state_store._save_state()
                    
                    return self._create_result(
                        command=command,
                        status="success",
                        data={"variable": variable, "type": var_type, "description": description, "reset": True},
                        count=1,
                        provenance=[self._create_provenance(
                            source_id="gasl-declare",
                            method="reset_variable",
                            variable=variable,
                            type=var_type,
                            description=description
                        )]
                    )
                else:
                    # Different type - just update description
                    if description:
                        existing_var["_meta"]["description"] = description
                        self.state_store._save_state()
                    
                    return self._create_result(
                        command=command,
                        status="success",
                        data={"variable": variable, "type": var_type, "description": description, "reused": True},
                        count=1,
                        provenance=[self._create_provenance(
                            source_id="gasl-declare",
                            method="reuse_variable",
                            variable=variable,
                            type=var_type,
                            description=description
                        )]
                    )
            
            # Declare the variable
            print(f"DEBUG: Declaring variable {variable}")
            self.state_store.declare_variable(variable, var_type, description)
            
            # Create provenance
            provenance = [
                self._create_provenance(
                    source_id="gasl-declare",
                    method="declare_variable",
                    variable=variable,
                    type=var_type,
                    description=description
                )
            ]
            
            return self._create_result(
                command=command,
                status="success",
                data={"variable": variable, "type": var_type, "description": description},
                count=1,
                provenance=provenance
            )
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
