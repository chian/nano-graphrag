"""
Multi-Variable Access command handlers.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..contracts import make_contract, merge_contract
from ..field_resolution import (
    has_field_path,
    observed_fields,
    read_field_path,
    resolve_field,
)
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

        # The join field is named by the planner; the rows are named by whatever
        # produced them. Resolve the name against each side's actual fields
        # before joining. A field that resolves on neither side used to read back
        # as None on both sides and compare equal, so an unjoinable pair of
        # variables produced |left| x |right| rows and reported success.
        fields1 = observed_fields(data1, contract=contract1)
        fields2 = observed_fields(data2, contract=contract2)
        resolution1 = resolve_field(join_field, fields1)
        resolution2 = resolve_field(join_field, fields2)

        unresolved = []
        if not resolution1.ok:
            unresolved.append((var1, resolution1))
        if not resolution2.ok:
            unresolved.append((var2, resolution2))
        if unresolved:
            detail = "; ".join(
                f"in {name}: {resolution.describe()}" for name, resolution in unresolved
            )
            return self._create_result(
                command=command,
                status="error",
                error_message=(
                    f"JOIN on {join_field!r} cannot run: the join field does not identify "
                    f"a column on {'both sides' if len(unresolved) == 2 else 'one side'}. {detail}. "
                    "Name a field that exists on each side, or project one onto the rows first."
                ),
            )

        left_field = resolution1.resolved
        right_field = resolution2.resolved

        # Perform join operation
        joined_data = []
        # Three different reasons a row cannot join, kept apart on purpose. Only
        # the first is pure absence; the other two are the engine's own policy
        # (null never joins, and an empty string is treated as absence rather
        # than as a shared identity). A policy decision has to be visible as one,
        # not folded into a count that reads as something the data said.
        unjoinable = {
            var1: self._unjoinable_reasons(data1, left_field),
            var2: self._unjoinable_reasons(data2, right_field),
        }

        for item1 in data1:
            for item2 in data2:
                # Check if join field matches
                if self._fields_match(item1, item2, left_field, right_field):
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
        # Every way this join could have quietly under- or over-produced is
        # written into the contract notes, so a zero-row join and an
        # everything-matched join are both self-describing downstream.
        join_notes = [f"join_field={join_field}"]
        if not resolution1.exact:
            join_notes.append(f"join_field resolved on {var1}: {resolution1.describe()}")
        if not resolution2.exact:
            join_notes.append(f"join_field resolved on {var2}: {resolution2.describe()}")
        for side_name, reasons in unjoinable.items():
            breakdown = {
                reason: count
                for reason, count in reasons.items()
                if reason != "rows" and count
            }
            if not breakdown:
                continue
            unusable = sum(breakdown.values())
            note = (
                f"{unusable}/{reasons['rows']} rows in {side_name} carry no usable "
                f"join key and matched nothing ({breakdown})"
            )
            if breakdown.get("value_empty_string"):
                note += (
                    "; empty-string keys are treated as absent by engine policy, "
                    "not joined to each other"
                )
            join_notes.append(note)
        if not joined_data:
            join_notes.append(
                f"join produced 0 rows from {len(data1)}x{len(data2)} candidate pairs; "
                f"the join key resolved but no value was shared between the sides"
            )
        elif len(joined_data) == len(data1) * len(data2):
            join_notes.append(
                f"join produced the full cartesian product ({len(data1)}x{len(data2)}); "
                f"the join key does not discriminate between rows"
            )

        join_contract = make_contract(
            payload_kind="joined_rows",
            data=joined_data,
            row_schema=identity_meta["row_schema"],
            label_field=contract1.get("label_field", "") or contract2.get("label_field", ""),
            scope="current_rows_only",
            usable_by=["PROCESS", "AGGREGATE", "SHOW", "SELECT", "JOIN"],
            grain_type=identity_meta["grain_type"],
            grain_keys=identity_meta["grain_keys"],
            multiplicity_preserved=identity_meta["multiplicity_preserved"],
            notes=join_notes,
        )
        # Columns JOIN authored: the identity it minted plus every collision
        # column it renamed. Declared here at the construction site, where the
        # command knows exactly what it wrote, rather than left to a consumer to
        # recognise by name.
        join_contract["engine_columns"] = sorted(
            {"row_id", "left_row_id", "right_row_id"}
            | {key for row in joined_data for key in row if key.startswith(f"{var2}_")}
        )
        join_contract["join_diagnostics"] = {
            "join_field": join_field,
            "left": {"variable": var1, "rows": len(data1), **resolution1.as_dict()},
            "right": {"variable": var2, "rows": len(data2), **resolution2.as_dict()},
            "unjoinable": unjoinable,
            "joined_rows": len(joined_data),
            "cartesian_rows": len(data1) * len(data2),
        }
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
    
    # Values the engine refuses to treat as a join identity. `None` is absence;
    # `""` is a policy call — an empty string is absence that was written down,
    # not an identity two rows can share. Named here so the rule is one visible
    # decision rather than an inline literal.
    NON_IDENTIFYING_JOIN_VALUES = (None, "")

    @staticmethod
    def _has_join_key(item: Any, field_path: str) -> bool:
        """True when a row carries a usable (present and identifying) join key."""
        if not has_field_path(item, field_path):
            return False
        value = read_field_path(item, field_path)
        return not any(value is candidate or value == candidate
                       for candidate in MultiVarHandler.NON_IDENTIFYING_JOIN_VALUES)

    @classmethod
    def _unjoinable_reasons(cls, rows: List[Dict], field_path: str) -> Dict[str, int]:
        """Count, by reason, the rows that cannot contribute a join key."""
        reasons = {"key_absent": 0, "value_null": 0, "value_empty_string": 0, "rows": len(rows)}
        for row in rows:
            if not has_field_path(row, field_path):
                reasons["key_absent"] += 1
                continue
            value = read_field_path(row, field_path)
            if value is None:
                reasons["value_null"] += 1
            elif value == "":
                reasons["value_empty_string"] += 1
        return reasons

    def _fields_match(self, item1: Dict, item2: Dict, left_field: str, right_field: str) -> bool:
        """Check whether two rows share a join key.

        A row that carries no value for its join key matches nothing. The old
        behaviour compared the two absent-field Nones and called them equal,
        which turned every unjoinable pair into a cartesian product.
        """
        if not self._has_join_key(item1, left_field):
            return False
        if not self._has_join_key(item2, right_field):
            return False
        return read_field_path(item1, left_field) == read_field_path(item2, right_field)


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
