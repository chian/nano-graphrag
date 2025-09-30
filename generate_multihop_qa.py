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
# Add examples directory to path for Argo Bridge functions
sys.path.append('./examples')

from nano_graphrag.graphrag import GraphRAG
from gasl.llm import ArgoBridgeLLM
from using_custom_argo_bridge_api import argo_bridge_llm, argo_bridge_embedding

def find_random_path(graph: nx.Graph, path_length: int):
    """Finds a random simple path of a specific length in the graph."""
    nodes = list(graph.nodes)
    while True:
        source = random.choice(nodes)
        
        # Find all paths up to path_length, then filter
        # This is more efficient than searching for a specific length from the start
        paths_found = []
        for target in nodes:
            if source != target:
                for path in nx.all_simple_paths(graph, source=source, target=target, cutoff=path_length):
                    if len(path) == path_length + 1:
                        paths_found.append(path)
        
        if paths_found:
            return random.choice(paths_found)

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

async def generate_qa_from_path(llm: ArgoBridgeLLM, path_info: str, start_node_label: str, end_node_label: str):
    """Generates a question and answer from the formatted path info."""
    # Generate Question
    question_prompt = (
        f"Based on the following connected facts, generate a single, clear question that asks about the "
        f"indirect relationship or connection between '{start_node_label}' and '{end_node_label}'. "
        f"The question should require reasoning across all the facts provided.\n\n"
        f"Facts:\n{path_info}\n\n"
        f"Question:"
    )
    
    question_response = await llm(question_prompt)
    question = question_response.strip()

    # Generate Answer
    answer_prompt = (
        f"Here is a question and the facts needed to answer it. Provide a comprehensive answer that explains "
        f"the step-by-step connection between the entities. Start the answer by explaining the first fact and "
        f"follow the chain of reasoning to the final entity.\n\n"
        f"Question: {question}\n\n"
        f"Facts:\n{path_info}\n\n"
        f"Answer:"
    )
    
    answer_response = await llm(answer_prompt)
    answer = answer_response.strip()

    return {"question": question, "answer": answer}

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
    
    llm = argo_bridge_llm
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

    # Save the generated pairs to a file
    with open(args.output_file, "w") as f:
        json.dump(generated_qa_pairs, f, indent=2)

    print(f"\nSuccessfully generated and saved {len(generated_qa_pairs)} QA pairs to {args.output_file}.")
    print("QA pair generation complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate multi-hop question-answer pairs from a knowledge graph.")
    parser.add_argument("--working-dir", type=str, required=True, help="Path to the working directory containing the graph.")
    parser.add_argument("--output-file", type=str, default="multihop_qa.json", help="Path to save the generated QA pairs.")
    parser.add_argument("--num-questions", type=int, default=10, help="Number of questions to generate.")
    parser.add_argument("--path-length", type=int, default=2, help="The number of hops for the questions (e.g., 2 or 3).")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))
