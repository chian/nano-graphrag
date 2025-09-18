#!/usr/bin/env python3
"""
Simple script to run nano-graphrag with your Argo Bridge API
Make sure to set your environment variables before running:
export LLM_API_KEY=your_api_key
export EMBEDDING_API_KEY=your_api_key
"""

import os
import sys
import argparse
from nano_graphrag import GraphRAG, QueryParam

# Add the examples directory to path to import our custom functions
sys.path.append('./examples')
from using_custom_argo_bridge_api import argo_bridge_llm, argo_bridge_embedding

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Query nano-graphrag with Argo Bridge API")
    parser.add_argument("--working-dir", default="./nano_graphrag_cache_argo_bridge",
                       help="Working directory with processed knowledge graph (default: ./nano_graphrag_cache_argo_bridge)")
    parser.add_argument("--query", default="Make me a graph representation of authors connected by co-authorship",
                       help="Query to execute")
    args = parser.parse_args()
    
    # Check environment variables
    if not os.getenv("LLM_API_KEY"):
        print("Error: Please set LLM_API_KEY environment variable")
        return
    
    if not os.getenv("EMBEDDING_API_KEY"):
        print("Error: Please set EMBEDDING_API_KEY environment variable")
        return
    
    # Check if knowledge graph cache exists
    cache_files = [
        "vdb_entities.json",
        "kv_store_full_docs.json", 
        "kv_store_text_chunks.json",
        "kv_store_community_reports.json",
        "graph_chunk_entity_relation.graphml"
    ]
    
    cache_exists = all(os.path.exists(os.path.join(args.working_dir, f)) for f in cache_files)
    
    # Initialize GraphRAG with your custom API
    rag = GraphRAG(
        working_dir=args.working_dir,
        best_model_func=argo_bridge_llm,
        cheap_model_func=argo_bridge_llm,
        embedding_func=argo_bridge_embedding,
        enable_llm_cache=True
    )
    
    # Example usage
    print("Nano-GraphRAG with Argo Bridge API")
    print("=" * 40)
    print("Note: No retry logic - can handle 15+ minute response times")
    
    if not cache_exists:
        print(f"No existing knowledge graph found in: {args.working_dir}")
        print("Processing text files to create knowledge graph...")
        
        # Find text files in the directory
        text_files = []
        for file in os.listdir(args.working_dir):
            if file.endswith('.txt') and not file.startswith('.'):
                text_files.append(os.path.join(args.working_dir, file))
        
        if not text_files:
            print("Error: No .txt files found in the directory to process")
            return
        
        print(f"Found {len(text_files)} text files to process:")
        for f in text_files:
            print(f"  - {os.path.basename(f)}")
        
        # Process each text file
        all_text = ""
        for text_file in text_files:
            print(f"Processing {os.path.basename(text_file)}...")
            with open(text_file, 'r', encoding='utf-8') as f:
                content = f.read()
                all_text += f"\n\n--- {os.path.basename(text_file)} ---\n\n"
                all_text += content
        
        print("Building knowledge graph...")
        rag.insert(all_text)
        print("Knowledge graph created successfully!")
    else:
        print(f"Using existing processed knowledge graph from: {args.working_dir}")
    
    # Query the system
    print(f"\nQuery: {args.query}")
    print("=" * 60)
    
    # Try different modes to see what data we can extract
    print("\n1. LOCAL MODE - Entity and Relationship Analysis:")
    local_result = rag.query(
        args.query, 
        param=QueryParam(mode="local", top_k=20)
    )
    print(f"Local Result: {local_result}")
    
    print("\n2. GLOBAL MODE - Community Analysis:")
    global_result = rag.query(
        args.query, 
        param=QueryParam(mode="global", level=2)
    )
    print(f"Global Result: {global_result}")
    
    print("\n3. RAW CONTEXT - What data is actually retrieved:")
    context = rag.query(
        args.query, 
        param=QueryParam(mode="local", top_k=15, only_need_context=True)
    )
    print(f"Retrieved Context:\n{context}")

if __name__ == "__main__":
    main()
