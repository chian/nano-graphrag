"""
CLASSIFY command handler.
"""

from typing import Any, List
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance
from ..validation import LLMJudgeValidator


class ClassifyHandler(CommandHandler):
    """Handles CLASSIFY commands for LLM-based classification."""
    
    def __init__(self, state_store, context_store, llm_func):
        super().__init__(state_store, context_store)
        self.llm_func = llm_func
        self.validator = LLMJudgeValidator(llm_func) if llm_func else None
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type == "CLASSIFY"
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute CLASSIFY command."""
        try:
            args = command.args
            variable = args["variable"]
            instruction = args["instruction"]
            
            # Get data from context or state
            data = None
            if self.context_store.has(variable):
                data = self.context_store.get(variable)
            elif self.state_store.has_variable(variable):
                var_data = self.state_store.get_variable(variable)
                if isinstance(var_data, dict) and "items" in var_data:
                    data = var_data["items"]
                else:
                    data = var_data
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Variable {variable} not found in context or state"
                )
            
            # Prepare prompt for LLM classification
            prompt = self._create_classify_prompt(data, instruction)
            
            # Call LLM
            llm_response = self.llm_func.call(prompt)
            print(f"DEBUG: CLASSIFY - LLM Response:\n{llm_response}\n")
            
            # Parse LLM response
            try:
                import json
                parsed_result = json.loads(llm_response)
                
                # Extract classified items
                classified_items = parsed_result.get("classified_items", [])
                
                # Create a mapping from item ID to category
                category_map = {}
                for item in classified_items:
                    if isinstance(item, dict):
                        item_id = item.get("id", "")
                        category = item.get("category", "unknown")
                        category_map[item_id] = category
                
                # Update original data with category fields
                updated_items = []
                for i, original_item in enumerate(data):
                    if isinstance(original_item, dict):
                        # Create a copy of the original item
                        updated_item = original_item.copy()
                        
                        # Try to match by ID first, then by index
                        item_id = original_item.get("id", f"item_{i}")
                        if item_id in category_map:
                            updated_item["category"] = category_map[item_id]
                        elif i < len(classified_items):
                            updated_item["category"] = classified_items[i].get("category", "unknown")
                        else:
                            updated_item["category"] = "unknown"
                        
                        updated_items.append(updated_item)
                    else:
                        updated_items.append(original_item)
                
                # Update the state variable with classified results
                if self.state_store.has_variable(variable):
                    var_data = self.state_store.get_variable(variable)
                    if isinstance(var_data, dict) and "items" in var_data:
                        var_data["items"] = updated_items
                        self.state_store._save_state()
                        print(f"DEBUG: CLASSIFY - Updated {variable} with {len(updated_items)} classified items")
                
                # Store full LLM analysis in context
                result_key = f"classify_{variable}_{len(self.context_store.keys())}"
                self.context_store.set(result_key, parsed_result)
                
                result = {
                    "classified_items": updated_items,
                    "analysis": parsed_result,
                    "count": len(updated_items)
                }
                
            except json.JSONDecodeError:
                # If LLM response is not valid JSON, store as text
                result_key = f"classify_{variable}_{len(self.context_store.keys())}"
                self.context_store.set(result_key, llm_response)
                result = {"raw_response": llm_response, "count": 0}
            
            # Create provenance
            provenance = [
                self._create_provenance(
                    source_id="llm-classify",
                    method="classify",
                    variable=variable,
                    instruction=instruction,
                    model="llm"
                )
            ]
            
            # Count successful classifications
            successful_classifications = len([item for item in updated_items if item.get("category") != "unknown"])
            
            # Create initial result
            result_obj = self._create_result(
                command=command,
                status="success",
                data=result,
                count=successful_classifications,
                provenance=provenance
            )
            
            # Validate with LLM judge if available
            if self.validator and successful_classifications > 0:
                validation = self.validator.validate_command_success(
                    command.command_type, command.args, result, successful_classifications
                )
                
                if not validation.get("valid", True):
                    # Override status if LLM judge says it failed
                    result_obj.status = "error"
                    result_obj.error_message = f"LLM Judge Validation Failed: {validation.get('reason', 'Unknown validation failure')}"
                    print(f"DEBUG: CLASSIFY - LLM Judge validation failed: {validation}")
                else:
                    print(f"DEBUG: CLASSIFY - LLM Judge validation passed: {validation.get('reason', 'Valid')}")
            
            return result_obj
            
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _create_classify_prompt(self, data: Any, instruction: str) -> str:
        """Create prompt for LLM classification."""
        prompt = f"""You are classifying data according to this instruction: {instruction}

Data to classify (list of items):
{self._format_data_for_llm(data)}

Instructions:
1. Analyze each item and assign it to one of the specified categories
2. For each item, determine which category it belongs to
3. Return your results as a JSON object with this structure:
{{
  "classified_items": [
    {{"id": "item_id", "name": "item_name", "category": "category_name", "reason": "why this category"}},
    ...
  ],
  "summary": {{
    "total_classified": 0,
    "categories_found": ["category1", "category2", ...],
    "category_counts": {{"category1": 0, "category2": 0, ...}}
  }}
}}

Be consistent in your classification and provide clear reasoning for each decision.
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
                
                formatted.append(f"Item {i+1}:")
                formatted.append(f"  ID: {node_id}")
                formatted.append(f"  Name: {name}")
                formatted.append(f"  Entity Type: {entity_type}")
                formatted.append(f"  Description: {description}")
                formatted.append("")
        
        if len(data) > 20:
            formatted.append(f"... and {len(data) - 20} more items")
        
        return "\n".join(formatted)
