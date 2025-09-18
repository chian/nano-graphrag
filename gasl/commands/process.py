"""
PROCESS command handler.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class ProcessHandler(CommandHandler):
    """Handles PROCESS commands for LLM-based data processing."""
    
    def __init__(self, state_store, context_store, llm_func):
        super().__init__(state_store, context_store)
        self.llm_func = llm_func
    
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
                data = self.state_store.get_variable(variable)
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
            
            # Prepare prompt for LLM
            prompt = self._create_process_prompt(data, instruction)
            
            # Call LLM
            llm_response = self.llm_func.call(prompt)
            print(f"DEBUG: PROCESS - LLM Response:\n{llm_response}\n")
            
            # Parse LLM response
            try:
                import json
                parsed_result = json.loads(llm_response)
                
                # Extract included items (the filtered results)
                included_items = parsed_result.get("included", [])
                
                # Check if this is a filtering operation or field calculation
                if "included" in parsed_result and "excluded" in parsed_result:
                    # This is a filtering operation - map LLM results back to original node format
                    filtered_nodes = []
                    for item in included_items:
                        # Find the original node data by matching the ID
                        original_node = self._find_original_node(data, item.get("id", ""))
                        if original_node:
                            filtered_nodes.append(original_node)
                    
                    # Store results in target variable
                    self._store_processed_data(target_variable, filtered_nodes)
                    print(f"DEBUG: PROCESS - Updated {target_variable} with {len(filtered_nodes)} filtered items")
                    
                elif "processed_items" in parsed_result:
                    # This is a field calculation operation - use the processed items directly
                    processed_items = parsed_result["processed_items"]
                    self._store_processed_data(target_variable, processed_items)
                    print(f"DEBUG: PROCESS - Updated {target_variable} with {len(processed_items)} processed items")
                    
                else:
                    # Fallback to original behavior
                    filtered_nodes = []
                    for item in included_items:
                        original_node = self._find_original_node(data, item.get("id", ""))
                        if original_node:
                            filtered_nodes.append(original_node)
                    
                    self._store_processed_data(target_variable, filtered_nodes)
                    print(f"DEBUG: PROCESS - Updated {target_variable} with {len(filtered_nodes)} filtered items")
                
                # Store full LLM analysis in context
                result_key = f"process_{variable}_{len(self.context_store.keys())}"
                self.context_store.set(result_key, parsed_result)
                
                result = {
                    "filtered_items": included_items,
                    "analysis": parsed_result,
                    "count": len(included_items)
                }
                
            except json.JSONDecodeError:
                # If LLM response is not valid JSON, store as text
                result_key = f"process_{variable}_{len(self.context_store.keys())}"
                self.context_store.set(result_key, llm_response)
                result = {"raw_response": llm_response, "count": 0}
            
            # Create provenance
            provenance = [
                self._create_provenance(
                    source_id="llm-process",
                    method="process",
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