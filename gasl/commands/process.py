"""
PROCESS command handler.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..validation import LLMJudgeValidator
from ..utils import normalize_node_id


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
    
    def _parse_process_response(self, llm_response: str, data: Any) -> Dict[str, Any]:
        """Parse LLM response for PROCESS command."""
        try:
            import json
            response_data = json.loads(llm_response)
            
            if "processed_items" in response_data:
                # Handle dynamic field names - merge the new fields back into original nodes
                processed_items = []
                for processed_item in response_data["processed_items"]:
                    # Find the original node
                    original_node = self._find_original_node(data, processed_item.get("id", ""))
                    if original_node:
                        # Create a copy of the original node
                        updated_node = original_node.copy()
                        
                        # Add all fields from the processed item (except id, name, reason)
                        for key, value in processed_item.items():
                            if key not in ["id", "name", "reason"]:
                                updated_node[key] = value
                        
                        processed_items.append(updated_node)
                
                return {
                    "processed_items": processed_items,
                    "summary": response_data.get("summary", {}),
                    "processing_method": "process_items"
                }
            elif "included" in response_data:
                # Map back to original nodes
                processed_items = []
                for item in response_data.get("included", []):
                    original_node = self._find_original_node(data, item.get("id", ""))
                    if original_node:
                        processed_items.append(original_node)
                
                return {
                    "processed_items": processed_items,
                    "summary": response_data.get("summary", {}),
                    "processing_method": "filter_items"
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
        # Extract the new fields from processed_data and merge them back into original structure
        integrated_data = self._integrate_processed_fields(processed_data)
        
        # Always store in state store for persistence
        if self.state_store.has_variable(target_variable):
            # Update existing variable
            self.state_store.update_variable(target_variable, integrated_data)
        else:
            # Create new variable in state store
            self.state_store.set_variable_with_fields(
                target_variable, 
                integrated_data, 
                "LIST", 
                f"Processed data from {target_variable}"
            )
        
        # Also store in context store for immediate access
        self.context_store.set(target_variable, integrated_data)
    
    def _integrate_processed_fields(self, processed_data: List[Dict]) -> List[Dict]:
        """Integrate processed fields back into the original data structure."""
        integrated = []
        
        for item in processed_data:
            if isinstance(item, dict):
                # Create a new item with the original structure plus new fields
                integrated_item = {}
                
                # Copy original fields (id, name, etc.)
                for key, value in item.items():
                    if key not in ['processed_field', 'reason']:
                        integrated_item[key] = value
                
                # Add the processed field with a meaningful name
                if 'processed_field' in item and item['processed_field'] is not None:
                    # Determine field name based on the processing context
                    field_name = self._determine_field_name(item)
                    integrated_item[field_name] = item['processed_field']
                
                integrated.append(integrated_item)
            else:
                integrated.append(item)
        
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
                    data = item['data']
                    name = node_id  # Use ID as name since there's no separate name field
                    description = data.get('description', 'No description')
                    entity_type = data.get('entity_type', 'Unknown')
                else:
                    # Handle flat structure
                    name = item.get('name', node_id)
                    description = item.get('description', 'No description')
                    entity_type = item.get('entity_type', 'Unknown')
                
                formatted.append(f"Node {i+1} ({node_id}):")
                formatted.append(f"  Name: {name}")
                formatted.append(f"  Entity Type: {entity_type}")
                formatted.append(f"  Description: {description}")
                formatted.append("")
        
        if len(data) > 20:
            formatted.append(f"... and {len(data) - 20} more items")
        
        return "\n".join(formatted)
    
    def _parse_process_response(self, llm_response: str, original_data: Any) -> Dict[str, Any]:
        """Parse LLM response for PROCESS command."""
        try:
            import json
            
            # Try to parse as JSON
            response_data = json.loads(llm_response)
            
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