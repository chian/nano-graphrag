#!/usr/bin/env python3
"""
Superprompt optimizer for GASL planning prompts.
Uses an LLM to analyze and optimize the verbose GASL prompt into a more effective version.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from gasl.llm.argo_bridge import ArgoBridgeLLM

def create_superprompt_optimizer():
    """Create a superprompt to optimize GASL planning prompts."""
    
    current_prompt = """You are an AI agent that analyzes knowledge graphs to answer queries. 

Query: create a histogram of how often author names appear - show frequency vs count of appearances

Available Graph Schema:
- Node Labels: ['ORGANIZATION', 'EVENT', 'PERSON', 'UNKNOWN', 'GEO']
- Edge Types: []
- Node Properties: ['source_id', 'entity_type', 'description', 'clusters']
- Edge Properties: ['description', 'source_id', 'weight', 'order']

Current State Variables:
- authors_list (LIST): 0 items - List to store all author names found in EVENT node properties
- authors_counter (COUNTER): 0 - Counter for author name frequencies

IMPORTANT: Before creating new variables, check if existing variables can be reused or updated. 
- If a variable already exists with the same type, you can reuse it (it will be reset)
- If you need different data, consider updating existing variables with UPDATE commands
- Only create new variables if you need a fundamentally different data structure

Execution History:
- error: PROCESS last_nodes_result with instruction: Extract all author names from node properties (description, clusters, source_id); append all found names to authors_list; (result count: 0)
- success: FIND nodes with entity_type=EVENT; (result count: 333)
- error: PROCESS last_nodes_result with instruction: Extract all author names from node properties (description, clusters, source_id); append all found names to authors_list; (result count: 0)
- success: FIND nodes with entity_type=EVENT; (result count: 333)
- error: PROCESS last_nodes_result with instruction: Extract all author names from node properties (description, clusters, source_id); append all found names to authors_list; (result count: 0)

[LONG COMMAND REFERENCE LISTS FOLLOW...]"""

    superprompt = f"""You are a prompt optimization expert specializing in AI planning systems. Your task is to analyze the current GASL planning prompt and create a more effective version.

CURRENT PROMPT ANALYSIS:
The current prompt has these issues:
1. Execution history is buried deep in the prompt
2. Failed approaches are not prominently highlighted
3. No explicit instruction to learn from failures
4. Overwhelming command reference distracts from key information
5. The LLM keeps repeating the same failed EVENT approach despite clear failure patterns

CURRENT PROMPT:
{current_prompt}

OPTIMIZATION REQUIREMENTS:
Create a shorter, more effective prompt that:

1. **LEARNS FROM FAILURES**: Make execution history prominent and explicit about what failed
2. **AVOIDS REPETITION**: Clearly state "DO NOT repeat failed approaches"
3. **GUIDES TOWARD SUCCESS**: Highlight successful patterns and guide toward PERSON nodes
4. **REDUCES COGNITIVE LOAD**: Focus on essential information, minimize command reference
5. **EXPLICIT INSTRUCTIONS**: Add clear learning and strategy guidance

KEY INSIGHTS TO INCORPORATE:
- EVENT nodes have been tried 5+ times and consistently fail to produce author names
- PERSON nodes are likely to contain author information
- The LLM should explore PERSON nodes instead of EVENT nodes
- Failed approaches should be explicitly avoided

Create an optimized prompt that will get the LLM to try PERSON nodes instead of repeating the failed EVENT approach."""

    return superprompt

def optimize_prompt():
    """Use the superprompt to optimize the GASL planning prompt."""
    llm = ArgoBridgeLLM()
    
    superprompt = create_superprompt_optimizer()
    
    print("=== SUPERPROMPT OPTIMIZER ===")
    print("Analyzing current GASL prompt and creating optimized version...\n")
    
    optimized_prompt = llm.call(superprompt)
    
    print("=== OPTIMIZED GASL PLANNING PROMPT ===")
    print(optimized_prompt)
    
    return optimized_prompt

if __name__ == "__main__":
    optimize_prompt()
