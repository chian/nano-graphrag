"""
State management for GASL system.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from .types import HistoryEntry, StateSnapshot, Provenance
from .errors import StateError


class ContextStore:
    """Ephemeral storage for intermediate results during execution."""
    
    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._provenance: Dict[str, List[Provenance]] = {}
        self._contracts: Dict[str, Dict[str, Any]] = {}
    
    def set(self, key: str, value: Any, provenance: List[Provenance] = None, contract: Dict[str, Any] = None) -> None:
        """Set a context variable."""
        self._data[key] = value
        if provenance:
            self._provenance[key] = provenance
        if contract is not None:
            self._contracts[key] = contract
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a context variable."""
        return self._data.get(key, default)
    
    def has(self, key: str) -> bool:
        """Check if context variable exists."""
        return key in self._data
    
    def delete(self, key: str) -> None:
        """Delete a context variable."""
        self._data.pop(key, None)
        self._provenance.pop(key, None)
        self._contracts.pop(key, None)
    
    def clear(self) -> None:
        """Clear all context variables."""
        self._data.clear()
        self._provenance.clear()
        self._contracts.clear()
    
    def get_provenance(self, key: str) -> List[Provenance]:
        """Get provenance for a context variable."""
        return self._provenance.get(key, [])

    def get_contract(self, key: str) -> Dict[str, Any]:
        """Get contract for a context variable."""
        return self._contracts.get(key, {})
    
    def keys(self) -> List[str]:
        """Get all context variable keys."""
        return list(self._data.keys())


class StateStore:
    """Persistent storage for accumulated results and metadata."""
    
    def __init__(self, state_file: str = None):
        self.state_file = Path(state_file) if state_file else None
        self._state: Dict[str, Any] = {}
        self._load_state()
    
    def _load_state(self) -> None:
        """Load state from file."""
        if self.state_file and self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    self._state = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                raise StateError(f"Failed to load state file: {e}")
        else:
            self._initialize_empty_state()
    
    def _initialize_empty_state(self) -> None:
        """Initialize empty state structure."""
        self._state = {
            "version": "0.1",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "query": "",
            "config": {},
            "variables": {},
            "history": [],
            "replay": [],
            "strategy_insights": None,
            "planner_constraints": [],
            "last_failure_summary": None,
            "plan_symbol_table": None,
            "produced_artifacts": [],
            "final_answer": None,
            "query_answered": None,
            "final_answer_at": None,
            "final_answer_mode": None,
        }
        self._save_state()
    
    def _save_state(self) -> None:
        """Save state to file."""
        self._state["updated_at"] = datetime.now().isoformat()
        if self.state_file:
            try:
                # Ensure directory exists
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.state_file, 'w') as f:
                    json.dump(self._state, f, indent=2, default=str)
            except IOError as e:
                raise StateError(f"Failed to save state file: {e}")
    
    def set_query(self, query: str) -> None:
        """Set the original query."""
        self._state["query"] = query
        self._state["final_answer"] = None
        self._state["query_answered"] = None
        self._state["final_answer_at"] = None
        self._state["final_answer_mode"] = None
        self._state["strategy_insights"] = None
        # A new query invalidates constraints authored for the previous one.
        # This is the ONLY clear, and it is tied to the event that genuinely
        # makes them irrelevant.
        self._state["planner_constraints"] = []
        self._save_state()
    
    def set_config(self, config: Dict[str, Any]) -> None:
        """Set configuration."""
        self._state["config"] = config
        self._save_state()
    
    def declare_variable(self, key: str, var_type: str, description: str = None) -> None:
        """Declare a new state variable with type and description."""
        if key not in self._state["variables"]:
            if var_type == "DICT":
                self._state["variables"][key] = {
                    "_meta": {"type": "DICT", "description": description, "contract": {}}
                }
            elif var_type == "LIST":
                self._state["variables"][key] = {
                    "_meta": {"type": "LIST", "description": description, "contract": {}},
                    "items": []
                }
            elif var_type == "COUNTER":
                self._state["variables"][key] = {
                    "_meta": {"type": "COUNTER", "description": description, "contract": {}},
                    "value": 0
                }
            else:
                raise StateError(f"Unknown variable type: {var_type}")
            self._save_state()

    def ensure_variable_type(self, key: str, var_type: str) -> None:
        """Ensure an existing variable has the requested shape, coercing only if empty."""
        if key not in self._state["variables"]:
            raise StateError(f"Variable {key} not declared")
        var_data = self._state["variables"][key]
        current_type = var_data.get("_meta", {}).get("type")
        if current_type == var_type:
            return
        if not self._variable_is_effectively_empty(var_data):
            raise StateError(f"Cannot coerce non-empty {current_type} variable {key} to {var_type}")
        description = var_data.get("_meta", {}).get("description")
        contract = var_data.get("_meta", {}).get("contract", {})
        if var_type == "DICT":
            self._state["variables"][key] = {
                "_meta": {"type": "DICT", "description": description, "contract": contract}
            }
        elif var_type == "LIST":
            self._state["variables"][key] = {
                "_meta": {"type": "LIST", "description": description, "contract": contract},
                "items": []
            }
        elif var_type == "COUNTER":
            self._state["variables"][key] = {
                "_meta": {"type": "COUNTER", "description": description, "contract": contract},
                "value": 0
            }
        else:
            raise StateError(f"Unknown variable type: {var_type}")
        self._save_state()
    
    def update_variable(self, key: str, value: Any, provenance: List[Provenance] = None) -> None:
        """Update a state variable with value and provenance."""
        if key not in self._state["variables"]:
            raise StateError(f"Variable {key} not declared")
        
        var_data = self._state["variables"][key]
        var_type = var_data["_meta"]["type"]
        
        if var_type == "DICT":
            if isinstance(value, dict):
                var_data.update(value)
            elif isinstance(value, list):
                self.ensure_variable_type(key, "LIST")
                var_data = self._state["variables"][key]
                var_data["items"].extend(value)
            else:
                raise StateError(f"Cannot update DICT variable with {type(value)}")
        elif var_type == "LIST":
            if isinstance(value, list):
                var_data["items"].extend(value)
            else:
                var_data["items"].append(value)
        elif var_type == "COUNTER":
            if isinstance(value, (int, float)):
                var_data["value"] += value
            else:
                raise StateError(f"Cannot update COUNTER variable with {type(value)}")
        
        # Store provenance if provided
        if provenance:
            if "provenance" not in var_data:
                var_data["provenance"] = []
            var_data["provenance"].extend(provenance)
        
        self._save_state()

    @staticmethod
    def _variable_is_effectively_empty(var_data: Dict[str, Any]) -> bool:
        meta = var_data.get("_meta", {})
        var_type = meta.get("type")
        if var_type == "DICT":
            return not any(key != "_meta" for key in var_data.keys())
        if var_type == "LIST":
            return len(var_data.get("items", [])) == 0
        if var_type == "COUNTER":
            return not var_data.get("value", 0)
        return False
    
    def get_variable(self, key: str) -> Any:
        """Get a state variable."""
        if key not in self._state["variables"]:
            raise StateError(f"Variable {key} not found")
        return self._state["variables"][key]

    def set_variable_contract(self, key: str, contract: Dict[str, Any]) -> None:
        """Set contract metadata for a variable."""
        if key not in self._state["variables"]:
            raise StateError(f"Variable {key} not declared")
        meta = self._state["variables"][key].setdefault("_meta", {})
        meta["contract"] = contract or {}
        self._save_state()

    def get_variable_contract(self, key: str) -> Dict[str, Any]:
        """Get contract metadata for a variable."""
        if key not in self._state["variables"]:
            raise StateError(f"Variable {key} not found")
        meta = self._state["variables"][key].get("_meta", {})
        return meta.get("contract", {})
    
    def has_variable(self, key: str) -> bool:
        """Check if state variable exists."""
        return key in self._state["variables"]
    
    def add_history_entry(self, entry: HistoryEntry) -> None:
        """Add entry to execution history."""
        self._state["history"].append({
            "step_id": entry.step_id,
            "command": entry.command,
            "status": entry.status,
            "result_count": entry.result_count,
            "duration_ms": entry.duration_ms,
            "timestamp": entry.timestamp.isoformat(),
            "error_message": entry.error_message,
            "provenance": [
                {
                    "source_id": p.source_id,
                    "doc_id": p.doc_id,
                    "offset_start": p.offset_start,
                    "offset_end": p.offset_end,
                    "snippet": p.snippet,
                    "extraction": p.extraction
                } for p in entry.provenance
            ],
            "produced_artifact": entry.produced_artifact,
        })
        self._save_state()

    def append_produced_artifact(self, artifact: Dict[str, Any], max_keep: int = 50) -> None:
        """Append a compact artifact record produced by a command."""
        self._state.setdefault("produced_artifacts", []).append(artifact)
        if len(self._state["produced_artifacts"]) > max_keep:
            self._state["produced_artifacts"] = self._state["produced_artifacts"][-max_keep:]
        self._save_state()
    
    def create_snapshot(self, snapshot_id: str, next_actions: List[Dict[str, Any]] = None) -> StateSnapshot:
        """Create a state snapshot for MCTS future-proofing."""
        snapshot = StateSnapshot(
            snapshot_id=snapshot_id,
            timestamp=datetime.now(),
            variables=self._state["variables"].copy(),
            history=[HistoryEntry(**entry) for entry in self._state["history"]],
            next_actions=next_actions or []
        )
        
        # Store snapshot in replay section
        if "replay" not in self._state:
            self._state["replay"] = []
        
        self._state["replay"].append({
            "snapshot_id": snapshot.snapshot_id,
            "timestamp": snapshot.timestamp.isoformat(),
            "variables": snapshot.variables,
            "next_actions": snapshot.next_actions
        })
        
        self._save_state()
        return snapshot
    
    def get_state(self) -> Dict[str, Any]:
        """Get complete state."""
        return self._state.copy()
    
    def clear_state(self) -> None:
        """Clear all state data."""
        self._initialize_empty_state()
    
    def set_strategy_insights(self, insights: str) -> None:
        """Set strategy insights from previous iteration."""
        self._state["strategy_insights"] = insights
        self._save_state()
    
    def get_strategy_insights(self) -> str:
        """Get strategy insights from previous iteration."""
        return self._state.get("strategy_insights")

    #: Status of a persisted planner constraint.
    #:
    #: There is no third state and there is deliberately no expiry rule. A
    #: constraint does not become wrong at some age -- "use only declared
    #: symbols" is as true on iteration 40 as on iteration 1 -- so any number of
    #: iterations chosen as a cutoff would be an invented rule pretending to
    #: compute a relevance the engine cannot compute. What the engine CAN
    #: establish is provenance: which iteration authored this, and for which
    #: query. So it discloses the age and lets the reader judge.
    CONSTRAINT_ACTIVE = "active"
    CONSTRAINT_UNREFRESHED = "unrefreshed"

    def set_planner_constraints(
        self,
        constraints: List[str],
        *,
        authored_iteration: Optional[int] = None,
        authored_for: str = "",
    ) -> None:
        """Persist planner constraints as typed authoring records.

        REPLACES; it does not append. A bare list of strings could not answer
        "when was this written, and for what", so a state file resumed without a
        fresh `set_query` presented constraints authored for a different query,
        in a different run, as if the current planner had just been given them.

        `authored_iteration` and `authored_for` are supplied by the ENGINE and
        never by the model. Both are in hand at every call site, and a model
        asked to date its own output would be asserting a fact the engine
        already knows -- an assertion where a measurement exists.
        """
        records = []
        for constraint in constraints or []:
            if isinstance(constraint, dict):
                # Already a record (a resumed state file, or a re-write of what
                # was read back). Keep its original authorship rather than
                # restamping it with the current iteration, which would launder
                # an old constraint into a fresh one.
                text = str(constraint.get("text", "")).strip()
                if not text:
                    continue
                records.append(
                    {
                        "text": text,
                        "authored_iteration": constraint.get("authored_iteration"),
                        "authored_for": constraint.get("authored_for", ""),
                        "status": constraint.get("status", self.CONSTRAINT_ACTIVE),
                    }
                )
                continue
            text = str(constraint).strip()
            if not text:
                continue
            records.append(
                {
                    "text": text,
                    "authored_iteration": authored_iteration,
                    "authored_for": authored_for,
                    "status": self.CONSTRAINT_ACTIVE,
                }
            )
        self._state["planner_constraints"] = records
        self._save_state()

    def get_planner_constraints(
        self,
        *,
        current_iteration: Optional[int] = None,
        current_for: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Planner constraints as records, with status resolved against context.

        Status is recomputed on read rather than stored-and-trusted: a stored
        status goes stale the moment the run moves on, and a stale "active" is
        exactly the claim this mechanism exists to stop. A caller that supplies
        no context gets the records with their stored status and the authorship
        fields intact, so it can still show the age.
        """
        stored = self._state.get("planner_constraints") or []
        records: List[Dict[str, Any]] = []
        for entry in stored:
            if not isinstance(entry, dict):
                # A pre-record state file. Its authorship is genuinely unknown,
                # and unknown authorship is reported as unknown -- not defaulted
                # to the current iteration, which would date it to now.
                records.append(
                    {
                        "text": str(entry),
                        "authored_iteration": None,
                        "authored_for": "",
                        "status": self.CONSTRAINT_UNREFRESHED,
                    }
                )
                continue
            record = dict(entry)
            record.setdefault("status", self.CONSTRAINT_ACTIVE)
            stale = record.get("authored_iteration") is None
            if current_iteration is not None:
                stale = stale or record.get("authored_iteration") != current_iteration
            if current_for is not None:
                stale = stale or record.get("authored_for", "") != current_for
            if stale:
                record["status"] = self.CONSTRAINT_UNREFRESHED
            records.append(record)
        return records

    @staticmethod
    def planner_constraint_texts(records: List[Any]) -> List[str]:
        """Just the text, for callers that only need the instructions."""
        texts = []
        for record in records or []:
            texts.append(str(record.get("text", "")) if isinstance(record, dict) else str(record))
        return [text for text in texts if text]

    def set_last_failure_summary(self, summary: Dict[str, Any]) -> None:
        """Persist the most recent structured iteration failure summary."""
        self._state["last_failure_summary"] = summary
        self._save_state()

    def get_last_failure_summary(self) -> Dict[str, Any]:
        """Get the most recent structured iteration failure summary."""
        return self._state.get("last_failure_summary") or {}

    def set_plan_symbol_table(self, symbol_table: List[Dict[str, Any]]) -> None:
        """Persist the current query's plan-local symbol table."""
        self._state["plan_symbol_table"] = symbol_table
        self._save_state()

    def get_plan_symbol_table(self) -> Optional[List[Dict[str, Any]]]:
        """Get the current query's plan-local symbol table, if any."""
        return self._state.get("plan_symbol_table")

    def set_final_answer(
        self,
        answer: str,
        *,
        query_answered: bool,
        mode: Optional[str] = None,
    ) -> None:
        """Persist the final answer immediately for crash-safe recovery."""
        self._state["final_answer"] = answer
        self._state["query_answered"] = bool(query_answered)
        self._state["final_answer_at"] = datetime.now().isoformat()
        self._state["final_answer_mode"] = mode or None
        self._save_state()
    
    def add_field_metadata(self, variable_name: str, field_name: str, description: str, source: str = None) -> str:
        """Add field metadata with conflict resolution."""
        if variable_name not in self._state["variables"]:
            raise StateError(f"Variable {variable_name} does not exist")
        
        # Get existing fields for this variable
        var_data = self._state["variables"][variable_name]
        if "fields" not in var_data:
            var_data["fields"] = {}
        
        # Resolve field name conflicts
        actual_field_name = self._resolve_field_name_conflict(var_data["fields"], field_name)
        
        # Add field metadata
        var_data["fields"][actual_field_name] = {
            "description": description,
            "source": source or "ADD_FIELD command",
            "created_at": datetime.now().isoformat()
        }
        
        self._save_state()
        return actual_field_name
    
    def _resolve_field_name_conflict(self, existing_fields: Dict[str, Any], field_name: str) -> str:
        """Resolve field name conflicts by auto-generating names."""
        if field_name not in existing_fields:
            return field_name
        
        counter = 1
        while f"{field_name}_{counter}" in existing_fields:
            counter += 1
        
        return f"{field_name}_{counter}"
    
    def get_field_metadata(self, variable_name: str) -> Dict[str, Any]:
        """Get field metadata for a variable."""
        if variable_name not in self._state["variables"]:
            return {}
        
        var_data = self._state["variables"][variable_name]
        return var_data.get("fields", {})
    
    def set_variable_with_fields(self, name: str, value: Any, var_type: str, description: str = None, fields: Dict[str, Any] = None) -> None:
        """Set a variable with field metadata."""
        self._state["variables"][name] = {
            "value": value,
            "type": var_type,
            "description": description,
            "fields": fields or {},
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        self._save_state()
