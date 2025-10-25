"""
Centralized state management utilities for GASL commands.
This module provides consistent data access patterns across all GASL command handlers.
"""

from typing import Any, List, Dict, Optional, Union
from .state import StateStore, ContextStore
from .types import Provenance


class StateManager:
    """
    Centralized state management for GASL commands.
    Provides consistent data access patterns and debugging capabilities.
    """
    
    def __init__(self, state_store: StateStore, context_store: ContextStore):
        self.state_store = state_store
        self.context_store = context_store
        self.debug = True  # Enable debug logging
    
    def get_variable_data(self, variable_name: str, fallback_to_last_nodes: bool = True) -> List[Dict]:
        """
        Get data from a variable, trying multiple sources in order.
        
        Args:
            variable_name: Name of the variable to retrieve
            fallback_to_last_nodes: Whether to fall back to 'last_nodes_result' if variable not found
            
        Returns:
            List of data items, or empty list if not found
        """
        if self.debug:
            print(f"🔍 STATE_MANAGER: Getting data for variable '{variable_name}'")
        
        # Try context store first
        if self.context_store.has(variable_name):
            data = self.context_store.get(variable_name)
            if self.debug:
                print(f"🔍 STATE_MANAGER: Found in context store, length={len(data) if isinstance(data, list) else 'not a list'}")
            return self._normalize_data(data)
        
        # Try state store
        if self.state_store.has_variable(variable_name):
            var_data = self.state_store.get_variable(variable_name)
            if self.debug:
                print(f"🔍 STATE_MANAGER: Found in state store")
            return self._extract_items_from_state_variable(var_data)
        
        # Fallback to last_nodes_result if enabled
        if fallback_to_last_nodes and self.context_store.has("last_nodes_result"):
            data = self.context_store.get("last_nodes_result")
            if self.debug:
                print(f"🔍 STATE_MANAGER: Using last_nodes_result fallback, length={len(data) if isinstance(data, list) else 'not a list'}")
            return self._normalize_data(data)
        
        if self.debug:
            print(f"🔍 STATE_MANAGER: Variable '{variable_name}' not found in any store")
        return []
    
    def store_variable_data(self, variable_name: str, data: List[Dict], 
                          store_in_state: bool = True, store_in_context: bool = True,
                          description: str = None) -> None:
        """
        Store data in both state and context stores.
        
        Args:
            variable_name: Name of the variable to store
            data: Data to store
            store_in_state: Whether to store in persistent state store
            store_in_context: Whether to store in ephemeral context store
            description: Description for state store variable
        """
        if self.debug:
            print(f"🔍 STATE_MANAGER: Storing data for variable '{variable_name}', length={len(data)}")
        
        # Store in context store
        if store_in_context:
            self.context_store.set(variable_name, data)
            if self.debug:
                print(f"🔍 STATE_MANAGER: Stored in context store")
        
        # Store in state store
        if store_in_state:
            if self.state_store.has_variable(variable_name):
                # Update existing variable
                self.state_store.update_variable(variable_name, data)
                if self.debug:
                    print(f"🔍 STATE_MANAGER: Updated existing state store variable")
            else:
                # Create new variable
                var_type = "LIST" if isinstance(data, list) else "DICT"
                var_description = description or f"Data for {variable_name}"
                self.state_store.set_variable_with_fields(
                    variable_name, 
                    data, 
                    var_type, 
                    var_description
                )
                if self.debug:
                    print(f"🔍 STATE_MANAGER: Created new state store variable")
    
    def has_variable(self, variable_name: str) -> bool:
        """Check if variable exists in either store."""
        return (self.context_store.has(variable_name) or 
                self.state_store.has_variable(variable_name))
    
    def get_variable_info(self, variable_name: str) -> Dict[str, Any]:
        """Get information about a variable's location and content."""
        info = {
            "name": variable_name,
            "in_context": self.context_store.has(variable_name),
            "in_state": self.state_store.has_variable(variable_name),
            "context_data_length": 0,
            "state_data_length": 0
        }
        
        if info["in_context"]:
            context_data = self.context_store.get(variable_name)
            info["context_data_length"] = len(context_data) if isinstance(context_data, list) else 1
        
        if info["in_state"]:
            state_data = self.state_store.get_variable(variable_name)
            if isinstance(state_data, dict) and "items" in state_data:
                info["state_data_length"] = len(state_data["items"])
            else:
                info["state_data_length"] = 1 if state_data else 0
        
        return info
    
    def debug_variable_access(self, variable_name: str) -> None:
        """Debug information about variable access."""
        if not self.debug:
            return
            
        print(f"🔍 STATE_MANAGER DEBUG: Variable '{variable_name}'")
        info = self.get_variable_info(variable_name)
        print(f"  - In context: {info['in_context']} (length: {info['context_data_length']})")
        print(f"  - In state: {info['in_state']} (length: {info['state_data_length']})")
        
        # Show context store contents
        context_keys = list(self.context_store.keys())
        print(f"  - Context store keys: {context_keys}")
        
        # Show state store contents
        state_vars = list(self.state_store.get_state().get('variables', {}).keys())
        print(f"  - State store variables: {state_vars}")
    
    def _normalize_data(self, data: Any) -> List[Dict]:
        """Normalize data to a list of dictionaries."""
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []
    
    def _extract_items_from_state_variable(self, var_data: Any) -> List[Dict]:
        """Extract items from state store variable structure."""
        if var_data is None:
            return []
        
        # Handle state store variable structure (with _meta and items)
        if isinstance(var_data, dict) and "items" in var_data:
            return var_data["items"]
        elif isinstance(var_data, list):
            return var_data
        elif isinstance(var_data, dict):
            return [var_data]
        else:
            return []


def create_state_manager(state_store: StateStore, context_store: ContextStore) -> StateManager:
    """Factory function to create a StateManager instance."""
    return StateManager(state_store, context_store)
