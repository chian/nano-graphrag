import argparse
import json
import asyncio
import random
import networkx as nx
import os
from pathlib import Path
import sys

# Add nano_graphrag to the python path
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from nano_graphrag.graphrag import GraphRAG
from gasl.llm import ArgoBridgeLLM

def find_random_path(graph: nx.Graph, path_length: int):
    """Finds a random simple path of a specific length in the graph."""
    import time
    start_time = time.time()
    timeout = 30  # 30 second timeout
    
    nodes = list(graph.nodes)
    attempts = 0
    max_attempts = 100
    
    while attempts < max_attempts and (time.time() - start_time) < timeout:
        source = random.choice(nodes)
        attempts += 1
        
        # Try to find a path of the exact length more efficiently
        try:
            # Use a more targeted approach - try a few random targets
            targets = random.sample([n for n in nodes if n != source], min(20, len(nodes)-1))
            
            for target in targets:
                try:
                    # Limit the search to avoid exponential explosion
                    paths = list(nx.all_simple_paths(graph, source=source, target=target, cutoff=path_length))
                    exact_length_paths = [p for p in paths if len(p) == path_length + 1]
                    
                    if exact_length_paths:
                        return random.choice(exact_length_paths)
                        
                except nx.NetworkXNoPath:
                    continue
                except Exception:
                    # Skip problematic paths
                    continue
                    
        except Exception:
            continue
    
    # If we can't find the exact length, try a shorter path
    print(f"Warning: Could not find path of length {path_length} within timeout. Trying shorter paths...")
    for shorter_length in range(path_length - 1, 1, -1):
        try:
            source = random.choice(nodes)
            target = random.choice([n for n in nodes if n != source])
            paths = list(nx.all_simple_paths(graph, source=source, target=target, cutoff=shorter_length))
            exact_length_paths = [p for p in paths if len(p) == shorter_length + 1]
            if exact_length_paths:
                print(f"Using path of length {shorter_length} instead")
                return random.choice(exact_length_paths)
        except:
            continue
    
    # Last resort: return any path
    try:
        source = random.choice(nodes)
        target = random.choice([n for n in nodes if n != source])
        path = nx.shortest_path(graph, source, target)
        print(f"Using shortest path of length {len(path)-1}")
        return path
    except:
        # If all else fails, return a single node
        return [random.choice(nodes)]

def format_path_for_llm(graph: nx.Graph, path: list) -> str:
    """Formats the path into a string for the LLM prompt."""
    formatted_string = ""
    for i in range(len(path) - 1):
        u, v = path[i], path[i+1]
        
        node_u_data = graph.nodes[u]
        node_v_data = graph.nodes[v]
        edge_data = graph.get_edge_data(u, v)

        formatted_string += f"Fact {i+1}:\n"
        formatted_string += f"- Entity: {node_u_data.get('label', u)}\n"
        formatted_string += f"  - Type: {node_u_data.get('type', 'N/A')}\n"
        formatted_string += f"  - Description: {node_u_data.get('description', 'N/A')}\n"
        formatted_string += f"- Relationship: {edge_data.get('description', 'N/A')}\n"
        formatted_string += f"- Entity: {node_v_data.get('label', v)}\n"
        formatted_string += f"  - Type: {node_v_data.get('type', 'N/A')}\n"
        formatted_string += f"  - Description: {node_v_data.get('description', 'N/A')}\n\n"
        
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

async def generate_qa_from_path(llm: ArgoBridgeLLM, path_info: str, start_node_label: str, end_node_label: str):
    """Generates a multi-hop question (with options) and minimal final answer from the formatted path."""
    # Load multihop question generation prompt (self-contained with options A–H)
    question_prompt_template = load_prompt_template("multihop_question_generation")
    question_prompt = question_prompt_template.format(start_entity=start_node_label, end_entity=end_node_label, context=path_info)
    
    question_response = await llm.call_async(question_prompt)
    question = question_response.strip()

    # Load multihop answer generation prompt (reasoning + single-letter final answer)
    answer_prompt_template = load_prompt_template("multihop_answer_generation")
    answer_prompt = answer_prompt_template.format(question=question)
    
    answer_response = await llm.call_async(answer_prompt)
    answer_text = answer_response.strip()

    # Extract FINAL_ANSWER letter if present; otherwise fallback
    final_answer = None
    marker = "FINAL_ANSWER:"
    if marker in answer_text:
        final_answer = answer_text.split(marker, 1)[-1].strip()
    else:
        stripped = answer_text.strip()
        if stripped in ["A", "B", "C", "D", "E", "F", "G", "H"]:
            final_answer = stripped
        else:
            final_answer = stripped

    return {"question": question, "answer": final_answer}

async def main(args):
    """Main function to generate multi-hop question-answer pairs."""
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

    print(f"Generating {args.num_questions} question-answer pairs...")
    for i in range(args.num_questions):
        print(f"  Generating pair {i+1}/{args.num_questions}...")
        try:
            path = find_random_path(graph, args.path_length)
            
            start_node_label = graph.nodes[path[0]].get('label', path[0])
            end_node_label = graph.nodes[path[-1]].get('label', path[-1])
            
            path_info = format_path_for_llm(graph, path)
            
            qa_pair = await generate_qa_from_path(llm, path_info, start_node_label, end_node_label)
            generated_qa_pairs.append(qa_pair)
            
            print(f"    - Question: {qa_pair['question']}")

        except Exception as e:
            print(f"    - Error generating pair {i+1}: {e}")
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
    parser = argparse.ArgumentParser(description="Generate multi-hop question-answer pairs from a knowledge graph.")
    parser.add_argument("--working-dir", type=str, required=True, help="Path to the working directory containing the graph.")
    parser.add_argument("--output-file", type=str, default="multihop_qa.json", help="Path to save the generated QA pairs.")
    parser.add_argument("--num-questions", type=int, default=10, help="Number of questions to generate.")
    parser.add_argument("--path-length", type=int, default=2, help="The number of hops for the questions (e.g., 2 or 3).")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))
