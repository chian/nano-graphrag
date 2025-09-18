"""
Main entry point for GASL system.
"""

import argparse
import json
import sys
from pathlib import Path

# Add examples directory to path for imports
sys.path.insert(0, str(Path(__file__).parent / "examples"))

from gasl import GASLExecutor
from gasl.adapters import NetworkXAdapter, Neo4jAdapter
from gasl.llm import ArgoBridgeLLM
from gasl.errors import GASLError


def load_graph_from_nano_graphrag(working_dir: str):
    """Load graph from nano-graphrag working directory."""
    try:
        import networkx as nx
        import os
        
        # Load graph directly from GraphML file to avoid LLM initialization
        graph_file = os.path.join(working_dir, "graph_chunk_entity_relation.graphml")
        if not os.path.exists(graph_file):
            raise GASLError(f"Graph file not found: {graph_file}")
        
        # Load the graph directly
        graph = nx.read_graphml(graph_file)
        
        return graph, "networkx"
        
    except Exception as e:
        raise GASLError(f"Failed to load graph from nano-graphrag: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="GASL - Graph Analysis & State Language")
    parser.add_argument("--working-dir", required=True, help="Working directory with graph data")
    parser.add_argument("--query", required=True, help="Query to analyze")
    parser.add_argument("--adapter", choices=["networkx", "neo4j"], default="networkx", help="Graph adapter to use")
    parser.add_argument("--state-file", default="gasl_state.json", help="State file path")
    parser.add_argument("--max-iterations", type=int, default=10, help="Maximum HDT iterations")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    try:
        print(f"DEBUG: Starting main function...")
        # Load graph
        print(f"Loading graph from {args.working_dir}...")
        print(f"DEBUG: About to call load_graph_from_nano_graphrag...")
        graph, graph_type = load_graph_from_nano_graphrag(args.working_dir)
        print(f"DEBUG: Graph loaded successfully, type: {graph_type}")
        
        # Create adapter
        print(f"DEBUG: Creating {args.adapter} adapter...")
        if args.adapter == "networkx":
            adapter = NetworkXAdapter(graph)
        elif args.adapter == "neo4j":
            adapter = Neo4jAdapter(graph)
        else:
            raise GASLError(f"Unknown adapter: {args.adapter}")
        print(f"DEBUG: Adapter created successfully")
        
        # Create LLM
        print(f"DEBUG: Creating ArgoBridgeLLM...")
        llm = ArgoBridgeLLM()
        print(f"DEBUG: LLM created successfully")
        
        # Create executor
        print(f"DEBUG: Creating GASLExecutor...")
        executor = GASLExecutor(adapter, llm, args.state_file)
        print(f"DEBUG: Executor created successfully")
        
        # Run HDT
        print(f"Running Hypothesis-Driven Traversal for query: {args.query}")
        result = executor.run_hypothesis_driven_traversal(args.query, args.max_iterations)
        
        # Print results
        print("\n" + "="*80)
        print("FINAL ANSWER:")
        print("="*80)
        print(result["final_answer"])
        
        if args.verbose:
            print("\n" + "="*80)
            print("DETAILED RESULTS:")
            print("="*80)
            print(f"Iterations: {result['iterations']}")
            print(f"Final State Variables:")
            variables = result["final_state"].get("variables", {})
            for var_name, var_data in variables.items():
                if isinstance(var_data, dict) and "_meta" in var_data:
                    var_type = var_data["_meta"]["type"]
                    if var_type == "LIST":
                        count = len(var_data.get("items", []))
                        print(f"  - {var_name} ({var_type}): {count} items")
                    elif var_type == "DICT":
                        keys = [k for k in var_data.keys() if k != "_meta"]
                        print(f"  - {var_name} ({var_type}): {len(keys)} keys")
                    elif var_type == "COUNTER":
                        value = var_data.get("value", 0)
                        print(f"  - {var_name} ({var_type}): {value}")
                else:
                    print(f"  - {var_name}: {var_data}")
        
        # Save state to file
        state_file = Path(args.state_file)
        with open(state_file, 'w') as f:
            json.dump(result["final_state"], f, indent=2, default=str)
        
        print(f"\nState saved to: {state_file}")
        
    except GASLError as e:
        print(f"GASL Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
