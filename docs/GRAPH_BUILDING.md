# Graph Building

This repo can still build and grow graphs from a seed document or a set
of papers, but that path is intentionally split out of the main README.

## Minimal graph-building quick start

```bash
export LLM_API_KEY=...
export LLM_ENDPOINT=...        # only when using an Argo-compatible gateway
export FIRECRAWL_API_KEY=...

python run_haiqu_iterative_pipeline.py \
  --seed-pdf "haiqu/20260126 Cognitive Tests for HAIQU.pdf" \
  --output haiqu_graph/
```

That pipeline:

1. chunks the seed content
2. extracts typed entities and relations
3. prioritizes entities for follow-on search
4. generates targeted search queries
5. fetches and parses literature
6. merges new evidence into the working graph
7. stops on convergence

## Main graph-building modules

- [run_haiqu_iterative_pipeline.py](../run_haiqu_iterative_pipeline.py)
- [iterative_search/](../iterative_search/)
- [paper_fetching/](../paper_fetching/)
- [graph_enrichment/](../graph_enrichment/)
- [nano_graphrag/](../nano_graphrag/)

## Output format

The result is a standard GraphML file. Build a graph only when you need to
create or refresh the substrate used by the graph-query runtime.
