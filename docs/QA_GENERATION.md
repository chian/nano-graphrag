# QA Generation Guide

This guide covers all question-answer generation scripts in nano-graphrag, which create high-quality training data for reasoning models.

## Table of Contents

1. [Overview](#overview)
2. [QA Generation Types](#qa-generation-types)
3. [Reasoning QA (Recommended)](#reasoning-qa-recommended)
4. [Multi-Hop QA](#multi-hop-qa)
5. [Synthesis QA](#synthesis-qa)
6. [Logic Puzzle QA](#logic-puzzle-qa)
7. [Short Answer QA](#short-answer-qa)
8. [GASL-Based QA](#gasl-based-qa)
9. [Output Formats](#output-formats)
10. [Best Practices](#best-practices)

---

## Overview

### Purpose

Generate high-quality question-answer pairs from knowledge graphs for:
- **Training reasoning models**: Create datasets with `<think>` tokens
- **Model evaluation**: Test complex reasoning capabilities
- **Educational content**: Generate challenging questions
- **Research applications**: Create evaluation benchmarks

### Key Features

- **Diversity**: Ensures varied topics and reasoning types
- **Quality Control**: LLM-based scoring and filtering
- **Graph-Grounded**: All Q&A pairs backed by graph structure
- **Multiple Types**: Different reasoning patterns (multi-hop, synthesis, etc.)
- **Configurable**: Control difficulty, length, topic focus

### Common Workflow

```
Knowledge Graph (GraphML)
    ↓
[Sample Graph Context]
    ↓
[Generate Questions via LLM]
    ↓
[Quality Filtering]
    ↓
[Save to JSON]
```

---

## QA Generation Types

### Comparison

| Type | Reasoning Required | Difficulty | Best For |
|------|-------------------|------------|----------|
| **Reasoning QA** | ⭐⭐⭐⭐⭐ | High | Complex scientific reasoning |
| **Multi-Hop** | ⭐⭐⭐⭐ | Medium-High | Chaining facts |
| **Synthesis** | ⭐⭐⭐⭐ | Medium-High | Information integration |
| **Logic Puzzle** | ⭐⭐⭐⭐⭐ | Very High | Logical deduction |
| **Short Answer** | ⭐⭐ | Low-Medium | Direct facts |
| **GASL-Based** | ⭐⭐⭐⭐ | High | Graph-specific queries |

### When to Use Each Type

**Reasoning QA**: Scientific papers, complex domain knowledge
**Multi-Hop**: Citation networks, collaboration graphs
**Synthesis**: Multi-source integration, broad knowledge
**Logic Puzzle**: Constraint satisfaction, logical inference
**Short Answer**: Quick facts, simple lookups
**GASL-Based**: Graph analysis, systematic exploration

---

## Reasoning QA (Recommended)

### Overview

The most sophisticated QA generator with:
- **Diverse reasoning types**: Mechanistic, comparative, causal, predictive
- **Topic diversity**: Tracks recent topics and avoids repetition
- **Quality filtering**: Only questions scoring ≥7/10 pass
- **Scientific rigor**: Self-contained, no "the text" references

### Usage

```bash
python generate_reasoning_qa.py \
  --working-dir /path/to/papers/graphrag_cache \
  --num-questions 100 \
  --output /path/to/output.json \
  --min-quality-score 7
```

### Parameters

```python
--working-dir         # Path to nano-graphrag working directory
--num-questions       # Number of questions to generate (default: 10)
--output              # Output JSON file path
--min-quality-score   # Minimum quality score 0-10 (default: 7)
--samples-per-question  # Graph samples per question (default: 5)
--topic-refresh-interval  # Questions before topic refresh (default: 20)
```

### How It Works

**Step 1: Sample Graph Context**
```python
# Sample diverse subgraphs, avoiding recent topics
context = await sample_graph_context(
    graph,
    num_samples=5,
    exclude_topics=recent_topics  # Last 20 topics
)
```

**Step 2: Topic Refresh (Every 20 Questions)**
```python
# Extract keywords from recent questions to exclude
recent_topics = extract_keywords_from_recent_questions(
    recent_questions[-20:]
)
# Examples: {"gene", "protein", "mutation", ...}
```

**Step 3: Generate Question**
```python
# LLM creates multi-choice question with reasoning
prompt = f"""
Based on this graph context:
{context}

Recent topics to avoid: {recent_topics}

Generate a complex scientific reasoning question with:
- 8 answer choices (A-H)
- Multiple plausible distractors
- One clearly correct answer
- Reasoning type: {random choice from types}
"""
```

**Reasoning Types**:
- `mechanistic` - How does X cause Y?
- `comparative` - What's the difference between X and Y?
- `causal` - Why does X lead to Y?
- `predictive` - What would happen if X?
- `integrative` - How do X, Y, Z relate?

**Step 4: Quality Filtering**
```python
# LLM judges quality 0-10
judge_prompt = """
Rate this question on:
- Scientific accuracy (1-10)
- Reasoning complexity (1-10)
- Answer clarity (1-10)
- Self-contained (yes/no)
- No "the text" references (yes/no)
"""

if score >= min_quality_score:
    save_question()
else:
    discard_question()
```

### Output Format

```json
{
  "question": "Which mechanism best explains how antibiotic resistance emerges in bacterial populations?",
  "choices": {
    "A": "Spontaneous generation of resistant bacteria",
    "B": "Natural selection favoring pre-existing resistant mutants",
    "C": "Direct exposure making bacteria stronger",
    "D": "Bacteria learning to resist antibiotics",
    "E": "Horizontal gene transfer only",
    "F": "Programmed bacterial evolution",
    "G": "Environmental adaptation without genetics",
    "H": "Random chance with no pattern"
  },
  "answer": "B",
  "reasoning_type": "mechanistic",
  "biological_focus": "bacterial evolution and antibiotic resistance",
  "quality_score": 9,
  "graph_context_sample_count": 5
}
```

### Advanced Features

**1. Diversity Tracking**
```python
# Tracks last 20 questions
recent_questions = []

# Extracts keywords to avoid
recent_topics = {"gene", "protein", "mutation", "expression"}

# Samples exclude these topics
context = sample_graph_context(graph, exclude_topics=recent_topics)
```

**2. Topic Refresh**
```python
# Every 20 questions, refresh topic list
if len(questions) % 20 == 0:
    print("🔄 Refreshing topic diversity...")
    recent_topics = extract_keywords(recent_questions[-20:])
```

**3. Quality Metrics**
```python
# Scoring criteria
criteria = {
    "scientific_accuracy": 0-10,
    "reasoning_complexity": 0-10,
    "clarity": 0-10,
    "self_contained": boolean,
    "no_text_references": boolean
}
```

---

## Multi-Hop QA

### Overview

Generates questions requiring chaining facts across multiple graph hops.

### Usage

```bash
python generate_multihop_qa.py \
  --working-dir /path/to/papers/graphrag_cache \
  --num-questions 50 \
  --path-length 2 \
  --output multihop_qa.json
```

### Parameters

```python
--working-dir     # Path to working directory
--num-questions   # Number of questions (default: 10)
--path-length     # Length of paths to find (default: 2)
--output          # Output file (default: multihop_qa.json)
```

### How It Works

**Step 1: Find Random Paths**
```python
# Find paths of length N in graph
def find_random_paths(graph, length=2, num_paths=10):
    paths = []
    for _ in range(num_paths * 10):  # Try many times
        # Pick random start node
        start = random.choice(list(graph.nodes()))

        # BFS to find path of target length
        path = bfs_path(graph, start, target_length=length)

        if path and len(path) == length + 1:
            paths.append(path)

    return paths[:num_paths]
```

**Step 2: Extract Path Information**
```python
path_info = {
    "nodes": [
        {"id": node, "data": graph.nodes[node]}
        for node in path
    ],
    "edges": [
        graph.get_edge_data(path[i], path[i+1])
        for i in range(len(path)-1)
    ]
}
```

**Step 3: Generate Question**
```python
prompt = f"""
Given this path through the knowledge graph:

Node 1: {node1}
→ {edge1} →
Node 2: {node2}
→ {edge2} →
Node 3: {node3}

Generate a question that requires understanding how
these facts connect across multiple steps.
"""
```

### Output Format

```json
{
  "question": "How might the use of prescription opioids among older adults be indirectly connected to the risk of heroin overdose in this population?",
  "answer": "Step 1: Prescription opioids can lead to dependence in older adults\nStep 2: Dependence may lead to seeking cheaper alternatives\nStep 3: Heroin is a cheaper but more dangerous opioid\nStep 4: This transition increases overdose risk",
  "path_length": 3,
  "node_types": ["PRESCRIPTION_DRUG", "CONDITION", "ILLEGAL_DRUG"],
  "relationship_types": ["CAUSES", "LEADS_TO"]
}
```

### Example Questions

**2-Hop Question**:
> "If Gene A regulates Protein B, and Protein B activates Process C, what is the indirect effect of Gene A on Process C?"

**3-Hop Question**:
> "Given that Author X collaborated with Author Y, Author Y cited Paper Z, and Paper Z introduced Method M, how is Author X connected to Method M?"

---

## Synthesis QA

### Overview

Generates "why" and "how" questions requiring synthesizing information from multiple sources.

### Usage

```bash
python generate_synthesis_qa.py \
  --working-dir /path/to/papers/graphrag_cache \
  --num-questions 30 \
  --output synthesis_qa.json
```

### Parameters

```python
--working-dir     # Path to working directory
--num-questions   # Number of questions (default: 10)
--min-degree      # Minimum node degree to sample (default: 3)
--output          # Output file (default: synthesis_qa.json)
```

### How It Works

**Step 1: Find High-Connectivity Nodes**
```python
# Find nodes with many connections (hubs)
def find_hub_nodes(graph, min_degree=3):
    hubs = [
        node for node in graph.nodes()
        if graph.degree(node) >= min_degree
    ]
    return sorted(hubs, key=lambda n: graph.degree(n), reverse=True)
```

**Step 2: Aggregate Context**
```python
# Get rich context from node and neighbors
def get_synthesis_context(graph, node):
    # Node data
    center = graph.nodes[node]

    # All neighbors
    neighbors = list(graph.neighbors(node))

    # All edges
    edges = [
        graph.get_edge_data(node, n)
        for n in neighbors
    ]

    # Build comprehensive context
    return {
        "center": center,
        "neighbors": [graph.nodes[n] for n in neighbors],
        "relationships": edges
    }
```

**Step 3: Generate Synthesis Question**
```python
prompt = f"""
Given this entity with {len(neighbors)} connections:

Center: {center}

Connected to:
{neighbors}

Via relationships:
{relationships}

Generate a "how" or "why" question that requires
synthesizing information from multiple connections.
"""
```

### Output Format

```json
{
  "question": "How does the CDC integrate data from diverse surveillance systems to identify emerging public health threats?",
  "answer": "The CDC synthesizes data from multiple sources:\n1. NNDSS: Mandatory disease reporting from states\n2. Sentinel surveillance: Selected sites for detailed monitoring\n3. Syndromic surveillance: Real-time symptom tracking\n4. Laboratory networks: Pathogen identification\n5. These systems provide complementary views that together enable early threat detection",
  "center_node": "CDC",
  "num_connections": 12,
  "synthesis_sources": ["surveillance", "laboratories", "states", "healthcare"]
}
```

### Example Questions

**Integration Question**:
> "How do gene expression, protein abundance, and metabolite levels together determine cellular phenotype?"

**System Question**:
> "Why does the immune system require coordination between innate immunity, adaptive immunity, and inflammatory responses?"

---

## Logic Puzzle QA

### Overview

Creates logic-based puzzles using graph constraints.

### Usage

```bash
python generate_logic_puzzle_qa.py \
  --working-dir /path/to/papers/graphrag_cache \
  --num-questions 20 \
  --output logic_puzzles.json
```

### Output Format

```json
{
  "question": "Given these constraints:\n1. Gene A activates Gene B\n2. Gene B inhibits Gene C\n3. Gene C is required for Process P\n\nIf Gene A is overexpressed, what happens to Process P?",
  "answer": "Process P is reduced because:\n1. Gene A overexpression → more Gene B\n2. More Gene B → less Gene C (inhibition)\n3. Less Gene C → reduced Process P",
  "puzzle_type": "constraint_satisfaction",
  "difficulty": "medium"
}
```

---

## Short Answer QA

### Overview

Direct factual questions from graph entities.

### Usage

```bash
python generate_short_answer_qa.py \
  --working-dir /path/to/papers/graphrag_cache \
  --num-questions 100 \
  --output short_answer_qa.json
```

### Output Format

```json
{
  "question": "What entity type represents authors in the graph?",
  "answer": "PERSON",
  "difficulty": "easy",
  "category": "factual"
}
```

---

## GASL-Based QA

### Overview

Uses GASL to generate questions about graph structure and analysis.

### Usage

```bash
python generate_reasoning_qa_gasl.py \
  --working-dir /path/to/papers/graphrag_cache \
  --num-questions 50 \
  --output gasl_qa.json
```

### How It Works

**Step 1: Generate GASL Query**
```python
# LLM creates GASL query based on graph
gasl_query = llm.generate(f"""
Create a GASL query that analyzes this graph:
{graph_summary}

Query should require multiple steps and reasoning.
""")
```

**Step 2: Execute GASL Query**
```python
from gasl import GASLExecutor

executor = GASLExecutor(adapter, llm, state_file)
result = executor.run_hypothesis_driven_traversal(gasl_query)
```

**Step 3: Generate Question from Results**
```python
question = llm.generate(f"""
Based on this GASL analysis:
Query: {gasl_query}
Results: {result}

Create a question that tests understanding of the analysis.
""")
```

### Output Format

```json
{
  "question": "What GASL commands would you use to find the most prolific author in the graph?",
  "answer": "1. FIND nodes with entity_type=PERSON AS authors\n2. PROCESS authors with instruction: Extract author name AS names\n3. COUNT authors field author_name AS frequency\n4. RANK frequency by count order desc AS top_authors",
  "gasl_query": "Create histogram of author names",
  "reasoning_required": "multi-step planning"
}
```

---

## Output Formats

### Standard JSON Format

```json
[
  {
    "id": 1,
    "question": "...",
    "answer": "...",
    "type": "reasoning|multihop|synthesis|...",
    "metadata": {
      "difficulty": "easy|medium|hard",
      "quality_score": 8,
      "graph_nodes_used": 5,
      "timestamp": "2024-01-01T10:00:00"
    }
  },
  ...
]
```

### Multi-Choice Format (Reasoning QA)

```json
{
  "question": "Which mechanism...",
  "choices": {
    "A": "Option A",
    "B": "Option B",
    "C": "Option C",
    "D": "Option D",
    "E": "Option E",
    "F": "Option F",
    "G": "Option G",
    "H": "Option H"
  },
  "answer": "B",
  "reasoning_type": "mechanistic",
  "quality_score": 9
}
```

### Chain-of-Thought Format (Multi-Hop)

```json
{
  "question": "How is X connected to Y?",
  "answer": "Step 1: X relates to Z because...\nStep 2: Z leads to Y because...\nTherefore: X indirectly affects Y through Z",
  "steps": [
    {"entity": "X", "relation": "CAUSES", "target": "Z"},
    {"entity": "Z", "relation": "LEADS_TO", "target": "Y"}
  ]
}
```

---

## Best Practices

### 1. Graph Preparation

**Ensure Quality Graph**:
```bash
# Build graph with sufficient context
python -c "
from nano_graphrag import GraphRAG
rag = GraphRAG(
    working_dir='./cache',
    chunk_token_size=1200,
    entity_extract_max_gleaning=2  # More thorough extraction
)
rag.insert(documents)
"
```

**Verify Graph Size**:
```python
import networkx as nx
graph = nx.read_graphml("./cache/graph_chunk_entity_relation.graphml")
print(f"Nodes: {len(graph.nodes())}")
print(f"Edges: {len(graph.edges())}")
# Aim for: 100+ nodes, 200+ edges for good QA generation
```

### 2. Diversity Strategy

**Track Recent Topics**:
```python
recent_topics = set()
questions = []

for i in range(num_questions):
    # Every 20 questions, refresh
    if i % 20 == 0:
        recent_topics = extract_keywords(questions[-20:])

    # Sample with exclusions
    context = sample_graph_context(graph, exclude_topics=recent_topics)
    question = generate_question(context)
    questions.append(question)
```

**Rotate Reasoning Types**:
```python
reasoning_types = ["mechanistic", "comparative", "causal", "predictive"]
for i, question_num in enumerate(range(num_questions)):
    reasoning_type = reasoning_types[i % len(reasoning_types)]
    question = generate_question(context, reasoning_type=reasoning_type)
```

### 3. Quality Control

**Multi-Stage Filtering**:
```python
# Stage 1: Generate candidate
candidate = generate_question(context)

# Stage 2: Quality scoring
score = llm_judge(candidate)
if score < 7:
    continue

# Stage 3: Verify self-contained
if "the text" in candidate or "the passage" in candidate:
    continue

# Stage 4: Check uniqueness
if is_duplicate(candidate, existing_questions):
    continue

# Accept question
questions.append(candidate)
```

**Quality Metrics**:
- Scientific accuracy: 7-10/10
- Reasoning complexity: Requires 2+ inference steps
- Clarity: Unambiguous question and answer
- Self-contained: No external references
- Uniqueness: Not duplicate of existing questions

### 4. Performance Optimization

**Batch Processing**:
```python
async def generate_qa_batch(graph, batch_size=10):
    tasks = [
        generate_single_qa(graph)
        for _ in range(batch_size)
    ]
    return await asyncio.gather(*tasks)
```

**Caching**:
```python
# Cache graph samples
sample_cache = {}

def get_or_create_sample(seed):
    if seed not in sample_cache:
        sample_cache[seed] = sample_graph_context(graph, seed)
    return sample_cache[seed]
```

### 5. Domain Customization

**Scientific Papers**:
```python
python generate_reasoning_qa.py \
  --working-dir ./papers/cache \
  --num-questions 100 \
  --min-quality-score 8 \
  --samples-per-question 7  # More context
```

**Collaboration Networks**:
```python
python generate_multihop_qa.py \
  --working-dir ./collabs/cache \
  --path-length 3 \  # Longer chains
  --num-questions 50
```

**General Knowledge**:
```python
python generate_synthesis_qa.py \
  --working-dir ./wiki/cache \
  --min-degree 5 \  # Highly connected nodes
  --num-questions 30
```

### 6. Output Processing

**Combine Multiple Types**:
```python
import json

# Generate different types
reasoning_qa = generate_reasoning_qa(graph, 40)
multihop_qa = generate_multihop_qa(graph, 30)
synthesis_qa = generate_synthesis_qa(graph, 30)

# Combine
all_qa = {
    "reasoning": reasoning_qa,
    "multihop": multihop_qa,
    "synthesis": synthesis_qa,
    "metadata": {
        "total": 100,
        "graph_nodes": len(graph.nodes()),
        "created_at": datetime.now().isoformat()
    }
}

with open("combined_qa.json", "w") as f:
    json.dump(all_qa, f, indent=2)
```

**Filter by Difficulty**:
```python
# Keep only high-quality, hard questions
filtered = [
    q for q in questions
    if q.get("quality_score", 0) >= 8
    and q.get("difficulty") == "hard"
]
```

---

## Troubleshooting

### Common Issues

**1. Low Diversity**
- Increase `topic_refresh_interval`
- Use `exclude_topics` parameter
- Sample from different graph regions

**2. Poor Quality**
- Increase `min_quality_score`
- Improve graph quality (more extraction gleaning)
- Use more graph samples per question

**3. Slow Generation**
- Reduce `samples_per_question`
- Use async batch processing
- Cache graph samples

**4. Repetitive Questions**
- Track more recent questions (40 instead of 20)
- Extract more exclusion keywords
- Rotate reasoning types

---

## Next Steps

- [Architecture Guide](./ARCHITECTURE.md) - Understanding nano-graphrag
- [GASL Guide](./GASL_GUIDE.md) - Advanced graph analysis
- [API Reference](./API_REFERENCE.md) - Programmatic access
