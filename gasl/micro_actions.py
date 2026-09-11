from __future__ import annotations
"""
Micro-action framework for handling large datasets with batching.

Supports resumable checkpointing: each batch result is written to disk
immediately so that interrupted runs can resume from the last completed batch.
Memory usage is bounded — raw items are never accumulated across all batches.
"""

import json
import os
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict, Optional
from .json_utils import extract_json
from .process_runtime import (
    normalize_table_items,
    recover_row_container,
    requires_row_materialization,
)
from .types import Command, ExecutionResult, Provenance
from .llm.argo_bridge import ArgoBridgeLLM
from .utils import normalize_node_id


_IMMUTABLE_IDENTITY_FIELDS = {
    "id",
    "row_id",
    "left_row_id",
    "right_row_id",
    "parent_row_id",
}
_ROW_PRESERVING_SYNTHETIC_FALLBACK_ERROR_PREFIX = (
    "Row-preserving PROCESS synthesized "
)


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
        self.batch_retries = max(0, int(os.getenv("GASL_MICRO_BATCH_RETRIES", "2")))

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

    def _iter_batch_results(self, variable_name: str, batch_indexes: List[int]):
        """Yield items from each batch file one-by-one (streaming, low memory)."""
        for i in batch_indexes:
            items = self._load_batch_result(variable_name, i)
            if items:
                yield from items

    def _build_tally_from_batches(self, variable_name: str, batch_indexes: List[int]) -> Dict:
        """Stream through all batch files and build a domain-tally dict."""
        tally: Dict[str, int] = {}
        total = 0
        field = None
        for item in self._iter_batch_results(variable_name, batch_indexes):
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
                                    target_variable: str = None,
                                    preserve_input_count: bool = False,
                                    store_target: bool = True) -> ExecutionResult:
        """Execute any command with batching.

        Batches are checkpointed to disk immediately after processing so that
        interrupted runs can resume.  Raw items are never kept across multiple
        batches — memory use is bounded to ~1 batch at a time.
        """

        if not isinstance(data, list) or len(data) == 0:
            return self._create_empty_result(command_type, instruction)

        if batch_size is None:
            batch_size = self._calculate_optimal_batch_size(
                data,
                instruction,
                target_variable=target_variable,
            )

        # If all data fits in one batch, process normally (no checkpoint overhead)
        if batch_size >= len(data):
            return self._execute_batch_with_retries(
                data,
                command_type,
                instruction,
                target_variable=target_variable,
                preserve_input_count=preserve_input_count,
            )

        total_batches = (len(data) + batch_size - 1) // batch_size
        var_key = target_variable or command_type.lower()
        signature = self._checkpoint_signature(
            data=data,
            command_type=command_type,
            instruction=instruction,
            batch_size=batch_size,
            total_batches=total_batches,
            target_variable=target_variable,
            preserve_input_count=preserve_input_count,
        )

        print(f"DEBUG: MICRO_ACTIONS - Processing {len(data)} items in {total_batches} batches of {batch_size}")

        # ── Load or create checkpoint manifest ────────────────────────────────
        manifest = self._load_manifest(var_key)
        if (
            manifest
            and manifest.get("status") != "complete"
            and self._manifest_matches(manifest, signature)
        ):
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
                "signature": signature,
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
            batch_result = self._execute_batch_with_retries(
                batch,
                command_type,
                instruction,
                target_variable=target_variable,
                preserve_input_count=preserve_input_count,
            )
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

        if len(completed) < total_batches:
            manifest["completed_batches"] = sorted(completed)
            manifest["status"] = "in_progress"
            self._save_manifest(manifest)
            return self._create_error_result(
                f"{command_type} completed {len(completed)}/{total_batches} batches"
            )

        completed_batches = sorted(completed)
        manifest["completed_batches"] = completed_batches
        manifest["status"] = "complete"
        self._save_manifest(manifest)

        # ── Build final tally by streaming batch files (bounded memory) ───────
        all_items = list(self._iter_batch_results(var_key, completed_batches))
        tally = {}
        if target_variable:
            tally = self._build_tally_from_batches(var_key, completed_batches)
            print(f"DEBUG: MICRO_ACTIONS - Tally: {tally}")
            if store_target:
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
            data={"processed_items": all_items, "_checkpoint_tally": tally},
            count=total_processed
        )

    def _enforce_input_count(
        self,
        result: ExecutionResult,
        *,
        expected_count: int,
        preserve_input_count: bool,
        allow_synthesized_fallbacks: bool = False,
    ) -> ExecutionResult:
        if not preserve_input_count or result.status != "success":
            return result
        items = self._items_for_result(result)
        synthetic_repairs = self._count_synthesized_missing_rows(items)
        if synthetic_repairs and not allow_synthesized_fallbacks:
            return self._create_error_result(
                f"{_ROW_PRESERVING_SYNTHETIC_FALLBACK_ERROR_PREFIX}"
                f"{synthetic_repairs} fallback rows; retrying the batch "
                "instead of accepting incomplete LLM output"
            )
        if len(items) == expected_count:
            return result
        return self._create_error_result(
            "Row-preserving PROCESS expected "
            f"{expected_count} output rows but produced {len(items)}"
        )

    @staticmethod
    def _items_for_result(result: ExecutionResult) -> List[Dict]:
        if not isinstance(result.data, dict):
            return []
        return (
            result.data.get("processed_items")
            or result.data.get("updated_items")
            or result.data.get("count_results")
            or result.data.get("aggregated_groups")
            or result.data.get("items")
            or []
        )

    @staticmethod
    def _count_synthesized_missing_rows(items: List[Dict]) -> int:
        return sum(
            1
            for item in items
            if (
                isinstance(item, dict)
                and item.get("_row_preserving_repair")
                == "synthesized_missing_process_row"
            )
        )

    def _checkpoint_signature(
        self,
        *,
        data: List[Dict],
        command_type: str,
        instruction: str,
        batch_size: int,
        total_batches: int,
        target_variable: str | None,
        preserve_input_count: bool,
    ) -> Dict[str, Any]:
        input_hash = hashlib.sha256()
        for item in data:
            input_hash.update(
                json.dumps(
                    item,
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            input_hash.update(b"\n")

        return {
            "command_type": command_type,
            "instruction_hash": hashlib.sha256(
                instruction.encode("utf-8")
            ).hexdigest(),
            "target_variable": target_variable or "",
            "batch_size": batch_size,
            "total_batches": total_batches,
            "total_items": len(data),
            "preserve_input_count": preserve_input_count,
            "input_hash": input_hash.hexdigest(),
        }

    @staticmethod
    def _manifest_matches(manifest: Dict[str, Any], signature: Dict[str, Any]) -> bool:
        return manifest.get("signature") == signature
    
    def _execute_single_batch(
        self,
        batch: List[Dict],
        command_type: str,
        instruction: str,
        target_variable: str = None,
        preserve_input_count: bool = False,
    ) -> ExecutionResult:
        """Execute core command logic on a single batch - the shared execution logic."""
        
        if command_type == "PROCESS":
            return self._process_batch(
                batch,
                instruction,
                target_variable=target_variable,
                preserve_input_count=preserve_input_count,
            )
        elif command_type == "CLASSIFY":
            return self._classify_batch(batch, instruction)
        elif command_type == "COUNT":
            return self._count_batch(batch, instruction)
        elif command_type == "AGGREGATE":
            return self._aggregate_batch(batch, instruction)
        else:
            return self._create_error_result(f"Unknown command type: {command_type}")
    
    def _strip_json_fences(self, text: str) -> str:
        """Extract a JSON payload from an LLM response."""
        return extract_json(text)

    def _execute_batch_with_retries(
        self,
        batch: List[Dict],
        command_type: str,
        instruction: str,
        target_variable: str = None,
        preserve_input_count: bool = False,
    ) -> ExecutionResult:
        last_result: Optional[ExecutionResult] = None
        for attempt in range(self.batch_retries + 1):
            attempt_instruction = (
                instruction
                if attempt == 0
                else self._retry_instruction(
                    instruction,
                    attempt=attempt,
                    last_result=last_result,
                )
            )
            result = self._execute_single_batch(
                batch,
                command_type,
                attempt_instruction,
                target_variable=target_variable,
                preserve_input_count=preserve_input_count,
            )
            checked_result = self._enforce_input_count(
                result,
                expected_count=len(batch),
                preserve_input_count=preserve_input_count,
            )
            if checked_result.status == "success":
                if attempt:
                    print(
                        "DEBUG: MICRO_ACTIONS - "
                        f"Batch recovered on retry {attempt}/{self.batch_retries}"
                    )
                return checked_result

            if (
                attempt >= self.batch_retries
                and self._only_failed_on_synthesized_fallbacks(checked_result)
            ):
                final_result = self._enforce_input_count(
                    result,
                    expected_count=len(batch),
                    preserve_input_count=preserve_input_count,
                    allow_synthesized_fallbacks=True,
                )
                if final_result.status == "success":
                    synthetic_repairs = self._count_synthesized_missing_rows(
                        self._items_for_result(final_result)
                    )
                    print(
                        "DEBUG: MICRO_ACTIONS - Accepting "
                        f"{synthetic_repairs} synthesized row-preserving "
                        "fallback rows after retries were exhausted"
                    )
                    return final_result

            last_result = checked_result
            if not self._batch_result_retryable(checked_result):
                return checked_result
            if attempt < self.batch_retries:
                print(
                    "DEBUG: MICRO_ACTIONS - "
                    f"Retrying failed batch {attempt + 1}/{self.batch_retries}: "
                    f"{checked_result.error_message or checked_result.status}"
                )

        return last_result or self._create_error_result("Batch failed")

    @staticmethod
    def _only_failed_on_synthesized_fallbacks(result: ExecutionResult) -> bool:
        return (
            result.status == "error"
            and bool(result.error_message)
            and result.error_message.startswith(
                _ROW_PRESERVING_SYNTHETIC_FALLBACK_ERROR_PREFIX
            )
        )

    @staticmethod
    def _batch_result_retryable(result: ExecutionResult) -> bool:
        return result.status == "error"

    @staticmethod
    def _retry_instruction(
        instruction: str,
        *,
        attempt: int,
        last_result: Optional[ExecutionResult],
    ) -> str:
        error = (
            (last_result.error_message if last_result is not None else "")
            or (last_result.status if last_result is not None else "")
            or "the previous attempt failed"
        )
        return (
            f"{instruction}\n\n"
            f"Retry pass {attempt}: the previous attempt failed with: {error}. "
            "Return only the strict JSON object expected by this command, with "
            "no markdown fences, comments, or prose outside the JSON. Preserve "
            "the original task and input IDs exactly."
        )

    def _process_batch(
        self,
        batch: List[Dict],
        instruction: str,
        target_variable: str = None,
        preserve_input_count: bool = False,
    ) -> ExecutionResult:
        """Core PROCESS logic for a single batch."""
        parsed_result = self._call_process_llm(batch, instruction, target_variable)
        if isinstance(parsed_result, ExecutionResult):
            return parsed_result
        
        payload_key, raw_items = self._process_payload_items(
            parsed_result,
            target_variable,
        )
        if payload_key == "processed_items":
            # Handle dynamic field names - merge the new fields back into original nodes
            print(f"DEBUG: MICRO_ACTIONS - Processing {len(raw_items)} items from LLM response")
            if preserve_input_count:
                processed_items = self._row_preserving_process_items(
                    batch,
                    raw_items,
                    instruction,
                    target_variable=target_variable,
                )
            else:
                processed_items = self._merge_processed_items(
                    batch,
                    raw_items,
                    preserve_input_count=False,
                )
        elif payload_key == "included":
            if requires_row_materialization(instruction, target_variable):
                return self._create_error_result(
                    "PROCESS was required to materialize row objects but "
                    "returned filter decisions."
                )

            # Map back to original nodes
            processed_items = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                original_node = self._find_original_node(batch, item.get("id", ""))
                if original_node:
                    processed_items.append(original_node)
        else:
            processed_items = []
        
        processed_items = self._filter_target_table_items(
            processed_items,
            target_variable,
        )

        return self._create_result(
            status="success",
            data={"processed_items": processed_items},
            count=len(processed_items)
        )

    def _call_process_llm(
        self,
        batch: List[Dict],
        instruction: str,
        target_variable: str = None,
    ) -> Dict[str, Any] | List[Any] | ExecutionResult:
        prompt = self._create_process_prompt(batch, instruction, target_variable)
        llm_response = self._invoke_llm(prompt)
        if isinstance(llm_response, ExecutionResult):
            return llm_response

        # Parse JSON response (only catch JSON errors, not programming errors)
        try:
            return json.loads(self._strip_json_fences(llm_response))
        except json.JSONDecodeError:
            return self._create_error_result("Failed to parse LLM response as JSON")

    def _invoke_llm(self, prompt: str) -> str | ExecutionResult:
        """Call the provider, turning a raising call into a failed batch.

        A provider call can fail for reasons that are not defects in this
        engine (transport, rate limiting, an exhausted or unavailable backend).
        Such a failure must fail its own batch so the caller can retry it and
        so an incomplete run commits nothing — it must not escape and abort the
        whole batching loop. Errors raised by our own parsing and merging below
        are deliberately left to propagate.
        """
        try:
            return self.llm_func.call(prompt)
        except Exception as exc:  # noqa: BLE001 - provider failures are data
            return self._create_error_result(
                f"LLM call failed: {type(exc).__name__}: {exc}"
            )

    @staticmethod
    def _process_payload_items(
        parsed_result: Dict[str, Any] | List[Any],
        target_variable: str = None,
    ) -> tuple[str, List[Any]]:
        if isinstance(parsed_result, list):
            return "processed_items", parsed_result

        if not isinstance(parsed_result, dict):
            return "", []

        for key in ("processed_items", "included"):
            value = parsed_result.get(key)
            if isinstance(value, list):
                return key, value

        recovered = recover_row_container(parsed_result, target_variable)
        if recovered is not None:
            return "processed_items", recovered

        return "", []

    def _merge_processed_items(
        self,
        batch: List[Dict],
        raw_processed_items: List[Any],
        *,
        preserve_input_count: bool,
    ) -> List[Dict]:
        if not preserve_input_count:
            processed_items = []
            for index, processed_item in enumerate(raw_processed_items):
                if not isinstance(processed_item, dict):
                    continue

                processed_id = processed_item.get("id", "")
                original_node = (
                    self._find_original_node(batch, processed_id)
                    if processed_id
                    else None
                )
                if (
                    original_node is None
                    and not processed_id
                    and len(raw_processed_items) == len(batch)
                ):
                    original_node = batch[index]

                print(
                    f"DEBUG: MICRO_ACTIONS - Looking for node ID '{processed_id}', "
                    f"found: {original_node is not None}"
                )
                if original_node is not None:
                    processed_items.append(
                        self._merge_processed_item(original_node, processed_item)
                    )
                    continue

                processed_items.append(processed_item.copy())

            return processed_items

        slots, unmatched = self._merge_processed_item_slots(
            batch,
            raw_processed_items,
            preserve_input_count=preserve_input_count,
        )
        if preserve_input_count:
            return [slots[index] for index in range(len(batch)) if index in slots]
        return [*slots.values(), *unmatched]

    def _row_preserving_process_items(
        self,
        batch: List[Dict],
        raw_processed_items: List[Any],
        instruction: str,
        target_variable: str = None,
    ) -> List[Dict]:
        slots, _ = self._merge_processed_item_slots(
            batch,
            raw_processed_items,
            preserve_input_count=True,
        )
        missing_indexes = [index for index in range(len(batch)) if index not in slots]
        if missing_indexes:
            print(
                "DEBUG: MICRO_ACTIONS - "
                f"Repairing {len(missing_indexes)} missing row-preserving outputs"
            )
            missing_batch = [batch[index] for index in missing_indexes]
            retry_instruction = (
                f"{instruction}\n\n"
                "Repair pass: emit exactly one processed_items entry for every "
                "row in this smaller repair batch. Use each row ID exactly as "
                "shown and do not create rows for absent inputs."
            )
            retry_result = self._call_process_llm(
                missing_batch,
                retry_instruction,
                target_variable,
            )
            if not isinstance(retry_result, ExecutionResult):
                _, retry_items = self._process_payload_items(
                    retry_result,
                    target_variable,
                )
                retry_slots, _ = self._merge_processed_item_slots(
                    missing_batch,
                    retry_items,
                    preserve_input_count=True,
                )
                for retry_index, item in retry_slots.items():
                    slots[missing_indexes[retry_index]] = item
                print(
                    "DEBUG: MICRO_ACTIONS - Row-preserving repair filled "
                    f"{len(retry_slots)}/{len(missing_indexes)} missing rows"
                )

        for index in range(len(batch)):
            if index not in slots:
                slots[index] = self._fallback_row_for_missing_input(
                    batch[index],
                    instruction,
                )

        return [slots[index] for index in range(len(batch))]

    def _merge_processed_item_slots(
        self,
        batch: List[Dict],
        raw_processed_items: List[Any],
        *,
        preserve_input_count: bool,
    ) -> tuple[Dict[int, Dict], List[Dict]]:
        slots: Dict[int, Dict] = {}
        unmatched: List[Dict] = []
        ordinal_candidates: List[tuple[int, Dict, str]] = []

        for index, processed_item in enumerate(raw_processed_items):
            if not isinstance(processed_item, dict):
                continue

            processed_id = (
                processed_item.get("id")
                or processed_item.get("row_id")
                or processed_item.get("group_key")
                or ""
            )
            original_index = (
                self._find_original_node_index(batch, processed_id)
                if processed_id
                else None
            )

            found = original_index is not None and original_index not in slots
            print(f"DEBUG: MICRO_ACTIONS - Looking for node ID '{processed_id}', found: {found}")
            if found:
                slots[original_index] = self._merge_processed_item(
                    batch[original_index],
                    processed_item,
                )
                continue

            if original_index is None:
                ordinal_candidates.append((index, processed_item, str(processed_id)))
            elif not preserve_input_count:
                unmatched.append(processed_item.copy())

        for index, processed_item, processed_id in ordinal_candidates:
            original_index = self._ordinal_fallback_index(
                batch,
                raw_processed_items,
                output_index=index,
                slots=slots,
                preserve_input_count=preserve_input_count,
                processed_id=processed_id,
            )
            if original_index is None:
                if not preserve_input_count:
                    unmatched.append(processed_item.copy())
                continue

            print(
                "DEBUG: MICRO_ACTIONS - Mapping unmatched node ID "
                f"'{processed_id}' by output ordinal {index}"
            )
            slots[original_index] = self._merge_processed_item(
                batch[original_index],
                processed_item,
            )

        return slots, unmatched

    @staticmethod
    def _ordinal_fallback_index(
        batch: List[Dict],
        raw_processed_items: List[Any],
        *,
        output_index: int,
        slots: Dict[int, Dict],
        preserve_input_count: bool,
        processed_id: str,
    ) -> int | None:
        if output_index >= len(batch) or output_index in slots:
            return None

        if preserve_input_count:
            return output_index

        if not processed_id and len(raw_processed_items) == len(batch):
            return output_index

        return None

    def _merge_processed_item(
        self,
        original_node: Dict,
        processed_item: Dict,
    ) -> Dict:
        updated_node = original_node.copy()
        new_fields = []
        for key, value in processed_item.items():
            if key not in _IMMUTABLE_IDENTITY_FIELDS and key not in ["name", "reason"]:
                updated_node[key] = value
                new_fields.append(f"{key}={value}")

        print(
            "DEBUG: MICRO_ACTIONS - Added fields to node "
            f"{processed_item.get('id', '')}: {', '.join(new_fields)}"
        )
        return updated_node

    def _fallback_row_for_missing_input(
        self,
        original: Dict,
        instruction: str,
    ) -> Dict:
        row = original.copy()
        for column in self._required_columns_from_instruction(instruction):
            if column not in row:
                row[column] = self._fallback_column_value(original, column)
        if "evidence_gap" not in row or not row.get("evidence_gap"):
            row["evidence_gap"] = (
                "LLM omitted this row during row-preserving PROCESS; "
                "retained the original input and filled unavailable target "
                "columns with null."
            )
        row["_row_preserving_repair"] = "synthesized_missing_process_row"
        return row

    @staticmethod
    def _required_columns_from_instruction(instruction: str) -> List[str]:
        match = re.search(
            r"required (?:output )?columns(?: exactly)?:\s*(.*?)(?:\.|\n|$)",
            instruction or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return []

        columns = []
        for part in match.group(1).replace(" and ", ",").split(","):
            column = part.strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column):
                columns.append(column)
        return columns

    def _fallback_column_value(self, original: Dict, column: str) -> Any:
        for path in (column, f"data.{column}"):
            value = self._nested_value(original, path)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _nested_value(item: Dict, path: str) -> Any:
        current: Any = item
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    @staticmethod
    def _filter_target_table_items(
        items: List[Dict],
        target_variable: str = None,
    ) -> List[Dict]:
        return normalize_table_items(items, target_variable)
    
    def _find_original_node(self, data: List[Dict], target_id: str) -> Optional[Dict]:
        """Find the original node by ID, with quote normalization."""
        index = self._find_original_node_index(data, target_id)
        return data[index] if index is not None else None

    def _find_original_node_index(
        self,
        data: List[Dict],
        target_id: str,
    ) -> int | None:
        """Find the original node index by ID, with quote normalization.

        Identity is matched only against IDs the input batch actually carries.
        An output ID of the form ``row_1``/``item 3`` is NOT read as a
        positional reference to the Nth input: when PROCESS materializes rows,
        those are legitimate synthetic row identities, and resolving them
        positionally silently rewrote a new row into an unrelated input row and
        destroyed its ID. Positional recovery for genuinely unmatched output
        remains available through ``_ordinal_fallback_index``, which is applied
        only after identity matching has failed and only where the caller's
        cardinality contract makes position meaningful.
        """
        target_normalized = normalize_node_id(target_id)

        for index, item in enumerate(data):
            for item_id in self._candidate_item_ids(item):
                if normalize_node_id(item_id) == target_normalized:
                    return index

        prefix = self._truncated_lookup_prefix(target_normalized)
        if prefix:
            matches = {
                index
                for index, item in enumerate(data)
                for item_id in self._candidate_item_ids(item)
                if normalize_node_id(item_id).startswith(prefix)
            }
            if len(matches) == 1:
                return next(iter(matches))
        
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

    @staticmethod
    def _candidate_item_ids(item: Any) -> List[str]:
        if not isinstance(item, dict):
            return []

        candidates: List[str] = []
        data = item.get("data")
        if isinstance(data, dict):
            for key in ("stable_id", "id", "entity_name"):
                value = data.get(key)
                if value not in (None, ""):
                    candidates.append(str(value))

        # Prefer graph node IDs, then row/group IDs materialized by projection,
        # aggregate, collapse, join, and select commands.
        for key in ("id", "row_id", "stable_id", "group_key", "group_name", "name"):
            value = item.get(key)
            if value not in (None, ""):
                candidates.append(str(value))

        return candidates

    @staticmethod
    def _truncated_lookup_prefix(target_normalized: str) -> str:
        prefix = re.sub(r"\s*(?:\.{3}|\u2026)\s*$", "", target_normalized).strip()
        if prefix == target_normalized or len(prefix) < 24:
            return ""
        return prefix
    
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
    
    def _calculate_optimal_batch_size(
        self,
        data: List[Dict],
        instruction: str,
        target_variable: str = None,
    ) -> int:
        """Calculate optimal batch size based on token estimation."""
        if len(data) <= 5:
            return len(data)

        # The LLM returns one strict JSON object per input row for PROCESS-style
        # batches. Keep every batch small enough to avoid losing a whole
        # checkpoint run to one oversized, unparsable response.
        max_batch_size = 15

        # Test with different batch sizes
        for batch_size in [5, 10, 15]:
            if batch_size > max_batch_size:
                return min(max_batch_size, len(data))
            test_batch = data[:batch_size]
            test_prompt = self._create_process_prompt(test_batch, instruction)
            
            # Rough token estimation
            estimated_tokens = len(test_prompt.split()) * 1.3
            
            if estimated_tokens > 3000:  # Token limit
                return max(1, batch_size - 5)
        
        return min(max_batch_size, len(data))
    
    def _create_process_prompt(
        self,
        data: List[Dict],
        instruction: str,
        target_variable: str = None,
    ) -> str:
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

        # The base template defers every response-shape decision to "the final
        # authoritative PROCESS contract appended after this template". This is
        # the caller that must append it; without it the template names no
        # response key at all and the model has to guess one.
        return final_prompt + self._process_response_contract(target_variable)

    @staticmethod
    def _process_response_contract(target_variable: str = None) -> str:
        target_clause = (
            f'The target variable for this instruction is "{target_variable}".\n'
            if target_variable
            else ""
        )
        return (
            "\n\nFINAL AUTHORITATIVE PROCESS CONTRACT "
            "(supersedes the template above wherever they differ):\n\n"
            f"{target_clause}"
            "Shape. Return one JSON object whose single top-level key is "
            '"processed_items" and whose value is an array of row objects. Do '
            "not name that array after the target variable, the table, the "
            "mode, or the task, and do not add any other top-level key. An "
            "array under any other name is not a valid response.\n\n"
            "Rows. Each element of the array is one output row.\n"
            '- Every row carries an "id". A row that restates or enriches a '
            "supplied input row must reuse that input row's ID exactly as "
            "shown above. A row this instruction newly materializes must "
            "instead use synthetic stable row IDs, unique within this "
            "response and derived from the row's own content. Never use a row "
            "position as an ID.\n"
            "- Populate the exact requested table columns named in the "
            "instruction. Use null for a column the supplied evidence does not "
            "support; do not drop the column and do not invent a value.\n"
            "- Carry provenance through from the input row unchanged whenever "
            "the input supplies it. Do not invent, rewrite, or reattribute it.\n"
            "- If a row names a table, it must be the target table for this "
            "instruction. Never emit rows belonging to a sibling table.\n\n"
            "Cardinality. Emit rows only for supplied input rows that the "
            "instruction makes eligible; return an empty array only when no "
            "supplied row supports one. Return valid JSON and nothing else.\n"
        )

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
                name = self._display_id_for_llm(item)
                label = self._display_label_for_llm(item, name)
                entity_type = (
                    (item.get('data') or {}).get('entity_type')
                    if isinstance(item.get('data'), dict)
                    else item.get('entity_type', 'Unknown')
                )
                normalized_id = normalize_node_id(name)
                formatted.append(f"Row {i+1} (ID: {name} -> normalized: {normalized_id}):")
                formatted.append(f"  label: {self._truncate_scalar(label)}")
                formatted.append(f"  entity_type: {self._truncate_scalar(entity_type)}")
                for key, value in self._scalar_preview(item):
                    formatted.append(f"  {key}: {self._truncate_scalar(value)}")
                formatted.append("")
        
        return "\n".join(formatted)

    def _scalar_preview(self, item: Dict[str, Any], *, limit: int = 16) -> List[tuple[str, Any]]:
        preview: List[tuple[str, Any]] = []

        def walk(obj: Any, prefix: str = "", depth: int = 0):
            if depth > 2:
                return
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if depth > 0 and self._is_nested_identity_key(str(key)):
                        continue
                    name = f"{prefix}.{key}" if prefix else str(key)
                    if isinstance(value, (str, int, float, bool)):
                        preview.append((name, value))
                    elif isinstance(value, dict):
                        walk(value, name, depth + 1)
                    elif isinstance(value, list):
                        for index, entry in enumerate(value[:2]):
                            list_name = f"{name}[{index}]"
                            if isinstance(entry, dict):
                                walk(entry, list_name, depth + 1)
                            elif isinstance(entry, (str, int, float, bool)):
                                preview.append((list_name, entry))
            elif isinstance(obj, (str, int, float, bool)) and prefix:
                preview.append((prefix, obj))
        walk(item)
        return preview[:limit]

    @staticmethod
    def _is_nested_identity_key(key: str) -> bool:
        return key in {"id", "row_id", "stable_id", "group_key", "group_name"}

    @staticmethod
    def _display_id_for_llm(item: Dict[str, Any]) -> str:
        for key in ("row_id", "stable_id", "group_key", "group_name", "name", "id"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)

        data = item.get("data")
        if isinstance(data, dict):
            for key in ("stable_id", "id", "entity_name"):
                value = data.get(key)
                if value not in (None, ""):
                    return str(value)

        return "Unknown"

    @staticmethod
    def _display_label_for_llm(item: Dict[str, Any], fallback: str) -> str:
        data = item.get("data")
        if isinstance(data, dict):
            value = data.get("entity_name")
            if value not in (None, ""):
                return str(value)

        for key in ("group_name", "name", "entity_name", "group_key", "row_id", "id"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)

        return fallback

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
