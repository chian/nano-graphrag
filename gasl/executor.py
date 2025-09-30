"""
Main execution engine for GASL system.
"""

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

from .types import PlanObject, Command, ExecutionResult, HistoryEntry, StateSnapshot
from .parser import GASLParser
from .state import StateStore, ContextStore
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


class GASLExecutor:
    """Main execution engine for GASL plans."""
    
    def __init__(self, adapter: GraphAdapter, llm_func, state_file: str = None):
        self.adapter = adapter
        self.llm_func = llm_func
        self.parser = GASLParser()
        self.state_store = StateStore(state_file)
        self.context_store = ContextStore()
        
        # Get versioned graph from adapter if available
        versioned_graph = getattr(adapter, 'versioned_graph', None)
        
        # Initialize micro-action framework
        self.micro_framework = MicroActionFramework(llm_func, self.state_store, self.context_store)
        
        # Pass versioned graph to micro framework
        if versioned_graph:
            self.micro_framework.versioned_graph = versioned_graph
        
        # Initialize command handlers
        self.handlers = [
            # Core commands
            DeclareHandler(self.state_store, self.context_store),
            FindHandler(self.state_store, self.context_store, adapter, llm_func),
            ProcessHandler(self.state_store, self.context_store, llm_func, self.micro_framework),
            ClassifyHandler(self.state_store, self.context_store, llm_func),
            UpdateHandler(self.state_store, self.context_store),
            CountHandler(self.state_store, self.context_store, llm_func),
            DebugHandler(self.state_store, self.context_store),
            
            # Graph modification commands
            AddFieldHandler(self.state_store, self.context_store, llm_func),
            CreateNodesHandler(self.state_store, self.context_store, adapter, llm_func),
            CreateEdgesHandler(self.state_store, self.context_store, adapter, llm_func),
            CreateGroupsHandler(self.state_store, self.context_store, adapter, llm_func),
            IterateHandler(self.state_store, self.context_store, self.micro_framework),
            
            # New command categories
            GraphNavHandler(self.state_store, self.context_store, adapter, llm_func),
            MultiVarHandler(self.state_store, self.context_store),
            DataTransformHandler(self.state_store, self.context_store, llm_func),
            FieldCalcHandler(self.state_store, self.context_store, llm_func),
            ObjectCreateHandler(self.state_store, self.context_store, llm_func),
            PatternAnalysisHandler(self.state_store, self.context_store, llm_func),
            
            # Control flow commands
            AnalyzeHandler(self.state_store, self.context_store, llm_func),
            SelectHandler(self.state_store, self.context_store),
            SetHandler(self.state_store, self.context_store),
            RequireHandler(self.state_store, self.context_store),
            AssertHandler(self.state_store, self.context_store),
            OnHandler(self.state_store, self.context_store),
            TryCatchHandler(self.state_store, self.context_store),
            CancelHandler(self.state_store, self.context_store)
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
            for i, command in enumerate(commands):
                step_id = f"{plan.plan_id}-step-{i+1}"
                result = self._execute_command(command, step_id)
                results.append(result)
                
                # Add to history
                history_entry = HistoryEntry(
                    step_id=step_id,
                    command=command.raw_text,
                    status=result.status,
                    result_count=result.count,
                    duration_ms=result.duration_ms,
                    timestamp=result.timestamp,
                    error_message=result.error_message,
                    provenance=result.provenance
                )
                self.state_store.add_history_entry(history_entry)
                
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
            print(f"DEBUG: Executing command: {command.command_type} - {command.args}")
            result = handler.execute(command)
            result.duration_ms = int((time.time() - start_time) * 1000)
            print(f"DEBUG: Command result: {result.status} - count: {result.count}")
            
            # Store FIND results in context store for subsequent commands
            if command.command_type == "FIND" and result.status == "success" and result.data:
                # Extract variable name from command args or use a default
                target = command.args.get("target", "nodes")
                self.context_store.set(f"last_{target}_result", result.data, result.provenance)
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
        
        iteration = 0
        all_results = []
        
        while iteration < max_iterations:
            iteration += 1
            
            # Get current state and schema
            current_state = self.state_store.get_state()
            schema = self.get_schema()
            history = current_state.get("history", [])
            
            # Create plan prompt
            plan_prompt = self.llm_func.create_plan_prompt(query, schema, current_state.get("variables", {}), history)
            
            # Get plan from LLM (prompt will be printed by the call method)
            print(f"🔄 ITERATION {iteration} - Generating Plan...")
            plan_response = self.llm_func.call(plan_prompt)
            print(f"DEBUG: LLM Response:\n{plan_response}\n")
            
            try:
                # Parse JSON response
                plan_json = json.loads(plan_response)
                plan_json["query"] = query  # Ensure query is set
                
                # Execute plan
                result = self.execute_plan(plan_json)
                all_results.append(result)
                
                print(f"DEBUG: Plan execution result status: '{result['status']}'")
                print(f"DEBUG: Status type: {type(result['status'])}")
                print(f"DEBUG: Status repr: {repr(result['status'])}")
                
                # Check if we should continue
                if result["status"] in ["completed", "success"]:
                    print(f"DEBUG: Plan completed successfully, checking for completion validation")
                    # Check if we have enough information to answer
                    final_state = result["final_state"]
                    variables = final_state.get("variables", {})
                    
                    print(f"DEBUG: Final state variables: {list(variables.keys())}")
                    
                    # Use LLM to validate if query was actually answered
                    validation_prompt = self.llm_func.create_completion_validator_prompt(query, variables)
                    print(f"DEBUG: Sending completion validation prompt to LLM")
                    validation_response = self.llm_func.call(validation_prompt).strip().upper()
                    
                    print(f"DEBUG: Completion validation: {validation_response}")
                    
                    # Only stop if LLM confirms the query was answered
                    if validation_response == "YES":
                        print(f"DEBUG: Query successfully answered after {iteration} iterations")
                        break
                    else:
                        print(f"DEBUG: Query not yet answered, continuing to iteration {iteration + 1}")
                        if iteration >= max_iterations - 1:
                            print(f"DEBUG: Reached max iterations ({max_iterations}) without answering query")
                            break
                        
                        # Show results to LLM for strategy adaptation
                        # Prepare results for analysis
                        current_schema = self.get_schema()
                        
                        # Create strategy adaptation prompt to help LLM learn from results
                        strategy_prompt = self.llm_func.create_strategy_adaptation_prompt(query, variables, iteration, current_schema, self.state_store.get_state())
                        strategy_response = self.llm_func.call(strategy_prompt)
                        print(f"DEBUG: Strategy Analysis (Iteration {iteration}):\n{strategy_response}\n")
                        
                        # Store validation hint and strategy insights for next iteration
                        self.state_store.set_validation_hint(validation_response)
                        self.state_store.set_strategy_insights(strategy_response)
                
            except json.JSONDecodeError:
                # LLM didn't return valid JSON, try again
                continue
            except Exception as e:
                # Plan execution failed, try again
                continue
        
        # Generate final answer only if query was answered
        final_state = self.state_store.get_state()
        variables = final_state.get("variables", {})
        
        # Validate if query was actually answered
        validation_prompt = self.llm_func.create_completion_validator_prompt(query, variables)
        validation_response = self.llm_func.call(validation_prompt).strip().upper()
        
        if validation_response == "YES":
            final_answer = self._generate_final_answer(query, final_state)
        else:
            final_answer = f"Query could not be answered after {iteration} iterations. No meaningful results found."
        
        return {
            "query": query,
            "iterations": iteration,
            "results": all_results,
            "final_state": final_state,
            "final_answer": final_answer,
            "query_answered": validation_response == "YES"
        }
    
    def _generate_final_answer(self, query: str, state: Dict[str, Any]) -> str:
        """Generate final answer from accumulated state."""
        # Prepare results for LLM
        results = {}
        variables = state.get("variables", {})
        
        for var_name, var_data in variables.items():
            if isinstance(var_data, dict) and "_meta" in var_data:
                var_type = var_data["_meta"]["type"]
                if var_type == "LIST":
                    results[var_name] = var_data.get("items", [])
                elif var_type == "DICT":
                    results[var_name] = {k: v for k, v in var_data.items() if k != "_meta"}
                elif var_type == "COUNTER":
                    results[var_name] = var_data.get("value", 0)
            elif isinstance(var_data, dict) and "value" in var_data:
                # Handle variables stored as {"value": [...]} without _meta
                results[var_name] = var_data["value"]
            else:
                results[var_name] = var_data
        
        # Create analysis prompt
        print(f"DEBUG: FINAL ANSWER - Query: {query}")
        print(f"DEBUG: FINAL ANSWER - Results keys: {list(results.keys())}")
        for key, value in results.items():
            if isinstance(value, list):
                print(f"DEBUG: FINAL ANSWER - {key}: {len(value)} items")
                if value and isinstance(value[0], dict):
                    print(f"DEBUG: FINAL ANSWER - First item keys: {list(value[0].keys())}")
            else:
                print(f"DEBUG: FINAL ANSWER - {key}: {value}")
        
        analysis_prompt = self.llm_func.create_analysis_prompt(query, results)
        print(f"DEBUG: FINAL ANSWER - Analysis prompt being sent to LLM:")
        print("=" * 80)
        print(analysis_prompt)
        print("=" * 80)
        
        # Get final answer from LLM
        return self.llm_func.call(analysis_prompt)
