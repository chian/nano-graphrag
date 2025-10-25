#!/usr/bin/env python3
"""
Debug script for generating one question at a time with full context visibility using GASL.
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

# Import the main function from generate_reasoning_qa_gasl.py
from generate_reasoning_qa_gasl import main as gasl_main

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
    
    print_separator("DEBUG: Testing generate_reasoning_qa_gasl.py")
    print(f"Working Directory: {args.working_dir}")
    print(f"Paper: {os.path.basename(os.path.dirname(args.working_dir))}")
    
    # Set num_questions to 1 for debugging
    args.num_questions = 1
    
    print("Calling the real generate_reasoning_qa_gasl.py main function...")
    print("="*80)
    
    # Call the actual main function from the real script
    await gasl_main(args)
    
    print("="*80)
    print("DEBUG: Real script execution completed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Debug single question generation with GASL and full context visibility.")
    parser.add_argument("--working-dir", type=str, required=True, help="Path to the working directory containing the graph.")
    parser.add_argument("--output-file", type=str, help="Path to save the generated QA pair (optional).")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))