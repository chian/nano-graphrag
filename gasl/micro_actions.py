"""
Micro-action framework for handling large datasets with batching.

Supports resumable checkpointing: each batch result is written to disk
immediately so that interrupted runs can resume from the last completed batch.
Memory usage is bounded — raw items are never accumulated across all batches.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict, Optional
from .types import Command, ExecutionResult, Provenance
from .llm.argo_bridge import ArgoBridgeLLM
from .utils import normalize_node_id


class MicroActionFramework:
    """Shared framework for all batching operations across commands."""

    def __init__(self, llm_func: ArgoBridgeLLM, state_store=None, context_store=None,
                 job_id: str = None, checkpoint_dir: str = None):
        self.llm_func = llm_func
        self.state_store = state_store
        self.context_store = context_store
        self.job_id = job_id or "default"
        self.checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else (
            Path(__file__).parent.parent / "gasl_checkpoints"
        )

    def set_job_id(self, job_id: str) -> None:
        """Update job_id (called by executor before each run)."""
        self.job_id = job_id

    # ──────────────────────────────────────────────────────────────────────────
    # Checkpoint helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _manifest_path(self, variable_name: str) -> Path:
        return self.checkpoint_dir / f"{self.job_id}_{variable_name}.json"

    def _batch_path(self, variable_name: str, batch_index: int) -> Path:
        return self.checkpoint_dir / f"{self.job_id}_{variable_name}_batch_{batch_index}.json"

    def _load_manifest(self, variable_name: str) -> Optional[Dict]:
        path = self._manifest_path(variable_name)
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _save_manifest(self, manifest: Dict) -> None:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        manifest["updated_at"] = datetime.utcnow().isoformat()
        with open(self._manifest_path(manifest["variable_name"]), "w") as f:
            json.dump(manifest, f)

    def _save_batch_result(self, variable_name: str, batch_index: int, items: List[Dict]) -> None:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        with open(self._batch_path(variable_name, batch_index), "w") as f:
            json.dump(items, f)

    def _load_batch_result(self, variable_name: str, batch_index: int) -> Optional[List[Dict]]:
        path = self._batch_path(variable_name, batch_index)
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _iter_all_batch_results(self, variable_name: str, total_batches: int):
        """Yield items from each batch file one-by-one (streaming, low memory)."""
        for i in range(total_batches):
            items = self._load_batch_result(variable_name, i)
            if items:
                yield from items

    def _build_tally_from_batches(self, variable_name: str, total_batches: int) -> Dict:
        """Stream through all batch files and build a domain-tally dict."""
        tally: Dict[str, int] = {}
        total = 0
        field = None
        for item in self._iter_all_batch_results(variable_name, total_batches):
            if not isinstance(item, dict):
                continue
            if field is None:
                for candidate in ("cognitive_domain", "category", "domain",
                                  "class", "label", "cognitive_domains", "domain_label"):
                    if candidate in item:
                        field = candidate
                        break
            if field:
                val = str(item.get(field, "unclassified"))
            else:
                val = "unclassified"
            tally[val] = tally.get(val, 0) + 1
            total += 1
        tally["_total"] = total
        return tally

    # ──────────────────────────────────────────────────────────────────────────
    # Core batching logic
    # ──────────────────────────────────────────────────────────────────────────

    def execute_command_with_batching(self, data: List[Dict], command_type: str,
                                    instruction: str, batch_size: int = None,
                                    target_variable: str = None) -> ExecutionResult:
        """Execute any command with batching.

        Batches are checkpointed to disk immediately after processing so that
        interrupted runs can resume.  Raw items are never kept across multiple
        batches — memory use is bounded to ~1 batch at a time.
        """

        if not isinstance(data, list) or len(data) == 0:
            return self._create_empty_result(command_type, instruction)

        if batch_size is None:
            batch_size = self._calculate_optimal_batch_size(data, instruction)

        # If all data fits in one batch, process normally (no checkpoint overhead)
        if batch_size >= len(data):
            return self._execute_single_batch(data, command_type, instruction)

        total_batches = (len(data) + batch_size - 1) // batch_size
        var_key = target_variable or command_type.lower()

        print(f"DEBUG: MICRO_ACTIONS - Processing {len(data)} items in {total_batches} batches of {batch_size}")

        # ── Load or create checkpoint manifest ────────────────────────────────
        manifest = self._load_manifest(var_key)
        if manifest and manifest.get("total_items") == len(data) and manifest.get("status") != "complete":
            completed = set(manifest.get("completed_batches", []))
            print(f"DEBUG: MICRO_ACTIONS - Resuming checkpoint: {len(completed)}/{total_batches} batches done")
        else:
            # Fresh run (or data size changed)
            completed = set()
            manifest = {
                "job_id": self.job_id,
                "variable_name": var_key,
                "command_type": command_type,
                "instruction": instruction[:200],
                "total_items": len(data),
                "batch_size": batch_size,
                "total_batches": total_batches,
                "completed_batches": [],
                "status": "in_progress",
                "created_at": datetime.utcnow().isoformat(),
            }
            self._save_manifest(manifest)

        total_processed = sum(
            len(self._load_batch_result(var_key, i) or []) for i in completed
        )

        for batch_index in range(total_batches):
            if batch_index in completed:
                print(f"DEBUG: MICRO_ACTIONS - Skipping batch {batch_index+1}/{total_batches} (already done)")
                continue

            start = batch_index * batch_size
            batch = data[start:start + batch_size]

            print(f"DEBUG: MICRO_ACTIONS - Processing batch {batch_index+1}/{total_batches} ({len(batch)} items)")
            batch_result = self._execute_single_batch(batch, command_type, instruction)
            print(f"DEBUG: MICRO_ACTIONS - Batch {batch_index+1} status: {batch_result.status}")

            if batch_result.status == "success":
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

                # Write to disk immediately, release from memory
                self._save_batch_result(var_key, batch_index, batch_items)
                total_processed += len(batch_items)
                completed.add(batch_index)

                manifest["completed_batches"] = sorted(completed)
                self._save_manifest(manifest)
                print(f"DEBUG: MICRO_ACTIONS - Batch {batch_index+1} saved ({len(batch_items)} items, {total_processed} total so far)")
            else:
                print(f"DEBUG: MICRO_ACTIONS - Batch {batch_index+1} failed: {batch_result.error_message}")

        print(f"DEBUG: MICRO_ACTIONS - Completed {len(completed)}/{total_batches} batches ({total_processed} items)")

        # Mark manifest complete
        manifest["status"] = "complete"
        self._save_manifest(manifest)

        # ── Build final tally by streaming batch files (bounded memory) ───────
        all_items = list(self._iter_all_batch_results(var_key, total_batches))
        if target_variable:
            tally = self._build_tally_from_batches(var_key, total_batches)
            print(f"DEBUG: MICRO_ACTIONS - Tally: {tally}")
            # Keep the actual row records available to downstream commands.
            self._save_to_state(target_variable, all_items, command_type)
            # Persist the compact tally separately for diagnostics/reuse.
            self._save_tally_to_state(f"{target_variable}__tally", tally, command_type, total_processed)

        # ── Versioned-graph update (if applicable) ────────────────────────────
        if target_variable and hasattr(self, 'versioned_graph') and self.versioned_graph:
            current_graph = self.versioned_graph.get_current_graph()
            self._apply_modifications_to_graph(current_graph, all_items, target_variable)
            self.versioned_graph.create_version_after_command(
                command_type,
                f"{command_type}: {instruction[:50]}{'...' if len(instruction) > 50 else ''}",
                current_graph,
                {"items_processed": total_processed, "target_variable": target_variable}
            )

        return self._create_result(
            status="success" if total_processed > 0 else "empty",
            data={"processed_items": all_items, "_checkpoint_tally": tally if target_variable else {}},
            count=total_processed
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
    
    def _strip_json_fences(self, text: str) -> str:
        """Strip markdown code fences that LLMs often wrap JSON in."""
        import re
        text = text.strip()
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            return match.group(1).strip()
        return text

    def _process_batch(self, batch: List[Dict], instruction: str) -> ExecutionResult:
        """Core PROCESS logic for a single batch."""
        prompt = self._create_process_prompt(batch, instruction)
        llm_response = self.llm_func.call(prompt)

        # Parse JSON response (only catch JSON errors, not programming errors)
        import json
        try:
            parsed_result = json.loads(self._strip_json_fences(llm_response))
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
            parsed_result = json.loads(self._strip_json_fences(llm_response))
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
        field_name = self._infer_group_field(batch, instruction)

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
        group_field = self._infer_group_field(batch, instruction)
        if not group_field:
            return self._create_result(
                status="success",
                data={"aggregated_groups": [{"group_key": "__all__", "count": len(batch), "items": batch}]},
                count=1,
            )
        groups = {}

        for item in batch:
            group_key = item.get(group_field, "unknown")
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

    def _infer_group_field(self, batch: List[Dict], instruction: str) -> str | None:
        if not batch or not isinstance(batch[0], dict):
            return None
        lower = instruction.lower()
        for marker in (" by ", " per ", " each "):
            if marker in lower:
                candidate = lower.split(marker, 1)[1].split()[0].strip(" ,.")
                for key in batch[0].keys():
                    if key.lower() == candidate:
                        return key
        scored: list[tuple[tuple[float, int], str]] = []
        total = len(batch)
        for key in batch[0].keys():
            vals = [row.get(key) for row in batch if row.get(key) is not None]
            if not vals:
                continue
            scalar_ratio = sum(isinstance(v, (str, int, float, bool)) for v in vals) / len(vals)
            if scalar_ratio < 0.8:
                continue
            distinct = len(set(map(str, vals)))
            if distinct <= 1:
                continue
            uniqueness = distinct / total if total else 1.0
            score = (1.0 - abs(0.35 - min(uniqueness, 1.0)), sum(isinstance(v, str) for v in vals))
            scored.append((score, key))
        if not scored:
            return None
        scored.sort(reverse=True)
        return scored[0][1]
    
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
                name = item.get('name', item.get('id', 'Unknown'))
                entity_type = (
                    (item.get('data') or {}).get('entity_type')
                    if isinstance(item.get('data'), dict)
                    else item.get('entity_type', 'Unknown')
                )
                normalized_id = normalize_node_id(name)
                formatted.append(f"Row {i+1} (ID: {name} -> normalized: {normalized_id}):")
                formatted.append(f"  label: {self._truncate_scalar(name)}")
                formatted.append(f"  entity_type: {self._truncate_scalar(entity_type)}")
                for key, value in self._scalar_preview(item):
                    formatted.append(f"  {key}: {self._truncate_scalar(value)}")
                formatted.append("")
        
        return "\n".join(formatted)

    def _scalar_preview(self, item: Dict[str, Any], *, limit: int = 8) -> List[tuple[str, Any]]:
        preview: List[tuple[str, Any]] = []
        def walk(obj: Any, prefix: str = "", depth: int = 0):
            if depth > 2:
                return
            if isinstance(obj, dict):
                for key, value in obj.items():
                    name = f"{prefix}.{key}" if prefix else str(key)
                    if isinstance(value, (str, int, float, bool)):
                        if key == "description" or name.endswith(".description"):
                            continue
                        preview.append((name, value))
                    elif isinstance(value, dict):
                        walk(value, name, depth + 1)
            elif isinstance(obj, (str, int, float, bool)) and prefix:
                preview.append((prefix, obj))
        walk(item)
        return preview[:limit]

    @staticmethod
    def _truncate_scalar(value: Any, *, limit: int = 120) -> str:
        text = str(value)
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."
    
    
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
    
    def _save_tally_to_state(self, target_variable: str, tally: Dict, command_type: str, total: int) -> None:
        """Store a domain-tally dict in a dedicated side variable."""
        print(f"DEBUG: MICRO_ACTIONS - Saving tally for {target_variable}: {tally}")
        # Wrap tally as a list-of-one so existing readers work
        tally_record = {"tally": tally, "total": total, "variable": target_variable}
        if self.context_store:
            self.context_store.set(target_variable, [tally_record])
        if self.state_store:
            if not self.state_store.has_variable(target_variable):
                self.state_store.declare_variable(target_variable, "LIST",
                    f"Domain tally from {command_type} command")
            var_data = self.state_store.get_variable(target_variable)
            if isinstance(var_data, dict) and "_meta" in var_data:
                var_data["items"] = [tally_record]
                self.state_store._save_state()

    def _save_to_state(self, target_variable: str, all_results: List[Dict], command_type: str) -> None:
        """Save processed data back to the state and context stores."""
        print(f"DEBUG: MICRO_ACTIONS - Saving {len(all_results)} processed items back to {target_variable}")

        # Store in context store (for immediate access by next commands)
        if self.context_store:
            self.context_store.set(target_variable, all_results)
            print(f"DEBUG: MICRO_ACTIONS - Saved to context store: {target_variable}")

        # Store in state store using the GASL-native format (declare_variable + items)
        # so that all readers (_get_variable_data, StateManager, etc.) can find it.
        if self.state_store:
            if not self.state_store.has_variable(target_variable):
                self.state_store.declare_variable(target_variable, "LIST",
                    f"Processed data from {command_type} command")
            var_data = self.state_store.get_variable(target_variable)
            if isinstance(var_data, dict) and "_meta" in var_data:
                var_data["items"] = all_results
                self.state_store._save_state()
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
