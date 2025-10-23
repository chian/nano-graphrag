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
    
    if not nodes_list:
        return samples
    
    # Dynamically detect available fields from the first few nodes
    sample_nodes = nodes_list[:min(10, len(nodes_list))]
    available_fields = set()
    for node in sample_nodes:
        available_fields.update(graph.nodes[node].keys())
    
    # Find the best field to use as a label (prefer common label-like fields)
    label_field = None
    for preferred in ['label', 'name', 'title', 'id', 'text']:
        if preferred in available_fields:
            label_field = preferred
            break
    
    # If no preferred field found, use the first available field
    if not label_field and available_fields:
        label_field = list(available_fields)[0]
    
    # Find description field (prefer common description-like fields)
    desc_field = None
    for preferred in ['description', 'text', 'content', 'summary']:
        if preferred in available_fields:
            desc_field = preferred
            break
    
    # Find type field
    type_field = None
    for preferred in ['type', 'category', 'class', 'kind']:
        if preferred in available_fields:
            type_field = preferred
            break
    
    # Track what we've sampled to ensure diversity
    sampled_labels = set()
    attempts = 0
    max_attempts = num_samples * 20  # Try up to 20x to get diverse samples
    
    while len(samples) < num_samples and attempts < max_attempts:
        attempts += 1
        
        # Pick a random starting node
        start_node = random.choice(nodes_list)
        start_data = graph.nodes[start_node]
        
        # Create clean label using the helper function
        clean_label = create_clean_entity_label(start_data, label_field, desc_field)
        
        # Skip if label is already sampled
        if clean_label in sampled_labels:
            continue
        
        # Skip if this label contains excluded topic keywords
        if exclude_topics:
            label_lower = clean_label.lower()
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
        
        # Build sample with available fields
        center_node = {'label': clean_label}
        if type_field:
            center_node['type'] = start_data.get(type_field, 'N/A')
        if desc_field:
            desc = start_data.get(desc_field, 'N/A')
            center_node['description'] = str(desc)[:200] if desc else 'N/A'
        
        sample = {
            'center_node': center_node,
            'neighbors': [
                {
                    'label': nd.get(label_field, 'unknown') if label_field else 'unknown',
                    'type': nd.get(type_field, 'N/A') if type_field else 'N/A',
                    'description': str(nd.get(desc_field, 'N/A'))[:100] if desc_field and nd.get(desc_field) else 'N/A'
                }
                for nd in neighbor_data
            ],
            'relationships': [
                str(ed.get('description', 'connected to'))[:100] if ed.get('description') else 'connected to'
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
        
        # Build sample with available fields
        center_node = {'label': start_data.get(label_field, 'unknown') if label_field else 'unknown'}
        if type_field:
            center_node['type'] = start_data.get(type_field, 'N/A')
        if desc_field:
            desc = start_data.get(desc_field, 'N/A')
            center_node['description'] = str(desc)[:200] if desc else 'N/A'
        
        sample = {
            'center_node': center_node,
            'neighbors': [
                {
                    'label': nd.get(label_field, 'unknown') if label_field else 'unknown',
                    'type': nd.get(type_field, 'N/A') if type_field else 'N/A',
                    'description': str(nd.get(desc_field, 'N/A'))[:100] if desc_field and nd.get(desc_field) else 'N/A'
                }
                for nd in neighbor_data
            ],
            'relationships': [
                str(ed.get('description', 'connected to'))[:100] if ed.get('description') else 'connected to'
                for ed in edges
            ]
        }
        samples.append(sample)
    
    return samples

async def get_exploration_ideas(llm: ArgoBridgeLLM, graph_samples: list):
    """Ask LLM to suggest interesting reasoning questions based on graph samples."""
    
    # Format samples for prompt
    samples_text = ""
    for i, sample in enumerate(graph_samples, 1):
        samples_text += f"\nSample {i}:\n"
        center = sample['center_node']
        type_info = f" (Type: {center.get('type', 'N/A')})" if 'type' in center else ""
        samples_text += f"  Center: {center['label']}{type_info}\n"
        if 'description' in center:
            samples_text += f"  Description: {center['description']}\n"
        samples_text += f"  Connected to:\n"
        for j, neighbor in enumerate(sample['neighbors']):
            rel = sample['relationships'][j] if j < len(sample['relationships']) else 'connected to'
            neighbor_type = f" (Type: {neighbor.get('type', 'N/A')})" if 'type' in neighbor else ""
            samples_text += f"    - {neighbor['label']}{neighbor_type}: {rel}\n"
    
    prompt = f"""You are analyzing a scientific knowledge graph to identify interesting reasoning questions. 

Here are some random samples from the graph:
{samples_text}

Based on these samples, suggest 3-5 interesting reasoning questions that could be asked about this knowledge graph. 

For each question idea, specify:
1. REASONING_TYPE: What kind of reasoning is required? (causal, comparative, mechanistic, temporal, quantitative, synthesis)
2. BIOLOGICAL_FOCUS: What biological/scientific concept is central?
3. QUERY_STRATEGY: What graph patterns or entities should we search for to compile the answer?
4. EXAMPLE_QUESTION: A sample question (without the answer - we'll compile that from the graph)

Focus on questions that require:
- Biological/scientific reasoning (not just graph structure)
- Synthesis of multiple facts
- Understanding of mechanisms or relationships
- Free-hand logic and thoughtfulness

Avoid:
- Simple lookups or definitions
- Degree counting or graph metrics
- Questions with "unknown" as the answer
- Generic structural questions

Output format (JSON):
{{
  "ideas": [
    {{
      "reasoning_type": "causal",
      "biological_focus": "antibiotic resistance mechanisms",
      "query_strategy": "Find compounds that affect bacterial strains, analyze mechanism relationships",
      "example_question": "If compound X disrupts bacterial cell walls and compound Y inhibits protein synthesis, what happens when they're combined against a strain with both membrane permeability and efflux pump mechanisms?"
    }}
  ]
}}

Be creative and scientifically rigorous. The questions should make researchers think deeply about the biology."""

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

def create_clean_entity_label(node_data: dict, label_field: str, desc_field: str) -> str:
    """Create a clean, readable entity label from node data."""
    # Try to get a clean label from the available fields
    label = node_data.get(label_field, '')
    description = node_data.get(desc_field, '') if desc_field else ''
    
    # If label is a complex chunk ID, try to extract meaningful content
    if label and not label.startswith('chunk-'):
        return str(label)[:100]  # Truncate long labels
    
    # If we have a description, use the first meaningful part
    if description:
        desc_str = str(description)
        # Remove chunk IDs and separators
        desc_clean = desc_str.replace('<SEP>', ' ').replace('chunk-', '')
        # Take first sentence or 100 chars
        first_sentence = desc_clean.split('.')[0]
        if len(first_sentence) > 20:
            return first_sentence[:100]
        elif len(desc_clean) > 20:
            return desc_clean[:100]
    
    # Fallback: create a simple label from available text
    for field in ['text', 'content', 'summary', 'name', 'title']:
        if field in node_data and node_data[field]:
            text = str(node_data[field])
            if len(text) > 10 and not text.startswith('chunk-'):
                return text[:100]
    
    # Last resort: use a shortened version of the node ID
    return f"Entity-{str(label)[:20]}" if label else "Unknown Entity"

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
    
    # Dynamically detect available fields from the first few nodes
    nodes_list = list(graph.nodes())
    if not nodes_list:
        return compiled_state
    
    sample_nodes = nodes_list[:min(10, len(nodes_list))]
    available_fields = set()
    for node in sample_nodes:
        available_fields.update(graph.nodes[node].keys())
    
    # Find the best field to use as a label
    label_field = None
    for preferred in ['label', 'name', 'title', 'id', 'text']:
        if preferred in available_fields:
            label_field = preferred
            break
    if not label_field and available_fields:
        label_field = list(available_fields)[0]
    
    # Find description field
    desc_field = None
    for preferred in ['description', 'text', 'content', 'summary']:
        if preferred in available_fields:
            desc_field = preferred
            break
    
    # Find type field
    type_field = None
    for preferred in ['type', 'category', 'class', 'kind']:
        if preferred in available_fields:
            type_field = preferred
            break
    
    # Search for relevant nodes based on biological focus
    relevant_nodes = []
    focus_keywords = biological_focus.lower().split()
    
    for node_id in graph.nodes():
        node_data = graph.nodes[node_id]
        
        # Get text content from available fields
        text_content = ""
        if label_field:
            text_content += " " + str(node_data.get(label_field, '')).lower()
        if desc_field:
            text_content += " " + str(node_data.get(desc_field, '')).lower()
        
        # Check if node is relevant to biological focus
        if any(keyword in text_content for keyword in focus_keywords):
            # Create a clean, readable label
            clean_label = create_clean_entity_label(node_data, label_field, desc_field)
            
            entity = {
                'id': node_id,
                'label': clean_label
            }
            if type_field:
                entity['type'] = node_data.get(type_field, 'N/A')
            if desc_field:
                entity['description'] = node_data.get(desc_field, 'N/A')
            
            relevant_nodes.append(entity)
    
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
        type_info = f" (Type: {entity.get('type', 'N/A')})" if 'type' in entity else ""
        desc_info = f": {entity.get('description', 'N/A')[:150]}" if 'description' in entity else ""
        state_text += f"- {entity['label']}{type_info}{desc_info}\n"
    
    state_text += "\nRelationships:\n"
    for rel in compiled_state['relationships'][:10]:
        state_text += f"- {rel['from']} → {rel['to']}: {rel['relationship'][:100]}\n"
    
    prompt = f"""You are creating a challenging biological reasoning question based on compiled knowledge.

REASONING TYPE: {idea['reasoning_type']}
BIOLOGICAL FOCUS: {idea['biological_focus']}

COMPILED KNOWLEDGE FROM GRAPH:
{state_text}

Create ONE challenging reasoning question that:
1. Is SELF-CONTAINED (no references to external materials; embed all facts and quantities needed).
2. Requires biological/scientific reasoning, not just recall, and uses ≥3 reasoning steps.
3. Uses at least 3 concrete facts from COMPILED KNOWLEDGE (entities and relationships explicitly named).
4. Includes ≥1 quantitative element (e.g., MIC, fold-change, %, concentration, timepoint) participating in the reasoning.
5. Provides exactly 8 options (A–H) with exactly one correct answer; 7 distractors must be biologically plausible but wrong for a clear reason.
6. Stays strictly within the BIOLOGICAL FOCUS and uses only entities/types mentioned in COMPILED KNOWLEDGE (normalize labels for readability if needed).

CRITICAL REQUIREMENTS:
- Forbidden phrases: "the text", "the paper", "the study", "as mentioned", "Figure", "Table", "Section".
- The question must stand alone as a scientific reasoning problem.
- The correct answer must be derivable only by chaining the embedded facts (not guessable from general knowledge).
- Focus on biological mechanisms, causality, temporal dynamics, or synthesis; avoid trivia.

Example format (for a different topic):
"In bacterial antibiotic resistance, efflux pumps actively transport antibiotics out of the cell, 
reducing intracellular concentration by 80%. If a strain has both an efflux pump and a membrane 
permeability mutation that reduces antibiotic entry by 50%, and the minimum inhibitory 
concentration (MIC) of the antibiotic is normally 2 μg/mL, what is the effective MIC for this 
resistant strain?"

Output ONLY:
- One QUESTION line with all facts and quantitative details embedded
- Eight OPTIONS labeled A) through H)

No additional text."""

    response = await llm.call_async(prompt)
    return response.strip()

async def filter_question_quality(llm: ArgoBridgeLLM, question: str, compiled_state: dict):
    # Hard disqualifiers preserved from the older judge to avoid weak/self-referential questions
    lower_q = question.lower()
    auto_disqualifiers = [
        "the text", "the passage", "the document", "the paper", "the study",
        "according to", "as mentioned", "as described",
        "appendix", "figure", "table", "section", "chapter",
        "above", "below", "previously mentioned", "following",
        "unknown answer", "answer is unknown"
    ]
    if any(p in lower_q for p in auto_disqualifiers):
        return {"score": 0.0, "critique": "auto-disqualified (external reference/unknown)", "passed": False}

    filter_prompt = f"""Evaluate the text below according to the scoring instruction and criteria. If the scores are high on each axis, derive an exam question following the instructions.

## Scoring Instruction
1. Evaluate the text on each criteria step by step. Provide your honest answer to each sub-question. If the answer to a sub-question is a confident Yes, add or subtract the points corresponding to the criteria.
2. Keep track of the running points from each criteria to get the total score.
3. Summarize your final evaluation results in a valid JSON object following the instruction below.

### Scoring Criteria
Criteria 1: Problem Completeness
- The content does not have clear main question, or enough clues to derive the correct answer. (0 point)
- The content includes a main question, and enough clues to derive the correct answer. (+1 point)
- The text shows evidence of engagement and discussion among multiple authors, including proposing answers, evaluating and reflecting on answers, responding to critiques, revising and editing answers. (+1 point)

Criteria 2: Problem Complexity and Technical Depth
- The difficulty of the content is college-level or below. (0 point)
- The difficulty of the content is graduate-level or above, and only domain experts can understand. (+1 point)
- The question being discussed is so challenging that even highly skilled non-experts would not be able to fully understand the question or provide a correct answer, even after spending 30 minutes searching the internet or reading up literature. (+1 point)

Criteria 3: Technical Correctness and Accuracy
- The text contains significant technical errors or inaccuracies. (-1 point)
- The text demonstrates some technical correctness, but with notable flaws or omissions. (0 point)
- The text demonstrates technical correctness, with some minor flaws or omissions. (+0.5 point)
- The text demonstrates high technical correctness, with clear and accurate explanations. (+0.5 point)
- The text exemplifies exceptional technical correctness, with rigorous and precise explanations. (+1 point)

Criteria 4: Thinking and Reasoning
- The text lacks any evidence of thinking or reasoning. (-1 point)
- The text demonstrates some basic thinking and reasoning (+0.5 point).
- The text demonstrates some thinking and reasoning (+0.5 point), considering multiple approaches or trade-offs.
- The text demonstrates significant thinking and reasoning (+1 point), such as multi-step chains or advanced patterns.
- The text exemplifies exceptional thinking and reasoning (+1 point), combining multiple techniques with novel abstraction.

## Instruction on Exam Question and Final Report
Follow the reporting format from the criteria prompt. Penalize any reference to external materials (e.g., 'the text', 'the paper', 'as mentioned', 'Figure', 'Table', 'Section'). Reward clarity, biological relevance, self-containment, and answer specificity.
At the end, output ONLY a JSON object with these fields:
### Biological Context
Focus: {compiled_state['biological_focus']}

### Text
{question}
"""

    response = await llm.call_async(filter_prompt)

    # Parse JSON block and compute raw total score
    try:
        json_str = None
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "{" in response and "}" in response:
            start = response.find("{")
            end = response.rfind("}")
            json_str = response[start:end+1]
        else:
            json_str = response.strip()

        obj = json.loads(json_str)

        # Initialize subscores
        completeness = 0.0
        depth = 0.0
        correctness = 0.0
        reasoning = 0.0
        total_raw = 0.0

        # Case 1: scores list schema
        scores_list = obj.get("scores", [])
        used_scores_list = False

        def pick_score(match_substring: str) -> float:
            for entry in scores_list:
                # Case A: entry is like {"criteria": "Problem Completeness", "score": 1}
                label = str(entry.get("criteria") or entry.get("criterion") or entry.get("name") or entry.get("label") or "").lower()
                if label:
                    if match_substring in label:
                        try:
                            return float(entry.get("score", 0))
                        except (TypeError, ValueError):
                            return 0.0
                # Case B: entry is like {"Problem Completeness": 2}
                if not label and isinstance(entry, dict) and len(entry) == 1:
                    k, v = next(iter(entry.items()))
                    if match_substring in str(k).lower():
                        try:
                            return float(v)
                        except (TypeError, ValueError):
                            return 0.0
            return 0.0

        if scores_list:
            used_scores_list = True
            completeness = pick_score("complete")
            depth = pick_score("complex") or pick_score("depth")
            correctness = pick_score("correct") or pick_score("accuracy")
            reasoning = pick_score("reason")
            for entry in scores_list:
                # Sum any explicit numeric score field
                if isinstance(entry, dict):
                    if "score" in entry:
                        try:
                            total_raw += float(entry.get("score", 0))
                            continue
                        except (TypeError, ValueError):
                            pass
                    # Or sum single-key shorthand like {"Problem Completeness": 2}
                    if len(entry) == 1:
                        _, v = next(iter(entry.items()))
                        try:
                            total_raw += float(v)
                            continue
                        except (TypeError, ValueError):
                            pass

        # Case 2: nested Evaluation object with Points
        if not used_scores_list and isinstance(obj.get("Evaluation"), dict):
            ev = obj["Evaluation"]
            def get_points(container: dict, key: str) -> float:
                try:
                    item = container.get(key, {})
                    if isinstance(item, dict) and "Points" in item:
                        return float(item.get("Points", 0) or 0)
                    # Sometimes numeric directly
                    if isinstance(item, (int, float)):
                        return float(item)
                    return 0.0
                except Exception:
                    return 0.0
            completeness = get_points(ev, "Problem Completeness")
            depth = get_points(ev, "Problem Complexity and Technical Depth")
            correctness = get_points(ev, "Technical Correctness and Accuracy")
            reasoning = get_points(ev, "Thinking and Reasoning")
            # Prefer explicit Total Score if present
            try:
                total_raw = float(ev.get("Total Score", 0) or 0)
            except Exception:
                total_raw = completeness + depth + correctness + reasoning

        # Case 3: flat top-level numeric fields
        if not used_scores_list and total_raw == 0.0:
            def get_top(name: str) -> float:
                try:
                    return float(obj.get(name, 0) or 0)
                except Exception:
                    return 0.0
            # Only override if present
            c = get_top("Problem Completeness")
            d = get_top("Problem Complexity and Technical Depth")
            k = get_top("Technical Correctness and Accuracy")
            r = get_top("Thinking and Reasoning")
            if any([c, d, k, r]):
                completeness = c
                depth = d
                correctness = k
                reasoning = r
                ts = get_top("Total Score")
                total_raw = ts if ts > 0 else (completeness + depth + correctness + reasoning)

        # Use raw total score directly (no normalization)
        score_value = float(total_raw)
        difficulty = obj.get("question_difficulty", "")
        parts = []
        if difficulty:
            parts.append(f"difficulty={difficulty}")
        parts.append(f"completeness={completeness}")
        parts.append(f"depth={depth}")
        parts.append(f"correctness={correctness}")
        parts.append(f"reasoning={reasoning}")
        critique = ", ".join(parts)

        # Accept if raw total score is at least 4 (inclusive)
        passed = total_raw >= 4
        return {"score": score_value, "critique": critique, "passed": passed}
    except Exception:
        print(f"Warning: Could not parse filter response: {response}")
        return {"score": 0, "critique": "Parse error", "passed": False}

async def extract_answer_letter(llm: ArgoBridgeLLM, question: str):
    """Extract which option letter is correct."""
    
    # First, ask LLM to identify the correct answer from the question context
    prompt = f"""Given this question, identify which option letter (A-H) is correct based on the reasoning embedded in the question.

{question}

Output ONLY the single letter (A, B, C, D, E, F, G, or H) that corresponds to the correct answer.

FINAL_ANSWER:"""

    response = await llm.call_async(prompt)
    answer = response.strip().replace('FINAL_ANSWER:', '').strip()
    
    # Extract just the letter
    if len(answer) > 1:
        for char in answer:
            if char in "ABCDEFGH":
                answer = char
                break
    
    return answer if answer in "ABCDEFGH" else "A"

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
    refresh_interval = 1  # Refresh ideas every N questions
    
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
        
        # Get paper name from the parent directory of working_dir (since working_dir ends with /source_files)
        paper_name = os.path.basename(os.path.dirname(args.working_dir))
        print(f"\n  Attempt {attempts}/{max_attempts} - Paper: {paper_name} - Trying: {idea.get('biological_focus', 'N/A')[:60]}...")
        
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
            
            print(f"    - Quality score: {quality['score']}/7")
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
                print(f"    ❌ Rejected (score {quality['score']} < 4)")
        
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
    
    # Check if we already have enough questions
    if len(existing_pairs) >= args.num_questions:
        print(f"✅ Already have {len(existing_pairs)} questions (requested: {args.num_questions}). Skipping generation.")
        return
    
    # Combine existing and new pairs
    all_pairs = existing_pairs + generated_qa_pairs
    print(f"Combining {len(existing_pairs)} existing + {len(generated_qa_pairs)} new = {len(all_pairs)} total pairs.")
    
    # Save the combined pairs to a file
    print(f"Saving combined QA pairs to {args.output_file}...")
    
    # Validate output path - check for double BASE_DIR bug
    if "//" in args.output_file and args.output_file.count("/Users/chia/Documents/ANL/BioData/cognee/nano-graphrag") > 1:
        print(f"ERROR: Detected double BASE_DIR in output path: {args.output_file}")
        print(f"ERROR: This is a path construction bug in the batch script.")
        sys.exit(1)
    
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
    parser = argparse.ArgumentParser(description="Generate biological reasoning question-answer pairs from a knowledge graph using LLM-guided exploration.")
    parser.add_argument("--working-dir", type=str, required=True, help="Path to the working directory containing the graph.")
    parser.add_argument("--output-file", type=str, default="reasoning_qa.json", help="Path to save the generated QA pairs.")
    parser.add_argument("--num-questions", type=int, default=10, help="Number of reasoning questions to generate.")
    
    args = parser.parse_args()
    
    asyncio.run(main(args))

