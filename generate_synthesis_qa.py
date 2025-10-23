import argparse
import json
import asyncio
import networkx as nx
import os
from pathlib import Path
import sys

# Add nano_graphrag to the python path
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from nano_graphrag.graphrag import GraphRAG
from gasl.llm import ArgoBridgeLLM

def get_central_nodes(graph: nx.Graph, num_nodes: int):
    """Finds the top N nodes with the highest degree."""
    if graph.number_of_nodes() == 0:
        return []
    
    sorted_nodes = sorted(graph.degree, key=lambda item: item[1], reverse=True)
    return [node[0] for node in sorted_nodes[:num_nodes]]

def format_context_for_llm(graph: nx.Graph, central_node: str) -> str:
    """Aggregates and formats the context for a central node for the LLM prompt."""
    central_node_data = graph.nodes[central_node]
    formatted_string = f"Central Entity: {central_node_data.get('label', central_node)}\n"
    formatted_string += f"- Type: {central_node_data.get('type', 'N/A')}\n"
    formatted_string += f"- Description: {central_node_data.get('description', 'N/A')}\n\n"
    formatted_string += "Connections:\n"

    for neighbor in graph.neighbors(central_node):
        neighbor_data = graph.nodes[neighbor]
        edge_data = graph.get_edge_data(central_node, neighbor)

        formatted_string += f"- Connected to: {neighbor_data.get('label', neighbor)} ({neighbor_data.get('type', 'N/A')})\n"
        formatted_string += f"  - Relationship Description: {edge_data.get('description', 'N/A')}\n"
        formatted_string += f"  - Neighbor Description: {neighbor_data.get('description', 'N/A')}\n\n"
        
    return formatted_string.strip()

def load_prompt_template(prompt_name: str) -> str:
    """Load a prompt template from the prompts directory."""
    # Use absolute path based on script location
    script_dir = Path(__file__).parent.absolute()
    prompt_file = script_dir / "prompts" / f"{prompt_name}.txt"
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

async def generate_qa_from_context(llm: ArgoBridgeLLM, context: str, central_node_label: str):
    """Generates a synthesis question (with options) and minimal final answer from the aggregated context."""
    # Load synthesis question generation prompt (self-contained with options A–H)
    question_prompt_template = load_prompt_template("synthesis_question_generation")
    question_prompt = question_prompt_template.format(entity_label=central_node_label, context=context)
    
    question_response = await llm.call_async(question_prompt)
    question = question_response.strip()

    # Load synthesis answer generation prompt (reasoning + single-letter final answer)
    answer_prompt_template = load_prompt_template("synthesis_answer_generation")
    answer_prompt = answer_prompt_template.format(question=question)
    
    answer_response = await llm.call_async(answer_prompt)
    answer_text = answer_response.strip()

    # Extract FINAL_ANSWER letter if present; otherwise fallback to the stripped response
    final_answer = None
    marker = "FINAL_ANSWER:"
    if marker in answer_text:
        final_answer = answer_text.split(marker, 1)[-1].strip()
    else:
        # Try to find a single option letter at end
        stripped = answer_text.strip()
        if stripped in ["A", "B", "C", "D", "E", "F", "G", "H"]:
            final_answer = stripped
        else:
            final_answer = stripped

    return {"question": question, "answer": final_answer}

async def main(args):
    """Main function to generate synthesis question-answer pairs."""
    print("Loading graph directly from GraphML file...")
    
    # Load graph directly from GraphML file
    cache_dir = os.path.join(args.working_dir, "graphrag_cache")
    graph_file = os.path.join(cache_dir, "graph_chunk_entity_relation.graphml")
    
    if not os.path.exists(graph_file):
        print(f"Graph file not found: {graph_file}")
        return
    
    # Load the graph directly
    graph = nx.read_graphml(graph_file)
    print(f"Graph loaded with {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges.")
    
    llm = ArgoBridgeLLM()
    generated_qa_pairs = []

    print(f"Identifying {args.num_questions} central nodes for question generation...")
    central_nodes = get_central_nodes(graph, args.num_questions)

    if not central_nodes:
        print("No central nodes found to generate questions from.")
        return

    print(f"Generating QA pairs for {len(central_nodes)} nodes...")
    for i, node_id in enumerate(central_nodes):
        print(f"  Generating pair {i+1}/{len(central_nodes)} for node '{graph.nodes[node_id].get('label', node_id)}'...")
        try:
            context = format_context_for_llm(graph, node_id)
            central_node_label = graph.nodes[node_id].get('label', node_id)
            
            qa_pair = await generate_qa_from_context(llm, context, central_node_label)
            generated_qa_pairs.append(qa_pair)
            
            print(f"    - Question: {qa_pair['question']}")

        except Exception as e:
            print(f"    - Error generating pair for node {node_id}: {e}")
            continue

    # Load existing QA pairs if file exists, then append new ones
    existing_pairs = []
    if os.path.exists(args.output_file):
        print(f"Loading existing QA pairs from {args.output_file}...")
        try:
            with open(args.output_file, "r") as f:
                existing_pairs = json.load(f)
            print(f"Found {len(existing_pairs)} existing QA pairs.")
        except (json.JSONDecodeError, FileNotFoundError):
            print("No valid existing QA pairs found, starting fresh.")
            existing_pairs = []
    else:
        print(f"No existing file found at {args.output_file}, creating new file.")
    
    # Combine existing and new pairs
    all_pairs = existing_pairs + generated_qa_pairs
    print(f"Combining {len(existing_pairs)} existing + {len(generated_qa_pairs)} new = {len(all_pairs)} total pairs.")
    
    # Save the combined pairs to a file
    print(f"Saving combined QA pairs to {args.output_file}...")
    with open(args.output_file, "w") as f:
        json.dump(all_pairs, f, indent=2)

    print(f"\nSuccessfully generated and saved {len(generated_qa_pairs)} new QA pairs to {args.output_file}.")
    print(f"Total QA pairs in file: {len(all_pairs)}")
    print("QA pair generation complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthesis (Why/How) question-answer pairs from a knowledge graph.")
    parser.add_argument("--working-dir", type=str, required=True, help="Path to the working directory containing the graph.")
    parser.add_argument("--output-file", type=str, default="synthesis_qa.json", help="Path to save the generated QA pairs.")
    parser.add_argument("--num-questions", type=int, default=10, help="The maximum number of questions to generate (based on the most central nodes).")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))
