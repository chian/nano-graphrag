"""
Micro-action framework for handling large datasets with batching.
"""

from typing import Any, List, Dict, Optional
from .types import Command, ExecutionResult, Provenance
from .llm.argo_bridge import ArgoBridgeLLM
from .utils import normalize_node_id


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
            
            print(f"DEBUG: MICRO_ACTIONS - Batch {batch_num} status: {batch_result.status}")
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
                
                print(f"DEBUG: MICRO_ACTIONS - Batch {batch_num} extracted {len(batch_items)} items")
                all_results.extend(batch_items)
            else:
                print(f"DEBUG: MICRO_ACTIONS - Batch {batch_num} failed: {batch_result.error_message}")
        
        print(f"DEBUG: MICRO_ACTIONS - Completed processing {len(all_results)} total items")
        
        # Save the processed data back to storage and create new version
        if target_variable and all_results:
            self._save_to_state(target_variable, all_results, command_type)
            
            # Auto-create version if we have a versioned graph
            if hasattr(self, 'versioned_graph') and self.versioned_graph:
                # Apply modifications to current graph
                current_graph = self.versioned_graph.get_current_graph()
                self._apply_modifications_to_graph(current_graph, all_results, target_variable)
                
                # Create new version
                self.versioned_graph.create_version_after_command(
                    command_type,
                    f"{command_type}: {instruction[:50]}{'...' if len(instruction) > 50 else ''}",
                    current_graph,
                    {"items_processed": len(all_results), "target_variable": target_variable}
                )
        
        # Create final result
        return self._create_result(
            status="success" if all_results else "empty",
            data={"processed_items": all_results} if command_type == "PROCESS" else {"items": all_results},
            count=len(all_results)
        )
    
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
        
        # Parse JSON response (only catch JSON errors, not programming errors)
        import json
        try:
            parsed_result = json.loads(llm_response)
        except json.JSONDecodeError:
            return self._create_error_result("Failed to parse LLM response as JSON")
        
        if "processed_items" in parsed_result:
            # Handle dynamic field names - merge the new fields back into original nodes
            processed_items = []
            print(f"DEBUG: MICRO_ACTIONS - Processing {len(parsed_result['processed_items'])} items from LLM response")
            for processed_item in parsed_result["processed_items"]:
                # Find the original node
                original_node = self._find_original_node(batch, processed_item.get("id", ""))
                print(f"DEBUG: MICRO_ACTIONS - Looking for node ID '{processed_item.get('id', '')}', found: {original_node is not None}")
                if original_node:
                    # Create a copy of the original node
                    updated_node = original_node.copy()
                    
                    # Add all fields from the processed item (except id, name, reason)
                    new_fields = []
                    for key, value in processed_item.items():
                        if key not in ["id", "name", "reason"]:
                            updated_node[key] = value
                            new_fields.append(f"{key}={value}")
                    
                    print(f"DEBUG: MICRO_ACTIONS - Added fields to node {processed_item.get('id', '')}: {', '.join(new_fields)}")
                    processed_items.append(updated_node)
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
    
    def _find_original_node(self, data: List[Dict], target_id: str) -> Dict:
        """Find the original node by ID, with quote normalization."""
        target_normalized = normalize_node_id(target_id)
        
        for item in data:
            if isinstance(item, dict):
                # Check for stable_id in nested data structure (FIND results)
                if "data" in item and isinstance(item["data"], dict):
                    item_stable_id = item["data"].get("stable_id")
                    if item_stable_id and normalize_node_id(item_stable_id) == target_normalized:
                        return item
                
                # Check for stable_id in flat structure
                item_stable_id = item.get("stable_id")
                if item_stable_id and normalize_node_id(item_stable_id) == target_normalized:
                    return item
                
                # Fallback: check direct ID field (for backward compatibility)
                item_id = item.get("id")
                if item_id and normalize_node_id(item_id) == target_normalized:
                    return item
        
        # If not found, show debug info
        print(f"DEBUG: MICRO_ACTIONS - Could not find node '{target_id}' (normalized: '{target_normalized}') in batch data")
        if data and len(data) > 0:
            sample_item = data[0]
            print(f"DEBUG: MICRO_ACTIONS - Sample batch item structure: {list(sample_item.keys()) if isinstance(sample_item, dict) else type(sample_item)}")
            if isinstance(sample_item, dict):
                if "id" in sample_item:
                    print(f"DEBUG: MICRO_ACTIONS - Sample batch item top-level ID: '{sample_item['id']}' (normalized: '{normalize_node_id(sample_item['id'])}')")
                if "data" in sample_item and isinstance(sample_item["data"], dict):
                    data_id = sample_item["data"].get("id", "no_id_in_data")
                    print(f"DEBUG: MICRO_ACTIONS - Sample batch item data.id: '{data_id}' (normalized: '{normalize_node_id(data_id)}')")
        return None
    
    def _classify_batch(self, batch: List[Dict], instruction: str) -> ExecutionResult:
        """Core CLASSIFY logic for a single batch."""
        prompt = self._create_classify_prompt(batch, instruction)
        llm_response = self.llm_func.call(prompt)
        
        # Parse JSON response (only catch JSON errors, not programming errors)
        import json
        try:
            parsed_result = json.loads(llm_response)
        except json.JSONDecodeError:
            return self._create_error_result("Failed to parse LLM response as JSON")
        
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
        """Create prompt for PROCESS command using unified prompt system."""
        from nano_graphrag.prompt_system import QueryAwarePromptSystem
        
        # Use the unified prompt system
        prompt_system = QueryAwarePromptSystem()
        
        # Get the base prompt from the prompts directory
        base_prompt = prompt_system.get_prompt("process_batch")
        
        # Format the data for LLM consumption
        formatted_data = self._format_data_for_llm(data)
        
        # Compose the final prompt with the data and instruction
        final_prompt = base_prompt.format(
            instruction=instruction,
            data=formatted_data
        )
        
        return final_prompt
    
    def _create_classify_prompt(self, data: List[Dict], instruction: str) -> str:
        """Create prompt for CLASSIFY command using unified prompt system."""
        from nano_graphrag.prompt_system import QueryAwarePromptSystem
        
        # Use the unified prompt system
        prompt_system = QueryAwarePromptSystem()
        
        # Get the base prompt from the prompts directory
        base_prompt = prompt_system.get_prompt("classify_batch")
        
        # Format the data for LLM consumption
        formatted_data = self._format_data_for_llm(data)
        
        # Compose the final prompt with the data and instruction
        final_prompt = base_prompt.format(
            instruction=instruction,
            data=formatted_data
        )
        
        return final_prompt
    
    def _format_data_for_llm(self, data: List[Dict]) -> str:
        """Format data for LLM consumption."""
        if not isinstance(data, list):
            return str(data)
        
        formatted = []
        for i, item in enumerate(data):
            if isinstance(item, dict):
                # Get stable ID and name
                if 'data' in item and isinstance(item['data'], dict):
                    data_dict = item['data']
                    stable_id = data_dict.get('stable_id', f'item_{i}')
                    name = item.get('id', 'Unknown')  # The top-level ID is the entity name
                    description = data_dict.get('description', 'No description')
                    entity_type = data_dict.get('entity_type', 'Unknown')
                else:
                    # Handle flat structure (for processed data)
                    stable_id = item.get('stable_id', f'item_{i}')
                    name = item.get('name', item.get('id', 'Unknown'))
                    description = item.get('description', 'No description')
                    entity_type = item.get('entity_type', 'Unknown')
                
                processed_field = item.get('processed_field', 'No processed field')
                
                # Show both original and normalized IDs
                normalized_id = normalize_node_id(name)
                formatted.append(f"Node {i+1} (ID: {name} -> normalized: {normalized_id}):")
                formatted.append(f"  Name: {name}")
                formatted.append(f"  Entity Type: {entity_type}")
                formatted.append(f"  Description: {description}")
                formatted.append(f"  Processed Field: {processed_field}")
                formatted.append("")
        
        return "\n".join(formatted)
    
    
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
    
    def _save_to_state(self, target_variable: str, all_results: List[Dict], command_type: str) -> None:
        """Save processed data back to the state and context stores."""
        print(f"DEBUG: MICRO_ACTIONS - Saving {len(all_results)} processed items back to {target_variable}")
        
        # Store in context store (for immediate access by next commands)
        if self.context_store:
            self.context_store.set(target_variable, all_results)
            print(f"DEBUG: MICRO_ACTIONS - Saved to context store: {target_variable}")
        
        # Also store in state store if available (for persistence)
        if self.state_store:
            self.state_store.set_variable_with_fields(
                target_variable,
                all_results,
                "LIST",
                f"Processed data from {command_type} command"
            )
            print(f"DEBUG: MICRO_ACTIONS - Saved to state store: {target_variable}")
    
    def _save_to_graph(self, target_variable: str, all_results: List[Dict], command_type: str) -> None:
        """Save processed data back to the graph (for future implementation)."""
        # This would be implemented if we need to save back to the actual graph structure
        # For now, the state/context storage should be sufficient
        pass
    
    def _apply_modifications_to_graph(self, graph: 'nx.Graph', processed_data: List[Dict], target_variable: str) -> None:
        """Apply processed data modifications directly to the NetworkX graph."""
        print(f"DEBUG: MICRO_ACTIONS - Applying {len(processed_data)} modifications to graph")
        
        modifications_applied = 0
        for item in processed_data:
            if not isinstance(item, dict):
                continue
                
            node_id = item.get('id')
            if not node_id:
                continue
            
            # Check if node exists in graph
            if node_id in graph.nodes:
                # Apply all new fields to the graph node
                for key, value in item.items():
                    if key not in ['id', 'name', 'reason', 'data', 'type']:  # Skip metadata fields
                        graph.nodes[node_id][key] = value
                        print(f"DEBUG: MICRO_ACTIONS - Added {key}={value} to node {node_id}")
                        modifications_applied += 1
            else:
                print(f"DEBUG: MICRO_ACTIONS - Warning: Node {node_id} not found in graph")
        
        print(f"DEBUG: MICRO_ACTIONS - Applied {modifications_applied} field modifications to graph")
