"""
Main execution engine for GASL system.
"""

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path


def _extract_json(text: str) -> str:
    """Extract a JSON object/array from LLM output, tolerating markdown fences
    and any prose before/after. OpenAI models (notably gpt-4o-mini) often wrap
    JSON in ```json ... ``` blocks; the original Argo gpt41 typically did not."""
    s = text.strip()
    # Strip a leading ``` or ```json fence (any language tag)
    if s.startswith('```'):
        nl = s.find('\n')
        if nl >= 0:
            s = s[nl + 1:]
        end = s.rfind('```')
        if end >= 0:
            s = s[:end]
        s = s.strip()
    # If there's still prose before the JSON, jump to the first { or [
    if s and s[0] not in '{[':
        starts = [i for i in (s.find('{'), s.find('[')) if i >= 0]
        if starts:
            s = s[min(starts):]
    if not s or s[0] not in '{[':
        return s

    # If the model emitted multiple JSON objects back-to-back, keep only the
    # first balanced one so the downstream json parser sees a single object.
    open_ch = s[0]
    close_ch = '}' if open_ch == '{' else ']'
    depth = 0
    in_str = False
    escape = False
    for idx, ch in enumerate(s):
        if in_str:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return s[:idx + 1]
    return s


from .types import PlanObject, Command, ExecutionResult, HistoryEntry, StateSnapshot, Provenance
from .parser import GASLParser
from .state import StateStore, ContextStore
from .state_manager import StateManager
from .adapters import GraphAdapter
from .commands import (
    DeclareHandler, FindHandler, ProcessHandler, ClassifyHandler, UpdateHandler, CountHandler, DebugHandler,
    AnalyzeHandler, SelectHandler, SetHandler, RequireHandler,
    AssertHandler, OnHandler, TryCatchHandler, CancelHandler,
    GraphNavHandler, MultiVarHandler, DataTransformHandler, 
    FieldCalcHandler, ObjectCreateHandler, PatternAnalysisHandler
)
from .commands.add_field import AddFieldHandler
from .commands.create_nodes import CreateNodesHandler
from .commands.create_edges import CreateEdgesHandler
from .commands.create_groups import CreateGroupsHandler
from .commands.iterate import IterateHandler
from .micro_actions import MicroActionFramework
from .errors import ExecutionError, ParseError
from .trace import GASLTraceLogger
from .answer_layer import AnswerLayerCompiler, DeterministicAnswerFinalizer
from .prompt_observations import PromptObservationLogger
from .plan_iteration_agent import PlanIterationAgent, PlanIterationRequest


class GASLExecutor:
    """Main execution engine for GASL plans."""
    
    def __init__(self, adapter: GraphAdapter, llm_func, state_file: str = None,
                 job_id: str = None):
        self.adapter = adapter
        self.llm_func = llm_func
        self.parser = GASLParser()
        self.state_store = StateStore(state_file)
        self.context_store = ContextStore()
        self.state_manager = StateManager(self.state_store, self.context_store)

        # Get versioned graph from adapter if available
        versioned_graph = getattr(adapter, 'versioned_graph', None)

        # Initialize micro-action framework with job_id for checkpointing
        self.micro_framework = MicroActionFramework(
            llm_func, self.state_store, self.context_store, job_id=job_id
        )
        trace_base_dir = Path(state_file).parent if state_file else Path.cwd()
        self.trace = GASLTraceLogger(trace_base_dir, job_id=job_id)
        self.prompt_obs = PromptObservationLogger(trace_base_dir, job_id=job_id)
        self.plan_iteration_agent = PlanIterationAgent(self.llm_func, prompt_logger=self.prompt_obs, trace=self.trace)
        self.trace.log("executor_init", {
            "model": getattr(llm_func, "model", None),
            "state_file": str(state_file) if state_file else None,
            "adapter": type(adapter).__name__,
        })
        
        # Pass versioned graph to micro framework
        if versioned_graph:
            self.micro_framework.versioned_graph = versioned_graph
        
        # Initialize command handlers with centralized state manager
        self.handlers = [
            # Core commands
            DeclareHandler(self.state_store, self.context_store, self.state_manager),
            FindHandler(self.state_store, self.context_store, adapter, llm_func, self.state_manager),
            ProcessHandler(
                self.state_store,
                self.context_store,
                llm_func,
                self.micro_framework,
                self.state_manager,
                adapter=adapter,
                prompt_logger=self.prompt_obs,
            ),
            ClassifyHandler(self.state_store, self.context_store, llm_func, self.state_manager),
            UpdateHandler(self.state_store, self.context_store, self.state_manager),
            CountHandler(self.state_store, self.context_store, llm_func, self.state_manager),
            DebugHandler(self.state_store, self.context_store, self.state_manager),
            
            # Graph modification commands
            AddFieldHandler(self.state_store, self.context_store, llm_func, self.state_manager),
            CreateNodesHandler(self.state_store, self.context_store, adapter, llm_func, self.state_manager),
            CreateEdgesHandler(self.state_store, self.context_store, adapter, llm_func, self.state_manager),
            CreateGroupsHandler(self.state_store, self.context_store, adapter, llm_func, self.state_manager),
            IterateHandler(self.state_store, self.context_store, self.micro_framework, self.state_manager),
            
            # New command categories
            GraphNavHandler(self.state_store, self.context_store, adapter, llm_func, self.state_manager),
            MultiVarHandler(self.state_store, self.context_store, self.state_manager),
            DataTransformHandler(self.state_store, self.context_store, llm_func, self.state_manager),
            FieldCalcHandler(self.state_store, self.context_store, llm_func, self.state_manager),
            ObjectCreateHandler(self.state_store, self.context_store, llm_func, self.state_manager),
            PatternAnalysisHandler(self.state_store, self.context_store, llm_func, self.state_manager),
            
            # Control flow commands
            AnalyzeHandler(self.state_store, self.context_store, llm_func, self.state_manager),
            SelectHandler(self.state_store, self.context_store, self.state_manager),
            SetHandler(self.state_store, self.context_store, self.state_manager),
            RequireHandler(self.state_store, self.context_store, self.state_manager),
            AssertHandler(self.state_store, self.context_store, self.state_manager),
            OnHandler(self.state_store, self.context_store, self.state_manager),
            TryCatchHandler(self.state_store, self.context_store, self.state_manager),
            CancelHandler(self.state_store, self.context_store, self.state_manager)
        ]
    
    def execute_plan(self, plan_json: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a complete plan."""
        try:
            # Parse plan
            plan = PlanObject.from_dict(plan_json)
            commands = self.parser.parse_plan(plan_json)
            
            # Set query and config in state
            self.state_store.set_query(plan_json.get("query", ""))
            self.state_store.set_config(plan_json.get("config", {}))
            
            # Execute commands
            results = []
            previous_result: Optional[ExecutionResult] = None
            for i, command in enumerate(commands):
                step_id = f"{plan.plan_id}-step-{i+1}"
                if command.command_type == "ON":
                    on_result, nested_result = self._execute_on(command, step_id, previous_result)
                    results.append(on_result)
                    self.state_store.add_history_entry(HistoryEntry(
                        step_id=step_id,
                        command=command.raw_text,
                        status=on_result.status,
                        result_count=on_result.count,
                        duration_ms=on_result.duration_ms,
                        timestamp=on_result.timestamp,
                        error_message=on_result.error_message,
                        provenance=on_result.provenance,
                    ))
                    if nested_result is not None:
                        results.append(nested_result)
                        nested_step_id = f"{step_id}.action"
                        self.state_store.add_history_entry(HistoryEntry(
                            step_id=nested_step_id,
                            command=nested_result.command,
                            status=nested_result.status,
                            result_count=nested_result.count,
                            duration_ms=nested_result.duration_ms,
                            timestamp=nested_result.timestamp,
                            error_message=nested_result.error_message,
                            provenance=nested_result.provenance,
                        ))
                        previous_result = nested_result
                        if nested_result.status == "error" and plan.config.get("stop_on_error", True):
                            break
                        elif nested_result.status == "empty" and not plan.config.get("continue_on_empty", False):
                            break
                    else:
                        previous_result = on_result
                    continue

                result = self._execute_command(command, step_id)
                results.append(result)
                
                # Add to history
                artifact = self._build_produced_artifact(command, result)
                history_entry = HistoryEntry(
                    step_id=step_id,
                    command=command.raw_text,
                    status=result.status,
                    result_count=result.count,
                    duration_ms=result.duration_ms,
                    timestamp=result.timestamp,
                    error_message=result.error_message,
                    provenance=result.provenance,
                    produced_artifact=artifact,
                )
                self.state_store.add_history_entry(history_entry)
                if artifact:
                    self.state_store.append_produced_artifact(artifact)
                previous_result = result
                
                # Check for early termination
                if result.status == "error" and plan.config.get("stop_on_error", True):
                    break
                elif result.status == "empty" and not plan.config.get("continue_on_empty", False):
                    break
            
            return {
                "plan_id": plan.plan_id,
                "status": "completed",
                "results": results,
                "final_state": self.state_store.get_state()
            }
            
        except Exception as e:
            raise ExecutionError(f"Plan execution failed: {e}", plan_json.get("plan_id", "unknown"))

    def _execute_on(
        self,
        command: Command,
        step_id: str,
        previous_result: Optional[ExecutionResult],
    ) -> tuple[ExecutionResult, Optional[ExecutionResult]]:
        """Execute ON control flow by conditionally running its nested action."""
        start_time = time.time()
        args = command.args
        desired_status = args["status"]
        action_text = args["action"]
        matched = self._on_condition_matches(desired_status, previous_result)
        self.trace.log("command_start", {
            "step_id": step_id,
            "command_type": "ON",
            "raw_text": command.raw_text,
            "args": command.args,
            "inputs": {
                "previous_result": {
                    "status": getattr(previous_result, "status", None),
                    "count": getattr(previous_result, "count", None),
                    "data": getattr(previous_result, "data", None),
                }
            },
            "state_keys_before": list(self.state_store.get_state().get("variables", {}).keys()),
            "context_keys_before": list(self.context_store.keys()),
        })
        nested_result = None
        if matched:
            nested_command = self.parser.parse_command(action_text)
            nested_result = self._execute_command(nested_command, f"{step_id}.action")
        on_result = ExecutionResult(
            command=command.raw_text,
            status="success",
            data={"status": desired_status, "matched": matched, "action": action_text, "triggered": matched},
            count=1 if matched else 0,
            duration_ms=int((time.time() - start_time) * 1000),
            timestamp=datetime.now(),
            provenance=[
                Provenance(
                    source_id="gasl-on",
                    extraction={"method": "on_condition", "status": desired_status, "matched": matched, "action": action_text},
                )
            ],
        )
        self.trace.log("command_result", {
            "step_id": step_id,
            "command_type": "ON",
            "status": on_result.status,
            "count": on_result.count,
            "error_message": on_result.error_message,
            "duration_ms": on_result.duration_ms,
            "data": on_result.data,
            "contract": on_result.contract,
            "state_after": self.state_store.get_state().get("variables", {}),
            "context_keys_after": list(self.context_store.keys()),
        })
        return on_result, nested_result

    @staticmethod
    def _on_condition_matches(desired_status: str, previous_result: Optional[ExecutionResult]) -> bool:
        if previous_result is None:
            return False
        if desired_status == "error":
            return previous_result.status == "error"
        is_empty = (
            previous_result.status == "empty"
            or previous_result.count == 0
            or previous_result.data in (None, [], {})
        )
        if desired_status == "empty":
            return is_empty
        if desired_status == "success":
            return previous_result.status == "success" and not is_empty
        return False
    
    def _execute_command(self, command: Command, step_id: str) -> ExecutionResult:
        """Execute a single command."""
        start_time = time.time()
        
        try:
            # Find appropriate handler
            handler = None
            for h in self.handlers:
                if h.can_handle(command):
                    handler = h
                    break
            
            if not handler:
                raise ExecutionError(f"No handler for command: {command.command_type}", command.raw_text, step_id)
            
            # Execute command
            self.trace.log("command_start", {
                "step_id": step_id,
                "command_type": command.command_type,
                "raw_text": command.raw_text,
                "args": command.args,
                "inputs": self._capture_command_inputs(command),
                "state_keys_before": list(self.state_store.get_state().get("variables", {}).keys()),
                "context_keys_before": list(self.context_store.keys()),
            })
            print(f"DEBUG: Executing command: {command.command_type} - {command.args}")
            print(f"🔍 STATE DEBUG: Before command, state variables: {list(self.state_store.get_state().get('variables', {}).keys())}")
            result = handler.execute(command)
            result.duration_ms = int((time.time() - start_time) * 1000)
            print(f"DEBUG: Command result: {result.status} - count: {result.count}")
            print(f"🔍 STATE DEBUG: After command, state variables: {list(self.state_store.get_state().get('variables', {}).keys())}")
            self.trace.log("command_result", {
                "step_id": step_id,
                "command_type": command.command_type,
                "status": result.status,
                "count": result.count,
                "error_message": result.error_message,
                "duration_ms": result.duration_ms,
                "data": result.data,
                "contract": result.contract,
                "state_after": self.state_store.get_state().get("variables", {}),
                "context_keys_after": list(self.context_store.keys()),
            })
            
            # Store FIND results in context store for subsequent commands
            if command.command_type == "FIND" and result.status == "success" and result.data:
                # Extract variable name from command args or use a default
                target = command.args.get("target", "nodes")
                self.context_store.set(f"last_{target}_result", result.data, result.provenance, contract=result.contract)
                print(f"DEBUG: Stored FIND result in context as 'last_{target}_result' with {len(result.data) if isinstance(result.data, list) else 'non-list'} items")
                print(f"DEBUG: Context store now has: {list(self.context_store._data.keys())}")
            
            return result
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                command=command.raw_text,
                status="error",
                error_message=str(e),
                duration_ms=duration_ms,
                timestamp=datetime.now()
            )

    def _capture_command_inputs(self, command: Command) -> Dict[str, Any]:
        """Capture referenced variable payloads for command-level debugging."""
        referenced_state: Dict[str, Any] = {}
        referenced_context: Dict[str, Any] = {}
        referenced_contracts: Dict[str, Any] = {}
        for _, value in command.args.items():
            if isinstance(value, str):
                if self.state_store.has_variable(value):
                    referenced_state[value] = self.state_store.get_variable(value)
                    referenced_contracts[value] = self.state_store.get_variable_contract(value)
                if self.context_store.has(value):
                    referenced_context[value] = self.context_store.get(value)
                    referenced_contracts[value] = self.context_store.get_contract(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        if self.state_store.has_variable(item):
                            referenced_state[item] = self.state_store.get_variable(item)
                            referenced_contracts[item] = self.state_store.get_variable_contract(item)
                        if self.context_store.has(item):
                            referenced_context[item] = self.context_store.get(item)
                            referenced_contracts[item] = self.context_store.get_contract(item)
        return {
            "state": referenced_state,
            "context": referenced_context,
            "contracts": referenced_contracts,
        }

    def _build_produced_artifact(self, command: Command, result: ExecutionResult) -> Optional[Dict[str, Any]]:
        """Build a compact artifact record for future prompts and variable-flow debugging."""
        args = command.args or {}
        variable = None
        for key in ("result_variable", "target_variable", "result_var", "target"):
            value = args.get(key)
            if isinstance(value, str) and value:
                variable = value
                break
        if variable is None and command.command_type == "DECLARE":
            value = args.get("variable")
            if isinstance(value, str) and value:
                variable = value
        if not variable:
            return None
        contract = result.contract or self.state_manager.get_variable_contract(variable, fallback_to_last_nodes=False) or {}
        refinement = contract.get("refinement", {}) if isinstance(contract, dict) else {}
        return {
            "variable": variable,
            "command_type": command.command_type,
            "status": result.status,
            "item_count": result.count,
            "payload_kind": contract.get("payload_kind", ""),
            "row_schema": contract.get("row_schema", []),
            "label_field": contract.get("label_field", ""),
            "metric_field": contract.get("metric_field", ""),
            "grain_type": contract.get("grain_type", ""),
            "multiplicity_preserved": contract.get("multiplicity_preserved"),
            "safe_for": contract.get("usable_by", []),
            "refinement_hint": refinement.get("refinement_hint"),
            "refinement_reason": refinement.get("refinement_reason", ""),
            "timestamp": result.timestamp.isoformat(),
        }
    
    def create_snapshot(self, snapshot_id: str, next_actions: List[Dict[str, Any]] = None) -> StateSnapshot:
        """Create a state snapshot for MCTS future-proofing."""
        return self.state_store.create_snapshot(snapshot_id, next_actions)
    
    def get_schema(self) -> Dict[str, Any]:
        """Get graph schema."""
        return self.adapter.get_schema()
    
    def get_state(self) -> Dict[str, Any]:
        """Get current state."""
        return self.state_store.get_state()
    
    def clear_state(self) -> None:
        """Clear all state."""
        self.state_store.clear_state()
        self.context_store.clear()
    
    def run_hypothesis_driven_traversal(self, query: str, max_iterations: int = 10) -> Dict[str, Any]:
        """Run the complete HDT loop."""
        # Set initial query
        self.state_store.set_query(query)
        
        print(f"🔍 STATE DEBUG: Initial state variables: {list(self.state_store.get_state().get('variables', {}).keys())}")
        
        iteration = 0
        all_results = []
        pending_plan_json: Optional[Dict[str, Any]] = None
        clean_iteration_completed = False
        
        while iteration < max_iterations:
            iteration += 1
            plan_json: Optional[Dict[str, Any]] = None
            
            # Get current state and schema
            current_state = self.state_store.get_state()
            schema = self.get_schema()
            history = current_state.get("history", [])
            
            if pending_plan_json is None:
                # Create plan prompt
                plan_prompt = self.llm_func.create_plan_prompt(query, schema, current_state, history)
                plan_obs_id = self.prompt_obs.record_invocation(
                    prompt_name="plan_generation",
                    prompt_text=plan_prompt,
                    model=getattr(self.llm_func, "model", None),
                    metadata={
                        "iteration": iteration,
                        "query": query,
                        "history_len": len(history),
                        "state_var_count": len(current_state.get("variables", {})),
                    },
                )
                self.trace.log("planner_prompt", {
                    "iteration": iteration,
                    "query": query,
                    "prompt": plan_prompt,
                    "schema": schema,
                    "state": current_state.get("variables", {}),
                    "history": history,
                })
                
                # Get plan from LLM
                print(f"🔄 ITERATION {iteration} - Generating Plan...")
                plan_response = self.llm_func.call(plan_prompt)
                print(f"DEBUG: LLM Response:\n{plan_response}\n")
                self.trace.log("planner_response", {
                    "iteration": iteration,
                    "raw_response": plan_response,
                    "extracted_json": _extract_json(plan_response),
                })
            else:
                plan_json = pending_plan_json
                pending_plan_json = None
                plan_response = json.dumps(plan_json)
                plan_obs_id = None
                self.trace.log("planner_plan_reuse", {
                    "iteration": iteration,
                    "plan": plan_json,
                })
            
            try:
                # Parse JSON response — tolerant of markdown fences / prose
                if plan_json is None:
                    plan_json = json.loads(_extract_json(plan_response))
                plan_json["query"] = query  # Ensure query is set
                if plan_obs_id is not None:
                    self.prompt_obs.record_outcome(
                        plan_obs_id,
                        prompt_name="plan_generation",
                        response_text=plan_response,
                        parsed=plan_json,
                        labels={"parse_success": True},
                        metadata={"iteration": iteration},
                    )
                self.trace.log("planner_plan", {
                    "iteration": iteration,
                    "plan": plan_json,
                })
                
                # Execute plan
                result = self.execute_plan(plan_json)
                all_results.append(result)
                
                print(f"DEBUG: Plan execution result status: '{result['status']}'")
                print(f"DEBUG: Status type: {type(result['status'])}")
                print(f"DEBUG: Status repr: {repr(result['status'])}")
                print(f"🔍 STATE DEBUG: After plan execution, state variables: {list(self.state_store.get_state().get('variables', {}).keys())}")
                
                # Deterministic repair trigger: if this execution produced any command errors/empties,
                # the run failed and must be repaired. Do not gate repair on an LLM validator.
                if result["status"] in ["completed", "success"]:
                    final_state = result["final_state"]
                    variables = final_state.get("variables", {})
                    print(f"DEBUG: Final state variables: {list(variables.keys())}")
                    failure_summary = self._determine_iteration_failures(result["results"])
                    self.trace.log("iteration_failure_summary", {
                        "iteration": iteration,
                        "summary": failure_summary,
                    })
                    if not failure_summary["needs_repair"]:
                        print(f"DEBUG: Clean iteration completed after {iteration} iterations")
                        clean_iteration_completed = True
                        break

                    print(f"DEBUG: Iteration {iteration} needs repair: {failure_summary['reasons']}")
                    if iteration >= max_iterations:
                        print(f"DEBUG: Reached max iterations ({max_iterations}) with unresolved execution defects")
                        break

                    self.state_store.set_strategy_insights(json.dumps(failure_summary["reasons"]))
                    repaired_plan, plan_repair_response = self._attempt_plan_repair(
                        query=query,
                        previous_plan=plan_json,
                        variables=variables,
                        iteration=iteration,
                    )
                    if repaired_plan is not None:
                        pending_plan_json = repaired_plan
                        self.state_store.set_strategy_insights(
                            json.dumps(plan_repair_response.get("planner_constraints", []))
                        )
                        continue

                    current_schema = self.get_schema()
                    strategy_prompt = self.llm_func.create_strategy_adaptation_prompt(query, variables, iteration, current_schema, self.state_store.get_state())
                    strat_obs_id = self.prompt_obs.record_invocation(
                        prompt_name="strategy_adaptation",
                        prompt_text=strategy_prompt,
                        model=getattr(self.llm_func, "model", None),
                        metadata={"iteration": iteration, "query": query},
                    )
                    strategy_response = self.llm_func.call(strategy_prompt)
                    self.prompt_obs.record_outcome(
                        strat_obs_id,
                        prompt_name="strategy_adaptation",
                        response_text=strategy_response,
                        labels={"generated": True},
                        metadata={"iteration": iteration},
                    )
                    print(f"DEBUG: Strategy Analysis (Iteration {iteration}):\n{strategy_response}\n")
                    self.trace.log("strategy_prompt", {"iteration": iteration, "prompt": strategy_prompt})
                    self.trace.log("strategy_response", {"iteration": iteration, "response": strategy_response})
                    self.state_store.set_strategy_insights(strategy_response)
                
            except json.JSONDecodeError:
                # LLM didn't return valid JSON, try again
                if plan_obs_id is not None:
                    self.prompt_obs.record_outcome(
                        plan_obs_id,
                        prompt_name="plan_generation",
                        response_text=plan_response,
                        labels={"parse_success": False},
                        metadata={"iteration": iteration},
                    )
                continue
            except Exception as e:
                # Plan execution failed, try again
                continue
        
        final_state = self.state_store.get_state()
        variables = final_state.get("variables", {})

        print(f"🔍 STATE DEBUG: Final state variables: {list(variables.keys())}")
        for var_name, var_data in variables.items():
            if isinstance(var_data, dict) and "items" in var_data:
                print(f"🔍 STATE DEBUG: {var_name}: LIST({len(var_data['items'])} items)")
            else:
                print(f"🔍 STATE DEBUG: {var_name}: {var_data}")

        has_data = any(
            (isinstance(v, dict) and "_meta" in v and
             (v.get("items") or any(k != "_meta" for k in v)))
            for v in variables.values()
        )
        if clean_iteration_completed and has_data:
            final_answer = self._generate_final_answer(query, final_state)
            query_answered = True
        else:
            final_answer = f"Query could not be answered cleanly after {iteration} iterations. Execution defects remain."
            query_answered = False
        
        return {
            "query": query,
            "iterations": iteration,
            "results": all_results,
            "final_state": final_state,
            "final_answer": final_answer,
            "query_answered": query_answered,
        }

    @staticmethod
    def _determine_iteration_failures(results: List[ExecutionResult]) -> Dict[str, Any]:
        """Summarize deterministic execution defects for the current iteration."""
        failure_reasons: List[Dict[str, Any]] = []
        for result in results:
            status = getattr(result, "status", None)
            if status not in {"error", "empty"}:
                continue
            failure_reasons.append({
                "command": getattr(result, "command", ""),
                "status": status,
                "error_message": getattr(result, "error_message", ""),
            })
        return {
            "needs_repair": bool(failure_reasons),
            "reasons": failure_reasons,
        }

    def _attempt_plan_repair(
        self,
        query: str,
        previous_plan: Dict[str, Any],
        variables: Dict[str, Any],
        iteration: int,
    ) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        request = PlanIterationRequest(
            query=query,
            previous_plan=previous_plan,
            results=variables,
            iteration=iteration,
            state=self.state_store.get_state(),
        )
        return self.plan_iteration_agent.iterate_plan(request)

    @staticmethod
    def _parse_plan_repair_response(text: str) -> Dict[str, Any]:
        return PlanIterationAgent.parse_response(text)

    @staticmethod
    def _apply_plan_patch(plan_json: Dict[str, Any], patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return PlanIterationAgent.apply_patch(plan_json, patch)
    
    def _generate_final_answer(self, query: str, state: Dict[str, Any]) -> str:
        """Generate final answer from accumulated state."""
        runtime_view = {
            "state_variables": state.get("variables", {}),
            "context_variables": {key: self.context_store.get(key) for key in self.context_store.keys()},
            "produced_artifacts": state.get("produced_artifacts", []),
            "history": state.get("history", []),
        }
        compiler = AnswerLayerCompiler()
        views = compiler.build_views(runtime_view)
        selection = compiler.select_view(query, views, llm_func=self.llm_func)
        self.trace.log(
            "answer_views",
            {
                "query": query,
                "views": [
                    {
                        "view_id": view.view_id,
                        "kind": view.kind,
                        "source_variable": view.source_variable,
                        "sufficient": view.sufficient,
                        "payload": view.payload,
                    }
                    for view in views
                ],
                "selection": {
                    "view_id": selection.view.view_id if selection.view else None,
                    "kind": selection.view.kind if selection.view else None,
                    "supporting_view_ids": [view.view_id for view in selection.supporting_views],
                    "rationale": selection.rationale,
                },
            },
        )
        deterministic = DeterministicAnswerFinalizer().finalize(query, selection)
        if deterministic:
            self.trace.log("final_answer_response", {"query": query, "mode": "deterministic_view", "response": deterministic})
            return deterministic

        results = {}
        variables = state.get("variables", {})

        for var_name, var_data in variables.items():
            if isinstance(var_data, dict) and "_meta" in var_data:
                var_type = var_data["_meta"]["type"]
                if var_type == "LIST":
                    items = var_data.get("items", [])
                    results[var_name] = self._summarize_list(items)
                elif var_type == "DICT":
                    results[var_name] = {k: v for k, v in var_data.items() if k != "_meta"}
                elif var_type == "COUNTER":
                    results[var_name] = var_data.get("value", 0)
            elif isinstance(var_data, dict) and "value" in var_data:
                results[var_name] = var_data["value"]
            else:
                results[var_name] = var_data

        print(f"DEBUG: FINAL ANSWER - Query: {query}")
        print(f"DEBUG: FINAL ANSWER - Results keys: {list(results.keys())}")
        for key, value in results.items():
            if isinstance(value, (list, dict)):
                print(f"DEBUG: FINAL ANSWER - {key}: {type(value).__name__} len={len(value)}")
            else:
                print(f"DEBUG: FINAL ANSWER - {key}: {value}")

        if selection.view and selection.view.sufficient:
            results = {
                "selected_view_kind": selection.view.kind,
                "selected_view": selection.view.payload,
                "supporting_views": [
                    {"kind": view.kind, "payload": view.payload}
                    for view in selection.supporting_views
                ],
                "selection_rationale": selection.rationale,
            }
        analysis_prompt = self.llm_func.create_analysis_prompt(query, results)
        print(f"DEBUG: FINAL ANSWER - Analysis prompt being sent to LLM:")
        print("=" * 80)
        print(analysis_prompt[:3000])   # log only first 3k chars
        print("=" * 80)
        self.trace.log("final_analysis_prompt", {
            "query": query,
            "prompt": analysis_prompt,
            "results": results,
        })
        final_answer = self.llm_func.call(analysis_prompt)
        self.trace.log("final_analysis_response", {
            "query": query,
            "response": final_answer,
        })
        return final_answer

    def _summarize_list(self, items: list, max_items: int = 50) -> object:
        """Compress a large list for the final-answer prompt.

        If every item has a classification-like field (e.g. cognitive_domain,
        category) we tally the values and return a count dict instead of the
        raw list — much cheaper on tokens and actually more useful to the LLM.
        Otherwise we return at most max_items items.
        """
        if not items:
            return []

        # Detect a dominant classification field in the first item
        first = items[0] if isinstance(items[0], dict) else {}
        classification_fields = [k for k in first if k in (
            "cognitive_domain", "category", "domain", "class", "label",
            "cognitive_domains", "domain_label",
        )]

        if classification_fields:
            field = classification_fields[0]
            tally: dict = {}
            for item in items:
                val = item.get(field) if isinstance(item, dict) else None
                val = str(val) if val is not None else "unclassified"
                tally[val] = tally.get(val, 0) + 1
            tally["_total"] = len(items)
            return tally

        # No classification field — return a sample
        return items[:max_items]
