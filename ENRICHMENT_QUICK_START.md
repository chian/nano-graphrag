# Question Enrichment - Quick Start

## TL;DR

Add realistic distracting information to questions using two numerical parameters:
- `--enrich-info-pieces N` → How many distracting facts to add
- `--enrich-graph-depth D` → How far to search in graph (1-3 hops)

## Usage Examples

### Enabled by Default (3 distracting facts)
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology
```

### Disabled
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --enrich-info-pieces 0
```

### More Difficult
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --enrich-info-pieces 5 \
    --enrich-graph-depth 2
```

### Very Challenging
```bash
python generate_contrastive_qa.py graph.graphml molecular_biology \
    --enrich-info-pieces 7 \
    --enrich-graph-depth 3
```

## What Changes

### Before (Original)
```
Phocaeicola dorei consumes 60% inulin. Lachnoclostridium symbiosum
consumes 55%. Coculture reaches 95% with 70% higher SCFAs.
L. symbiosum lacks degradation genes but converts acetate to butyrate.
P. dorei produces acetate. Which maximizes utilization?

Answer: Coculture
```

### After (Enriched with N=2, D=1)
```
Phocaeicola dorei consumes 60% inulin. Lachnoclostridium symbiosum
consumes 55%. Bacteroides fragilis, a related species, ferments inulin
at 50% efficiency but produces primarily acetate and propionate.
Coculture reaches 95% with 70% higher SCFAs. L. symbiosum lacks
degradation genes but converts acetate to butyrate. Blautia producta
can also convert acetate to butyrate with 65% efficiency. P. dorei
produces acetate. Which maximizes utilization?

Answer: Coculture
```

**Answer unchanged, but question is harder to parse.**

## Parameter Guide

### `--enrich-info-pieces N`
| Value | Description | Use Case |
|-------|-------------|----------|
| 0 | Disabled | Testing, baseline questions |
| 1-2 | Light noise | Gentle difficulty increase |
| 3 | Medium noise (DEFAULT) | Noticeable challenge |
| 4-5 | Heavy noise | More challenging |
| 6+ | Very heavy noise | Advanced/frustrating |

### `--enrich-graph-depth D`
| Value | Description | Entities Found |
|-------|-------------|----------------|
| 1 | Immediate neighbors | Related, plausible |
| 2 | 2 hops away | Moderately related |
| 3 | 3 hops away | More distant, noisier |

## Files

- **Implementation**: `question_enrichment.py`
- **Modified pipeline**: `generate_contrastive_qa.py`
- **Full docs**: `ENRICHMENT_IMPLEMENTATION.md`
- **Test**: `test_enrichment.py`

## Testing

Run quick test:
```bash
python test_enrichment.py
```

## Output Format

Output JSON now includes:

```json
{
  "enrichment_settings": {
    "enabled": true,
    "info_pieces": 3,
    "graph_depth": 1
  },
  "questions": [
    {
      "question": "Enriched question...",
      "original_question": "Original without enrichment",
      "enrichment_pieces": ["Snippet 1", "Snippet 2", "Snippet 3"],
      "enrichment_entities": ["Entity1", "Entity2", "Entity3"]
    }
  ]
}
```

## Quality Guarantees

✓ **Always uses LLM validation** - No random selection
✓ **Score threshold ≥ 7** - Only high-quality distractors
✓ **Answer unchanged** - Enrichment doesn't break reasoning
✓ **Original preserved** - Output includes both versions

## Future: Graph Extension

Module is ready for graph-level enrichment (e.g., firecrawl):

```python
# TODO: Implement extend_graph_with_external_data()
# Then use extended graph for enrichment
```

See `question_enrichment.py:310` for placeholder function.
