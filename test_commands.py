#!/usr/bin/env python3
"""
Permanent test script for testing any GASL command input.
Usage: python test_commands.py "FIND nodes with entity_type=PERSON"
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(__file__))

from gasl.adapters.networkx import NetworkXAdapter
from gasl_main import load_graph_from_nano_graphrag
from gasl.parser import GASLParser
from gasl.state import StateStore, ContextStore
from gasl.commands import FindHandler, CountHandler, DataTransformHandler, SelectHandler, ProcessHandler

def test_command(command_text, working_dir, persistent_state=True):
    """Test any GASL command."""
    print(f"=== Testing Command: {command_text} ===")
    
    # Load graph
    print("Loading graph...")
    versioned_graph, graph_type = load_graph_from_nano_graphrag(working_dir)
    print(f"Graph loaded: {graph_type}")
    
    # Get current graph for stats
    current_graph = versioned_graph.get_current_graph()
    print(f"Total nodes: {current_graph.number_of_nodes()}")
    print(f"Total edges: {current_graph.number_of_edges()}")
    
    # Create adapter and handlers
    adapter = NetworkXAdapter(current_graph)
    adapter.versioned_graph = versioned_graph
    # Use working directory for state file
    state_file = os.path.join(working_dir, "gasl_state.json") if persistent_state else None
    state_store = StateStore(state_file)
    context_store = ContextStore()
    parser = GASLParser()
    
    # Parse the command
    print(f"\nParsing command: {command_text}")
    try:
        command = parser.parse_command(command_text)
        print(f"Parsed command: {command.command_type}")
        print(f"Command args: {command.args}")
    except Exception as e:
        print(f"Parse error: {e}")
        return
    
    # Execute the command
    print(f"\nExecuting command...")
    try:
        if command.command_type == "FIND":
            handler = FindHandler(state_store, context_store, adapter, None)
        elif command.command_type == "COUNT":
            handler = CountHandler(state_store, context_store, None)
        elif command.command_type == "AGGREGATE":
            handler = DataTransformHandler(state_store, context_store, adapter, None)
        elif command.command_type == "SELECT":
            handler = SelectHandler(state_store, context_store)
        elif command.command_type == "PROCESS":
            handler = ProcessHandler(state_store, context_store, None)
        else:
            print(f"Command type {command.command_type} not supported in this test script")
            return
            
        result = handler.execute(command)
        print(f"Result status: {result.status}")
        print(f"Result count: {result.count}")
        print(f"Result data type: {type(result.data)}")
        if result.data:
            print(f"Result data length: {len(result.data) if isinstance(result.data, list) else 'N/A'}")
            if isinstance(result.data, list) and len(result.data) > 0:
                print(f"First result: {result.data[0]}")
        if result.error_message:
            print(f"Error: {result.error_message}")
    except Exception as e:
        print(f"Execution error: {e}")
        import traceback
        traceback.print_exc()

def main():
    parser = argparse.ArgumentParser(description="Test GASL commands")
    parser.add_argument("command", help="GASL command to test")
    parser.add_argument("--working-dir", required=True, 
                       help="Working directory with graph data")
    
    args = parser.parse_args()
    test_command(args.command, args.working_dir)

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Interactive mode
        print("GASL Command Tester")
        print("Usage: python test_commands.py <command> --working-dir <path>")
        print("Example: python test_commands.py 'FIND nodes with entity_type=PERSON' --working-dir /path/to/papers")
        sys.exit(1)
    else:
        main()
