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
from gasl.graph_versioning import VersionedGraph, GraphVersionDebugger
from gasl.errors import GASLError


def load_graph_from_nano_graphrag(working_dir: str):
    """Load graph from nano-graphrag working directory, creating it if it doesn't exist."""
    try:
        import networkx as nx
        import os
        import xml.etree.ElementTree as ET
        
        # Load graph directly from GraphML file to avoid LLM initialization
        # First check in the graphrag_cache subdirectory
        cache_dir = os.path.join(working_dir, "graphrag_cache")
        graph_file = os.path.join(cache_dir, "graph_chunk_entity_relation.graphml")
        
        if not os.path.exists(graph_file):
            print(f"Graph file not found: {graph_file}")
            print("Creating graph from documents in working directory...")
            # Use the create_graph_from_folder function to build the graph
            graph_func, cache_dir = create_graph_from_folder(working_dir)
            # Update the graph_file path to the cache directory
            graph_file = os.path.join(cache_dir, "graph_chunk_entity_relation.graphml")
        
        # Load the graph directly
        graph = nx.read_graphml(graph_file)
        
        # Auto-discover GraphML key mapping and apply it
        graph = _apply_graphml_key_mapping(graph, graph_file)
        
        # Wrap in versioned graph system
        versioned_graph = VersionedGraph(graph, working_dir)
        
        return versioned_graph, "networkx"
        
    except Exception as e:
        raise GASLError(f"Failed to load graph from nano-graphrag: {e}")


def create_graph_from_folder(source_folder: str, working_dir: str = None):
    """Create a graph from all txt files in a source folder using nano-graphrag with Argo Bridge."""
    try:
        import os
        import json
        import sys
        from nano_graphrag import GraphRAG, QueryParam
        
        # Add the examples directory to path to import Argo Bridge functions
        sys.path.append('./examples')
        from using_custom_argo_bridge_api import argo_bridge_llm, argo_bridge_embedding
        
        # Use a subfolder for working directory to avoid conflicts
        if working_dir is None:
            working_dir = os.path.join(source_folder, "graphrag_cache")
        
        # Find all txt files in the source folder
        txt_files = []
        for file in os.listdir(source_folder):
            if file.endswith('.txt'):
                txt_files.append(os.path.join(source_folder, file))
        
        if not txt_files:
            raise GASLError(f"No .txt files found in {source_folder}")
        
        print(f"Found {len(txt_files)} text files to process")
        
        # Read and concatenate all text files
        all_text = ""
        for txt_file in txt_files:
            print(f"Processing {os.path.basename(txt_file)}...")
            with open(txt_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # Handle JSON files with "extracted text" field
                if content.strip().startswith('{'):
                    try:
                        data = json.loads(content)
                        if 'extracted text' in data:
                            content = data['extracted text']
                    except json.JSONDecodeError:
                        pass  # Use content as-is if not valid JSON
                
                all_text += f"\n\n--- {os.path.basename(txt_file)} ---\n\n"
                all_text += content
        
        # Create GraphRAG instance with Argo Bridge API
        print(f"Building knowledge graph in {working_dir}...")
        graph_func = GraphRAG(
            working_dir=working_dir,
            best_model_func=argo_bridge_llm,
            cheap_model_func=argo_bridge_llm,
            embedding_func=argo_bridge_embedding,
            enable_llm_cache=True
        )
        graph_func.insert(all_text)
        
        print("Knowledge graph created successfully!")
        return graph_func, working_dir
        
    except Exception as e:
        raise GASLError(f"Failed to create graph from folder: {e}")


def _apply_graphml_key_mapping(graph, graph_file):
    """Apply GraphML key mapping to use semantic names instead of keys."""
    try:
        import xml.etree.ElementTree as ET
        
        # Parse GraphML file to get key definitions
        tree = ET.parse(graph_file)
        root = tree.getroot()
        
        # Create mapping from keys to attribute names
        key_mapping = {}
        
        # Find all key definitions
        for key_elem in root.findall('.//key'):
            key_id = key_elem.get('id')
            attr_name = key_elem.get('attr.name')
            if key_id and attr_name:
                key_mapping[key_id] = attr_name
        
        # Apply mapping to all nodes
        for node_id, data in graph.nodes(data=True):
            new_data = {}
            for key, value in data.items():
                if key in key_mapping:
                    # Use semantic name instead of key
                    new_data[key_mapping[key]] = value
                else:
                    # Keep original key if no mapping found
                    new_data[key] = value
            # Update node data
            graph.nodes[node_id].update(new_data)
        
        # Apply mapping to all edges
        for source, target, data in graph.edges(data=True):
            new_data = {}
            for key, value in data.items():
                if key in key_mapping:
                    # Use semantic name instead of key
                    new_data[key_mapping[key]] = value
                else:
                    # Keep original key if no mapping found
                    new_data[key] = value
            # Update edge data
            graph.edges[source, target].update(new_data)
        
        return graph
        
    except Exception as e:
        # If mapping fails, return original graph
        print(f"Warning: Could not apply GraphML key mapping: {e}")
        return graph


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="GASL - Graph Analysis & State Language")
    parser.add_argument("--working-dir", required=True, help="Working directory with graph data")
    parser.add_argument("--query", required=True, help="Query to analyze")
    parser.add_argument("--adapter", choices=["networkx", "neo4j"], default="networkx", help="Graph adapter to use")
    parser.add_argument("--state-file", help="State file path (defaults to working-dir/gasl_state.json)")
    parser.add_argument("--max-iterations", type=int, default=10, help="Maximum HDT iterations")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    # Set default state file to be in working directory
    if not args.state_file:
        args.state_file = str(Path(args.working_dir) / "gasl_state.json")
    
    try:
        print(f"DEBUG: Starting main function...")
        print(f"DEBUG: Working directory: {args.working_dir}")
        print(f"DEBUG: State file: {args.state_file}")
        
        # Set up query-aware prompt system for graph creation
        print(f"Setting up query-aware prompts for: {args.query}")
        from nano_graphrag.prompt_system import set_prompt_system, QueryAwarePromptSystem
        from gasl.llm import ArgoBridgeLLM
        llm = ArgoBridgeLLM()
        ps = QueryAwarePromptSystem(llm_func=llm)
        set_prompt_system(ps)
        print("Query-aware prompt system activated!")
        
        # Load graph
        print(f"Loading graph from {args.working_dir}...")
        print(f"DEBUG: About to call load_graph_from_nano_graphrag...")
        graph, graph_type = load_graph_from_nano_graphrag(args.working_dir)
        print(f"DEBUG: Graph loaded successfully, type: {graph_type}")
        
        # Create adapter
        print(f"DEBUG: Creating {args.adapter} adapter...")
        if args.adapter == "networkx":
            # Pass the current graph from versioned graph to adapter
            current_graph = graph.get_current_graph()
            adapter = NetworkXAdapter(current_graph)
            # Store reference to versioned graph for updates
            adapter.versioned_graph = graph
        elif args.adapter == "neo4j":
            adapter = Neo4jAdapter(graph.get_current_graph())
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
        
        # Show version information if available
        if hasattr(adapter, 'versioned_graph') and adapter.versioned_graph:
            debugger = GraphVersionDebugger(adapter.versioned_graph)
            print("\n📚 Graph Versions Created:")
            debugger.show_versions()
        
    except GASLError as e:
        print(f"GASL Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
