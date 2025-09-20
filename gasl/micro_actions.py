"""
Micro-action framework for handling large datasets with batching.
"""

from typing import Any, List, Dict, Optional
from .types import Command, ExecutionResult, Provenance
from .llm.argo_bridge import ArgoBridgeLLM


class MicroActionFramework:
    """Shared framework for all batching operations across commands."""
    
    def __init__(self, llm_func: ArgoBridgeLLM, state_store=None, context_store=None):
        self.llm_func = llm_func
        self.state_store = state_store
        self.context_store = context_store
    
    def execute_command_with_batching(self, data: List[Dict], command_type: str, 
                                    instruction: str, batch_size: int = None, 
                                    target_variable: str = None) -> ExecutionResult:
        """Execute any command with batching - the single source of truth for all batching."""
        
        if not isinstance(data, list) or len(data) == 0:
            return self._create_empty_result(command_type, instruction)
        
        if batch_size is None:
            batch_size = self._calculate_optimal_batch_size(data, instruction)
        
        # If all data fits in one batch, process normally
        if batch_size >= len(data):
            return self._execute_single_batch(data, command_type, instruction)
        
        print(f"DEBUG: MICRO_ACTIONS - Processing {len(data)} items in batches of {batch_size}")
        
        all_results = []
        total_batches = (len(data) + batch_size - 1) // batch_size
        
        for i in range(0, len(data), batch_size):
            batch = data[i:i + batch_size]
            batch_num = i // batch_size + 1
            
            print(f"DEBUG: MICRO_ACTIONS - Processing batch {batch_num}/{total_batches} ({len(batch)} items)")
            
            # Execute the core command logic on this batch
            batch_result = self._execute_single_batch(batch, command_type, instruction)
            
            if batch_result.status == "success":
                # Extract results based on command type
                if command_type == "PROCESS":
                    batch_items = batch_result.data.get("processed_items", [])
                elif command_type == "CLASSIFY":
                    batch_items = batch_result.data.get("updated_items", [])
                elif command_type == "COUNT":
                    batch_items = batch_result.data.get("count_results", [])
                elif command_type == "AGGREGATE":
                    batch_items = batch_result.data.get("aggregated_groups", [])
                else:
                    batch_items = batch_result.data.get("items", [])
                
                all_results.extend(batch_items)
            else:
                print(f"DEBUG: MICRO_ACTIONS - Batch {batch_num} failed: {batch_result.error_message}")
        
        print(f"DEBUG: MICRO_ACTIONS - Completed processing {len(all_results)} total items")
        
        # Create final result with all accumulated items
        return self._create_batched_result(command_type, instruction, all_results, len(data), target_variable)
    
    def _execute_single_batch(self, batch: List[Dict], command_type: str, instruction: str) -> ExecutionResult:
        """Execute core command logic on a single batch - the shared execution logic."""
        
        if command_type == "PROCESS":
            return self._process_batch(batch, instruction)
        elif command_type == "CLASSIFY":
            return self._classify_batch(batch, instruction)
        elif command_type == "COUNT":
            return self._count_batch(batch, instruction)
        elif command_type == "AGGREGATE":
            return self._aggregate_batch(batch, instruction)
        else:
            return self._create_error_result(f"Unknown command type: {command_type}")
    
    def _process_batch(self, batch: List[Dict], instruction: str) -> ExecutionResult:
        """Core PROCESS logic for a single batch."""
        prompt = self._create_process_prompt(batch, instruction)
        llm_response = self.llm_func.call(prompt)
        
        try:
            import json
            parsed_result = json.loads(llm_response)
            
            if "processed_items" in parsed_result:
                processed_items = parsed_result["processed_items"]
            elif "included" in parsed_result:
                # Map back to original nodes
                processed_items = []
                for item in parsed_result.get("included", []):
                    original_node = self._find_original_node(batch, item.get("id", ""))
                    if original_node:
                        processed_items.append(original_node)
            else:
                processed_items = []
            
            return self._create_result(
                status="success",
                data={"processed_items": processed_items},
                count=len(processed_items)
            )
            
        except json.JSONDecodeError:
            return self._create_error_result("Failed to parse LLM response as JSON")
    
    def _classify_batch(self, batch: List[Dict], instruction: str) -> ExecutionResult:
        """Core CLASSIFY logic for a single batch."""
        prompt = self._create_classify_prompt(batch, instruction)
        llm_response = self.llm_func.call(prompt)
        
        try:
            import json
            parsed_result = json.loads(llm_response)
            
            # Update original nodes with category field
            updated_items = []
            for item in batch:
                item_copy = item.copy()
                # Find classification for this item
                item_id = item.get("id", "")
                category = "unknown"
                
                for classified_item in parsed_result.get("classified_items", []):
                    if classified_item.get("id") == item_id:
                        category = classified_item.get("category", "unknown")
                        break
                
                item_copy["category"] = category
                updated_items.append(item_copy)
            
            return self._create_result(
                status="success",
                data={"updated_items": updated_items},
                count=len(updated_items)
            )
            
        except json.JSONDecodeError:
            return self._create_error_result("Failed to parse LLM response as JSON")
    
    def _count_batch(self, batch: List[Dict], instruction: str) -> ExecutionResult:
        """Core COUNT logic for a single batch."""
        # For COUNT, we need to know what field to count
        # This is a simplified version - real implementation would parse instruction
        field_name = "entity_type"  # Default field
        
        count_results = []
        field_counts = {}
        
        for item in batch:
            field_value = item.get(field_name, "unknown")
            field_counts[field_value] = field_counts.get(field_value, 0) + 1
        
        for field_value, count in field_counts.items():
            count_results.append({
                "field_value": field_value,
                "count": count
            })
        
        return self._create_result(
            status="success",
            data={"count_results": count_results},
            count=len(count_results)
        )
    
    def _aggregate_batch(self, batch: List[Dict], instruction: str) -> ExecutionResult:
        """Core AGGREGATE logic for a single batch."""
        # Simplified aggregation - group by entity_type
        groups = {}
        
        for item in batch:
            group_key = item.get("entity_type", "unknown")
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(item)
        
        aggregated_groups = []
        for group_key, items in groups.items():
            aggregated_groups.append({
                "group_key": group_key,
                "count": len(items),
                "items": items
            })
        
        return self._create_result(
            status="success",
            data={"aggregated_groups": aggregated_groups},
            count=len(aggregated_groups)
        )
    
    def _calculate_optimal_batch_size(self, data: List[Dict], instruction: str) -> int:
        """Calculate optimal batch size based on token estimation."""
        if len(data) <= 5:
            return len(data)
        
        # Test with different batch sizes
        for batch_size in [5, 10, 20, 50]:
            test_batch = data[:batch_size]
            test_prompt = self._create_process_prompt(test_batch, instruction)
            
            # Rough token estimation
            estimated_tokens = len(test_prompt.split()) * 1.3
            
            if estimated_tokens > 3000:  # Token limit
                return max(1, batch_size - 5)
        
        return min(50, len(data))  # Cap at 50 items
    
    def _create_process_prompt(self, data: List[Dict], instruction: str) -> str:
        """Create prompt for PROCESS command."""
        prompt = f"""You are processing graph data according to this instruction: {instruction}

Data to process (list of nodes):
{self._format_data_for_llm(data)}

Instructions:
1. Analyze each node's content (name, description, properties) according to the instruction
2. Return a JSON object with this structure:
{{
  "processed_items": [
    {{"id": "node_id", "name": "node_name", "processed_field": "value", "reason": "explanation"}},
    ...
  ],
  "summary": {{
    "total_processed": 0,
    "processing_type": "description of what was processed"
  }}
}}

Be thorough in your analysis and provide clear reasoning for each decision.
"""
        return prompt
    
    def _create_classify_prompt(self, data: List[Dict], instruction: str) -> str:
        """Create prompt for CLASSIFY command."""
        prompt = f"""You are classifying graph data according to this instruction: {instruction}

Data to classify (list of nodes):
{self._format_data_for_llm(data)}

Instructions:
1. Classify each node according to the instruction
2. Return a JSON object with this structure:
{{
  "classified_items": [
    {{"id": "node_id", "name": "node_name", "category": "classification", "reason": "explanation"}},
    ...
  ],
  "summary": {{
    "total_classified": 0,
    "categories_found": []
  }}
}}

Be consistent in your classifications and provide clear reasoning.
"""
        return prompt
    
    def _format_data_for_llm(self, data: List[Dict]) -> str:
        """Format data for LLM consumption."""
        if not isinstance(data, list):
            return str(data)
        
        formatted = []
        for i, item in enumerate(data):
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
        
        return "\n".join(formatted)
    
    def _find_original_node(self, data: List[Dict], target_id: str) -> Optional[Dict]:
        """Find the original node data by matching the ID."""
        for node in data:
            if isinstance(node, dict) and node.get("id") == target_id:
                return node
        return None
    
    def _create_result(self, status: str, data: Dict, count: int) -> ExecutionResult:
        """Create a basic ExecutionResult."""
        return ExecutionResult(
            command=None,  # Will be set by caller
            status=status,
            data=data,
            count=count,
            provenance=[],
            error_message=None
        )
    
    def _create_empty_result(self, command_type: str, instruction: str) -> ExecutionResult:
        """Create empty result for empty data."""
        return self._create_result(
            status="empty",
            data={"processed_items": []},
            count=0
        )
    
    def _create_error_result(self, error_message: str) -> ExecutionResult:
        """Create error result."""
        return ExecutionResult(
            command=None,
            status="error",
            data={},
            count=0,
            provenance=[],
            error_message=error_message
        )
    
    def _create_batched_result(self, command_type: str, instruction: str, 
                              all_results: List[Dict], original_count: int, 
                              target_variable: str = None) -> ExecutionResult:
        """Create final result for batched processing."""
        
        # Store results in state if target variable is provided
        if target_variable and all_results:
            self._store_results_in_state(target_variable, all_results, command_type)
        
        return self._create_result(
            status="success",
            data={"processed_items": all_results},
            count=len(all_results)
        )
    
    def _store_results_in_state(self, target_variable: str, results: List[Dict], command_type: str) -> None:
        """Store processed results back to the state variable."""
        if command_type == "PROCESS":
            # For PROCESS, store as processed_items
            self.state_store.update_variable(target_variable, results, "replace")
        elif command_type == "CLASSIFY":
            # For CLASSIFY, store as classified_items
            self.state_store.update_variable(target_variable, results, "replace")
        elif command_type == "COUNT":
            # For COUNT, store as count_results
            self.state_store.update_variable(target_variable, results, "replace")
        elif command_type == "AGGREGATE":
            # For AGGREGATE, store as aggregated_groups
            self.state_store.update_variable(target_variable, results, "replace")
        else:
            # Default storage
            self.state_store.update_variable(target_variable, results, "replace")
        
        print(f"DEBUG: MICRO_ACTIONS - Stored {len(results)} results in {target_variable}")
