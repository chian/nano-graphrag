"""
Data Transformation command handlers.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..contracts import make_contract, merge_contract
from ..row_identity import IdentitySpec, materialize_row_identity
from nano_graphrag.graph_slots import get_source_refs


class DataTransformHandler(CommandHandler):
    """Handles data transformation commands: TRANSFORM, RESHAPE, AGGREGATE, PIVOT, PROJECT, COLLAPSE."""
    
    def __init__(self, state_store, context_store, llm_func=None, state_manager=None):
        super().__init__(state_store, context_store, state_manager)
        self.llm_func = llm_func
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type in ["TRANSFORM", "RESHAPE", "AGGREGATE", "PIVOT", "PROJECT", "COLLAPSE"]
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute data transformation command."""
        try:
            if command.command_type == "TRANSFORM":
                return self._execute_transform(command)
            elif command.command_type == "RESHAPE":
                return self._execute_reshape(command)
            elif command.command_type == "AGGREGATE":
                return self._execute_aggregate(command)
            elif command.command_type == "PIVOT":
                return self._execute_pivot(command)
            elif command.command_type == "PROJECT":
                return self._execute_project(command)
            elif command.command_type == "COLLAPSE":
                return self._execute_collapse(command)
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown data transformation command: {command.command_type}"
                )
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _execute_transform(self, command: Command) -> ExecutionResult:
        """Execute TRANSFORM command using LLM."""
        args = command.args
        variable = args["variable"]
        instruction = args["instruction"]
        
        print(f"DEBUG: TRANSFORM - variable: {variable}, instruction: {instruction}")
        
        # Get data to transform
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        if not self.llm_func:
            return self._create_result(command=command, status="error",
                                     error_message="LLM function not available for TRANSFORM command")
        
        # Create prompt for LLM transformation
        prompt = self._create_transform_prompt(data, instruction)
        
        # Call LLM
        llm_response = self.llm_func.call(prompt)
        print(f"DEBUG: TRANSFORM - LLM Response:\n{llm_response}\n")
        
        # Parse LLM response
        try:
            import json
            transformed_result = json.loads(llm_response)
            transformed_data = transformed_result.get("transformed_data", [])
            
            # Update the state variable with transformed results
            if self.state_store.has_variable(variable):
                var_data = self.state_store.get_variable(variable)
                if isinstance(var_data, dict) and "items" in var_data:
                    var_data["items"] = transformed_data
                    self.state_store._save_state()
                    print(f"DEBUG: TRANSFORM - Updated {variable} with {len(transformed_data)} transformed items")
            
            return self._create_result(
                command=command,
                status="success",
                data=transformed_data,
                count=len(transformed_data),
                provenance=[self._create_provenance("transform", "transform",
                                                   variable=variable, instruction=instruction)]
            )
            
        except json.JSONDecodeError:
            return self._create_result(command=command, status="error",
                                     error_message="Failed to parse LLM response as JSON")
    
    def _execute_reshape(self, command: Command) -> ExecutionResult:
        """Execute RESHAPE command."""
        args = command.args
        variable = args["variable"]
        from_format = args["from_format"]
        to_format = args["to_format"]
        
        print(f"DEBUG: RESHAPE - variable: {variable}, from: {from_format}, to: {to_format}")
        
        # Get data to reshape
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        # Perform reshape operation
        reshaped_data = []
        
        if from_format == "list" and to_format == "dict":
            # Convert list to dictionary using ID as key
            reshaped_data = {}
            for item in data:
                key = item.get("id", f"item_{len(reshaped_data)}")
                reshaped_data[key] = item
        
        elif from_format == "dict" and to_format == "list":
            # Convert dictionary to list
            if isinstance(data, dict):
                reshaped_data = list(data.values())
            else:
                reshaped_data = data
        
        elif from_format == "flat" and to_format == "hierarchical":
            # Group items by a field to create hierarchy
            hierarchy = {}
            for item in data:
                group_key = item.get("entity_type", "unknown")
                if group_key not in hierarchy:
                    hierarchy[group_key] = []
                hierarchy[group_key].append(item)
            reshaped_data = hierarchy
        
        else:
            return self._create_result(command=command, status="error",
                                     error_message=f"Unsupported reshape from {from_format} to {to_format}")
        
        # Update the state variable
        if self.state_store.has_variable(variable):
            var_data = self.state_store.get_variable(variable)
            if to_format == "list" and isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = reshaped_data
            else:
                # Replace entire variable data
                var_data.clear()
                if isinstance(reshaped_data, dict):
                    var_data.update(reshaped_data)
                else:
                    var_data["items"] = reshaped_data
            self.state_store._save_state()
        
        count = len(reshaped_data) if isinstance(reshaped_data, (list, dict)) else 1
        print(f"DEBUG: RESHAPE - reshaped {len(data)} items to {count} items")
        
        return self._create_result(
            command=command,
            status="success",
            data=reshaped_data,
            count=count,
            provenance=[self._create_provenance("reshape", "reshape",
                                               variable=variable, from_format=from_format, to_format=to_format)]
        )
    
    def _execute_aggregate(self, command: Command) -> ExecutionResult:
        """Execute AGGREGATE command."""
        args = command.args
        variable = args["variable"]
        by_field = args["by_field"]
        operation = args["operation"]  # sum, count, avg, min, max
        result_variable = args.get("result_variable") or variable
        
        print(f"DEBUG: AGGREGATE - variable: {variable}, by: {by_field}, operation: {operation}")
        
        # Get data to aggregate
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        source_contract = {}
        if self.state_manager:
            source_contract = self.state_manager.get_variable_contract(variable)
        resolved_by_field = self._resolve_aggregate_field(data, by_field, source_contract)
        
        resolved_metric_field, metric_basis = self._resolve_aggregate_metric(data, operation, source_contract)
        source_row_weight_field = source_contract.get("row_weight_field", "")

        # Perform aggregation
        aggregated_data = {}
        group_counter = 0
        
        for item in data:
            group_key = self._get_nested_field(item, resolved_by_field)
            print(f"DEBUG: AGGREGATE - item: {item}, by_field: {by_field}, resolved_by_field: {resolved_by_field}, group_key: {group_key}")
            if group_key is None:
                group_key = "unknown"
            
            if group_key not in aggregated_data:
                group_counter += 1
                aggregated_data[group_key] = {
                    "group_id": f"group_{group_counter}",
                    "group_name": str(group_key),
                    "group_key": group_key,
                    by_field: group_key,
                    resolved_by_field: group_key,
                    "items": [],
                    "item_ids": [],
                    "row_count": 0,
                    "count": 0,
                    "result": 0,
                }
                simple_alias = by_field.split(".")[-1]
                aggregated_data[group_key].setdefault(simple_alias, group_key)
            
            # Add item ID to tracking
            item_id = item.get("id", f"item_{len(aggregated_data[group_key]['items'])}")
            aggregated_data[group_key]["item_ids"].append(item_id)
            aggregated_data[group_key]["items"].append(item)
            aggregated_data[group_key]["row_count"] += 1

            # Use an effective row weight so grouped counts remain meaningful even
            # when upstream PROCESS has already deduplicated rows down to one row
            # per entity but preserved evidence-bearing fields.
            row_weight = self._infer_row_weight(
                item,
                resolved_metric_field=resolved_metric_field,
                source_row_weight_field=source_row_weight_field,
            )
            aggregated_data[group_key]["count"] += row_weight
            aggregated_data[group_key]["result"] += row_weight
        
        # Apply operation
        for group_key, group_data in aggregated_data.items():
            if operation == "count":
                group_data["result"] = group_data["count"]
            elif operation == "sum":
                # Sum a resolved numeric metric when present, otherwise fall back
                # to the same evidence-weight heuristic used for count.
                total = 0.0
                for item in group_data["items"]:
                    metric_value = self._extract_numeric_metric(item, resolved_metric_field)
                    total += metric_value if metric_value is not None else self._infer_row_weight(
                        item,
                        resolved_metric_field=resolved_metric_field,
                        source_row_weight_field=source_row_weight_field,
                    )
                group_data["result"] = total
            elif operation == "avg":
                group_data["result"] = (
                    group_data["count"] / group_data["row_count"] if group_data["row_count"] else 0
                )
        
        # Convert to list format
        result_list = list(aggregated_data.values())
        result_list, identity_meta = materialize_row_identity(
            result_list,
            spec=IdentitySpec(
                mode="group",
                grain_type="group",
                key_fields=("group_key",),
                preserve_multiplicity=False,
            ),
            source_contract=source_contract,
        )
        aggregate_contract = merge_contract(source_contract, make_contract(
            payload_kind="grouped_rows",
            data=result_list,
            row_schema=identity_meta["row_schema"],
            label_field=by_field.split(".")[-1] if by_field else "group_name",
            metric_field="count" if operation == "count" else "result",
            ordered=False,
            order_basis=f"grouped by {resolved_by_field}",
            scope="current_rows_only",
            usable_by=["RANK", "PROCESS", "SHOW", "SELECT"],
            confidence=0.95,
            grain_type=identity_meta["grain_type"],
            grain_keys=identity_meta["grain_keys"],
            multiplicity_preserved=identity_meta["multiplicity_preserved"],
            row_weight_field="count" if operation == "count" else ("result" if operation == "sum" else ""),
            notes=[
                f"requested_by_field={by_field}",
                f"resolved_by_field={resolved_by_field}",
                f"metric_basis={metric_basis}",
                f"resolved_metric_field={resolved_metric_field}",
            ],
        ))
        
        # Store aggregated results
        if self.state_store.has_variable(result_variable):
            # Update existing state variable
            var_data = self.state_store.get_variable(result_variable)
            var_type = var_data.get("_meta", {}).get("type") if isinstance(var_data, dict) else None
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = result_list
                var_data["_meta"]["contract"] = aggregate_contract
                self.state_store._save_state()
                print(f"DEBUG: AGGREGATE - Updated state variable {result_variable} with {len(result_list)} groups")
            elif var_type == "COUNTER":
                # Planner often declares counters for eventual counts, but AGGREGATE
                # returns grouped rows that downstream RANK/JOIN should read from
                # context, not from the persisted counter slot.
                self.context_store.set(result_variable, result_list, contract=aggregate_contract)
                print(
                    f"DEBUG: AGGREGATE - Stored {len(result_list)} groups in context as {result_variable} "
                    f"because declared state variable is COUNTER"
                )
            else:
                # If it's not a LIST type, update it directly
                self.state_store.update_variable(result_variable, result_list)
                self.state_store.set_variable_contract(result_variable, aggregate_contract)
                print(f"DEBUG: AGGREGATE - Updated state variable {result_variable} directly with {len(result_list)} groups")
        else:
            self.context_store.set(result_variable, result_list, contract=aggregate_contract)
            print(f"DEBUG: AGGREGATE - Stored {len(result_list)} groups in context as {result_variable}")
        
        # Keep context synchronized with the latest grouped rows even when state was updated.
        self.context_store.set(result_variable, result_list, contract=aggregate_contract)

        # Also store as last_aggregate_result for consistency
        self.context_store.set("last_aggregate_result", result_list, contract=aggregate_contract)
        print(f"DEBUG: AGGREGATE - Also stored as last_aggregate_result with {len(result_list)} groups")
        
        print(f"DEBUG: AGGREGATE - created {len(result_list)} aggregated groups")
        
        # Create initial result
        result_obj = self._create_result(
            command=command,
            status="success",
            data=result_list,
            count=len(result_list),
            contract=aggregate_contract,
            provenance=[self._create_provenance("aggregate", "aggregate",
                                               variable=variable, by_field=by_field, operation=operation)]
        )
        
        return result_obj

    def _resolve_aggregate_field(self, data: List[Dict[str, Any]], requested_field: str, source_contract: Dict[str, Any]) -> str:
        """Resolve the grouping field using row contents and contract metadata."""
        if not requested_field:
            return requested_field
        if any(self._get_nested_field(item, requested_field) is not None for item in data[:25]):
            return requested_field
        label_field = source_contract.get("label_field", "")
        if label_field and any(self._get_nested_field(item, label_field) is not None for item in data[:25]):
            return label_field
        if "." not in requested_field:
            fallback = f"data.{requested_field}"
            if any(self._get_nested_field(item, fallback) is not None for item in data[:25]):
                return fallback
        return requested_field

    def _resolve_aggregate_metric(
        self,
        data: List[Dict[str, Any]],
        operation: str,
        source_contract: Dict[str, Any],
    ) -> tuple[str, str]:
        """Resolve the best numeric/evidence metric to aggregate."""
        metric_field = source_contract.get("metric_field", "")
        if metric_field and any(self._extract_numeric_metric(item, metric_field) is not None for item in data[:25]):
            return metric_field, "contract_metric"

        numeric_candidates = []
        if data:
            sample_fields = list(data[0].keys())
            numeric_candidates = [field for field in sample_fields if field not in {"count", "row_count", "result"}]
        for field in numeric_candidates:
            if any(self._extract_numeric_metric(item, field) is not None for item in data[:25]):
                return field, "row_numeric_field"

        if source_contract.get("row_weight_field"):
            return source_contract.get("row_weight_field", ""), "contract_row_weight"

        if operation in {"count", "sum", "avg"}:
            return "", "evidence_weight"
        return "", "none"

    def _extract_numeric_metric(self, item: Dict[str, Any], field_path: str) -> Any:
        if not field_path:
            return None
        value = self._get_nested_field(item, field_path)
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except Exception:
            return None

    def _infer_row_weight(
        self,
        item: Dict[str, Any],
        *,
        resolved_metric_field: str = "",
        source_row_weight_field: str = "",
    ) -> float:
        """Infer an evidence-bearing row weight for aggregation."""
        if source_row_weight_field:
            metric_value = self._extract_numeric_metric(item, source_row_weight_field)
            if metric_value is not None:
                return float(metric_value)
        metric_value = self._extract_numeric_metric(item, resolved_metric_field)
        if metric_value is not None:
            return float(metric_value)

        for list_field in ("item_ids", "items"):
            value = item.get(list_field)
            if isinstance(value, list) and value:
                return float(len(value))

        # Graph-linked rows often preserve evidence multiplicity in source metadata.
        for path in ("data.source_chunks", "source_chunks"):
            value = self._get_nested_field(item, path)
            if isinstance(value, str) and value.strip():
                parts = [part.strip() for part in value.split(",") if part.strip()]
                if parts:
                    return float(len(dict.fromkeys(parts)))
        for container_path in ("data", ""):
            container = self._get_nested_field(item, container_path) if container_path else item
            if isinstance(container, dict):
                refs = get_source_refs(container)
                if refs:
                    return float(len(dict.fromkeys(refs)))

        return 1.0

    def _execute_project(self, command: Command) -> ExecutionResult:
        args = command.args
        variable = args["variable"]
        grain = args["grain"]
        field_specs = self._parse_project_fields(args.get("fields", ""))
        key_specs = [part.strip() for part in args.get("keys", "").split(",") if part.strip()]
        weight_field = args.get("weight_field", "")
        preserve = bool(args.get("preserve_multiplicity", False))
        result_variable = args.get("result_variable") or variable

        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        source_contract = self.state_manager.get_variable_contract(variable) if self.state_manager else {}

        projected = []
        for item in data:
            grain_rows = self._project_rows_for_grain(item, grain, field_specs)
            for row in grain_rows:
                if not row.get("id") and item.get("id"):
                    row["id"] = item["id"]
                if not preserve:
                    dedupe_key = tuple(row.get(key) for key in (key_specs or [alias for _, alias in field_specs]))
                    row["_collapse_key"] = dedupe_key
                if weight_field:
                    row[weight_field] = self._infer_row_weight(item)
                projected.append(row)

        if not preserve:
            seen = set()
            deduped = []
            for row in projected:
                key = row.pop("_collapse_key", tuple(sorted(row.items())))
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(row)
            projected = deduped

        projected, identity_meta = materialize_row_identity(
            projected,
            spec=IdentitySpec(
                mode="rekey",
                grain_type=grain,
                key_fields=tuple(key_specs or self._default_grain_keys(grain)),
                preserve_multiplicity=preserve,
            ),
            source_contract=source_contract,
        )

        contract = merge_contract(source_contract, make_contract(
            payload_kind="projected_rows",
            data=projected,
            row_schema=identity_meta["row_schema"],
            label_field=field_specs[0][1] if field_specs else "",
            metric_field=weight_field,
            scope="current_rows_only",
            usable_by=["PROCESS", "AGGREGATE", "RANK", "SHOW", "SELECT", "COLLAPSE"],
            confidence=0.98,
            grain_type=identity_meta["grain_type"],
            grain_keys=identity_meta["grain_keys"],
            multiplicity_preserved=identity_meta["multiplicity_preserved"],
            row_weight_field=weight_field,
            notes=[f"project_from={variable}"],
        ))

        if self.state_manager:
            self.state_manager.store_variable_data(
                result_variable,
                projected,
                store_in_state=self.state_store.has_variable(result_variable),
                store_in_context=True,
                description=f"Projected rows from {variable}",
                contract=contract,
            )
        else:
            self.context_store.set(result_variable, projected, contract=contract)

        return self._create_result(
            command=command,
            status="success" if projected else "empty",
            data=projected,
            count=len(projected),
            contract=contract,
            provenance=[self._create_provenance("project", "project", variable=variable, grain=grain)],
        )

    def _execute_collapse(self, command: Command) -> ExecutionResult:
        args = command.args
        variable = args["variable"]
        by_field = args["by_field"]
        weight_field = args.get("weight_field") or "occurrence_count"
        result_variable = args.get("result_variable") or variable

        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        source_contract = self.state_manager.get_variable_contract(variable) if self.state_manager else {}

        collapsed = {}
        for item in data:
            key = self._get_nested_field(item, by_field)
            if key is None:
                key = "unknown"
            if key not in collapsed:
                collapsed[key] = {
                    "group_name": str(key),
                    by_field.split(".")[-1]: key,
                    "items": [],
                    weight_field: 0,
                }
            collapsed[key]["items"].append(item)
            collapsed[key][weight_field] += self._infer_row_weight(
                item, source_row_weight_field=source_contract.get("row_weight_field", "")
            )

        result_rows = list(collapsed.values())
        result_rows, identity_meta = materialize_row_identity(
            result_rows,
            spec=IdentitySpec(
                mode="group",
                grain_type="group",
                key_fields=("group_key",),
                preserve_multiplicity=False,
            ),
            source_contract=source_contract,
        )
        contract = merge_contract(source_contract, make_contract(
            payload_kind="collapsed_rows",
            data=result_rows,
            row_schema=identity_meta["row_schema"],
            label_field=by_field.split(".")[-1],
            metric_field=weight_field,
            scope="current_rows_only",
            usable_by=["AGGREGATE", "RANK", "SHOW", "SELECT"],
            confidence=0.98,
            grain_type=identity_meta["grain_type"],
            grain_keys=identity_meta["grain_keys"],
            multiplicity_preserved=identity_meta["multiplicity_preserved"],
            row_weight_field=weight_field,
            notes=[f"collapsed_by={by_field}"],
        ))

        if self.state_manager:
            self.state_manager.store_variable_data(
                result_variable,
                result_rows,
                store_in_state=self.state_store.has_variable(result_variable),
                store_in_context=True,
                description=f"Collapsed rows from {variable}",
                contract=contract,
            )
        else:
            self.context_store.set(result_variable, result_rows, contract=contract)

        return self._create_result(
            command=command,
            status="success" if result_rows else "empty",
            data=result_rows,
            count=len(result_rows),
            contract=contract,
            provenance=[self._create_provenance("collapse", "collapse", variable=variable, by_field=by_field)],
        )

    @staticmethod
    def _parse_project_fields(fields_text: str) -> List[tuple[str, str]]:
        field_specs: List[tuple[str, str]] = []
        for raw in [part.strip() for part in fields_text.split(",") if part.strip()]:
            parts = raw.split(" AS ")
            if len(parts) == 2:
                field_specs.append((parts[0].strip(), parts[1].strip()))
            else:
                source = raw.strip()
                field_specs.append((source, source.split(".")[-1]))
        return field_specs

    @staticmethod
    def _default_grain_keys(grain: str) -> List[str]:
        if grain == "edge":
            return ["src_id", "tgt_id", "relation_type", "path_depth"]
        if grain == "path":
            return ["src_id", "tgt_id", "path_depth"]
        if grain == "paper":
            return ["paper_id"]
        if grain == "chunk":
            return ["chunk_id"]
        return ["id"]

    def _project_rows_for_grain(
        self,
        item: Dict[str, Any],
        grain: str,
        field_specs: List[tuple[str, str]],
    ) -> List[Dict[str, Any]]:
        base_row = {}
        for source_path, alias in field_specs:
            base_row[alias] = self._get_nested_field(item, source_path)
        if grain == "paper":
            papers = self._extract_source_refs(item)
            if not papers:
                return [{**base_row, "paper_id": None}]
            return [{**base_row, "paper_id": paper_id} for paper_id in papers]
        if grain == "chunk":
            chunks = self._explode_csv_field(item, ["data.source_chunks", "source_chunks"])
            if not chunks:
                return [{**base_row, "chunk_id": None}]
            return [{**base_row, "chunk_id": chunk_id} for chunk_id in chunks]
        return [base_row]

    def _explode_csv_field(self, item: Dict[str, Any], candidate_paths: List[str]) -> List[str]:
        for path in candidate_paths:
            value = self._get_nested_field(item, path)
            if isinstance(value, str) and value.strip():
                return [part.strip() for part in value.split(",") if part.strip()]
        return []

    def _extract_source_refs(self, item: Dict[str, Any]) -> List[str]:
        data_container = item.get("data")
        if isinstance(data_container, dict):
            refs = get_source_refs(data_container)
            if refs:
                return refs
        return get_source_refs(item)
    
    def _get_nested_field(self, item: Dict, field_path: str) -> Any:
        """Get nested field value using dot notation with automatic path resolution."""
        if not field_path:
            return None
        
        # First try the exact field path
        keys = field_path.split('.')
        value = item
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                break
        else:
            # If we successfully traversed all keys, return the value
            return value
        
        # If exact path failed, try to find the field in common nested locations
        if '.' not in field_path:
            # Try common nested locations for single field names
            common_paths = [
                f"data.{field_path}",
                f"properties.{field_path}",
                f"attributes.{field_path}",
                field_path  # Try the original path again
            ]
            
            for path in common_paths:
                keys = path.split('.')
                value = item
                
                for key in keys:
                    if isinstance(value, dict) and key in value:
                        value = value[key]
                    else:
                        break
                else:
                    # If we successfully traversed all keys, return the value
                    return value
        
        return None
    
    def _execute_pivot(self, command: Command) -> ExecutionResult:
        """Execute PIVOT command."""
        args = command.args
        variable = args["variable"]
        pivot_field = args["pivot_field"]
        value_field = args["value_field"]
        
        print(f"DEBUG: PIVOT - variable: {variable}, pivot: {pivot_field}, value: {value_field}")
        
        # Get data to pivot
        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        
        # Perform pivot operation
        pivot_result = {}
        pivot_columns = set()
        
        # First pass: collect all pivot values
        for item in data:
            pivot_value = self._get_nested_field(item, pivot_field)
            if pivot_value:
                pivot_columns.add(str(pivot_value))
        
        # Second pass: create pivoted structure
        for item in data:
            row_key = item.get("id", f"row_{len(pivot_result)}")
            if row_key not in pivot_result:
                pivot_result[row_key] = {**item}  # Copy original item
                # Initialize pivot columns
                for col in pivot_columns:
                    pivot_result[row_key][f"pivot_{col}"] = None
            
            pivot_value = str(self._get_nested_field(item, pivot_field))
            value = self._get_nested_field(item, value_field)
            if pivot_value and pivot_value in pivot_columns:
                pivot_result[row_key][f"pivot_{pivot_value}"] = value
        
        # Convert to list
        pivoted_list = list(pivot_result.values())
        
        # Update variable
        if self.state_store.has_variable(variable):
            var_data = self.state_store.get_variable(variable)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = pivoted_list
                self.state_store._save_state()
        
        print(f"DEBUG: PIVOT - created {len(pivoted_list)} pivoted rows with {len(pivot_columns)} pivot columns")
        
        return self._create_result(
            command=command,
            status="success",
            data=pivoted_list,
            count=len(pivoted_list),
            provenance=[self._create_provenance("pivot", "pivot",
                                               variable=variable, pivot_field=pivot_field, value_field=value_field)]
        )
    
    def _create_transform_prompt(self, data: Any, instruction: str) -> str:
        """Create prompt for LLM transformation."""
        prompt = f"""You are transforming data according to this instruction: {instruction}

Data to transform:
{self._format_data_for_llm(data)}

Instructions:
1. Transform the data according to the instruction
2. Maintain the original structure but modify/enhance as requested
3. Return your results as a JSON object with this structure:
{{
  "transformed_data": [
    // Array of transformed items
  ],
  "transformation_summary": {{
    "total_processed": 0,
    "changes_made": "description of changes",
    "new_fields_added": ["field1", "field2"]
  }}
}}

Apply the transformation consistently to all items.
"""
        return prompt
    
    def _format_data_for_llm(self, data: Any) -> str:
        """Format data for LLM consumption."""
        if not isinstance(data, list):
            return str(data)
        
        # Limit to first 10 items to avoid token limits
        sample_data = data[:10]
        formatted = []
        
        for i, item in enumerate(sample_data):
            formatted.append(f"Item {i+1}: {item}")
        
        if len(data) > 10:
            formatted.append(f"... and {len(data) - 10} more items")
        
        return "\n".join(formatted)
    
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
    
    def _get_nested_field(self, item: Dict, field_path: str) -> Any:
        """Get nested field value using dot notation with common node-data fallbacks."""
        if not field_path:
            return None

        fields = field_path.split(".")
        value = item
        for field in fields:
            if isinstance(value, dict) and field in value:
                value = value[field]
            else:
                break
        else:
            return value

        if "." not in field_path:
            for path in (f"data.{field_path}", f"properties.{field_path}", f"attributes.{field_path}"):
                fields = path.split(".")
                value = item
                for field in fields:
                    if isinstance(value, dict) and field in value:
                        value = value[field]
                    else:
                        break
                else:
                    return value

        return None
