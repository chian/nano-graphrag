#!/usr/bin/env python3
"""
Debug script for generating one question at a time with full context visibility.
This script helps debug question generation by showing all intermediate steps.
"""

import argparse
import json
import asyncio
import networkx as nx
import os
from pathlib import Path
import sys
import random

# Add nano_graphrag to the python path
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from nano_graphrag.graphrag import GraphRAG
from gasl.llm import ArgoBridgeLLM

# Import the actual functions from generate_reasoning_qa.py
from generate_reasoning_qa import (
    sample_graph_context,
    get_exploration_ideas,
    compile_state_for_idea,
    generate_reasoning_question,
    filter_question_quality,
    extract_answer_letter
)

def print_separator(title=""):
    """Print a visual separator with optional title."""
    print("\n" + "="*80)
    if title:
        print(f" {title}")
        print("="*80)
    else:
        print("="*80)

def print_subsection(title):
    """Print a subsection header."""
    print(f"\n--- {title} ---")

def wait_for_continue():
    """Wait for user to press Enter to continue."""
    print("\n--- Continuing to next step ---")
    # input("\nPress Enter to continue to the next step...")


async def main(args):
    """Main function for debugging single question generation."""
    
    print_separator("DEBUG: Single Question Generation")
    print(f"Working Directory: {args.working_dir}")
    print(f"Paper: {os.path.basename(os.path.dirname(args.working_dir))}")
    
    # Load graph directly from GraphML file
    cache_dir = os.path.join(args.working_dir, "graphrag_cache")
    graph_file = os.path.join(cache_dir, "graph_chunk_entity_relation.graphml")
    
    if not os.path.exists(graph_file):
        print(f"ERROR: Graph file not found: {graph_file}")
        return
    
    print_subsection("Loading Graph")
    # Load the graph directly
    graph = nx.read_graphml(graph_file)
    print(f"Graph loaded with {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges.")
    
    wait_for_continue()
    
    llm = ArgoBridgeLLM()
    
    print_subsection("Sampling Graph Context")
    # Sample diverse contexts
    graph_samples = await sample_graph_context(graph, num_samples=10)
    print(f"Sampled {len(graph_samples)} diverse graph contexts.")
    
    # Show the samples
    for i, sample in enumerate(graph_samples[:3], 1):  # Show first 3 samples
        print(f"\nSample {i}:")
        center = sample['center_node']
        type_info = f" ({center.get('type', 'N/A')})" if 'type' in center else ""
        print(f"  Center: {center['label']}{type_info}")
        if 'description' in center:
            print(f"  Description: {center['description']}")
        print(f"  Neighbors: {', '.join([n['label'] for n in sample['neighbors'][:3]])}")
        print(f"  Relationships: {', '.join(sample['relationships'][:2])}")
    
    wait_for_continue()
    
    print_subsection("Generating Exploration Ideas")
    # Get new exploration ideas
    print("DEBUG: Calling get_exploration_ideas with graph samples...")
    ideas = await get_exploration_ideas(llm, graph_samples)
    
    print(f"Generated {len(ideas)} exploration ideas:")
    for i, idea in enumerate(ideas, 1):
        print(f"  {i}. [{idea.get('reasoning_type', 'N/A')}] {idea.get('biological_focus', 'N/A')}")
    
    wait_for_continue()
    
    # Select a random idea
    idea = random.choice(ideas)
    print_subsection("Selected Idea")
    print(f"Reasoning Type: {idea.get('reasoning_type', 'N/A')}")
    print(f"Biological Focus: {idea.get('biological_focus', 'N/A')}")
    
    wait_for_continue()
    
    print_subsection("Compiling State from Graph")
    # Compile state from graph
    compiled_state = await compile_state_for_idea(graph, llm, idea)
    
    print(f"Biological Focus: {compiled_state['biological_focus']}")
    print(f"Found {len(compiled_state['entities'])} relevant entities:")
    for i, entity in enumerate(compiled_state['entities'][:5], 1):
        type_info = f" ({entity.get('type', 'N/A')})" if 'type' in entity else ""
        desc_info = f": {entity.get('description', 'N/A')[:100]}..." if 'description' in entity else ""
        print(f"  {i}. {entity['label']}{type_info}{desc_info}")
    
    print(f"\nFound {len(compiled_state['relationships'])} relationships:")
    for i, rel in enumerate(compiled_state['relationships'][:5], 1):
        print(f"  {i}. {rel['from']} → {rel['to']}: {rel['relationship'][:80]}...")
    
    if len(compiled_state['entities']) < 3:
        print("ERROR: Not enough relevant entities found!")
        return
    
    wait_for_continue()
    
    print_subsection("Generating Reasoning Question")
    # Generate question
    question = await generate_reasoning_question(llm, idea, compiled_state)
    print("Generated Question:")
    print(question)
    
    wait_for_continue()
    
    print_subsection("Filtering for Quality")
    # Filter for quality
    quality = await filter_question_quality(llm, question, compiled_state)
    
    print(f"Quality Score: {quality['score']}/7")
    print(f"Critique: {quality['critique']}")
    print(f"Passed: {quality['passed']}")
    
    if not quality['passed']:
        print("Question failed quality filter!")
        return
    
    wait_for_continue()
    
    print_subsection("Extracting Answer")
    # Extract answer
    answer = await extract_answer_letter(llm, question)
    print(f"Extracted Answer: {answer}")
    
    print_separator("Final Result")
    print("Generated QA Pair:")
    print(f"Question: {question}")
    print(f"Answer: {answer}")
    print(f"Reasoning Type: {idea.get('reasoning_type', 'N/A')}")
    print(f"Biological Focus: {idea.get('biological_focus', 'N/A')}")
    print(f"Quality Score: {quality['score']}/7")
    
    # Save to file if requested
    if args.output_file:
        qa_pair = {
            'question': question,
            'answer': answer,
            'reasoning_type': idea.get('reasoning_type', 'N/A'),
            'biological_focus': idea.get('biological_focus', 'N/A'),
            'quality_score': quality['score'],
            'compiled_state': compiled_state
        }
        
        with open(args.output_file, "w") as f:
            json.dump([qa_pair], f, indent=2)
        
        print(f"\nSaved to: {args.output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Debug single question generation with full context visibility.")
    parser.add_argument("--working-dir", type=str, required=True, help="Path to the working directory containing the graph.")
    parser.add_argument("--output-file", type=str, help="Path to save the generated QA pair (optional).")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))



