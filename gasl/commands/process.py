"""
PROCESS command handler.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..validation import LLMJudgeValidator


class ProcessHandler(CommandHandler):
    """Handles PROCESS commands for LLM-based data processing."""
    
    def __init__(self, state_store, context_store, llm_func, micro_framework=None):
        super().__init__(state_store, context_store)
        self.llm_func = llm_func
        self.micro_framework = micro_framework
        self.validator = LLMJudgeValidator(llm_func) if llm_func else None
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "PROCESS"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute PROCESS command."""
        try:
            args = command.args
            variable = args["variable"]
            instruction = args["instruction"]
            target_variable = args.get("target_variable", variable)  # Default to same variable
            
            # Get data from context or state
            data = None
            if self.context_store.has(variable):
                data = self.context_store.get(variable)
            elif self.state_store.has_variable(variable):
                data = self.state_store.get(variable)
            else:
                # If variable not found, try to get from last_nodes_result
                if self.context_store.has("last_nodes_result"):
                    data = self.context_store.get("last_nodes_result")
                    print(f"DEBUG: PROCESS - Using last_nodes_result as data source: {len(data) if isinstance(data, list) else 'not a list'}")
                else:
                    return self._create_result(
                        command=command,
                        status="error",
                        error_message=f"Variable {variable} not found in context or state, and no last_nodes_result available"
                    )
            
            # Use MicroActionFramework for batching if available
            if self.micro_framework and isinstance(data, list) and len(data) > 20:
                print(f"DEBUG: PROCESS - Using MicroActionFramework for {len(data)} items")
                return self.micro_framework.execute_command_with_batching(
                    data=data,
                    command_type="PROCESS",
                    instruction=instruction,
                    batch_size=None,  # Let framework calculate optimal batch size
                    target_variable=target_variable
                )
            else:
                print(f"DEBUG: PROCESS - Processing {len(data) if isinstance(data, list) else 1} items normally")
                return self._execute_single_batch(data, instruction, command, target_variable)
                
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    
    def _execute_single_batch(self, data: Any, instruction: str, command: Command, target_variable: str) -> ExecutionResult:
        """Execute PROCESS on a single batch (original logic)."""
        # Prepare prompt for LLM
        prompt = self._create_process_prompt(data, instruction)
        
        # Call LLM
        llm_response = self.llm_func.call(prompt)
        print(f"DEBUG: PROCESS - LLM Response:\n{llm_response}\n")
        
        # Parse LLM response
        result = self._parse_process_response(llm_response, data)
        
        # Store results in target variable
        processed_items = result.get("processed_items", [])
        self._store_processed_data(target_variable, processed_items)
        print(f"DEBUG: PROCESS - Updated {target_variable} with {len(processed_items)} processed items using {result.get('processing_method', 'unknown')} method")
        
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
                model="llm"
            )
        ]
        
        # Determine status based on actual work done
        if "processed_items" in result:
            status = "success" if len(result['processed_items']) > 0 else "empty"
        elif "filtered_items" in result:
            status = "success" if len(result['filtered_items']) > 0 else "empty"
        else:
            status = "empty"
        
        # Create initial result
        result_obj = self._create_result(
            command=command,
            status=status,
            data=result,
            count=len(result.get('filtered_items', [])) if 'filtered_items' in result else len(result.get('processed_items', [])),
            provenance=provenance
        )
        
        # Validate with LLM judge if available
        if self.validator and status == "success":
            validation = self.validator.validate_command_success(
                command.command_type, command.args, result, 
                len(result.get('filtered_items', [])) if 'filtered_items' in result else len(result.get('processed_items', []))
            )
            
            if not validation.get("valid", True):
                # Override status if LLM judge says it failed
                result_obj.status = "error"
                result_obj.error_message = f"LLM Judge Validation Failed: {validation.get('reason', 'Unknown validation failure')}"
                print(f"DEBUG: PROCESS - LLM Judge validation failed: {validation}")
            else:
                print(f"DEBUG: PROCESS - LLM Judge validation passed: {validation.get('reason', 'Valid')}")
        
        return result_obj
    
    def _store_processed_data(self, target_variable: str, processed_data: List[Dict]) -> None:
        """Store processed data in the target variable."""
        # Check if target variable exists in state store
        if self.state_store.has_variable(target_variable):
            var_data = self.state_store.get_variable(target_variable)
            if isinstance(var_data, dict) and "items" in var_data:
                var_data["items"] = processed_data
                self.state_store._save_state()
            else:
                # If it's not a LIST type, update it directly
                self.state_store.update_variable(target_variable, processed_data)
        else:
            # Store in context store if not in state
            self.context_store.set(target_variable, processed_data)
    
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
                name = item.get('name', 'Unknown')
                description = item.get('description', 'No description')
                entity_type = item.get('entity_type', 'Unknown')
                
                formatted.append(f"Node {i+1}:")
                formatted.append(f"  ID: {node_id}")
                formatted.append(f"  Name: {name}")
                formatted.append(f"  Entity Type: {entity_type}")
                formatted.append(f"  Description: {description}")
                formatted.append("")
        
        if len(data) > 20:
            formatted.append(f"... and {len(data) - 20} more items")
        
        return "\n".join(formatted)
    
    def _find_original_node(self, data: list, target_id: str) -> dict:
        """Find the original node data by matching the ID."""
        if not isinstance(data, list):
            return None
        
        for node in data:
            if isinstance(node, dict) and node.get("id") == target_id:
                return node
        return None