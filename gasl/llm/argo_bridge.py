"""
Argo Bridge LLM wrapper for GASL system.
"""

import os
import asyncio
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI
from ..errors import LLMError
from nano_graphrag.prompt_system import QueryAwarePromptSystem


class ArgoBridgeLLM:
    """Wrapper around existing argo_bridge_llm function."""
    
    def __init__(self, model: str = None, temperature: float = 0.0, max_tokens: int = 4000):
        self.model = model or os.getenv("LLM_MODEL", "gpt41")
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Initialize OpenAI client
        self.client = AsyncOpenAI(
            api_key=os.getenv("LLM_API_KEY", "api+key"),
            base_url=os.getenv("LLM_ENDPOINT", "https://argo-bridge.cels.anl.gov/v1")
        )
        
        # Initialize prompt system
        self.prompt_system = QueryAwarePromptSystem()
    
    async def call_async(self, prompt: str) -> str:
        """Make async LLM call."""
        print(f"DEBUG: LLM PROMPT SENT:\n{prompt}\n")
        print("="*80)
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            result = response.choices[0].message.content
            print(f"DEBUG: LLM RESPONSE RECEIVED:\n{result}\n")
            print("="*80)
            return result
        except Exception as e:
            raise LLMError(f"LLM call failed: {e}", "argo_bridge", self.model)
    
    def call(self, prompt: str) -> str:
        """Make synchronous LLM call."""
        try:
            # Run async call in event loop
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(self.call_async(prompt))
            return result
        except RuntimeError:
            # No event loop running, create new one
            result = asyncio.run(self.call_async(prompt))
            return result
    
    def create_plan_prompt(self, query: str, schema: Dict[str, Any], 
                          state: Dict[str, Any], history: list) -> str:
        """Create prompt for LLM to generate a plan using centralized prompt system."""
        # Get the base prompt from the centralized system with query optimization
        base_prompt = self.prompt_system.get_prompt("plan_generation", user_query=query, optimize=True)
        
        # Get validation hint from state
        validation_hint = state.get("validation_hint", "")
        
        # Format the prompt with the current context
        formatted_prompt = base_prompt.format(
            query=query,
            hint_text=f"\n\nPrevious validation feedback: {validation_hint}" if validation_hint else "",
            node_labels=schema.get('node_labels', []),
            edge_types=schema.get('edge_types', []),
            node_properties=schema.get('node_properties', []),
            edge_properties=schema.get('edge_properties', []),
            state_variables=self._format_state(state),
            execution_history=self._format_history(history)
        )
        
        return formatted_prompt
    
    def create_completion_validator_prompt(self, query: str, results: Dict[str, Any]) -> str:
        """Create prompt to validate if query was successfully answered."""
        # Get the prompt from the centralized system
        base_prompt = self.prompt_system.get_prompt("completion_validator")
        
        # Format the prompt with the current context
        formatted_prompt = base_prompt.format(
            query=query,
            results=self._format_results(results)
        )
        
        return formatted_prompt

    def create_analysis_prompt(self, query: str, results: Dict[str, Any]) -> str:
        """Create prompt for final analysis."""
        # Get the prompt from the centralized system
        base_prompt = self.prompt_system.get_prompt("final_analysis")
        
        # Format the prompt with the current context
        formatted_prompt = base_prompt.format(
            query=query,
            results=self._format_results(results)
        )
        
        return formatted_prompt
    
    def create_strategy_adaptation_prompt(self, query: str, results: Dict[str, Any], iteration: int, schema: Dict[str, Any], state: Dict[str, Any]) -> str:
        """Create prompt for strategy adaptation between iterations."""
        # Get the prompt from the centralized system
        base_prompt = self.prompt_system.get_prompt("strategy_adaptation")
        
        # Get validation hint and execution history from state
        validation_hint = state.get("validation_hint", "")
        execution_history = state.get("execution_history", "")
        
        # Format the prompt with the current context
        prompt = base_prompt.format(
            query=query,
            iteration=iteration,
            results=self._format_results(results),
            validation_hint=f"\n\nValidation Feedback: {validation_hint}" if validation_hint else "",
            execution_history=execution_history,
            node_labels=schema.get('node_labels', []),
            edge_types=schema.get('edge_types', []),
            node_properties=schema.get('node_properties', []),
            edge_properties=schema.get('edge_properties', [])
        )
        return prompt
    
    def _format_state(self, state: Dict[str, Any]) -> str:
        """Format state for prompt."""
        if not state:
            return "No state variables defined yet."
        
        formatted = []
        for key, value in state.items():
            if isinstance(value, dict) and "_meta" in value:
                var_type = value["_meta"].get("type", "unknown")
                description = value["_meta"].get("description", "")
                if var_type == "LIST":
                    count = len(value.get("items", []))
                    formatted.append(f"- {key} ({var_type}): {count} items - {description}")
                    
                    # Show available fields for LIST variables
                    items = value.get("items", [])
                    if items and isinstance(items, list) and len(items) > 0:
                        # Analyze first few items to determine available fields
                        sample_fields = self._analyze_item_fields(items[:3])
                        if sample_fields:
                            formatted.append(f"  🔍 AVAILABLE FIELDS (use these exact names in commands):")
                            for field_name, field_type in sample_fields.items():
                                formatted.append(f"    - {field_name}: {field_type}")
                            
                            # Show sample data structure
                            formatted.append(f"  📋 Sample item structure:")
                            sample_item = items[0]
                            if isinstance(sample_item, dict):
                                for field, val in sample_item.items():
                                    if isinstance(val, str) and len(val) > 50:
                                        val = val[:47] + "..."
                                    formatted.append(f"    - {field}: {val}")
                            else:
                                formatted.append(f"    - {sample_item}")
                                
                elif var_type == "DICT":
                    keys = [k for k in value.keys() if k != "_meta"]
                    formatted.append(f"- {key} ({var_type}): {len(keys)} keys - {description}")
                elif var_type == "COUNTER":
                    count = value.get("value", 0)
                    formatted.append(f"- {key} ({var_type}): {count} - {description}")
            else:
                formatted.append(f"- {key}: {value}")
        
        return "\n".join(formatted)
    
    def _analyze_item_fields(self, items: List[Dict]) -> Dict[str, str]:
        """Analyze sample items to determine available fields and their types."""
        if not items:
            return {}
        
        field_types = {}
        for item in items:
            if isinstance(item, dict):
                for field_name, field_value in item.items():
                    if field_name == "_meta":
                        continue
                    
                    # Determine field type
                    if isinstance(field_value, bool):
                        field_type = "boolean"
                    elif isinstance(field_value, (int, float)):
                        field_type = "number"
                    elif isinstance(field_value, str):
                        field_type = "string"
                    elif field_value is None:
                        field_type = "null"
                    else:
                        field_type = "unknown"
                    
                    # Store the most specific type we've seen for this field
                    if field_name not in field_types or field_type != "unknown":
                        field_types[field_name] = field_type
        
        return field_types
    
    def _format_history(self, history: list) -> str:
        """Format history for prompt."""
        if not history:
            return "No execution history yet."
        
        formatted = []
        for entry in history[-5:]:  # Last 5 entries
            status = entry.get("status", "unknown")
            command = entry.get("command", "")
            count = entry.get("result_count", 0)
            formatted.append(f"- {status}: {command} (result count: {count})")
        
        return "\n".join(formatted)
    
    def _format_results(self, results: Dict[str, Any]) -> str:
        """Format results for prompt."""
        formatted = []
        for key, value in results.items():
            if isinstance(value, list):
                formatted.append(f"{key}: {len(value)} items")
                # Show first few items
                for i, item in enumerate(value[:3]):
                    formatted.append(f"  {i+1}. {item}")
                if len(value) > 3:
                    formatted.append(f"  ... and {len(value) - 3} more")
            else:
                formatted.append(f"{key}: {value}")
        
        return "\n".join(formatted)
