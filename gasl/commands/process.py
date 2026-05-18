"""
PROCESS command handler.
"""

import os
import re
from typing import Any, List, Dict, Optional
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..validation import LLMJudgeValidator
from ..utils import normalize_node_id
from ..state_manager import StateManager
from ..process_runtime import (
    CandidateSelector,
    DerivedArtifactRegistry,
    ProcessSubtypeRouter,
)
from ..contracts import make_contract, merge_contract
from ..process_repair_prompting import format_process_repair_case
from ..prompt_observations import PromptObservationLogger


class ProcessHandler(CommandHandler):
    """Handles PROCESS commands for LLM-based data processing."""

    PROBE_THRESHOLD = 40
    MICROACTION_THRESHOLD = 24
    TOP_K_WORDS = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }

    def __init__(
        self,
        state_store,
        context_store,
        llm_func,
        micro_framework=None,
        state_manager=None,
        adapter=None,
        artifact_registry: Optional[DerivedArtifactRegistry] = None,
        prompt_logger: Optional[PromptObservationLogger] = None,
    ):
        super().__init__(state_store, context_store)
        self.llm_func = llm_func
        self.micro_framework = micro_framework
        self.validator = LLMJudgeValidator(llm_func)
        self.state_manager = state_manager or StateManager(state_store, context_store)
        self.adapter = adapter
        api_key = None
        if hasattr(llm_func, "_client_kwargs"):
            api_key = llm_func._client_kwargs.get("api_key")
        self.selector = CandidateSelector(
            graph=getattr(adapter, "graph", None),
            api_key=api_key,
        )
        self.subtype_router = ProcessSubtypeRouter()
        state_file = getattr(state_store, "state_file", None)
        self.artifact_registry = artifact_registry or DerivedArtifactRegistry(state_file=state_file)
        self.prompt_logger = prompt_logger
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "PROCESS"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute PROCESS command."""
        args = command.args
        variable = args["variable"]
        instruction = args["instruction"]
        target_variable = args.get("target_variable", variable)  # Default to same variable
        
        print(f"🔍 PROCESS DEBUG: execute called with variable='{variable}', target_variable='{target_variable}', instruction='{instruction[:100]}...'")
        
        # Use centralized state manager to get data
        self.state_manager.debug_variable_access(variable)
        data = self.state_manager.get_variable_data(variable, fallback_to_last_nodes=True)
        
        if not data:
            print(f"🔍 PROCESS DEBUG: No data found for variable '{variable}'")
            return self._create_result(
                command=command,
                status="error",
                error_message=f"Variable {variable} not found in context or state, and no last_nodes_result available"
            )
        
        print(f"🔍 PROCESS DEBUG: Retrieved data with length={len(data)}")
        
        print(f"🔍 PROCESS DEBUG: Data type: {type(data)}")
        if isinstance(data, list) and data:
            print(f"🔍 PROCESS DEBUG: First data item keys: {list(data[0].keys()) if isinstance(data[0], dict) else 'not a dict'}")
        elif isinstance(data, dict):
            print(f"🔍 PROCESS DEBUG: Data dict keys: {list(data.keys())}")

        query = (self.state_store.get_state().get("query") or "").strip()
        history = self.state_store.get_state().get("history", [])
        incoming_contract = self.state_manager.get_variable_contract(variable, fallback_to_last_nodes=True)
        initial_subtype = self.subtype_router.infer(instruction)
        interpretation = (
            self._interpret_process_context(data, query=query, instruction=instruction, history=history, incoming_contract=incoming_contract)
            if isinstance(data, list) and data
            else None
        )

        selection = (
            self.selector.select(
                data,
                query=query,
                instruction=instruction,
                subtype=initial_subtype,
                strategy_hint="stratified",
            )
            if isinstance(data, list)
            else None
        )

        diagnostics = selection.diagnostics if selection else {"strategy": "single"}
        subtype = initial_subtype
        final_instruction = self._apply_interpretation(instruction, interpretation)
        final_data = data
        diagnostics["routed_model"] = getattr(self._llm_for_subtype(initial_subtype), "model", getattr(self.llm_func, "model", None))
        if interpretation:
            diagnostics["interpretation"] = interpretation

        if selection and len(data) > self.PROBE_THRESHOLD:
            probe_result = self._run_process_batch(
                selection.probe_items,
                instruction,
                subtype=subtype,
                phase="probe",
            )
            subtype = self.subtype_router.confirm_from_result(initial_subtype, probe_result)
            final_instruction = self.selector.refine_instruction(instruction, probe_result, subtype)
            diagnostics["confirmed_subtype"] = subtype
            diagnostics["refined_instruction"] = final_instruction
            diagnostics["probe_result_count"] = len(
                probe_result.get("filtered_items") or probe_result.get("processed_items") or []
            )
            hit_density = diagnostics["probe_result_count"] / max(1, len(selection.probe_items))
            diagnostics["probe_hit_density"] = round(hit_density, 3)
            repair = None
            if self._should_attempt_repair(interpretation, hit_density):
                repair = self._repair_contract_and_strategy(
                    data=data,
                    query=query,
                    instruction=instruction,
                    history=history,
                    incoming_contract=incoming_contract,
                    interpretation=interpretation,
                    selection=selection,
                    probe_result=probe_result,
                )
            if repair:
                diagnostics["repair"] = repair
                final_instruction = repair.get("refined_instruction") or final_instruction
                selector_hint = repair.get("selector_hint", "keep_current")
                if selector_hint not in {"keep_current", ""}:
                    selection = self.selector.select(
                        data,
                        query=query,
                        instruction=final_instruction,
                        subtype=subtype,
                        strategy_hint=selector_hint,
                    )
                    diagnostics["strategy"] = selector_hint
                    probe_result = self._run_process_batch(
                        selection.probe_items,
                        final_instruction,
                        subtype=subtype,
                        phase="repair_probe",
                    )
                    diagnostics["repair_probe_result_count"] = len(
                        probe_result.get("filtered_items") or probe_result.get("processed_items") or []
                    )
            if self._should_stop_after_probe(data, instruction, probe_result, interpretation):
                top_k = self._requested_top_k(instruction) or 3
                final_data = self._ranked_head_window(data, top_k, interpretation)
                final_instruction = self._materialization_instruction(final_instruction, top_k)
                diagnostics["stopped_after_probe"] = True
                diagnostics["stop_reason"] = "ranked_topk_converged"
                diagnostics["final_window_size"] = len(final_data)
            else:
                final_data = self.selector.widen(
                    data,
                    probe_result,
                    selection,
                    query=query,
                    instruction=instruction,
                    subtype=subtype,
                )
        elif selection:
            final_data = selection.final_items

        # Use MicroActionFramework for batching if available
        if self.micro_framework and isinstance(final_data, list) and len(final_data) > self.MICROACTION_THRESHOLD:
            print(f"DEBUG: PROCESS - Using MicroActionFramework for {len(final_data)} items")
            original_llm = getattr(self.micro_framework, "llm_func", None)
            self.micro_framework.llm_func = self._llm_for_subtype(subtype)
            try:
                result = self.micro_framework.execute_command_with_batching(
                    data=final_data,
                    command_type="PROCESS",
                    instruction=final_instruction,
                    batch_size=None,
                    target_variable=target_variable
                )
            finally:
                self.micro_framework.llm_func = original_llm
            process_contract = self._build_process_contract(
                source_contract=incoming_contract,
                interpretation=interpretation,
                output_data=result.data.get("processed_items", []),
                subtype=subtype,
                strategy=diagnostics.get("strategy", ""),
            )
            self.state_manager.store_variable_contract(target_variable, process_contract, store_in_state=True, store_in_context=True)
            result.contract = process_contract
            self._record_artifact_candidate(
                variable=variable,
                target_variable=target_variable,
                instruction=instruction,
                subtype=subtype,
                diagnostics=diagnostics,
                final_result=result,
                source_size=len(data) if isinstance(data, list) else 1,
                final_size=len(final_data) if isinstance(final_data, list) else 1,
            )
            return result

        print(f"DEBUG: PROCESS - Processing {len(final_data) if isinstance(final_data, list) else 1} items normally")
        result = self._execute_single_batch(final_data, final_instruction, command, target_variable, subtype=subtype)
        self._record_artifact_candidate(
            variable=variable,
            target_variable=target_variable,
            instruction=instruction,
            subtype=subtype,
            diagnostics=diagnostics,
            final_result=result,
            source_size=len(data) if isinstance(data, list) else 1,
            final_size=len(final_data) if isinstance(final_data, list) else 1,
        )
        return result
    
    def _execute_single_batch(
        self,
        data: Any,
        instruction: str,
        command: Command,
        target_variable: str,
        *,
        subtype: str,
    ) -> ExecutionResult:
        """Execute PROCESS on a single batch (original logic)."""
        result = self._run_process_batch(data, instruction, subtype=subtype, phase="main")
        normalized_items = self._normalized_items(result)
        print(f"🔍 PROCESS DEBUG: Parsed result keys: {list(result.keys())}")
        print(f"🔍 PROCESS DEBUG: processed_items length: {len(normalized_items)}")
        print(f"🔍 PROCESS DEBUG: processing_method: {result.get('processing_method', 'unknown')}")
        
        # Store results in target variable
        print(f"🔍 PROCESS DEBUG: About to store {len(normalized_items)} items in {target_variable}")
        if normalized_items:
            print(f"🔍 PROCESS DEBUG: First item keys: {list(normalized_items[0].keys()) if normalized_items[0] else 'empty'}")
        
        self._store_processed_data(target_variable, normalized_items)
        print(f"DEBUG: PROCESS - Updated {target_variable} with {len(normalized_items)} processed items using {result.get('processing_method', 'unknown')} method")
        
        # Store full result in context
        result_key = f"process_{command.args['variable']}_{len(self.context_store.keys())}"
        self.context_store.set(result_key, result)
        
        # Create provenance
        provenance = [
            self._create_provenance(
                source_id="llm-process",
                method="process",
                variable=command.args["variable"],
                instruction=instruction,
                model="llm",
                process_subtype=subtype,
            )
        ]
        
        # Determine status based on actual work done
        status = "success" if len(normalized_items) > 0 else "empty"
        
        # Create initial result
        process_contract = self._build_process_contract(
            source_contract=self.state_manager.get_variable_contract(command.args["variable"], fallback_to_last_nodes=True),
            interpretation=None,
            output_data=normalized_items,
            subtype=subtype,
            strategy="single_batch",
        )
        self.state_manager.store_variable_contract(target_variable, process_contract, store_in_state=True, store_in_context=True)
        result_obj = self._create_result(
            command=command,
            status=status,
            data=normalized_items,
            count=len(normalized_items),
            provenance=provenance,
            contract=process_contract,
        )
        
        # Validate with LLM judge if available
        if self.validator and status == "success":
            validation = self.validator.validate_command_success(
                command.command_type, command.args, normalized_items, len(normalized_items)
            )
            
            if not validation.get("valid", True):
                # Override status if LLM judge says it failed
                result_obj.status = "error"
                result_obj.error_message = f"LLM Judge Validation Failed: {validation.get('reason', 'Unknown validation failure')}"
                print(f"DEBUG: PROCESS - LLM Judge validation failed: {validation}")
            else:
                print(f"DEBUG: PROCESS - LLM Judge validation passed: {validation.get('reason', 'Valid')}")
        
        return result_obj

    @staticmethod
    def _normalized_items(result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return the row/list payload downstream commands should see."""
        if result.get("processing_method") == "filter":
            return result.get("filtered_items", [])
        return result.get("processed_items", [])

    def _run_process_batch(self, data: Any, instruction: str, *, subtype: str, phase: str) -> Dict[str, Any]:
        prompt = self._create_process_prompt(data, instruction)
        llm = self._llm_for_subtype(subtype)
        llm_response = llm.call(prompt)
        print(f"DEBUG: PROCESS ({phase}/{subtype}) - LLM Response:\n{llm_response}\n")
        return self._parse_process_response(llm_response, data)

    def _llm_for_subtype(self, subtype: str):
        if hasattr(self.llm_func, "clone"):
            routed_model = self.subtype_router.routed_model(getattr(self.llm_func, "model", ""), subtype)
            reasoning_effort = "low" if subtype in {"semantic_filter", "field_derivation"} else None
            if routed_model and routed_model != getattr(self.llm_func, "model", ""):
                return self.llm_func.clone(model=routed_model, reasoning_effort=reasoning_effort)
            if reasoning_effort and getattr(self.llm_func, "reasoning_effort", None) != reasoning_effort:
                return self.llm_func.clone(reasoning_effort=reasoning_effort)
        return self.llm_func

    def _llm_for_interpretation(self):
        if hasattr(self.llm_func, "clone"):
            current_model = getattr(self.llm_func, "model", "")
            large_model = self.subtype_router.routed_model(current_model, "cross_node_synthesis")
            reasoning_effort = os.getenv("PROCESS_INTERPRET_REASONING", "high")
            if large_model != current_model or getattr(self.llm_func, "reasoning_effort", None) != reasoning_effort:
                return self.llm_func.clone(model=large_model, reasoning_effort=reasoning_effort)
        return self.llm_func

    def _interpret_process_context(
        self,
        data: List[Dict[str, Any]],
        *,
        query: str,
        instruction: str,
        history: List[Dict[str, Any]],
        incoming_contract: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            llm = self._llm_for_interpretation()
            prompt = self._create_interpretation_prompt(data, query=query, instruction=instruction, history=history, incoming_contract=incoming_contract)
            obs_id = None
            if self.prompt_logger:
                obs_id = self.prompt_logger.record_invocation(
                    prompt_name="process_interpretation",
                    prompt_text=prompt,
                    model=getattr(llm, "model", None),
                    metadata={"query": query, "instruction": instruction},
                )
            raw = llm.call(prompt)
            parsed = self._parse_interpretation_response(raw)
            if self.prompt_logger and obs_id:
                self.prompt_logger.record_outcome(
                    obs_id,
                    prompt_name="process_interpretation",
                    response_text=raw,
                    parsed=parsed,
                    labels={"parse_success": bool(parsed)},
                )
            return parsed
        except Exception as exc:
            print(f"DEBUG: PROCESS interpretation skipped: {exc}")
            return None

    def _apply_interpretation(self, instruction: str, interpretation: Optional[Dict[str, Any]]) -> str:
        if not interpretation:
            return instruction
        contract = (interpretation.get("output_contract") or "").strip()
        if not contract:
            return instruction
        return f"{instruction}\nContract: {contract}"

    @staticmethod
    def _should_attempt_repair(interpretation: Optional[Dict[str, Any]], hit_density: float) -> bool:
        if interpretation is None:
            return True
        if interpretation.get("confidence", 0.0) < 0.65:
            return True
        if hit_density < 0.2:
            return True
        return False

    def _repair_contract_and_strategy(
        self,
        *,
        data: List[Dict[str, Any]],
        query: str,
        instruction: str,
        history: List[Dict[str, Any]],
        incoming_contract: Dict[str, Any],
        interpretation: Optional[Dict[str, Any]],
        selection,
        probe_result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        try:
            llm = self._llm_for_interpretation()
            prompt = self._create_repair_prompt(
                data=data,
                query=query,
                instruction=instruction,
                history=history,
                incoming_contract=incoming_contract,
                interpretation=interpretation,
                selection=selection,
                probe_result=probe_result,
            )
            obs_id = None
            if self.prompt_logger:
                obs_id = self.prompt_logger.record_invocation(
                    prompt_name="process_repair",
                    prompt_text=prompt,
                    model=getattr(llm, "model", None),
                    metadata={
                        "query": query,
                        "instruction": instruction,
                        "probe_result_count": len(probe_result.get("filtered_items") or probe_result.get("processed_items") or []),
                    },
                )
            raw = llm.call(prompt)
            parsed = self._parse_repair_response(raw)
            if self.prompt_logger and obs_id:
                self.prompt_logger.record_outcome(
                    obs_id,
                    prompt_name="process_repair",
                    response_text=raw,
                    parsed=parsed,
                    labels={
                        "parse_success": bool(parsed),
                        "current_rows_sufficient": parsed.get("current_rows_sufficient"),
                        "selector_valid": parsed.get("selector_hint") in {"keep_current", "lexical", "vector", "central", "broaden", "narrow"},
                    },
                )
            return parsed
        except Exception as exc:
            print(f"DEBUG: PROCESS repair skipped: {exc}")
            return None

    def _record_artifact_candidate(
        self,
        *,
        variable: str,
        target_variable: str,
        instruction: str,
        subtype: str,
        diagnostics: Dict[str, Any],
        final_result: ExecutionResult,
        source_size: int,
        final_size: int,
    ) -> None:
        try:
            state = self.state_store.get_state()
            graph_version = None
            if self.adapter is not None and hasattr(self.adapter, "versioned_graph"):
                graph_version = getattr(self.adapter.versioned_graph, "current_version", None)
            self.artifact_registry.record_candidate({
                "query": state.get("query", ""),
                "variable": variable,
                "target_variable": target_variable,
                "instruction": instruction,
                "subtype": subtype,
                "source_size": source_size,
                "final_size": final_size,
                "graph_version": graph_version,
                "model": getattr(self.llm_func, "model", None),
                "status": final_result.status,
                "result_count": final_result.count,
                "diagnostics": diagnostics,
            })
        except Exception as exc:
            print(f"DEBUG: PROCESS artifact logging skipped: {exc}")
    
    def _store_processed_data(self, target_variable: str, processed_data: List[Dict]) -> None:
        """Store processed data in the target variable."""
        print(f"🔍 PROCESS DEBUG: _store_processed_data called with target_variable='{target_variable}', processed_data length={len(processed_data)}")
        
        # Extract the new fields from processed_data and merge them back into original structure
        integrated_data = self._integrate_processed_fields(processed_data)
        print(f"🔍 PROCESS DEBUG: integrated_data length={len(integrated_data)}")
        
        # Use centralized state manager to store data
        self.state_manager.store_variable_data(
            target_variable, 
            integrated_data, 
            store_in_state=True, 
            store_in_context=True,
            description=f"Processed data from {target_variable}"
        )
    
    def _integrate_processed_fields(self, processed_data: List[Dict]) -> List[Dict]:
        """Integrate processed fields back into the original data structure."""
        integrated = []
        
        print(f"🔍 INTEGRATE DEBUG: Processing {len(processed_data)} items")
        if processed_data:
            print(f"🔍 INTEGRATE DEBUG: First item keys: {list(processed_data[0].keys())}")
        
        for item in processed_data:
            if isinstance(item, dict):
                # For filtering responses, just return the item as-is since it already contains the relevant data
                # The LLM has already filtered and included the relevant items
                integrated_item = {}
                
                # Copy all fields except metadata fields
                for key, value in item.items():
                    if key not in ['reason']:  # Skip reason field but keep everything else
                        integrated_item[key] = value
                
                integrated.append(integrated_item)
            else:
                integrated.append(item)
        
        print(f"🔍 INTEGRATE DEBUG: Final integrated data length: {len(integrated)}")
        return integrated
    
    def _determine_field_name(self, item: Dict) -> str:
        """Determine the appropriate field name for the processed field."""
        # For first name extraction, use 'first_name'
        if 'reason' in item and 'first name' in item['reason'].lower():
            return 'first_name'
        
        # For other processing, use a generic name
        return 'processed_value'
    
    def _create_process_prompt(self, data: Any, instruction: str) -> str:
        """Create prompt for LLM processing."""
        prompt = f"""You are processing graph data according to this instruction: {instruction}

Data to process (list of nodes):
{self._format_data_for_llm(data)}

Instructions:
1. Analyze each node's content (name, description, properties) according to the instruction
2. If the instruction asks to FILTER or SELECT nodes, return a JSON object with this structure:
{{
  "included": [
    {{"id": "node_id", "name": "node_name", "reason": "why included"}},
    ...
  ],
  "excluded": [
    {{"id": "node_id", "name": "node_name", "reason": "why excluded"}},
    ...
  ],
  "summary": {{
    "total_analyzed": 0,
    "included_count": 0,
    "excluded_count": 0,
    "categories_found": []
  }}
}}

3. If the instruction asks to CALCULATE, COUNT, or ADD FIELDS, return a JSON object with this structure:
{{
  "processed_items": [
    {{"id": "node_id", "name": "node_name", "calculated_field": "value", "reason": "explanation"}},
    ...
  ],
  "summary": {{
    "total_processed": 0,
    "calculation_type": "description of what was calculated",
    "fields_added": ["list", "of", "new", "fields"]
  }}
}}

Be thorough in your analysis and provide clear reasoning for each decision.
"""
        return prompt

    def _create_interpretation_prompt(
        self,
        data: List[Dict[str, Any]],
        *,
        query: str,
        instruction: str,
        history: List[Dict[str, Any]],
        incoming_contract: Optional[Dict[str, Any]],
    ) -> str:
        sample_rows = [self._flatten_row(row) for row in data[:8]]
        history_tail = history[-4:] if history else []
        return f"""You are interpreting the current PROCESS context.

User query:
{query}

Current PROCESS instruction:
{instruction}

Recent workflow history:
{history_tail}

Incoming contract:
{incoming_contract or {}}

Sample current rows (flattened):
{sample_rows}

Return strict JSON with this schema:
{{
  "label_field": "<dotted field path or empty string>",
  "metric_field": "<dotted field path or empty string>",
  "ordered": true,
  "order_basis": "<what the current row order most likely means>",
  "order_field": "<dotted field path or empty string>",
  "order_direction": "asc|desc|unknown",
  "scope": "current_rows_only|needs_recompute|unknown",
  "output_contract": "<short imperative contract for the PROCESS step>",
  "confidence": 0.0
}}

Rules:
- Base the answer only on the current rows and recent workflow history.
- If the rows already look ordered or ranked, say so explicitly.
- If the PROCESS should only materialize from the current rows, set scope=current_rows_only.
- Do not answer the user query. Interpret the data shape and instruction only.
"""

    def _create_repair_prompt(
        self,
        *,
        data: List[Dict[str, Any]],
        query: str,
        instruction: str,
        history: List[Dict[str, Any]],
        incoming_contract: Dict[str, Any],
        interpretation: Optional[Dict[str, Any]],
        selection,
        probe_result: Dict[str, Any],
    ) -> str:
        from nano_graphrag.prompt_system import get_prompt_system
        base_prompt = get_prompt_system().get_prompt("process_repair", optimize=False)
        case_text = format_process_repair_case(
            data=data,
            query=query,
            instruction=instruction,
            history=history,
            incoming_contract=incoming_contract,
            interpretation=interpretation,
            selection_diagnostics=selection.diagnostics,
            probe_result=probe_result,
        )
        return f"{base_prompt}\n\n{case_text}"

    def _format_data_for_llm(self, data: Any) -> str:
        """Format data for LLM consumption."""
        if not isinstance(data, list):
            return str(data)
        
        # Limit to first 20 items to avoid token limits
        sample_data = data[:20]
        formatted = []
        
        for i, item in enumerate(sample_data):
            if isinstance(item, dict):
                node_id = item.get('id', f'item_{i}')

                # Handle nested data structure from FIND command
                if 'data' in item and isinstance(item['data'], dict):
                    node_data = item['data']
                    name = node_id
                    description = node_data.get('description', 'No description')
                    entity_type = node_data.get('entity_type', 'Unknown')
                else:
                    # Handle flat structure
                    name = self._primary_label(item) or node_id
                    description = item.get('description', 'No description')
                    entity_type = item.get('entity_type', 'Unknown')
                
                formatted.append(f"Node {i+1} ({node_id}):")
                formatted.append(f"  Name: {name}")
                formatted.append(f"  Entity Type: {entity_type}")
                formatted.append(f"  Description: {description}")
                for field_name, field_value in self._scalar_preview(item):
                    formatted.append(f"  {field_name}: {field_value}")
                formatted.append("")
        
        if len(data) > 20:
            formatted.append(f"... and {len(data) - 20} more items")
        
        return "\n".join(formatted)

    @classmethod
    def _requested_top_k(cls, instruction: str) -> Optional[int]:
        text = (instruction or "").lower()
        numeric = re.search(r"\btop\s+(\d+)\b", text)
        if numeric:
            return int(numeric.group(1))
        for word, value in cls.TOP_K_WORDS.items():
            if re.search(rf"\btop\s+{word}\b", text):
                return value
        return None

    @staticmethod
    def _item_labels(item: Dict[str, Any], interpretation: Optional[Dict[str, Any]] = None) -> set[str]:
        if not isinstance(item, dict):
            return set()
        labels = set()
        label_field = (interpretation or {}).get("label_field", "")
        if label_field:
            value = ProcessHandler._get_by_path(item, label_field)
            if value is not None:
                text = str(value).strip().lower()
                if text:
                    labels.add(text)
        for _, value in ProcessHandler._iter_scalar_fields(item):
            label = str(value).strip().lower()
            if label:
                labels.add(label)
        return labels

    @staticmethod
    def _iter_scalar_fields(item: Any, prefix: str = "", *, depth: int = 0, max_depth: int = 2):
        if depth > max_depth:
            return
        if isinstance(item, dict):
            for key, value in item.items():
                next_prefix = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, (str, int, float, bool)):
                    yield next_prefix, value
                elif isinstance(value, dict):
                    yield from ProcessHandler._iter_scalar_fields(value, next_prefix, depth=depth + 1, max_depth=max_depth)
        elif isinstance(item, (str, int, float, bool)):
            yield prefix or "value", item

    @staticmethod
    def _scalar_preview(item: Dict[str, Any], *, limit: int = 6) -> List[tuple[str, Any]]:
        preview = []
        for field_name, field_value in ProcessHandler._iter_scalar_fields(item):
            if field_name in {"id", "description"}:
                continue
            preview.append((field_name, field_value))
            if len(preview) >= limit:
                break
        return preview

    @staticmethod
    def _primary_label(item: Dict[str, Any]) -> str:
        for field_name, field_value in ProcessHandler._iter_scalar_fields(item):
            if field_name.endswith(".description") or field_name == "description":
                continue
            text = str(field_value).strip()
            if text and len(text) <= 120:
                return text
        return ""

    @staticmethod
    def _flatten_row(item: Dict[str, Any], *, limit: int = 16) -> Dict[str, Any]:
        flattened: Dict[str, Any] = {}
        for field_name, field_value in ProcessHandler._iter_scalar_fields(item):
            flattened[field_name] = field_value
            if len(flattened) >= limit:
                break
        return flattened

    @staticmethod
    def _parse_interpretation_response(text: str) -> Dict[str, Any]:
        try:
            import json
            payload = json.loads(ProcessHandler._strip_json_fences(text))
            return {
                "label_field": str(payload.get("label_field", "") or ""),
                "metric_field": str(payload.get("metric_field", "") or ""),
                "ordered": bool(payload.get("ordered", False)),
                "order_basis": str(payload.get("order_basis", "") or ""),
                "order_field": str(payload.get("order_field", "") or ""),
                "order_direction": str(payload.get("order_direction", "unknown") or "unknown"),
                "scope": str(payload.get("scope", "unknown") or "unknown"),
                "output_contract": str(payload.get("output_contract", "") or ""),
                "confidence": float(payload.get("confidence", 0.0) or 0.0),
            }
        except Exception:
            return {
                "label_field": "",
                "metric_field": "",
                "ordered": False,
                "order_basis": "",
                "order_field": "",
                "order_direction": "unknown",
                "scope": "unknown",
                "output_contract": "",
                "confidence": 0.0,
            }

    @staticmethod
    def _parse_repair_response(text: str) -> Dict[str, Any]:
        try:
            import json
            payload = json.loads(ProcessHandler._strip_json_fences(text))
            return {
                "refined_instruction": str(payload.get("refined_instruction", "") or ""),
                "selector_hint": str(payload.get("selector_hint", "keep_current") or "keep_current"),
                "current_rows_sufficient": bool(payload.get("current_rows_sufficient", True)),
                "confidence": float(payload.get("confidence", 0.0) or 0.0),
                "reason": str(payload.get("reason", "") or ""),
            }
        except Exception:
            return {}

    @staticmethod
    def _get_by_path(item: Any, path: str) -> Any:
        if not path:
            return None
        current = item
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    @classmethod
    def _rows_are_ranked(cls, data: Any, interpretation: Optional[Dict[str, Any]] = None) -> bool:
        if not isinstance(data, list):
            return False
        if interpretation and interpretation.get("ordered") and interpretation.get("scope") == "current_rows_only":
            return True
        return any(isinstance(item, dict) and "rank" in item for item in data)

    @classmethod
    def _ranked_head_window(
        cls,
        data: List[Dict[str, Any]],
        top_k: int,
        interpretation: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        rows = [item for item in data if isinstance(item, dict)]
        order_field = (interpretation or {}).get("order_field", "")
        order_direction = (interpretation or {}).get("order_direction", "unknown")
        if order_field:
            def sort_key(item):
                value = cls._get_by_path(item, order_field)
                try:
                    return float(value)
                except Exception:
                    return str(value)
            ranked = sorted(rows, key=sort_key, reverse=(order_direction == "desc"))
        else:
            ranked = sorted(rows, key=lambda item: int(item.get("rank", 10**9)))
        window = max(top_k * 2, top_k + 3)
        return ranked[: min(len(ranked), window)]

    @classmethod
    def _should_stop_after_probe(
        cls,
        data: Any,
        instruction: str,
        probe_result: Dict[str, Any],
        interpretation: Optional[Dict[str, Any]] = None,
    ) -> bool:
        top_k = cls._requested_top_k(instruction)
        if not top_k or not cls._rows_are_ranked(data, interpretation):
            return False
        if interpretation and interpretation.get("confidence", 0.0) < 0.5:
            return False
        ranked_head = cls._ranked_head_window(data, top_k, interpretation)[:top_k]
        if len(ranked_head) < top_k:
            return False
        positives = probe_result.get("filtered_items") or probe_result.get("processed_items") or []
        if not positives:
            return False
        positive_labels = set().union(*(cls._item_labels(item, interpretation) for item in positives if isinstance(item, dict)))
        if not positive_labels:
            return False
        for row in ranked_head:
            if cls._item_labels(row, interpretation).isdisjoint(positive_labels):
                return False
        return True

    @classmethod
    def _materialization_instruction(cls, instruction: str, top_k: int) -> str:
        return (
            f"{instruction}\n"
            f"The input rows are already globally ranked. Materialize exactly the top {top_k} rows "
            "from this ranked list, preserve their order, and do not expand beyond the provided ranked window."
        )

    def _build_process_contract(
        self,
        *,
        source_contract: Dict[str, Any],
        interpretation: Optional[Dict[str, Any]],
        output_data: List[Dict[str, Any]],
        subtype: str,
        strategy: str,
    ) -> Dict[str, Any]:
        payload_kind = {
            "semantic_filter": "filtered_rows",
            "field_derivation": "derived_rows",
            "classification": "classified_rows",
            "cross_node_synthesis": "synthesized_rows",
        }.get(subtype, "processed_rows")
        inferred = make_contract(
            payload_kind=payload_kind,
            data=output_data,
            label_field=(interpretation or {}).get("label_field", source_contract.get("label_field", "")),
            metric_field=(interpretation or {}).get("metric_field", source_contract.get("metric_field", "")),
            ordered=(interpretation or {}).get("ordered", source_contract.get("ordered", False)),
            order_basis=(interpretation or {}).get("order_basis", source_contract.get("order_basis", "")),
            order_field=(interpretation or {}).get("order_field", source_contract.get("order_field", "")),
            order_direction=(interpretation or {}).get("order_direction", source_contract.get("order_direction", "unknown")),
            scope=(interpretation or {}).get("scope", "current_rows_only"),
            usable_by=["PROCESS", "AGGREGATE", "RANK", "SHOW", "SELECT"],
            confidence=(interpretation or {}).get("confidence", 0.8),
            strategy=strategy,
        )
        return merge_contract(source_contract, inferred)
    
    @staticmethod
    def _strip_json_fences(text: str) -> str:
        import re
        text = text.strip()
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        return match.group(1).strip() if match else text

    def _parse_process_response(self, llm_response: str, original_data: Any) -> Dict[str, Any]:
        """Parse LLM response for PROCESS command."""
        try:
            import json

            response_data = json.loads(self._strip_json_fences(llm_response))
            
            # Handle different response formats
            if "included" in response_data and "excluded" in response_data:
                # Filtering response format
                return {
                    "filtered_items": response_data.get("included", []),
                    "excluded_items": response_data.get("excluded", []),
                    "summary": response_data.get("summary", {}),
                    "processing_method": "filter"
                }
            elif "processed_items" in response_data:
                # Processing response format
                return {
                    "processed_items": response_data.get("processed_items", []),
                    "summary": response_data.get("summary", {}),
                    "processing_method": "process"
                }
            elif "extracted_authors" in response_data:
                # Special case for author extraction
                return {
                    "processed_items": response_data.get("extracted_authors", []),
                    "summary": response_data.get("summary", {}),
                    "processing_method": "extract_authors"
                }
            else:
                # Fallback - treat as processed items
                return {
                    "processed_items": [response_data] if isinstance(response_data, dict) else [],
                    "summary": {"total_processed": 1},
                    "processing_method": "fallback"
                }
                
        except json.JSONDecodeError:
            # If JSON parsing fails, try to extract information from text
            return {
                "processed_items": [],
                "summary": {"error": "Failed to parse LLM response as JSON"},
                "processing_method": "error"
            }
        except Exception as e:
            return {
                "processed_items": [],
                "summary": {"error": f"Error parsing response: {str(e)}"},
                "processing_method": "error"
            }

    def _find_original_node(self, data: list, target_id: str) -> dict:
        """Find the original node data by matching the ID with quote normalization."""
        if not isinstance(data, list):
            return None
        
        target_normalized = normalize_node_id(target_id)
        for node in data:
            if isinstance(node, dict):
                node_id = node.get("id")
                if node_id and normalize_node_id(node_id) == target_normalized:
                    return node
        return None
