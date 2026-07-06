#!/usr/bin/env python3
"""
Debug script for testing GASL queries directly.
This script allows you to test individual GASL commands or run full hypothesis-driven traversal.
"""

import sys
import os
import argparse
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from gasl.adapters.networkx import NetworkXAdapter
from gasl_main import load_graph_from_nano_graphrag
from gasl.parser import GASLParser
from gasl.state import StateStore, ContextStore
from gasl.executor import GASLExecutor
from gasl.llm import ArgoBridgeLLM
from gasl.commands import (
    FindHandler, CountHandler, DataTransformHandler, SelectHandler, 
    ProcessHandler, DeclareHandler, UpdateHandler
)

def print_separator(title: str):
    print(f"\n{'=' * 80}")
    print(f" {title}")
    print(f"{'=' * 80}")

def print_subsection(title: str):
    print(f"\n--- {title} ---")

def test_single_command(command_text: str, working_dir: str, persistent_state: bool = True):
    """Test a single GASL command."""
    print_separator(f"Testing Single GASL Command: {command_text}")
    
    # Load graph
    print("Loading graph...")
    versioned_graph, graph_type = load_graph_from_nano_graphrag(working_dir)
    print(f"Graph loaded: {graph_type}")
    
    # Get current graph for stats
    current_graph = versioned_graph.get_current_graph()
    print(f"Total nodes: {current_graph.number_of_nodes()}")
    print(f"Total edges: {current_graph.number_of_edges()}")
    
    # Create adapter and stores
    adapter = NetworkXAdapter(current_graph)
    adapter.versioned_graph = versioned_graph
    state_file = os.path.join(working_dir, "gasl_state.json") if persistent_state else None
    state_store = StateStore(state_file)
    context_store = ContextStore()
    parser = GASLParser()
    
    # Parse the command
    print_subsection("Parsing Command")
    try:
        command = parser.parse_command(command_text)
        print(f"✅ Parsed command: {command.command_type}")
        print(f"Command args: {command.args}")
    except Exception as e:
        print(f"❌ Parse error: {e}")
        return
    
    # Execute the command
    print_subsection("Executing Command")
    try:
        # Create appropriate handler
        if command.command_type == "FIND":
            handler = FindHandler(state_store, context_store, adapter, None)
        elif command.command_type == "COUNT":
            handler = CountHandler(state_store, context_store, None)
        elif command.command_type == "AGGREGATE":
            handler = DataTransformHandler(state_store, context_store, adapter, None)
        elif command.command_type == "SELECT":
            handler = SelectHandler(state_store, context_store)
        elif command.command_type == "PROCESS":
            from gasl.llm import ArgoBridgeLLM
            llm = ArgoBridgeLLM()
            handler = ProcessHandler(state_store, context_store, llm)
        elif command.command_type == "DECLARE":
            handler = DeclareHandler(state_store, context_store)
        elif command.command_type == "UPDATE":
            handler = UpdateHandler(state_store, context_store)
        elif command.command_type == "SHOW":
            print(f"❌ SHOW command not supported in this test script")
            return
        else:
            print(f"❌ Command type {command.command_type} not supported in this test script")
            return
            
        result = handler.execute(command)
        print(f"✅ Result status: {result.status}")
        print(f"Result count: {result.count}")
        print(f"Result data type: {type(result.data)}")
        
        if result.data:
            if isinstance(result.data, list):
                print(f"Result data length: {len(result.data)}")
                if len(result.data) > 0:
                    print(f"First result: {result.data[0]}")
                    if len(result.data) > 1:
                        print(f"Second result: {result.data[1]}")
            else:
                print(f"Result data: {result.data}")
        
        if result.error_message:
            print(f"❌ Error: {result.error_message}")
            
        # Show state and context after command
        print_subsection("State After Command")
        state_vars = state_store.get_state().get('variables', {})
        print(f"State variables: {list(state_vars.keys())}")
        for var_name, var_data in state_vars.items():
            if isinstance(var_data, dict) and 'items' in var_data:
                print(f"  {var_name}: {len(var_data['items'])} items")
            else:
                print(f"  {var_name}: {var_data}")
        
        print_subsection("Context After Command")
        context_keys = list(context_store.keys())
        print(f"Context keys: {context_keys}")
        for key in context_keys:
            data = context_store.get(key)
            if isinstance(data, list):
                print(f"  {key}: {len(data)} items")
            else:
                print(f"  {key}: {data}")
                
    except Exception as e:
        print(f"❌ Execution error: {e}")
        import traceback
        traceback.print_exc()

async def test_hypothesis_driven_traversal(query: str, working_dir: str, max_iterations: int = 5):
    """Test full hypothesis-driven traversal."""
    print_separator(f"Testing Hypothesis-Driven Traversal: {query}")
    
    # Load graph
    print("Loading graph...")
    versioned_graph, graph_type = load_graph_from_nano_graphrag(working_dir)
    print(f"Graph loaded: {graph_type}")
    
    # Get current graph for stats
    current_graph = versioned_graph.get_current_graph()
    print(f"Total nodes: {current_graph.number_of_nodes()}")
    print(f"Total edges: {current_graph.number_of_edges()}")
    
    # Create adapter and LLM
    adapter = NetworkXAdapter(current_graph)
    adapter.versioned_graph = versioned_graph
    llm = ArgoBridgeLLM()
    
    # Create executor with state file
    state_file = os.path.join(working_dir, "gasl_state.json")
    executor = GASLExecutor(adapter, llm, state_file)
    
    print_subsection("Running Hypothesis-Driven Traversal")
    try:
        result = executor.run_hypothesis_driven_traversal(query, max_iterations=max_iterations)
        
        print(f"✅ GASL completed: {result.get('iterations', 0)} iterations")
        print(f"Query answered: {result.get('query_answered', False)}")
        
        # Show final state
        print_subsection("Final State")
        final_state = result.get('final_state', {})
        variables = final_state.get('variables', {})
        print(f"Final state variables: {list(variables.keys())}")
        
        for var_name, var_data in variables.items():
            if isinstance(var_data, dict) and 'items' in var_data:
                print(f"  {var_name}: {len(var_data['items'])} items")
                if len(var_data['items']) > 0:
                    print(f"    Sample: {var_data['items'][0]}")
            else:
                print(f"  {var_name}: {var_data}")
        
        # Show final answer
        if result.get('final_answer'):
            print_subsection("Final Answer")
            print(result['final_answer'])
        
        return result
        
    except Exception as e:
        print(f"❌ HDT error: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    parser = argparse.ArgumentParser(description="Debug GASL queries")
    parser.add_argument("--working-dir", required=True, help="Working directory with graph data")
    parser.add_argument("--command", help="Single GASL command to test")
    parser.add_argument("--query", help="Query for hypothesis-driven traversal")
    parser.add_argument("--max-iterations", type=int, default=5, help="Max iterations for HDT")
    parser.add_argument("--no-persistent-state", action="store_true", help="Don't use persistent state file")
    
    args = parser.parse_args()
    
    if args.command:
        # Test single command
        test_single_command(args.command, args.working_dir, not args.no_persistent_state)
    elif args.query:
        # Test hypothesis-driven traversal
        asyncio.run(test_hypothesis_driven_traversal(args.query, args.working_dir, args.max_iterations))
    else:
        print("❌ Please specify either --command or --query")
        print("\nExamples:")
        print("  python debug_gasl_queries.py --working-dir /path/to/papers --command 'FIND nodes with entity_type=PERSON'")
        print("  python debug_gasl_queries.py --working-dir /path/to/papers --query 'Find all authors and their publications'")
        sys.exit(1)

if __name__ == "__main__":
    main()
