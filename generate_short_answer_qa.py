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

async def sample_graph_context(graph: nx.Graph, num_samples: int = 5, exclude_topics: set = None):
    """Sample diverse subgraphs from different parts of the graph, avoiding recent topics."""
    samples = []
    nodes_list = list(graph.nodes())
    
    # Track what we've sampled to ensure diversity
    sampled_labels = set()
    attempts = 0
    max_attempts = num_samples * 20  # Try up to 20x to get diverse samples
    
    while len(samples) < num_samples and attempts < max_attempts:
        attempts += 1
        
        # Pick a random starting node
        start_node = random.choice(nodes_list)
        start_data = graph.nodes[start_node]
        label = start_data.get('label', 'unknown')
        
        # Skip if label is unknown or already sampled
        if label == 'unknown' or label in sampled_labels:
            continue
        
        # Skip if this label contains excluded topic keywords
        if exclude_topics:
            label_lower = label.lower()
            if any(keyword in label_lower for keyword in exclude_topics):
                continue
        
        # Get its neighbors
        neighbors = list(graph.neighbors(start_node))[:5]
        neighbor_data = [graph.nodes[n] for n in neighbors]
        
        # Get edge descriptions
        edges = []
        for n in neighbors:
            edge_data = graph.get_edge_data(start_node, n)
            edges.append(edge_data)
        
        sample = {
            'center_node': {
                'label': label,
                'type': start_data.get('type', 'N/A'),
                'description': start_data.get('description', 'N/A')[:200]  # Limit length
            },
            'neighbors': [
                {
                    'label': nd.get('label', 'unknown'),
                    'type': nd.get('type', 'N/A'),
                    'description': nd.get('description', 'N/A')[:100]
                }
                for nd in neighbor_data
            ],
            'relationships': [
                ed.get('description', 'connected to')[:100]
                for ed in edges
            ]
        }
        samples.append(sample)
        sampled_labels.add(label)
    
    # If we couldn't get enough diverse samples, fill with any samples
    while len(samples) < num_samples and attempts < max_attempts:
        attempts += 1
        start_node = random.choice(nodes_list)
        start_data = graph.nodes[start_node]
        
        neighbors = list(graph.neighbors(start_node))[:5]
        neighbor_data = [graph.nodes[n] for n in neighbors]
        edges = []
        for n in neighbors:
            edge_data = graph.get_edge_data(start_node, n)
            edges.append(edge_data)
        
        sample = {
            'center_node': {
                'label': start_data.get('label', 'unknown'),
                'type': start_data.get('type', 'N/A'),
                'description': start_data.get('description', 'N/A')[:200]
            },
            'neighbors': [
                {
                    'label': nd.get('label', 'unknown'),
                    'type': nd.get('type', 'N/A'),
                    'description': nd.get('description', 'N/A')[:100]
                }
                for nd in neighbor_data
            ],
            'relationships': [
                ed.get('description', 'connected to')[:100]
                for ed in edges
            ]
        }
        samples.append(sample)
    
    return samples

async def get_exploration_ideas(llm: ArgoBridgeLLM, graph_samples: list):
    """Ask LLM to suggest short-answer questions based on graph samples."""
    
    # Format samples for prompt
    samples_text = ""
    for i, sample in enumerate(graph_samples, 1):
        samples_text += f"\nSample {i}:\n"
        samples_text += f"  Center: {sample['center_node']['label']} (Type: {sample['center_node']['type']})\n"
        samples_text += f"  Description: {sample['center_node']['description']}\n"
        samples_text += f"  Connected to:\n"
        for j, neighbor in enumerate(sample['neighbors']):
            rel = sample['relationships'][j] if j < len(sample['relationships']) else 'connected to'
            samples_text += f"    - {neighbor['label']} (Type: {neighbor['type']}): {rel}\n"
    
    prompt = f"""You are analyzing a scientific knowledge graph to identify SHORT-ANSWER reasoning questions.

Here are some random samples from the graph:
{samples_text}

Suggest 3-5 short-answer reasoning questions where the answer is:
- 1-2 words (entity name, direction like "increased"/"decreased")
- A number with units (e.g., "2.5 μg/mL", "72 hours", "45%")
- Yes/no

For each idea, specify:
1. REASONING_TYPE: causal, comparative, mechanistic, quantitative, or identification
2. BIOLOGICAL_FOCUS: The biological concept
3. ANSWER_TYPE: "short_text", "numeric", or "yes_no"
4. EXPECTED_ANSWER: Exact answer (for validation)
5. QUERY_STRATEGY: What to search in graph
6. EXAMPLE_QUESTION: Sample question

Output JSON:
{{
  "ideas": [
    {{
      "reasoning_type": "quantitative",
      "biological_focus": "antibiotic potency",
      "answer_type": "numeric",
      "expected_answer": "4 μg/mL",
      "query_strategy": "Find MIC values",
      "example_question": "What is the MIC of compound X against MRSA?"
    }}
  ]
}}

Be precise."""

    response = await llm.call_async(prompt)
    
    # Parse JSON response
    try:
        # Extract JSON from response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
        else:
            json_str = response.strip()
        
        ideas = json.loads(json_str)
        return ideas.get('ideas', [])
    except:
        print(f"Warning: Could not parse LLM response as JSON. Response:\n{response}")
        return []

async def compile_state_for_idea(graph: nx.Graph, llm: ArgoBridgeLLM, idea: dict):
    """Use the query strategy to compile relevant information from the graph."""
    
    query_strategy = idea.get('query_strategy', '')
    biological_focus = idea.get('biological_focus', '')
    
    # Parse the query strategy to find relevant nodes
    compiled_state = {
        'biological_focus': biological_focus,
        'entities': [],
        'relationships': [],
        'mechanisms': []
    }
    
    # Search for relevant nodes based on biological focus
    relevant_nodes = []
    focus_keywords = biological_focus.lower().split()
    
    for node_id in graph.nodes():
        node_data = graph.nodes[node_id]
        label = node_data.get('label', '').lower()
        desc = node_data.get('description', '').lower()
        
        # Check if node is relevant to biological focus
        if any(keyword in label or keyword in desc for keyword in focus_keywords):
            relevant_nodes.append({
                'id': node_id,
                'label': node_data.get('label', 'unknown'),
                'type': node_data.get('type', 'N/A'),
                'description': node_data.get('description', 'N/A')
            })
    
    # Limit to most relevant
    compiled_state['entities'] = relevant_nodes[:10]
    
    # Find relationships between these entities
    for i, entity1 in enumerate(compiled_state['entities'][:5]):
        for entity2 in compiled_state['entities'][i+1:]:
            if graph.has_edge(entity1['id'], entity2['id']):
                edge_data = graph.get_edge_data(entity1['id'], entity2['id'])
                compiled_state['relationships'].append({
                    'from': entity1['label'],
                    'to': entity2['label'],
                    'relationship': edge_data.get('description', 'connected to')
                })
    
    return compiled_state

async def generate_reasoning_question(llm: ArgoBridgeLLM, idea: dict, compiled_state: dict):
    """Generate a high-quality reasoning question based on compiled state."""
    
    # Format compiled state
    state_text = f"Biological Focus: {compiled_state['biological_focus']}\n\n"
    
    state_text += "Relevant Entities:\n"
    for entity in compiled_state['entities'][:8]:
        state_text += f"- {entity['label']} (Type: {entity['type']}): {entity['description'][:150]}\n"
    
    state_text += "\nRelationships:\n"
    for rel in compiled_state['relationships'][:10]:
        state_text += f"- {rel['from']} → {rel['to']}: {rel['relationship'][:100]}\n"
    
    prompt = f"""You are creating a challenging biological reasoning question based on compiled knowledge.

REASONING TYPE: {idea['reasoning_type']}
BIOLOGICAL FOCUS: {idea['biological_focus']}

COMPILED KNOWLEDGE FROM GRAPH:
{state_text}

Create ONE challenging reasoning question that:
1. Is SELF-CONTAINED (embeds all necessary facts - no references to "the text", "the study", etc.)
2. Requires biological/scientific reasoning, not just recall
3. Tests understanding of {idea['reasoning_type']} reasoning
4. Has a specific, easily gradable, non-guessable answer based on the compiled knowledge
5. Can be answered in 1-2 words, a specific number with units, or as a fill in the blank.
6. DO NOT use easily guessable questions such as yes/no or true/false questions.

CRITICAL REQUIREMENTS:
- NO references to external materials ("the text", "the paper", "the study", "as mentioned")
- Question must stand alone as a scientific reasoning problem
- Answer must be derivable from the embedded facts
- Question should require thoughtful analysis, not just lookup
- Focus on biological mechanisms, causality, or synthesis

Example format (for a different topic):
"In bacterial antibiotic resistance, efflux pumps actively transport antibiotics out of the cell, 
reducing intracellular concentration by 80%. If a strain has both an efflux pump and a membrane 
permeability mutation that reduces antibiotic entry by 50%, and the minimum inhibitory 
concentration (MIC) of the antibiotic is normally 2 μg/mL, what is the effective MIC for this 
resistant strain?"

Output ONLY:
- One QUESTION line with all facts embedded
- One ANSWER line with brief unambigious answer in as few words as possible

No additional text."""

    response = await llm.call_async(prompt)
    return response.strip()

async def filter_question_quality(llm: ArgoBridgeLLM, question: str, compiled_state: dict):
    """Filter question quality using LLM judge."""
    
    filter_prompt = f"""Evaluate the following question on a scale from 1-10, where 10 is perfect.

QUESTION:
{question}

BIOLOGICAL CONTEXT:
Focus: {compiled_state['biological_focus']}

Rate based on these criteria:
- Clarity: Is the question clear and unambiguous?
- Scientific Accuracy: Does the question make biological/scientific sense?
- Self-contained: CRITICAL - Does the question stand alone without ANY references to external materials?
- Reasoning Depth: Does it require thoughtful analysis rather than simple recall?
- Biological Relevance: Is it about biology/science, not just graph structure?
- Answer Quality: Is the answer specific and non-trivial?
- Unambiguous: Is the answer objective, discrete, and not open to interpretation?

AUTOMATIC DISQUALIFIERS (score must be 1-3 if ANY are present):
- References to 'the text', 'the passage', 'the document', 'the paper', 'the study'
- References to 'the author', 'according to', 'as mentioned', 'as described'
- References to 'Appendix', 'Figure', 'Table', 'Section', 'Chapter'
- References to 'above', 'below', 'previously mentioned', 'following'
- Answer is "unknown" or similarly meaningless
- Question is just about counting nodes/edges/connections
- Question lacks biological/scientific content

Provide your response in this format:
SCORE: <numeric score between 1-10>
CRITIQUE: <brief explanation of score>"""

    response = await llm.call_async(filter_prompt)
    
    # Parse score
    try:
        score_line = [line for line in response.split('\n') if 'SCORE:' in line][0]
        score = int(score_line.split('SCORE:')[1].strip().split()[0])
        critique_line = [line for line in response.split('\n') if 'CRITIQUE:' in line][0]
        critique = critique_line.split('CRITIQUE:')[1].strip()
        return {'score': score, 'critique': critique, 'passed': score >= 7}
    except:
        print(f"Warning: Could not parse filter response: {response}")
        return {'score': 0, 'critique': 'Parse error', 'passed': False}

async def extract_answer_letter(llm: ArgoBridgeLLM, question: str):
    """Extract which option letter is correct."""
    
    # First, ask LLM to identify the correct answer from the question context
    prompt = f"""Given this question, identify the correct answer based on the reasoning embedded in the question.

{question}

Output ONLY the correct answer.

FINAL_ANSWER:"""

    response = await llm.call_async(prompt)
    answer = response.strip().replace('FINAL_ANSWER:', '').strip()
    
    return answer.strip()

async def main(args):
    """Main function to generate reasoning question-answer pairs."""
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
    
    # Initialize diversity tracking
    ideas = []
    used_topics = []  # Track recent topics
    topic_keywords = set()  # Keywords to exclude from sampling
    refresh_interval = 20  # Refresh ideas every N questions
    
    # Phase 3: For each idea, compile state and generate question
    print(f"\nGenerating {args.num_questions} high-quality reasoning questions with diversity...")
    generated_qa_pairs = []
    attempts = 0
    max_attempts = args.num_questions * 3  # Try up to 3x to get enough good questions
    
    while len(generated_qa_pairs) < args.num_questions and attempts < max_attempts:
        attempts += 1
        
        # Refresh ideas periodically or on first run
        if len(generated_qa_pairs) % refresh_interval == 0 and (len(generated_qa_pairs) > 0 or attempts == 1):
            print(f"\n{'='*60}")
            print(f"  🔄 Refreshing exploration ideas (completed: {len(generated_qa_pairs)}/{args.num_questions})")
            if topic_keywords:
                print(f"  📌 Excluding recent topics: {', '.join(list(topic_keywords)[:5])}...")
            print(f"{'='*60}")
            
            # Sample diverse contexts, excluding recent topics
            graph_samples = await sample_graph_context(
                graph, 
                num_samples=10,
                exclude_topics=topic_keywords
            )
            print(f"  Sampled {len(graph_samples)} diverse graph contexts.")
            
            # Get new exploration ideas
            new_ideas = await get_exploration_ideas(llm, graph_samples)
            
            # Replace ideas (force freshness) instead of extending
            ideas = new_ideas if new_ideas else ideas
            
            print(f"  Generated {len(ideas)} new reasoning question ideas:")
            for i, idea in enumerate(ideas[:5], 1):  # Show first 5
                print(f"    {i}. [{idea.get('reasoning_type', 'N/A')}] {idea.get('biological_focus', 'N/A')}")
            if len(ideas) > 5:
                print(f"    ... and {len(ideas) - 5} more")
            
            if not ideas:
                print("  ⚠️  No exploration ideas generated. Using any available nodes.")
        
        if not ideas:
            print(f"  ⚠️  No ideas available at attempt {attempts}. Skipping...")
            continue
        
        # Select a random idea
        idea = random.choice(ideas)
        
        print(f"\n  Attempt {attempts}/{max_attempts} - Trying: {idea.get('biological_focus', 'N/A')[:60]}...")
        
        try:
            # Compile state from graph
            print("    - Compiling state from graph...")
            compiled_state = await compile_state_for_idea(graph, llm, idea)
            
            if len(compiled_state['entities']) < 3:
                print("    - Not enough relevant entities found, skipping...")
                continue
            
            # Generate question
            print("    - Generating reasoning question...")
            question = await generate_reasoning_question(llm, idea, compiled_state)
            
            # Filter for quality
            print("    - Filtering for quality...")
            quality = await filter_question_quality(llm, question, compiled_state)
            
            print(f"    - Quality score: {quality['score']}/10")
            print(f"    - Critique: {quality['critique']}")
            
            if quality['passed']:
                # Extract answer
                answer = await extract_answer_letter(llm, question)
                
                qa_pair = {
                    'question': question,
                    'answer': answer,
                    'reasoning_type': idea.get('reasoning_type', 'N/A'),
                    'biological_focus': idea.get('biological_focus', 'N/A'),
                    'quality_score': quality['score']
                }
                generated_qa_pairs.append(qa_pair)
                print(f"    ✅ Accepted! ({len(generated_qa_pairs)}/{args.num_questions} complete)")
                
                # Track this topic for diversity
                bio_focus = idea.get('biological_focus', '')
                used_topics.append(bio_focus)
                
                # Keep only last 20 topics for exclusion
                if len(used_topics) > 20:
                    used_topics = used_topics[-20:]
                
                # Extract keywords from recent topics (words > 4 chars)
                topic_keywords = set()
                for topic in used_topics:
                    words = topic.lower().split()
                    keywords = [w for w in words if len(w) > 4 and w not in ['about', 'between', 'among', 'within', 'through']]
                    topic_keywords.update(keywords[:3])  # Take top 3 keywords per topic
                
            else:
                print(f"    ❌ Rejected (score {quality['score']} < 7)")
        
        except Exception as e:
            print(f"    - Error: {e}")
            continue
    
    print(f"\n{'='*60}")
    print(f"Generated {len(generated_qa_pairs)} high-quality reasoning QA pairs")
    print(f"{'='*60}")
    
    # Load existing QA pairs if file exists, then append new ones
    existing_pairs = []
    if os.path.exists(args.output_file):
        print(f"\nLoading existing QA pairs from {args.output_file}...")
        try:
            with open(args.output_file, "r") as f:
                existing_pairs = json.load(f)
            print(f"Found {len(existing_pairs)} existing QA pairs.")
        except (json.JSONDecodeError, FileNotFoundError):
            print("No valid existing QA pairs found, starting fresh.")
            existing_pairs = []
    else:
        print(f"\nNo existing file found at {args.output_file}, creating new file.")
    
    # Combine existing and new pairs
    all_pairs = existing_pairs + generated_qa_pairs
    print(f"Combining {len(existing_pairs)} existing + {len(generated_qa_pairs)} new = {len(all_pairs)} total pairs.")
    
    # Save the combined pairs to a file
    print(f"Saving combined QA pairs to {args.output_file}...")
    
    # Validate output path - ensure it's within expected directory structure
    output_dir = os.path.dirname(args.output_file)
    if not os.path.exists(output_dir):
        print(f"ERROR: Output directory does not exist: {output_dir}")
        print(f"ERROR: This suggests a path construction bug. Output file: {args.output_file}")
        sys.exit(1)
    
    with open(args.output_file, "w") as f:
        json.dump(all_pairs, f, indent=2)
    
    print(f"\nSuccessfully generated and saved {len(generated_qa_pairs)} new QA pairs to {args.output_file}.")
    print(f"Total QA pairs in file: {len(all_pairs)}")
    print("\nReasoning QA generation complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate short-answer reasoning questions from a knowledge graph using LLM-guided exploration.")
    parser.add_argument("--working-dir", type=str, required=True, help="Path to the working directory containing the graph.")
    parser.add_argument("--output-file", type=str, default="short_answer_qa.json", help="Path to save the generated QA pairs.")
    parser.add_argument("--num-questions", type=int, default=10, help="Number of short-answer questions to generate.")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))

