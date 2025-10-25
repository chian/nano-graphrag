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
                    'label': create_clean_entity_label(nd, label_field, desc_field),
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
        sampled_labels.add(clean_label)
    
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
        clean_label = create_clean_entity_label(start_data, label_field, desc_field)
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
                    'label': create_clean_entity_label(nd, label_field, desc_field),
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
    # Try to get meaningful content from description field first
    if desc_field and desc_field in node_data and node_data[desc_field]:
        desc_str = str(node_data[desc_field])
        # Remove chunk IDs and separators
        desc_clean = desc_str.replace('<SEP>', ' ').replace('chunk-', '')
        # Take first sentence or 100 chars
        first_sentence = desc_clean.split('.')[0]
        if len(first_sentence) > 20:
            return first_sentence[:100]
        elif len(desc_clean) > 20:
            return desc_clean[:100]
    
    # Try other text fields
    for field in ['text', 'content', 'summary', 'name', 'title']:
        if field in node_data and node_data[field]:
            text = str(node_data[field])
            if len(text) > 10 and not text.startswith('chunk-'):
                return text[:100]
    
    # If label field has meaningful content (not chunk ID)
    if label_field and label_field in node_data and node_data[label_field]:
        label = str(node_data[label_field])
        if not label.startswith('chunk-') and len(label) > 5:
            return label[:100]
    
    # Use any available text content
    for key, value in node_data.items():
        if isinstance(value, str) and len(value) > 10 and not value.startswith('chunk-'):
            return value[:100]
    
    # If all else fails, return a generic label
    return "Entity"

async def compile_state_for_idea(graph: nx.Graph, llm: ArgoBridgeLLM, idea: dict, graph_samples: list = None):
    """Use GASL to compile relevant information from the graph based on the idea."""
    
    biological_focus = idea.get('biological_focus', '')
    query_strategy = idea.get('query_strategy', '')
    
    print(f"🔍 GASL State Compilation for: {biological_focus}")
    print(f"📋 Query Strategy: {query_strategy}")
    
    # Step 1: Use GASL to explore the graph and find relevant data
    # Create a general exploration query based on the biological focus
    exploration_query = f"Explore the knowledge graph to find information related to {biological_focus}. Look for entities, relationships, and patterns that could be relevant for generating reasoning questions."
    print(f"🔍 Exploration Query: {exploration_query[:200]}...")
    
    # Step 2: Use GASL to explore the graph
    gasl_result = await solve_question_with_gasl(graph, llm, exploration_query)
    print(f"🧠 GASL Result: {gasl_result.get('query_answered', False)}")
    
    # Step 3: Extract entities and relationships from GASL result
    compiled_state = extract_state_from_gasl_result(gasl_result, idea)
    print(f"📊 Extracted State: {len(compiled_state['entities'])} entities, {len(compiled_state['relationships'])} relationships")
    
    if not compiled_state['entities'] and not compiled_state['relationships']:
        print("    - Not enough relevant entities found, skipping...")
        return None
    
    return compiled_state

async def generate_initial_question_from_idea(llm: ArgoBridgeLLM, idea: dict, graph_samples: list = None):
    """Generate a GASL query question based on the idea and actual graph content."""
    
    reasoning_type = idea.get('reasoning_type', '')
    biological_focus = idea.get('biological_focus', '')
    example_question = idea.get('example_question', '')
    
    # Include graph context if available
    graph_context = ""
    if graph_samples:
        graph_context = "\n\nACTUAL GRAPH CONTENT:\n"
        for i, sample in enumerate(graph_samples[:3], 1):  # Show first 3 samples
            center = sample['center_node']
            graph_context += f"Sample {i}: {center.get('label', 'N/A')} ({center.get('type', 'N/A')})\n"
            if 'description' in center:
                graph_context += f"  Description: {center['description'][:150]}...\n"
            if sample.get('neighbors'):
                graph_context += f"  Connected to: {', '.join([n.get('label', 'N/A') for n in sample['neighbors'][:3]])}\n"
        graph_context += "\n"
    
    prompt = f"""Based on this reasoning idea and the actual graph content, create a specific question that can be used to explore this knowledge graph:

REASONING TYPE: {reasoning_type}
BIOLOGICAL FOCUS: {biological_focus}
EXAMPLE QUESTION: {example_question}{graph_context}

Create a specific, answerable question that would guide exploration of THIS knowledge graph to find relevant entities and relationships. The question should be:
1. Specific and focused on the biological concept
2. Answerable by finding and analyzing the ACTUAL entities and relationships in this graph
3. Clear enough to guide systematic graph exploration
4. Based on the actual content shown above, not generic examples

IMPORTANT: The question must be answerable using the actual entities and relationships present in this specific graph. Do not ask about entities that don't exist in this graph.

Output ONLY the question, no additional text."""

    response = await llm.call_async(prompt)
    return response.strip()

async def solve_question_with_gasl(graph: nx.Graph, llm: ArgoBridgeLLM, question: str):
    """Use GASL to solve the question by exploring the graph."""
    
    from gasl.executor import GASLExecutor
    from gasl.adapters import NetworkXAdapter
    import tempfile
    import os
    
    # Create a fresh state file for this question
    state_file = tempfile.mktemp(suffix='.json', prefix='gasl_state_')
    
    # Create GASL adapter and executor with fresh state
    adapter = NetworkXAdapter(graph)
    executor = GASLExecutor(adapter, llm, state_file=state_file)
    
    print(f"🚀 Starting GASL hypothesis-driven traversal for: {question[:100]}...")
    print(f"🔄 Using fresh state file: {state_file}")
    
    try:
        # Run GASL hypothesis-driven traversal
        result = executor.run_hypothesis_driven_traversal(question, max_iterations=5)
        
        print(f"✅ GASL completed: {result.get('iterations', 0)} iterations, answered: {result.get('query_answered', False)}")
        
        return result
    finally:
        # Clean up the temporary state file
        if os.path.exists(state_file):
            os.remove(state_file)
            print(f"🧹 Cleaned up temporary state file: {state_file}")

def extract_state_from_gasl_result(gasl_result: dict, idea: dict):
    """Extract entities and relationships from GASL result into the expected format."""
    
    biological_focus = idea.get('biological_focus', '')
    
    compiled_state = {
        'biological_focus': biological_focus,
        'entities': [],
        'relationships': [],
        'mechanisms': []
    }
    
    # Debug: Print the GASL result structure
    print(f"🔍 DEBUG: GASL result keys: {list(gasl_result.keys())}")
    if 'final_state' in gasl_result:
        final_state = gasl_result.get('final_state', {})
        print(f"🔍 DEBUG: final_state keys: {list(final_state.keys())}")
        variables = final_state.get('variables', {})
        print(f"🔍 DEBUG: variables keys: {list(variables.keys())}")
    else:
        print(f"🔍 DEBUG: No final_state in GASL result")
        final_state = {}
        variables = {}
    
    # Look for LIST variables that contain entities
    for var_name, var_data in variables.items():
        print(f"🔍 DEBUG: Processing variable '{var_name}' with type: {type(var_data)}")
        if isinstance(var_data, dict):
            # Check if it's a LIST type
            if var_data.get('_meta', {}).get('type') == 'LIST':
                items = var_data.get('items', [])
                print(f"🔍 DEBUG: Found LIST with {len(items)} items")
                for item in items:
                    if isinstance(item, dict):
                        # Create entity from GASL result
                        entity = create_entity_from_gasl_item(item, var_name)
                        if entity:
                            compiled_state['entities'].append(entity)
            # Check if it has a 'value' field with a list (like resistance_related_nodes)
            elif isinstance(var_data.get('value'), list):
                items = var_data.get('value', [])
                print(f"🔍 DEBUG: Found variable with 'value' list containing {len(items)} items")
                for item in items:
                    if isinstance(item, dict):
                        # Create entity from GASL result
                        entity = create_entity_from_gasl_item(item, var_name)
                        if entity:
                            compiled_state['entities'].append(entity)
            # Also check if it's a direct list of items (like relevant_nodes)
            elif var_name == 'relevant_nodes' and isinstance(var_data.get('items'), list):
                items = var_data.get('items', [])
                print(f"🔍 DEBUG: Found relevant_nodes with {len(items)} items")
                for item in items:
                    if isinstance(item, dict):
                        # Create entity from GASL result
                        entity = create_entity_from_gasl_item(item, var_name)
                        if entity:
                            compiled_state['entities'].append(entity)
    
    # Create simple node IDs for LLM consumption
    node_id_mapping = {}
    for i, entity in enumerate(compiled_state['entities']):
        simple_id = f"node_{i+1}"
        node_id_mapping[entity['id']] = simple_id
        entity['simple_id'] = simple_id
    
    # Extract relationships from GASL results
    # Look for variables that might contain relationships or connections
    for var_name, var_data in variables.items():
        if isinstance(var_data, dict):
            # Check if this variable contains relationship information
            relationships = extract_relationships_from_gasl_variable(var_data, node_id_mapping)
            compiled_state['relationships'].extend(relationships)
    
    # If no relationships found, try to infer from entities
    if not compiled_state['relationships'] and len(compiled_state['entities']) > 1:
        compiled_state['relationships'] = infer_relationships_from_entities(compiled_state['entities'])
    
    return compiled_state

def create_entity_from_gasl_item(item: dict, source_var: str):
    """Create an entity from a GASL result item."""
    
    # Extract ID
    entity_id = item.get('id', f"gasl_{source_var}_{hash(str(item))}")
    
    # Create clean label
    label = create_clean_entity_label(item, 'name', 'description')
    
    entity = {
        'id': entity_id,
        'label': label,
        'source': 'gasl',
        'source_variable': source_var
    }
    
    # Add type if available
    if 'entity_type' in item:
        entity['type'] = item['entity_type']
    elif 'type' in item:
        entity['type'] = item['type']
    
    # Add description if available
    if 'description' in item:
        entity['description'] = item['description']
    elif 'text' in item:
        entity['description'] = item['text']
    
    return entity

def extract_relationships_from_gasl_variable(var_data: dict, node_id_mapping: dict):
    """Extract relationships from a GASL variable."""
    
    relationships = []
    
    # Look for relationship patterns in the variable data
    if 'items' in var_data:
        items = var_data['items']
        for item in items:
            if isinstance(item, dict):
                # Check if item represents a relationship
                if 'from' in item and 'to' in item:
                    from_id = item['from']
                    to_id = item['to']
                    relationship_desc = item.get('relationship', item.get('description', 'connected to'))
                    
                    # Map to simple IDs if available
                    from_simple = node_id_mapping.get(from_id, from_id)
                    to_simple = node_id_mapping.get(to_id, to_id)
                    
                    relationships.append({
                        'from': from_simple,
                        'to': to_simple,
                        'relationship': relationship_desc
                    })
    
    return relationships

def infer_relationships_from_entities(entities: list):
    """Infer relationships between entities based on their content."""
    
    relationships = []
    
    # Simple heuristic: if entities share keywords, they might be related
    for i, entity1 in enumerate(entities[:5]):  # Limit to avoid too many relationships
        for entity2 in entities[i+1:]:
            # Check if entities share biological keywords
            if share_biological_keywords(entity1, entity2):
                relationships.append({
                    'from': entity1.get('simple_id', f'node_{i+1}'),
                    'to': entity2.get('simple_id', f'node_{i+2}'),
                    'relationship': 'biologically related'
                })
    
    return relationships

def share_biological_keywords(entity1: dict, entity2: dict):
    """Check if two entities share biological keywords."""
    
    text1 = f"{entity1.get('label', '')} {entity1.get('description', '')}".lower()
    text2 = f"{entity2.get('label', '')} {entity2.get('description', '')}".lower()
    
    # Common biological keywords
    bio_keywords = [
        'bacteria', 'antibiotic', 'resistance', 'infection', 'therapy', 'treatment',
        'strain', 'pathogen', 'microbial', 'phage', 'drug', 'mechanism'
    ]
    
    for keyword in bio_keywords:
        if keyword in text1 and keyword in text2:
            return True
    
    return False

async def generate_reasoning_question(llm: ArgoBridgeLLM, idea: dict, compiled_state: dict):
    """Generate a high-quality reasoning question based on compiled state."""
    
    # Format compiled state
    state_text = f"Biological Focus: {compiled_state['biological_focus']}\n\n"
    
    state_text += "Relevant Entities:\n"
    for entity in compiled_state['entities'][:8]:
        simple_id = entity.get('simple_id', 'unknown')
        type_info = f" (Type: {entity.get('type', 'N/A')})" if 'type' in entity else ""
        desc_info = f": {entity.get('description', 'N/A')[:150]}" if 'description' in entity else ""
        state_text += f"- {simple_id}: {entity['label']}{type_info}{desc_info}\n"
    
    state_text += "\nRelationships:\n"
    for rel in compiled_state['relationships'][:10]:
        state_text += f"- {rel['from']} → {rel['to']}: {rel['relationship'][:100]}\n"
    
    prompt = f"""You are creating a challenging biological reasoning question based on compiled knowledge.

REASONING TYPE: {idea['reasoning_type']}
BIOLOGICAL FOCUS: {idea['biological_focus']}

COMPILED KNOWLEDGE FROM GRAPH:
{state_text}

Create ONE challenging reasoning question that:
1. Is SELF-CONTAINED (no references to external materials; embed all facts needed).
2. Requires biological/scientific reasoning, not just recall, and uses ≥3 reasoning steps.
3. Uses at least 3 concrete facts from COMPILED KNOWLEDGE (entities and relationships explicitly named).
4. Uses ONLY facts, relationships, and mechanisms explicitly stated in COMPILED KNOWLEDGE - do not invent or assume quantitative data.
5. Provides exactly 8 options (A–H) with exactly one correct answer; 7 distractors must be biologically plausible but wrong for a clear reason.
6. Stays strictly within the BIOLOGICAL FOCUS and uses only entities/types mentioned in COMPILED KNOWLEDGE.

CRITICAL REQUIREMENTS:
- Forbidden phrases: "the text", "the paper", "the study", "as mentioned", "Figure", "Table", "Section".
- The question must stand alone as a scientific reasoning problem.
- The correct answer must be derivable only by chaining the embedded facts (not guessable from general knowledge).
- Focus on biological mechanisms, causality, temporal dynamics, or synthesis; avoid trivia.
- DO NOT invent quantitative data (percentages, concentrations, fold-changes) unless explicitly stated in COMPILED KNOWLEDGE.
- Base reasoning on the inherent relationships and mechanisms described in the entities and relationships.

Example format (for a different topic):
"If a bacterial strain expresses an efflux pump that actively transports antibiotics out of the cell, 
and the same strain also has a membrane permeability mutation that reduces antibiotic entry, 
what is the most likely mechanism by which this strain achieves resistance to β-lactam antibiotics?"

Output ONLY:
- One QUESTION line with all facts embedded
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
    import sys
    print("Loading graph directly from GraphML file...")
    
    # Load graph directly from GraphML file
    cache_dir = os.path.join(args.working_dir, "graphrag_cache")
    graph_file = os.path.join(cache_dir, "graph_chunk_entity_relation.graphml")
    
    if not os.path.exists(graph_file):
        print(f"Graph file not found: {graph_file}")
        print("Creating knowledge graph from source files...")
        
        # Use create_graph_only.py to create the graph
        import subprocess
        import sys
        
        try:
            # Run create_graph_only.py with the working directory
            result = subprocess.run([
                sys.executable, 
                "create_graph_only.py", 
                "--source-dir", args.working_dir,
                "--entity-prompt", "Study molecular biology, microbiology, and biochemistry concepts. Analyze scientific research on bacterial mechanisms, viral processes, and microbial ecology."
            ], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
            
            if result.returncode == 0:
                print("Knowledge graph created successfully!")
            else:
                print(f"Failed to create knowledge graph: {result.stderr}")
                return
        except Exception as e:
            print(f"Failed to create knowledge graph: {e}")
            return
        
        # Check if graph was created
        if not os.path.exists(graph_file):
            print(f"Graph file still not found after creation: {graph_file}")
            return
    
    # Load the graph directly
    graph = nx.read_graphml(graph_file)
    print(f"Graph loaded with {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges.")
    
    # If graph is empty, try to create one
    if graph.number_of_nodes() == 0:
        print("Graph is empty, attempting to create knowledge graph from source files...")
        
        # Use create_graph_only.py to create the graph
        import subprocess
        import sys
        
        try:
            # Run create_graph_only.py with the working directory
            result = subprocess.run([
                sys.executable, 
                "create_graph_only.py", 
                "--source-dir", args.working_dir,
                "--entity-prompt", "Study molecular biology, microbiology, and biochemistry concepts. Analyze scientific research on bacterial mechanisms, viral processes, and microbial ecology."
            ], capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
            
            if result.returncode == 0:
                print("Knowledge graph created successfully!")
                # Reload the graph
                graph = nx.read_graphml(graph_file)
                print(f"Graph reloaded with {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges.")
            else:
                print(f"Failed to create knowledge graph: {result.stderr}")
                return
        except Exception as e:
            print(f"Failed to create knowledge graph: {e}")
            return
    
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
            compiled_state = await compile_state_for_idea(graph, llm, idea, graph_samples)
            
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
    if output_dir and not os.path.exists(output_dir):
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

