import argparse
import json
import asyncio
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

async def generate_qa_from_context(llm: ArgoBridgeLLM, context: str, central_node_label: str):
    """Generates a synthesis question and answer from the aggregated context."""
    # Generate Question
    question_prompt = (
        f"You are a researcher analyzing a knowledge graph. Based on the following detailed context about '{central_node_label}' and its connections, "
        f"generate a single, insightful question that starts with 'Why' or 'How'. The question should not be answerable "
        f"by a single fact but must require synthesizing information from multiple parts of the provided context to answer.\n\n"
        f"Context:\n{context}\n\n"
        f"Question:"
    )
    
    question_response = await llm(question_prompt)
    question = question_response.strip()

    # Generate Answer
    answer_prompt = (
        f"Please provide a comprehensive, well-reasoned answer to the following question using only the provided context. "
        f"Structure your answer to show the synthesis of information. Explain how the different pieces of context connect to form the answer.\n\n"
        f"Question: {question}\n\n"
        f"Context:\n{context}\n\n"
        f"Answer:"
    )
    
    answer_response = await llm(answer_prompt)
    answer = answer_response.strip()

    return {"question": question, "answer": answer}

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
    
    llm = argo_bridge_llm
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

    # Save the generated pairs to a file
    with open(args.output_file, "w") as f:
        json.dump(generated_qa_pairs, f, indent=2)

    print(f"\nSuccessfully generated and saved {len(generated_qa_pairs)} QA pairs to {args.output_file}.")
    print("QA pair generation complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthesis (Why/How) question-answer pairs from a knowledge graph.")
    parser.add_argument("--working-dir", type=str, required=True, help="Path to the working directory containing the graph.")
    parser.add_argument("--output-file", type=str, default="synthesis_qa.json", help="Path to save the generated QA pairs.")
    parser.add_argument("--num-questions", type=int, default=10, help="The maximum number of questions to generate (based on the most central nodes).")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))
