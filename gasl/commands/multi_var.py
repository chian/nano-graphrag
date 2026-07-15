"""
Multi-Variable Access command handlers.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..contracts import make_contract, merge_contract
from ..row_identity import IdentitySpec, derive_row_id_for_row, materialize_row_identity


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
        target_var = args.get("target_variable") or args.get("result_variable")
        
        print(f"DEBUG: JOIN - {var1} with {var2} on {join_field} as {target_var}")
        
        # Get data from both variables
        data1 = self._get_variable_data(var1)
        data2 = self._get_variable_data(var2)
        contract1 = self.state_manager.get_variable_contract(var1) if self.state_manager else {}
        contract2 = self.state_manager.get_variable_contract(var2) if self.state_manager else {}
        
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
                    joined_item["left_row_id"] = item1.get("row_id") or derive_row_id_for_row(
                        item1,
                        grain_type=contract1.get("grain_type", "row"),
                        grain_keys=contract1.get("grain_keys", []),
                    )
                    joined_item["right_row_id"] = item2.get("row_id") or derive_row_id_for_row(
                        item2,
                        grain_type=contract2.get("grain_type", "row"),
                        grain_keys=contract2.get("grain_keys", []),
                    )
                    joined_data.append(joined_item)

        joined_data, identity_meta = materialize_row_identity(
            joined_data,
            spec=IdentitySpec(
                mode="join",
                grain_type="join",
                key_fields=("left_row_id", "right_row_id", join_field),
                preserve_multiplicity=True,
            ),
            source_contract=merge_contract(contract1, contract2),
        )
        join_contract = make_contract(
            payload_kind="joined_rows",
            data=joined_data,
            row_schema=identity_meta["row_schema"],
            label_field=contract1.get("label_field", "") or contract2.get("label_field", ""),
            scope="current_rows_only",
            usable_by=["PROCESS", "AGGREGATE", "SHOW", "SELECT", "JOIN"],
            confidence=0.97,
            grain_type=identity_meta["grain_type"],
            grain_keys=identity_meta["grain_keys"],
            multiplicity_preserved=identity_meta["multiplicity_preserved"],
            notes=[f"join_field={join_field}"],
        )
        if self.state_manager:
            self.state_manager.store_variable_data(
                target_var,
                joined_data,
                store_in_state=self.state_store.has_variable(target_var),
                store_in_context=True,
                description=f"Join result of {var1} and {var2}",
                contract=join_contract,
            )
        else:
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
            contract=join_contract,
            provenance=[self._create_provenance("join", "join",
                                               variable1=var1, variable2=var2, join_field=join_field)]
        )
    
    def _execute_merge(self, command: Command) -> ExecutionResult:
        """Execute MERGE command."""
        args = command.args
        variables = args["variables"]
        if isinstance(variables, str):
            variables = [variable.strip() for variable in variables.split(",") if variable.strip()]
        target_var = args.get("target_variable") or args.get("result_variable")
        
        print(f"DEBUG: MERGE - variables: {variables} as {target_var}")
        
        # Get data from all variables
        all_data = []
        contracts = []
        for var_name in variables:
            var_data = self._get_variable_data(var_name)
            if var_data:
                all_data.extend(var_data)
            if self.state_manager:
                contracts.append(
                    self.state_manager.get_variable_contract(
                        var_name,
                        fallback_to_last_nodes=False,
                    )
                )
        
        if not all_data:
            return self._create_result(command=command, status="error",
                                     error_message="No data found in specified variables")
        
        source_contract = self._merge_contracts(contracts)
        row_shaped_merge = any(isinstance(item, dict) and item.get("row_id") for item in all_data)

        # Entity lists should dedupe by entity id; row streams must preserve
        # multiplicity because many projected path rows can share one entity id.
        seen_keys = set()
        merged_data = []
        for index, item in enumerate(all_data):
            identity_key = self._merge_identity_key(
                item,
                index,
                prefer_row_id=row_shaped_merge,
            )
            if identity_key in seen_keys:
                continue
            seen_keys.add(identity_key)
            if row_shaped_merge and isinstance(item, dict) and not item.get("row_id"):
                item = {
                    **item,
                    "row_id": f"merge-ordinal-{index}",
                }
            merged_data.append(item)

        if row_shaped_merge:
            merged_data, identity_meta = materialize_row_identity(
                merged_data,
                spec=IdentitySpec(
                    mode="preserve",
                    grain_type=source_contract.get("grain_type") or "row",
                    preserve_multiplicity=True,
                ),
                source_contract=source_contract,
                source_rows=all_data,
            )
        else:
            identity_meta = {
                "row_schema": [],
                "grain_type": source_contract.get("grain_type", ""),
                "grain_keys": source_contract.get("grain_keys", []),
                "multiplicity_preserved": False,
            }

        merged_contract = merge_contract(source_contract, make_contract(
            payload_kind="merged_rows" if row_shaped_merge else "merged_items",
            data=merged_data,
            row_schema=identity_meta["row_schema"],
            label_field=source_contract.get("label_field", ""),
            metric_field=source_contract.get("metric_field", ""),
            scope="current_rows_only",
            usable_by=["PROCESS", "AGGREGATE", "SHOW", "SELECT", "JOIN", "COLLAPSE"],
            confidence=0.96,
            grain_type=identity_meta["grain_type"],
            grain_keys=identity_meta["grain_keys"],
            multiplicity_preserved=identity_meta["multiplicity_preserved"],
            row_weight_field=source_contract.get("row_weight_field", ""),
            notes=[f"merge_from={','.join(variables)}"],
        ))
        
        # Create or update target variable
        if self.state_manager:
            self.state_manager.store_variable_data(
                target_var,
                merged_data,
                store_in_state=True,
                store_in_context=True,
                description=f"Merged data from {', '.join(variables)}",
                contract=merged_contract,
            )
        else:
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
            contract=merged_contract,
            provenance=[self._create_provenance("merge", "merge", variables=variables)]
        )
    
    def _execute_compare(self, command: Command) -> ExecutionResult:
        """Execute COMPARE command."""
        args = command.args
        var1 = args["variable1"]
        var2 = args["variable2"]
        criteria = args.get("criteria") or args.get("comparison_field")
        target_var = args.get("target_variable") or args.get("result_variable")
        
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

    def _merge_contracts(self, contracts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge input contracts into a best-effort source contract."""
        result: Dict[str, Any] = {}
        for contract in contracts:
            result = merge_contract(result, contract or {})
        return result

    def _merge_identity_key(self, item: Dict[str, Any], index: int, *, prefer_row_id: bool) -> Any:
        """Return the key MERGE should use to identify one incoming item."""
        if not isinstance(item, dict):
            return ("ordinal", index)

        if prefer_row_id:
            row_id = item.get("row_id")
            if row_id:
                return ("row_id", row_id)
            return ("ordinal", index)

        item_id = item.get("id")
        if item_id:
            return ("id", item_id)
        return ("ordinal", index)
    
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
