"""
SELECT command handler.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..contracts import make_contract, merge_contract
from ..row_identity import IdentitySpec, materialize_row_identity


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
            source_contract = self.state_manager.get_variable_contract(source) if self.state_manager else {}
            identity_spec = self._projection_identity_spec(
                source_contract=source_contract,
                projected_rows=result if isinstance(result, list) else [],
                field_list=field_list,
            )
            result, identity_meta = materialize_row_identity(
                result,
                spec=identity_spec,
                source_contract=source_contract,
                source_rows=data if isinstance(data, list) else [],
            )
            select_contract = merge_contract(source_contract, make_contract(
                payload_kind="selected_rows" if isinstance(result, list) else "selected_fields",
                data=result,
                row_schema=identity_meta["row_schema"],
                label_field=field_list[0] if field_list else source_contract.get("label_field", ""),
                metric_field=source_contract.get("metric_field", ""),
                ordered=source_contract.get("ordered", False),
                order_basis=source_contract.get("order_basis", ""),
                order_field=source_contract.get("order_field", ""),
                order_direction=source_contract.get("order_direction", "unknown"),
                scope="current_rows_only",
                usable_by=["PROCESS", "AGGREGATE", "SHOW", "SELECT", "JOIN"],
                grain_type=identity_meta["grain_type"],
                grain_keys=identity_meta["grain_keys"],
                multiplicity_preserved=identity_meta["multiplicity_preserved"],
            ))
            if self.state_manager:
                self.state_manager.store_variable_data(
                    target,
                    result,
                    store_in_state=self.state_store.has_variable(target),
                    store_in_context=True,
                    description=f"Selected fields from {source}",
                    contract=select_contract,
                )
            else:
                self.context_store.set(target, result, contract=select_contract)
            
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
                provenance=provenance,
                contract=select_contract,
            )
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )

    def _projection_identity_spec(
        self,
        *,
        source_contract: Dict[str, Any],
        projected_rows: List[Dict[str, Any]],
        field_list: List[str],
    ) -> IdentitySpec:
        selected_fields = set(field_list)
        source_grain_type = source_contract.get("grain_type", "row")
        source_grain_keys = tuple(source_contract.get("grain_keys") or ())
        preserve_multiplicity = bool(source_contract.get("multiplicity_preserved", True))

        # Preserve the original semantic grain only when the projected rows still
        # expose the grain keys, or when group rows keep their grouping dimension.
        if source_grain_keys and self._rows_have_paths(projected_rows, source_grain_keys):
            return IdentitySpec(
                mode="preserve",
                grain_type=source_grain_type,
                key_fields=source_grain_keys,
                preserve_multiplicity=preserve_multiplicity,
            )

        label_field = source_contract.get("label_field", "")
        if (
            source_grain_type == "group"
            and label_field
            and label_field in selected_fields
            and self._rows_have_paths(projected_rows, (label_field,))
        ):
            return IdentitySpec(
                mode="preserve",
                grain_type="group",
                key_fields=(label_field,),
                preserve_multiplicity=preserve_multiplicity,
            )

        # Lossy projections should emit row-grain outputs even if row_id is
        # preserved from the source rows.
        return IdentitySpec(
            mode="preserve",
            grain_type="row",
            preserve_multiplicity=preserve_multiplicity,
        )

    @staticmethod
    def _rows_have_paths(rows: List[Dict[str, Any]], paths: tuple[str, ...]) -> bool:
        if not rows:
            return False
        for row in rows:
            for path in paths:
                current: Any = row
                for part in path.split("."):
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    else:
                        return False
        return True
    
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
