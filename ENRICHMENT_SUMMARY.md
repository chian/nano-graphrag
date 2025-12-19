# Question Enrichment - Implementation Summary

## What Was Built

A numerically-tunable system for adding realistic "noise" to self-contained reasoning questions by injecting non-essential but plausible information from neighboring graph entities.

## Key Features

### ✓ Numerical Parameters (Not Categorical Levels)
- `--enrich-info-pieces N`: Number of distracting facts to add (0=disabled)
- `--enrich-graph-depth D`: How many graph hops to search (1-3)

### ✓ Always Uses LLM Validation
- Every enrichment candidate is scored by LLM (score 1-10)
- Only candidates with score ≥ 7 are used
- No random selection - quality is guaranteed

### ✓ Modular Design
- Can be toggled on/off via parameters
- Separate module: `question_enrichment.py`
- Future-ready for graph extension (firecrawl, external sources)

### ✓ Preserves Answer
- Enrichment never changes the correct answer
- Original question is preserved in output
- Validation ensures no interference with reasoning chain

## Files Created/Modified

### New Files
1. **`question_enrichment.py`** (309 lines)
   - `QuestionEnricher` class with all enrichment logic
   - Placeholder for future `extend_graph_with_external_data()`
   - Modular design for easy extension

2. **`ENRICHMENT_IMPLEMENTATION.md`**
   - Complete technical documentation
   - Usage examples
   - Architecture diagrams
   - Performance considerations

3. **`test_enrichment.py`**
   - Simple test to verify module works
   - Creates mock graph and tests enrichment

4. **`ENRICHMENT_SUMMARY.md`** (this file)

### Modified Files
1. **`generate_contrastive_qa.py`** (modified 4 sections)
   - Imports `QuestionEnricher`
   - Added CLI args: `--enrich-info-pieces`, `--enrich-graph-depth`
   - Modified `generate_questions_from_analyses()` to accept enrichment params
   - Integrated enrichment step after validation passes
   - Added enrichment metadata to output JSON

## How to Use

### Enabled by Default (Medium Enrichment)
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology
```
3 distracting facts per question, 1-hop search (NEW DEFAULT).

### Disabled
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --enrich-info-pieces 0
```
Questions remain as-is, no enrichment.

### Light Enrichment
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --enrich-info-pieces 2 \
    --enrich-graph-depth 1
```
2 distracting facts per question, immediate neighbors only.

### Heavy Enrichment
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --enrich-info-pieces 5 \
    --enrich-graph-depth 2
```
5 distracting facts per question, 2-hop search.

### Very Heavy Enrichment
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --enrich-info-pieces 7 \
    --enrich-graph-depth 3
```
7 distracting facts per question, 3-hop search (very noisy).

## Output Changes

Questions now include enrichment metadata:

```json
{
  "enrichment_settings": {
    "enabled": true,
    "info_pieces": 3,
    "graph_depth": 2
  },
  "questions": [
    {
      "question": "Enriched question text...",
      "original_question": "Original without enrichment",
      "enrichment_pieces": ["Snippet 1", "Snippet 2"],
      "enrichment_entities": ["Entity1", "Entity2"]
    }
  ]
}
```

## How It Works (High-Level)

1. **Core Question Generated**: Normal pipeline, validated for quality
2. **Graph Traversal**: BFS from core entities, depth=`D`, collect candidates
3. **LLM Scoring**: Score each candidate (1-10) for plausibility and distraction quality
4. **Selection**: Take top `N` candidates with score ≥ 7
5. **Snippet Generation**: LLM generates factual snippets for each selected entity
6. **Injection**: Insert snippets naturally into question text
7. **Output**: Save enriched + original versions

## Future Extension Point

The module is designed to support graph-level enrichment:

```python
# FUTURE: Before enrichment, extend the graph itself
extended_graph = await extend_graph_with_external_data(
    graph=original_graph,
    domain=domain_name,
    llm=llm,
    firecrawl_key=args.firecrawl_key,
    max_entities=100
)

# Then enrich questions using extended graph
enricher = QuestionEnricher(graph=extended_graph, ...)
```

This placeholder function exists in `question_enrichment.py` and can be implemented later to:
- Scrape related entities from web (firecrawl)
- Query external knowledge bases
- Add entities/relationships before question generation

## Testing

Run the test:
```bash
python test_enrichment.py
```

This will:
- Create a mock graph with 5 entities
- Test enrichment disabled (info_pieces=0)
- Test light enrichment (info_pieces=2, depth=1)
- Show original vs enriched questions

## Performance Notes

**LLM Calls per Enriched Question:**
- Base generation: ~3 calls
- Enrichment (N=3, candidates=10): ~13 calls
- Total: ~16 calls per question

**Recommendation:**
- Start with `N=2-3` for testing
- Higher `N` and `D` increase cost/time
- Consider batching or caching for production

## Design Principles Met

✓ **Numerical parameters** (not categorical levels)
✓ **Always validates** (no --enrich-llm-calls flag)
✓ **Modular** (can be disabled, separate module)
✓ **Clear explanation** (not verbose code)
✓ **Future-ready** (graph extension placeholder)
✓ **Quality guaranteed** (LLM scoring + threshold)

## Next Steps

1. Test with real mSystems data
2. Tune `info_pieces` and `graph_depth` based on question difficulty
3. Optionally implement `extend_graph_with_external_data()` for graph extension
4. Experiment with different scoring thresholds if needed
