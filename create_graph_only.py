#!/usr/bin/env python3
"""
Script to create a knowledge graph from text files using nano-graphrag with query-aware prompts.
This script only creates the graph, it doesn't answer queries.
"""

import argparse
import sys
from pathlib import Path

# Add examples directory to path for imports
sys.path.insert(0, str(Path(__file__).parent / "examples"))

from gasl_main import create_graph_from_folder


def main():
    """Main entry point for graph creation only."""
    parser = argparse.ArgumentParser(description="Create knowledge graph from text files")
    parser.add_argument("--source-dir", required=True, help="Directory containing text files")
    parser.add_argument("--working-dir", help="Working directory for graph storage (defaults to source-dir/graphrag_cache)")
    parser.add_argument("--entity-prompt", required=True, help="Prompt for entity type generation")
    
    args = parser.parse_args()
    
    try:
        print(f"Creating knowledge graph from {args.source_dir}")
        print(f"Using entity prompt: {args.entity_prompt}")
        
        # Set up query-aware prompt system for graph creation
        print("Setting up query-aware prompts...")
        from nano_graphrag.prompt_system import set_prompt_system, QueryAwarePromptSystem
        from gasl.llm import ArgoBridgeLLM
        llm = ArgoBridgeLLM()
        ps = QueryAwarePromptSystem(llm_func=llm)
        # Set the user query in the prompt system's static prompts
        ps._static_prompts["user_query"] = args.entity_prompt
        set_prompt_system(ps)
        print("Query-aware prompt system activated!")
        
        # Create the graph
        working_dir = args.working_dir or str(Path(args.source_dir) / "graphrag_cache")
        graph_func, cache_dir = create_graph_from_folder(args.source_dir, working_dir)
        
        print(f"Knowledge graph created successfully in {cache_dir}")
        
    except Exception as e:
        print(f"Error creating graph: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
