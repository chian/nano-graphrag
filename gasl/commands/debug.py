"""
Debug commands for GASL.
"""

from typing import Any, Dict, List
from .base import CommandHandler


class DebugHandler(CommandHandler):
    """Handles debug commands."""
    
    def can_handle(self, command_type: str) -> bool:
        """Check if this handler can handle the command type."""
        return command_type in ["SHOW", "INSPECT"]
    
    def execute(self, command) -> Dict[str, Any]:
        """Execute debug command."""
        if command.command_type == "SHOW":
            return self._execute_show(command)
        elif command.command_type == "INSPECT":
            return self._execute_inspect(command)
        else:
            return self._create_result(
                command=command,
                status="error",
                error_message=f"Unknown debug command: {command.command_type}"
            )
    
    def _execute_show(self, command) -> Dict[str, Any]:
        """Execute SHOW command to display variable contents."""
        args = command.args
        variable = args.get("variable")
        limit = args.get("limit", 10)
        
        if not variable:
            return self._create_result(
                command=command,
                status="error",
                error_message="SHOW requires a variable name"
            )
        
        # Get data from state or context
        data = None
        source = "unknown"
        
        if self.state_store.has_variable(variable):
            data = self.state_store.get_variable(variable)
            source = "state"
        elif self.context_store.has(variable):
            data = self.context_store.get(variable)
            source = "context"
        else:
            return self._create_result(
                command=command,
                status="error",
                error_message=f"Variable {variable} not found in state or context"
            )
        
        # Format output
        if isinstance(data, list):
            if len(data) > limit:
                display_data = data[:limit]
                truncated = True
            else:
                display_data = data
                truncated = False
            
            print(f"DEBUG: SHOW {variable} ({source}) - {len(data)} items")
            for i, item in enumerate(display_data):
                print(f"  [{i}] {item}")
            
            if truncated:
                print(f"  ... and {len(data) - limit} more items")
                
        elif isinstance(data, dict):
            print(f"DEBUG: SHOW {variable} ({source}) - dict with keys: {list(data.keys())}")
            for key, value in data.items():
                if key == "_meta":
                    print(f"  {key}: {value}")
                elif isinstance(value, list) and len(value) > 5:
                    print(f"  {key}: [{len(value)} items] {value[:3]}...")
                else:
                    print(f"  {key}: {value}")
        else:
            print(f"DEBUG: SHOW {variable} ({source}) - {type(data).__name__}: {data}")
        
        return self._create_result(
            command=command,
            status="success",
            result_count=len(data) if isinstance(data, list) else 1
        )
    
    def _execute_inspect(self, command) -> Dict[str, Any]:
        """Execute INSPECT command to analyze data structure."""
        args = command.args
        variable = args.get("variable")
        
        if not variable:
            return self._create_result(
                command=command,
                status="error",
                error_message="INSPECT requires a variable name"
            )
        
        # Get data from state or context
        data = None
        source = "unknown"
        
        if self.state_store.has_variable(variable):
            data = self.state_store.get_variable(variable)
            source = "state"
        elif self.context_store.has(variable):
            data = self.context_store.get(variable)
            source = "context"
        else:
            return self._create_result(
                command=command,
                status="error",
                error_message=f"Variable {variable} not found in state or context"
            )
        
        # Analyze structure
        analysis = self._analyze_data_structure(data)
        
        print(f"DEBUG: INSPECT {variable} ({source})")
        print(f"  Type: {analysis['type']}")
        print(f"  Size: {analysis['size']}")
        if analysis['fields']:
            print(f"  Fields: {analysis['fields']}")
        if analysis['sample_values']:
            print(f"  Sample values: {analysis['sample_values']}")
        if analysis['warnings']:
            print(f"  Warnings: {analysis['warnings']}")
        
        return self._create_result(
            command=command,
            status="success",
            result_count=analysis['size']
        )
    
    def _analyze_data_structure(self, data: Any) -> Dict[str, Any]:
        """Analyze the structure of data."""
        analysis = {
            "type": type(data).__name__,
            "size": 0,
            "fields": [],
            "sample_values": {},
            "warnings": []
        }
        
        if isinstance(data, list):
            analysis["size"] = len(data)
            if data:
                # Analyze first few items
                sample_items = data[:3]
                all_fields = set()
                for item in sample_items:
                    if isinstance(item, dict):
                        all_fields.update(item.keys())
                
                analysis["fields"] = list(all_fields)
                
                # Get sample values for each field
                for field in analysis["fields"]:
                    values = []
                    for item in sample_items:
                        if isinstance(item, dict) and field in item:
                            values.append(str(item[field])[:50])  # Truncate long values
                    analysis["sample_values"][field] = values
                
                # Check for potential issues
                if len(data) == 0:
                    analysis["warnings"].append("Empty list")
                elif all(isinstance(item, dict) and not item for item in data):
                    analysis["warnings"].append("All items are empty dictionaries")
                elif all(isinstance(item, dict) and item.get("id") == "Unknown" for item in data):
                    analysis["warnings"].append("All items have 'Unknown' ID")
        
        elif isinstance(data, dict):
            analysis["size"] = len(data)
            analysis["fields"] = list(data.keys())
            
            # Check for meta information
            if "_meta" in data:
                analysis["sample_values"]["_meta"] = data["_meta"]
            
            # Check for items
            if "items" in data and isinstance(data["items"], list):
                analysis["sample_values"]["items_count"] = len(data["items"])
                if data["items"]:
                    analysis["sample_values"]["first_item"] = data["items"][0]
        
        return analysis
