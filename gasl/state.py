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
    
    def set(self, key: str, value: Any, provenance: List[Provenance] = None) -> None:
        """Set a context variable."""
        self._data[key] = value
        if provenance:
            self._provenance[key] = provenance
    
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
    
    def clear(self) -> None:
        """Clear all context variables."""
        self._data.clear()
        self._provenance.clear()
    
    def get_provenance(self, key: str) -> List[Provenance]:
        """Get provenance for a context variable."""
        return self._provenance.get(key, [])
    
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
            "validation_hint": None,
            "strategy_insights": None
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
                    "_meta": {"type": "DICT", "description": description}
                }
            elif var_type == "LIST":
                self._state["variables"][key] = {
                    "_meta": {"type": "LIST", "description": description},
                    "items": []
                }
            elif var_type == "COUNTER":
                self._state["variables"][key] = {
                    "_meta": {"type": "COUNTER", "description": description},
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
    
    def get_variable(self, key: str) -> Any:
        """Get a state variable."""
        if key not in self._state["variables"]:
            raise StateError(f"Variable {key} not found")
        return self._state["variables"][key]
    
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
            ]
        })
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
    
    def set_validation_hint(self, hint: str) -> None:
        """Set validation hint for next iteration."""
        self._state["validation_hint"] = hint
        self._save_state()
    
    def get_validation_hint(self) -> str:
        """Get validation hint from previous iteration."""
        return self._state.get("validation_hint")
    
    def set_strategy_insights(self, insights: str) -> None:
        """Set strategy insights from previous iteration."""
        self._state["strategy_insights"] = insights
        self._save_state()
    
    def get_strategy_insights(self) -> str:
        """Get strategy insights from previous iteration."""
        return self._state.get("strategy_insights")
    
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
