# Question Enrichment Implementation

## Overview

Adds numerically-tunable "noise" to self-contained questions by injecting non-essential but plausible information from neighboring graph entities.

## Architecture

### Modular Design

```
generate_contrastive_qa.py
    ↓
[Graph Extension Point] ← FUTURE: extend_graph_with_external_data()
    ↓                     (firecrawl, external sources)
[Core Question Generation]
    ↓
[Validation Pipeline]
    ↓
[QuestionEnricher] ← NEW MODULE (question_enrichment.py)
    ↓
[Final Output]
```

The design is modular:
1. **Graph Extension** (future): `extend_graph_with_external_data()` can be called before enrichment to add more entities/relationships
2. **Enrichment**: `QuestionEnricher` class operates on existing graph
3. **Toggle**: Can be completely disabled by setting `--enrich-info-pieces 0`

## Numerical Parameters

### `--enrich-info-pieces N` (default: 0)
- **What it controls**: Number of distracting facts to add per question
- **0 = disabled**: No enrichment, questions remain as-is
- **1-2 = light**: Minimal distraction, good for testing
- **3-5 = medium**: Noticeable complexity increase
- **6+ = heavy**: Significant noise, harder to parse

### `--enrich-graph-depth D` (default: 1)
- **What it controls**: How many hops away from core entities to search for candidates
- **1**: Only immediate neighbors (safer, more related)
- **2**: Neighbors of neighbors (moderate distance)
- **3**: Three hops away (distant entities, more noise)

## How It Works

### Step 1: Core Question Generation (Unchanged)
```
GASL Analysis → Question Generation → Validation → [PASS]
```

Core entities identified: ["Phocaeicola dorei", "Lachnoclostridium symbiosum"]

### Step 2: Graph Traversal (BFS)
```python
Starting from: P. dorei, L. symbiosum
Depth 1 (immediate neighbors):
  - Bacteroides fragilis
  - Blautia producta
  - inulinase enzyme
  - acetate

Depth 2 (neighbors of neighbors):
  - Prevotella copri
  - butyrate kinase
  - polysaccharide metabolism
```

Candidates collected: All entities within `graph_depth` hops

### Step 3: LLM Scoring (Always Enabled for Quality)
For each candidate entity, use LLM to score:

**Prompt:**
```
Evaluate this entity as a distractor:
1. PLAUSIBILITY: Is it plausible in this scenario?
2. NON-INTERFERENCE: Will it NOT change the reasoning path?
3. DISTRACTION QUALITY: Makes problem harder?

Score 1-10 where:
- 7-8: Good distractor
- 9-10: Excellent distractor
```

**Only keep candidates with:**
- Score ≥ 7
- Interference risk: low or medium

### Step 4: Selection
- Sort candidates by score (descending)
- Take top `N` candidates

### Step 5: Snippet Generation
For each selected entity, LLM generates a factual snippet:

**Example Output:**
```
"Bacteroides fragilis, a related species, ferments inulin at 50%
efficiency but produces primarily acetate and propionate."
```

### Step 6: Injection
Insert snippets naturally into question text:

**Original:**
```
Phocaeicola dorei consumes 60% inulin. Lachnoclostridium symbiosum
consumes 55%. Coculture reaches 95% with 70% higher SCFAs.
L. symbiosum lacks degradation genes but converts acetate to butyrate.
P. dorei produces acetate. Which maximizes utilization?
```

**Enriched (N=2, D=1):**
```
Phocaeicola dorei consumes 60% inulin. Lachnoclostridium symbiosum
consumes 55%. Bacteroides fragilis, a related species, ferments inulin
at 50% efficiency but produces primarily acetate and propionate.
Coculture reaches 95% with 70% higher SCFAs. L. symbiosum lacks
degradation genes but converts acetate to butyrate. Blautia producta
can also convert acetate to butyrate with 65% efficiency. P. dorei
produces acetate. Which maximizes utilization?
```

**Answer:** Still "Coculture" - enrichment doesn't change reasoning

## Usage

### Disabled (Default)
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --max-questions 20
```

Output: Standard questions, no enrichment

### Light Enrichment
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --max-questions 20 \
    --enrich-info-pieces 2 \
    --enrich-graph-depth 1
```

Output: 2 distracting facts per question, immediate neighbors only

### Medium Enrichment
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --max-questions 20 \
    --enrich-info-pieces 4 \
    --enrich-graph-depth 2
```

Output: 4 distracting facts per question, 2-hop search

### Heavy Enrichment
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --max-questions 20 \
    --enrich-info-pieces 7 \
    --enrich-graph-depth 3
```

Output: 7 distracting facts per question, 3-hop search (very noisy)

## Output Format

Each question now includes enrichment metadata:

```json
{
  "domain": "molecular_biology",
  "num_questions": 20,
  "enrichment_settings": {
    "enabled": true,
    "info_pieces": 3,
    "graph_depth": 2
  },
  "questions": [
    {
      "question": "Enriched question text with distractors...",
      "original_question": "Original question without enrichment",
      "correct_answer": "Coculture",
      "reasoning_steps": [...],
      "source_entities": ["P. dorei", "L. symbiosum"],
      "enrichment_pieces": [
        "Bacteroides fragilis, a related species...",
        "Blautia producta can also convert..."
      ],
      "enrichment_entities": ["Bacteroides fragilis", "Blautia producta"],
      "quality_score": 5.5,
      "answer_word_count": 1,
      "is_self_contained": true,
      "is_gradable": true
    }
  ]
}
```

## Future Extension: Graph Enrichment

The module is designed to support graph-level enrichment in the future:

```python
# FUTURE: Add to pipeline before question generation

# Step 1: Extend graph with external data
extended_graph = await extend_graph_with_external_data(
    graph=original_graph,
    domain=domain_name,
    llm=llm,
    firecrawl_key=args.firecrawl_key,  # Example parameter
    max_entities=100
)

# Step 2: Proceed with enriched graph
questions = await generate_questions_from_analyses(
    graph=extended_graph,  # Use extended graph
    ...
)
```

This would allow:
- Scraping related entities from web (firecrawl)
- Adding entities from external knowledge bases
- Enriching graph structure before question generation

The `question_enrichment.py` module already has a placeholder function:
```python
async def extend_graph_with_external_data(
    graph: nx.DiGraph,
    domain: str,
    llm: ArgoBridgeLLM,
    **kwargs
) -> nx.DiGraph:
    """FUTURE: Extend graph with additional entities/relationships."""
    # TODO: Implement
    return graph
```

## Code Organization

```
nano-graphrag/
├── generate_contrastive_qa.py          # Main pipeline (modified)
│   └── Imports: QuestionEnricher
│   └── Adds: --enrich-info-pieces, --enrich-graph-depth args
│   └── Modified: generate_questions_from_analyses()
│       └── Creates QuestionEnricher instance
│       └── Calls enricher.enrich_question() after validation
│
└── question_enrichment.py              # NEW MODULE
    ├── QuestionEnricher class
    │   ├── __init__(graph, llm, num_info_pieces, graph_depth)
    │   ├── is_enabled()
    │   ├── enrich_question()
    │   ├── _find_candidate_entities()       # BFS graph traversal
    │   ├── _score_candidates()              # LLM scoring (always on)
    │   ├── _select_top_candidates()         # Top N selection
    │   ├── _generate_enrichment_snippets()  # LLM snippet generation
    │   └── _inject_enrichments()            # Text injection
    │
    └── extend_graph_with_external_data()   # FUTURE: Graph extension
```

## Quality Guarantees

1. **Always Uses LLM Validation**: All enrichment candidates are scored by LLM (no random selection)
2. **Score Threshold ≥ 7**: Only high-quality distractors are used
3. **Interference Check**: Candidates with high interference risk are rejected
4. **Original Question Preserved**: Output includes both enriched and original versions
5. **Answer Unchanged**: Enrichment never changes the correct answer

## Performance Considerations

**LLM Calls per Question:**
- Base question generation: ~3 calls (generation, self-containment, gradability, quality)
- Enrichment with N=3, candidates=10:
  - Candidate scoring: 10 calls
  - Snippet generation: 3 calls
  - Total: ~13 additional calls

**Recommendation:**
- Use `N=2-3` for reasonable performance
- Higher `N` and `D` significantly increase LLM calls
- Consider running in batches or with caching
