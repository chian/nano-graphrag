#!/usr/bin/env python3
"""
Run Analytical Retriever with Argo Bridge API

This script integrates the analytical retriever with your existing Argo Bridge setup
to provide flexible, systematic querying of knowledge graphs.
"""

import asyncio
import os
import sys
import argparse
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from analytical_retriever import AnalyticalRetriever
from nano_graphrag import GraphRAG

# Import the Argo Bridge functions directly
import importlib.util
spec = importlib.util.spec_from_file_location("argo_bridge", "examples/using_custom_argo_bridge_api.py")
argo_bridge_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(argo_bridge_module)
argo_bridge_llm = argo_bridge_module.argo_bridge_llm
argo_bridge_embedding = argo_bridge_module.argo_bridge_embedding


async def main():
    """Main function to run the analytical retriever."""
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run Analytical Retriever with Argo Bridge API")
    parser.add_argument("--working-dir", default="./nano_graphrag_cache_argo_bridge",
                       help="Working directory with processed knowledge graph")
    parser.add_argument("--query", default="Make me a graph representation of authors connected by co-authorship",
                       help="Query to execute")
    parser.add_argument("--verbose", action="store_true",
                       help="Show detailed step-by-step execution")
    args = parser.parse_args()
    
    # Check environment variables
    if not os.getenv("LLM_API_KEY"):
        print("Error: Please set LLM_API_KEY environment variable")
        return
    
    if not os.getenv("EMBEDDING_API_KEY"):
        print("Error: Please set EMBEDDING_API_KEY environment variable")
        return
    
    print("Analytical Retriever with Argo Bridge API")
    print("=" * 50)
    print(f"Working Directory: {args.working_dir}")
    print(f"Query: {args.query}")
    print()
    
    try:
        # Initialize GraphRAG with your custom API
        print("Initializing GraphRAG...")
        rag = GraphRAG(
            working_dir=args.working_dir,
            best_model_func=argo_bridge_llm,
            cheap_model_func=argo_bridge_llm,
            embedding_func=argo_bridge_embedding,
            enable_llm_cache=True
        )
        
        # Get the graph storage instance
        graph_storage = rag.chunk_entity_relation_graph
        print(f"Graph storage type: {type(graph_storage).__name__}")
        
        if hasattr(graph_storage, '_graph'):
            print(f"Graph has {graph_storage._graph.number_of_nodes()} nodes and {graph_storage._graph.number_of_edges()} edges")
        print()
        
        # Create analytical retriever
        print("Creating Analytical Retriever...")
        analytical_retriever = AnalyticalRetriever(
            graph_storage=graph_storage,
            llm_func=argo_bridge_llm
        )
        print()
        
        # Get context (this will decompose the query and execute steps)
        print("Decomposing query and executing steps...")
        context = await analytical_retriever.get_context(args.query)
        print()
        
        # Display execution summary
        if "execution_summary" in context:
            summary = context["execution_summary"]
            print("EXECUTION SUMMARY:")
            print(f"  Total steps: {summary.get('total_steps', 0)}")
            print(f"  Successful steps: {summary.get('successful_steps', 0)}")
            print(f"  Failed steps: {summary.get('failed_steps', 0)}")
            print(f"  Success rate: {summary.get('success_rate', 0):.2%}")
            print()
        
        # Display step results if verbose
        if args.verbose:
            print("DETAILED STEP RESULTS:")
            for step_name, step_data in context.get("steps", {}).items():
                print(f"  {step_name}: {step_data.get('description', 'No description')}")
                print(f"    Status: {step_data.get('status', 'unknown')}")
                if step_data.get('status') == 'success':
                    result = step_data.get('result', {})
                    if isinstance(result, dict):
                        if 'count' in result:
                            print(f"    Count: {result['count']}")
                        if 'authors' in result:
                            print(f"    Authors found: {len(result['authors'])}")
                            if result['authors']:
                                print(f"    Sample authors: {', '.join(result['authors'][:5])}")
                        if 'entities' in result:
                            print(f"    Entities found: {len(result['entities'])}")
                            if result['entities']:
                                sample_entities = []
                                for entity in result['entities'][:5]:
                                    if isinstance(entity, dict):
                                        name = entity.get('node', entity.get('name', 'unnamed'))
                                        if name and name != 'unnamed':
                                            sample_entities.append(name)
                                if sample_entities:
                                    print(f"    Sample entities: {', '.join(sample_entities)}")
                else:
                    print(f"    Error: {step_data.get('error', 'Unknown error')}")
                print()
        
        # Generate final answer
        print("GENERATING FINAL ANSWER...")
        completion = await analytical_retriever.get_completion(args.query, context)
        print()
        
        print("FINAL ANSWER:")
        print("=" * 60)
        for answer in completion:
            print(answer)
        print("=" * 60)
        
        # If this is a co-authorship query, try to generate a Mermaid diagram
        if "co-authorship" in args.query.lower() or "authors" in args.query.lower():
            print("\n" + "=" * 60)
            print("MERMAID DIAGRAM GENERATION")
            print("=" * 60)
            
            # Look for co-authorship data in the results
            coauthorship_data = None
            for step_name, step_data in context.get("steps", {}).items():
                if step_data.get('status') == 'success':
                    result = step_data.get('result', {})
                    if 'authors' in result and 'coauthorships' in result:
                        coauthorship_data = result
                        break
            
            if coauthorship_data:
                print("Found co-authorship data! Generating Mermaid diagram...")
                mermaid_diagram = generate_mermaid_diagram(coauthorship_data)
                print("\nCopy this into a Mermaid visualizer:")
                print("-" * 40)
                print(mermaid_diagram)
                print("-" * 40)
            else:
                print("No co-authorship data found in the results.")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


def generate_mermaid_diagram(coauthorship_data):
    """Generate a Mermaid diagram from co-authorship data."""
    
    authors = coauthorship_data.get('authors', [])
    coauthorships = coauthorship_data.get('coauthorships', [])
    
    if not authors:
        return "No authors found in the data."
    
    # Create the Mermaid diagram
    diagram = ["graph TD"]
    
    # Add author nodes
    for author in authors[:20]:  # Limit to first 20 authors
        # Clean up author name for Mermaid
        clean_name = author.replace('"', '').replace("'", "").replace(" ", "_")
        diagram.append(f'    {clean_name}["{author}"]')
    
    # Add co-authorship edges
    for coauth in coauthorships[:50]:  # Limit to first 50 relationships
        source = coauth.get('source', '')
        target = coauth.get('target', '')
        
        if source and target and source in authors and target in authors:
            clean_source = source.replace('"', '').replace("'", "").replace(" ", "_")
            clean_target = target.replace('"', '').replace("'", "").replace(" ", "_")
            diagram.append(f'    {clean_source} -- "co-authored" --- {clean_target}')
    
    return "\n".join(diagram)


if __name__ == "__main__":
    asyncio.run(main())
