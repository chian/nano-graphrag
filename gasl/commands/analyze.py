"""
ANALYZE command handler.
"""

from typing import Any, List
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class AnalyzeHandler(CommandHandler):
    """Handles ANALYZE commands for LLM-based analysis."""
    
    def __init__(self, state_store, context_store, llm_func, state_manager=None):
        super().__init__(state_store, context_store, state_manager)
        self.llm_func = llm_func
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "ANALYZE"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute ANALYZE command."""
        try:
            args = command.args
            variable = args["variable"]
            instruction = args["instruction"]
            
            # Get data from context or state
            data = None
            if self.context_store.has(variable):
                data = self.context_store.get(variable)
            elif self.state_store.has_variable(variable):
                data = self.state_store.get_variable(variable)
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Variable {variable} not found in context or state"
                )
            
            # Prepare prompt for LLM analysis
            prompt = self._create_analyze_prompt(data, instruction)
            
            # Call LLM
            result = self.llm_func.call(prompt)
            
            # Store result in context
            result_key = f"analyze_{variable}_{len(self.context_store.keys())}"
            self.context_store.set(result_key, result)
            
            # Create provenance
            provenance = [
                self._create_provenance(
                    source_id="llm-analyze",
                    method="analyze",
                    variable=variable,
                    instruction=instruction,
                    model="llm"
                )
            ]
            
            return self._create_result(
                command=command,
                status="success",
                data=result,
                count=1,
                provenance=provenance
            )
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _create_analyze_prompt(self, data: Any, instruction: str) -> str:
        """Create prompt for LLM analysis."""
        prompt = f"""You are analyzing data according to this instruction: {instruction}

Data to analyze:
{data}

Please analyze this data according to the instruction and provide insights, patterns, or conclusions.
"""
        return prompt