"""
Data Transformation command handlers.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..contracts import make_contract, merge_contract
from ..field_resolution import (
    UNRESOLVED_MISSING,
    FieldResolution,
    has_field_path,
    observed_fields,
    read_field_path,
    resolve_field,
)
from ..provenance import (
    WEIGHT_BASIS_CONTRACT_ROW_WEIGHT,
    combine_bases,
    WEIGHT_BASIS_LIST_LENGTH,
    WEIGHT_BASIS_NO_EVIDENCE_DEFAULT,
    WEIGHT_BASIS_RESOLVED_METRIC,
    WEIGHT_BASIS_SOURCE_REF_COUNT_GROUP,
    WEIGHT_BASIS_SOURCE_REF_COUNT_ROW,
    distinct_source_refs,
    inherited_basis,
    is_no_evidence,
    row_source_refs,
)
from ..row_identity import IdentitySpec, materialize_row_identity


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
        by_resolution = self._resolve_aggregate_field(data, by_field, source_contract)

        # A grouping field that names no column on these rows is a question this
        # command cannot answer, and `error` is the only status that gets the
        # planner a chance to fix it: the engine routes command-local repair on
        # `error` and on nothing else, so a note here would be written and read
        # by nobody. The candidate list travels in the message because the
        # planner's next attempt needs the real column names, not the news that
        # its guess was wrong.
        if not by_resolution.ok:
            return self._create_result(
                command=command,
                status="error",
                error_message=(
                    f"AGGREGATE on {by_field!r} cannot run: the grouping field does not "
                    f"identify a column on these rows. {by_resolution.describe()}. "
                    "Name a field that exists on the rows, or project one onto them first."
                ),
            )

        resolved_by_field = by_resolution.resolved
        resolved_metric_field, metric_basis = self._resolve_aggregate_metric(data, operation, source_contract)
        source_row_weight_field = source_contract.get("row_weight_field", "")
        source_row_weight_basis = source_contract.get("row_weight_basis", "")

        # Perform aggregation
        aggregated_data = {}
        group_counter = 0
        # Resolution proves the grouping column exists on SOME row. It never
        # proves it exists on EVERY row, and those rows used to be swept into a
        # bucket literally named "unknown" — an engine-chosen string occupying
        # the same slot as values read from the data, indistinguishable from a
        # group whose key really is the word "unknown". Rows that cannot be
        # grouped are counted here and reported, never bucketed.
        key_presence = {
            "rows": len(data),
            "key_present": 0,
            "key_absent": 0,
            "key_present_null": 0,
        }

        for item in data:
            # `has_field_path` and a None read say different things, and only
            # `has_field_path` can tell them apart: a column that is absent and
            # a column that is present holding null are different facts about
            # the producer, and `_get_nested_field` collapses both to None.
            if not has_field_path(item, resolved_by_field):
                key_presence["key_absent"] += 1
                continue
            group_key = read_field_path(item, resolved_by_field)
            if group_key is None:
                key_presence["key_present_null"] += 1
                continue
            key_presence["key_present"] += 1

            if group_key not in aggregated_data:
                group_counter += 1
                aggregated_data[group_key] = {
                    "group_id": f"group_{group_counter}",
                    "group_name": str(group_key),
                    "group_key": group_key,
                    # Only the column actually grouped by is written onto the
                    # row. Writing the REQUESTED name here too was the
                    # masquerade: a row grouped by one column carrying the name
                    # of another, with the substitution baked into the payload
                    # where no disclosure could reach it.
                    resolved_by_field: group_key,
                    "items": [],
                    "item_ids": [],
                    "row_count": 0,
                    "count": 0,
                    "result": 0,
                }
                simple_alias = resolved_by_field.split(".")[-1]
                aggregated_data[group_key].setdefault(simple_alias, group_key)

            # Add item ID to tracking
            item_id = item.get("id", f"item_{len(aggregated_data[group_key]['items'])}")
            aggregated_data[group_key]["item_ids"].append(item_id)
            aggregated_data[group_key]["items"].append(item)
            aggregated_data[group_key]["row_count"] += 1

            # Use an effective row weight so grouped counts remain meaningful even
            # when upstream PROCESS has already deduplicated rows down to one row
            # per entity but preserved evidence-bearing fields.
            row_weight, _basis = self._infer_row_weight(
                item,
                resolved_metric_field=resolved_metric_field,
                source_row_weight_field=source_row_weight_field,
                source_row_weight_basis=source_row_weight_basis,
                source_contract=source_contract,
            )
            aggregated_data[group_key]["count"] += row_weight
            aggregated_data[group_key]["result"] += row_weight

        # Every row failed to yield a key. Under the old code this produced one
        # all-"unknown" group and reported success — 67 of the 103 "unknown"
        # groups in the recorded traces are exactly this shape, each one a
        # result whose entire output was that single fabricated bucket.
        if not aggregated_data:
            return self._create_result(
                command=command,
                status="error",
                error_message=(
                    f"AGGREGATE on {by_field!r} produced no groups: the field resolved to "
                    f"{resolved_by_field!r}, but none of the {key_presence['rows']} rows carry a "
                    f"usable value for it ({key_presence['key_absent']} absent, "
                    f"{key_presence['key_present_null']} present-and-null). "
                    f"{by_resolution.describe()}."
                ),
            )

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
                    if metric_value is None:
                        metric_value, _basis = self._infer_row_weight(
                            item,
                            resolved_metric_field=resolved_metric_field,
                            source_row_weight_field=source_row_weight_field,
                            source_row_weight_basis=source_row_weight_basis,
                            source_contract=source_contract,
                        )
                    total += metric_value
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
        # Notes carry PROSE ONLY. Every typed value this command knows -- the
        # requested and resolved grouping field, the metric field, the metric
        # basis, the key-presence counts -- lives in `aggregate_diagnostics`
        # below and in the typed contract fields, and none of it is restated
        # here.
        #
        # The four `k=v` lines that used to sit here were a typed value
        # serialized into free text that nothing parses: unjoinable,
        # unqueryable, unassertable. Worse than merely useless, they were the
        # precedent that would be cited to justify putting the next basis in
        # notes too, which is why they go rather than merely being duplicated.
        # The prose below is a rendering FOR A READER of numbers that are typed
        # elsewhere, never the only home of a value.
        aggregate_notes = []
        # A rung below `exact` means the rows were grouped by a column the
        # planner did not literally name. That is legitimate name resolution
        # rather than a substituted column, but it is still a difference between
        # what was asked and what ran, so it is stated.
        if not by_resolution.exact:
            aggregate_notes.append(f"by_field resolved: {by_resolution.describe()}")
        ungroupable = key_presence["key_absent"] + key_presence["key_present_null"]
        if ungroupable:
            aggregate_notes.append(
                f"{ungroupable}/{key_presence['rows']} rows carry no usable value for "
                f"{resolved_by_field!r} and were counted, not grouped "
                f"({key_presence['key_absent']} absent, "
                f"{key_presence['key_present_null']} present-and-null)"
            )

        aggregate_contract = merge_contract(source_contract, make_contract(
            payload_kind="grouped_rows",
            data=result_list,
            row_schema=identity_meta["row_schema"],
            label_field=resolved_by_field.split(".")[-1] if resolved_by_field else "group_name",
            metric_field="count" if operation == "count" else "result",
            ordered=False,
            order_basis=f"grouped by {resolved_by_field}",
            scope="current_rows_only",
            usable_by=["RANK", "PROCESS", "SHOW", "SELECT"],
            grain_type=identity_meta["grain_type"],
            grain_keys=identity_meta["grain_keys"],
            multiplicity_preserved=identity_meta["multiplicity_preserved"],
            row_weight_field="count" if operation == "count" else ("result" if operation == "sum" else ""),
            row_weight_basis=metric_basis,
            notes=aggregate_notes,
        ))
        # Explicit AFTER the merge, for the reason COLLAPSE sets its own fields
        # explicitly: `merge_contract` drops empty values, so an operation that
        # nominates no weight column would silently inherit the SOURCE
        # contract's -- group rows carrying a weight field that described the
        # pre-group rows, and a basis describing a derivation that did not
        # happen here.
        # Explicit for the same reason as the weight fields below: an empty list
        # is dropped by `merge_contract`, so a command with no prose of its own
        # would inherit the SOURCE contract's notes and present sentences about
        # the pre-group rows as if they described these.
        aggregate_contract["notes"] = aggregate_notes
        aggregate_contract["row_weight_field"] = (
            "count" if operation == "count" else ("result" if operation == "sum" else "")
        )
        aggregate_contract["row_weight_basis"] = metric_basis
        # The columns this command minted, declared so a consumer projecting
        # datapoints can exclude them without maintaining its own list of engine
        # vocabulary. This replaces the rejected underscore-prefix convention.
        aggregate_contract["engine_columns"] = sorted(
            {
                "group_id",
                "group_name",
                "group_key",
                "items",
                "item_ids",
                "row_count",
                "count",
                "result",
                resolved_by_field,
                resolved_by_field.split(".")[-1],
            }
        )
        aggregate_contract["aggregate_diagnostics"] = {
            "by_field": by_resolution.as_dict(),
            "metric_field": self._metric_resolution_dict(resolved_metric_field, metric_basis),
            "metric_basis": metric_basis,
            # The counted breakdown behind the deleted "unknown" bucket. Present
            # and null is kept apart from absent because they are different
            # facts about the producer, and only `has_field_path` can tell them
            # apart.
            "key_presence": dict(key_presence),
        }

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

    def _resolve_aggregate_field(
        self,
        data: List[Dict[str, Any]],
        requested_field: str,
        source_contract: Dict[str, Any],
    ) -> FieldResolution:
        """Resolve the grouping field name against the fields the rows carry.

        This is NAME RESOLUTION and nothing else — the same column under a
        different spelling, via the shared ladder in `field_resolution`.

        It used to do a second, different thing: when the requested name matched
        nothing it substituted the contract's `label_field`, a genuinely
        DIFFERENT column, and grouped by that instead. That is not resolution,
        it is answering a question nobody asked, and it could not be repaired by
        disclosure because the substituted column was written onto the output
        rows under the requested name. The masquerade lived in the payload, not
        in the summary.

        The old `data.<field>` probe is gone too — as redundant rather than as
        wrong. `resolve_field` already reaches `data.entity_name` from
        `entity_name` at the `leaf` rung, and the probe additionally baked in
        the adapter's row-envelope shape, which is not part of the canonical
        graph abstraction.

        Candidates come from every row at every depth, never a slice: a sampled
        candidate list turns "available fields" in the error message into a
        falsehood and makes a field on row 300 report as missing.
        """
        if not requested_field:
            return FieldResolution(requested_field, None, UNRESOLVED_MISSING, [])
        return resolve_field(
            requested_field, observed_fields(data, contract=source_contract)
        )

    @staticmethod
    def _metric_resolution_dict(resolved_metric_field: str, metric_basis: str) -> Dict[str, Any]:
        return {"resolved": resolved_metric_field or None, "how": metric_basis}

    def _resolve_aggregate_metric(
        self,
        data: List[Dict[str, Any]],
        operation: str,
        source_contract: Dict[str, Any],
    ) -> tuple[str, str]:
        """Resolve the best numeric/evidence metric to aggregate.

        `metric_field` from the contract stays, and is not the same kind of
        thing as the deleted `label_field` substitution: a contract's declared
        metric is the PRODUCER stating a fact about its own payload, whereas
        `label_field` was the engine guessing at what the planner must have
        meant. The first is testimony, the second is invention.
        """
        candidates = observed_fields(data, contract=source_contract)

        metric_field = source_contract.get("metric_field", "")
        if metric_field and any(
            self._extract_numeric_metric(item, metric_field) is not None for item in data
        ):
            return metric_field, "contract_metric"

        # Candidates from every row, not `data[0].keys()`. Keying off the first
        # row alone meant a numeric column that happened to be absent from row 0
        # did not exist as far as this resolver was concerned.
        numeric_candidates = [
            field
            for field in candidates
            if field.split(".")[-1] not in {"count", "row_count", "result"}
        ]
        for field in numeric_candidates:
            if any(self._extract_numeric_metric(item, field) is not None for item in data):
                return field, "row_numeric_field"

        if source_contract.get("row_weight_field"):
            return source_contract.get("row_weight_field", ""), WEIGHT_BASIS_CONTRACT_ROW_WEIGHT

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
        source_row_weight_basis: str = "",
        source_contract: Dict[str, Any] = None,
        source_grain_type: str = "",
    ) -> tuple[float, str]:
        """Infer a row weight AND say what it was derived from.

        The basis is the point. This function can return `1.0` because the row
        declared a metric of 1, because it cited exactly one source, or because
        it carried no evidence whatsoever — three different facts wearing the
        same number. Reward and audit read these weights, so "no signal" and
        "no problem" arriving as the identical float is precisely the silent
        degradation the engine is not allowed to have.

        Basis tokens name their own dedup domain, so a within-row count is never
        mistakable for an across-rows one.
        """
        if source_row_weight_field:
            metric_value = self._extract_numeric_metric(item, source_row_weight_field)
            if metric_value is not None:
                # Carry the upstream's declared basis through rather than
                # replacing it. `contract_row_weight` alone would erase what the
                # upstream derived the number from, and there is a live path
                # where that erasure matters: PROJECT writes a defaulted 1.0
                # into a weight column and declares it, then COLLAPSE reads it
                # back — so a row with no evidence at all would arrive at the
                # second hop labelled as a real derivation.
                return float(metric_value), inherited_basis(
                    WEIGHT_BASIS_CONTRACT_ROW_WEIGHT, source_row_weight_basis
                )
        metric_value = self._extract_numeric_metric(item, resolved_metric_field)
        if metric_value is not None:
            return float(metric_value), WEIGHT_BASIS_RESOLVED_METRIC

        # Only read a nested row list as multiplicity when this row is NOT
        # itself a group. A COLLAPSE over already-collapsed rows would otherwise
        # read the inner `items` length as evidence weight and compound across
        # passes.
        if source_grain_type != "group":
            for list_field in ("item_ids", "items"):
                value = item.get(list_field)
                if isinstance(value, list) and value:
                    return float(len(value)), WEIGHT_BASIS_LIST_LENGTH

        refs = row_source_refs(item, contract=source_contract or {})
        if refs:
            return float(len(refs)), WEIGHT_BASIS_SOURCE_REF_COUNT_ROW

        return 1.0, WEIGHT_BASIS_NO_EVIDENCE_DEFAULT

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
        # Which derivations the projected weights came from. A projection whose
        # weights are all `no_evidence_default` must not declare a weight column
        # that reads downstream as evidence.
        projection_weight_bases: set[str] = set()
        for item in data:
            grain_rows = self._project_rows_for_grain(item, grain, field_specs, source_contract)
            for row in grain_rows:
                self._preserve_projection_identity(item, row, grain)
                if not row.get("id") and item.get("id"):
                    row["id"] = item["id"]
                if not preserve:
                    dedupe_key = tuple(row.get(key) for key in (key_specs or [alias for _, alias in field_specs]))
                    row["_collapse_key"] = dedupe_key
                if weight_field:
                    row[weight_field], row_weight_basis = self._infer_row_weight(
                        item, source_contract=source_contract
                    )
                    projection_weight_bases.add(row_weight_basis)
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
            grain_type=identity_meta["grain_type"],
            grain_keys=identity_meta["grain_keys"],
            multiplicity_preserved=identity_meta["multiplicity_preserved"],
            row_weight_field=weight_field,
            # Declared beside the weight column so a downstream reader inherits
            # what the number was derived from instead of only that some
            # upstream called it a weight. Mixed bases are reported as mixed;
            # collapsing them to one token would hide the weakest.
            row_weight_basis=combine_bases(projection_weight_bases),
            notes=[f"project_from={variable}"],
        ))
        # Explicit for the same reason as COLLAPSE below: an empty basis is
        # dropped by `merge_contract`, and a weight column inheriting the
        # source's basis would describe a derivation that did not happen here.
        contract["row_weight_basis"] = combine_bases(projection_weight_bases)
        # Columns PROJECT authored, known at authoring time rather than inferred
        # from their names. The field aliases come from the caller's FIELDS
        # clause and are deliberately NOT listed: they are the caller's
        # vocabulary, not the engine's.
        contract["engine_columns"] = sorted(
            {"row_id", *self._default_grain_keys(grain), *([weight_field] if weight_field else [])}
        )

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
        # The weight column counts CONTRIBUTING ROWS. It used to sum
        # `_infer_row_weight` per row into `occurrence_count`, which dedupes
        # chunk ids within one row and never across rows — so one source cited
        # by twelve rows contributed 12, and every downstream reader saw twelve
        # units of evidence where there was one. Repeats are propagation of one
        # source, not independent replication.
        weight_field = args.get("weight_field") or "contributing_rows"
        result_variable = args.get("result_variable") or variable

        data = self._get_variable_data(variable)
        if not data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {variable} not found or empty")
        source_contract = self.state_manager.get_variable_contract(variable) if self.state_manager else {}
        source_grain_type = str(source_contract.get("grain_type") or "")

        collapsed = {}
        for idx, item in enumerate(data):
            key = self._get_nested_field(item, by_field)
            if self._is_missing_collapse_key(key):
                key = self._fallback_collapse_key(item, idx)
            if key not in collapsed:
                collapsed[key] = {
                    "group_name": str(key),
                    "group_key": key,
                    by_field.split(".")[-1]: key,
                    "items": [],
                    weight_field: 0,
                }
            collapsed[key]["items"].append(item)
            collapsed[key][weight_field] += 1

        result_rows = list(collapsed.values())
        # Cross-row deduplication, before any provenance-derived number leaves
        # this command. COLLAPSE cannot tell a row that EVIDENCES the group key
        # from one that merely rode along — it inspects no field but the key —
        # so it reports the grain it actually has and does not invent a label
        # it cannot justify.
        collapse_evidence = {"groups": len(result_rows), "groups_without_evidence": 0}
        for row in result_rows:
            contributors = row["items"]
            refs = distinct_source_refs(contributors, contract=source_contract)
            no_evidence_contributors = 0
            for contributor in contributors:
                _weight, basis = self._infer_row_weight(
                    contributor,
                    source_row_weight_field=source_contract.get("row_weight_field", ""),
                    source_row_weight_basis=source_contract.get("row_weight_basis", ""),
                    source_contract=source_contract,
                    source_grain_type=source_grain_type,
                )
                if is_no_evidence(basis):
                    no_evidence_contributors += 1
            # `provenance_grain` is declared on the CONTRACT, not on each row.
            # It describes the whole payload rather than any one row, and a
            # constant repeated onto every row is read by
            # `question_pipeline.criteria._is_value_field` as a datapoint value,
            # which would mint a fabricated cell reading "contributing_row" for
            # every collapsed group. The other columns added here
            # (`contributing_rows`, `distinct_source_ref_count`, `source_refs`,
            # `contributors_without_evidence`) are already excluded there.
            #
            # A contributor with no provenance contributes no refs — adding it
            # as one would be the propagation defect reappearing in a new field
            # — but it is still a contributing row, and how many there were is
            # recorded so a mixed group is not read as fully evidenced.
            row["contributors_without_evidence"] = no_evidence_contributors
            if refs:
                # The deduplicated SET, not only its size. Credit joins by
                # stable id; a bare count joins to nothing.
                row["source_refs"] = refs
                row["distinct_source_ref_count"] = len(refs)
                row["distinct_source_refs_available"] = True
            else:
                # Explicit, at ROW level. Absence would be coerced to 0 by the
                # `.get(field, 0)` readers downstream, turning "we could not
                # look" into "we looked and found no sources".
                row["distinct_source_refs_available"] = False
                collapse_evidence["groups_without_evidence"] += 1

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
        # Every group carries a real cross-row-deduped evidence count, so that
        # column — never the row count — is what downstream RANK/SHOW/SELECT
        # order by.
        evidence_is_universal = collapse_evidence["groups_without_evidence"] == 0 and result_rows
        # When it is not universal the contract nominates NO metric field at
        # all. Falling back to the contributing-row count would make the run
        # rank by merge volume, which is operational throughput steering which
        # rows get pursued one hop upstream of reward — and it would do so
        # invisibly at every call site. No metric is the honest answer when
        # there is no evidence metric.
        collapse_metric_field = "distinct_source_ref_count" if evidence_is_universal else ""
        # Prose only, as in AGGREGATE above. `provenance_grain`, the
        # contributing-rows column name and the evidence metric are typed in
        # `collapse_diagnostics`; the sentences here explain them to a reader
        # and are not the only home of any of them.
        collapse_notes = [
            f"{weight_field} counts contributing rows, not evidence",
            "COLLAPSE cannot distinguish a row that evidences the group key from "
            "one that rode along on the same row, so its provenance grain is the "
            "contributing row",
        ]
        if not evidence_is_universal:
            collapse_notes.append(
                f"{collapse_evidence['groups_without_evidence']}/{collapse_evidence['groups']} "
                "groups have no cross-row-deduplicated source refs, so this contract "
                "nominates no metric field; do not rank these rows by "
                f"{weight_field!r}, which measures merge volume"
            )

        contract = merge_contract(source_contract, make_contract(
            payload_kind="collapsed_rows",
            data=result_rows,
            row_schema=identity_meta["row_schema"],
            label_field=by_field.split(".")[-1],
            metric_field=collapse_metric_field,
            scope="current_rows_only",
            usable_by=["AGGREGATE", "RANK", "SHOW", "SELECT"],
            grain_type=identity_meta["grain_type"],
            grain_keys=identity_meta["grain_keys"],
            multiplicity_preserved=identity_meta["multiplicity_preserved"],
            row_weight_field=collapse_metric_field,
            row_weight_basis=(
                WEIGHT_BASIS_SOURCE_REF_COUNT_GROUP if evidence_is_universal else ""
            ),
            notes=collapse_notes,
        ))
        # Set explicitly AFTER the merge. `merge_contract` skips empty values, so
        # nominating nothing would otherwise leave the SOURCE contract's
        # metric_field in place — collapsed group rows inheriting a metric that
        # described the pre-collapse rows, which is precisely the silent
        # fallback to a wrong number that constraint forbids.
        contract["notes"] = collapse_notes
        contract["metric_field"] = collapse_metric_field
        contract["row_weight_field"] = collapse_metric_field
        contract["row_weight_basis"] = (
            WEIGHT_BASIS_SOURCE_REF_COUNT_GROUP if evidence_is_universal else ""
        )
        contract["engine_columns"] = sorted(
            {
                "group_name",
                "group_key",
                "items",
                by_field.split(".")[-1],
                weight_field,
                "contributors_without_evidence",
                "distinct_source_refs_available",
                "distinct_source_ref_count",
                "source_refs",
            }
        )
        contract["collapse_diagnostics"] = {
            "provenance_grain": "contributing_row",
            "groups": collapse_evidence["groups"],
            "groups_without_evidence": collapse_evidence["groups_without_evidence"],
            "contributing_rows_field": weight_field,
            "evidence_metric_field": collapse_metric_field,
        }

        if self.state_manager:
            self.state_manager.store_variable_data(
                result_variable,
                result_rows,
                store_in_state=True,
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
    def _is_missing_collapse_key(key: Any) -> bool:
        return key is None or key == ""

    @staticmethod
    def _fallback_collapse_key(item: Dict[str, Any], idx: int) -> str:
        for field in ("row_id", "id"):
            value = item.get(field)
            if value not in (None, ""):
                return f"__missing_key__{field}:{value}"
        return f"__missing_key__index:{idx}"

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
        source_contract: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        base_row = {}
        for source_path, alias in field_specs:
            base_row[alias] = self._get_nested_field(item, source_path)
        if grain == "paper":
            papers = self._extract_source_refs(item, source_contract)
            if not papers:
                return [{**base_row, "paper_id": None}]
            return [{**base_row, "paper_id": paper_id} for paper_id in papers]
        if grain == "chunk":
            chunks = self._explode_csv_field(item, ["data.source_chunks", "source_chunks"])
            if not chunks:
                return [{**base_row, "chunk_id": None}]
            return [{**base_row, "chunk_id": chunk_id} for chunk_id in chunks]
        return [base_row]

    def _preserve_projection_identity(
        self,
        source: Dict[str, Any],
        row: Dict[str, Any],
        grain: str,
    ) -> None:
        if grain not in {"edge", "path"}:
            return

        for field in ("src_id", "tgt_id", "relation_type", "path_depth", "source_chunk"):
            if row.get(field) not in (None, ""):
                continue
            value = self._get_nested_field(source, field)
            if value not in (None, ""):
                row[field] = value

    def _explode_csv_field(self, item: Dict[str, Any], candidate_paths: List[str]) -> List[str]:
        for path in candidate_paths:
            value = self._get_nested_field(item, path)
            if isinstance(value, str) and value.strip():
                return [part.strip() for part in value.split(",") if part.strip()]
        return []

    def _extract_source_refs(
        self, item: Dict[str, Any], source_contract: Dict[str, Any] = None
    ) -> List[str]:
        return row_source_refs(item, contract=source_contract or {})
    
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
