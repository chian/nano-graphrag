# HPC Graph Build Pipeline

Generic, reusable pipeline for embarrassingly parallel graph builds over large corpora.

## Layout

- `chunk_manifest.py`: build a canonical chunk manifest from an external inventory
- `split_shards.py`: split the canonical manifest into deterministic shard files by count
- `build_vllm_prompts.py`: build vLLM-ready prompt JSONL from one shard manifest
- `run_shard_extraction.py`: extract entities/relationships from one shard and write local artifacts
- `merge_hierarchy.py`: merge shard graphs in deterministic stages
- `review_final_merges.py`: run an LLM semantic review over candidate final-stage merges
- `common.py`: shared helpers

## Inventory Contract

The chunk manifest step accepts either:

- JSONL where each line is one paper record
- JSON with either a top-level list or `{"records": [...]}` payload

Required fields per record:

- `paper_id` or `id`
- either:
  - `path`: relative or absolute paper path, with `--paper-root` optionally provided
  - or `text`: inline paper text

Optional fields per record:

- `title`
- any other metadata fields you want to preserve upstream

See `examples/inventory.example.jsonl`.

## Command Order

1. Build one canonical chunk manifest

```bash
.venv/bin/python -m hpc.chunk_manifest \
  inventory.jsonl \
  run/chunks.jsonl \
  --paper-root /corpus/papers \
  --paper-id-key paper_id \
  --path-key path \
  --title-key title \
  --chunk-size 4000 \
  --overlap 400
```

2. Split into 100 shard files by count

```bash
.venv/bin/python -m hpc.split_shards \
  run/chunks.jsonl \
  run/shards \
  --shards 100
```

3. Run extraction shard-by-shard

```bash
.venv/bin/python -m hpc.run_shard_extraction \
  run/shards/shard_000.jsonl \
  run/shard_runs/shard_000 \
  --schema your_schema_name \
  --model gpt-5.4-mini \
  --self-refine
```

3a. Or build prompt rows for a vLLM endpoint from a shard

```bash
.venv/bin/python -m hpc.build_vllm_prompts \
  run/shards/shard_000.jsonl \
  run/prompts/shard_000.requests.jsonl \
  --schema your_schema_name \
  --model meta-llama/Llama-3.1-70B-Instruct \
  --format openai-chat
```

4. Merge local shard graphs hierarchically

```bash
.venv/bin/python -m hpc.merge_hierarchy \
  run/shard_runs/shard_*/local_graph.graphml \
  run/merge \
  --fan-in 10
```

5. Run final semantic merge review

```bash
.venv/bin/python -m hpc.review_final_merges \
  run/merge/final_graph.graphml \
  run/review \
  --model gpt-5.4-mini \
  --similarity-threshold 0.92
```

## Artifacts

Canonical manifest:

- stable `chunk_id`
- `paper_id`
- source offsets
- chunk text

Shard extraction:

- `entities.jsonl`
- `relationships.jsonl`
- `chunk_results.jsonl`
- `local_graph.graphml`
- `state.json`
- `summary.json`

Hierarchy merge:

- staged merged graphs
- stage summaries
- `final_graph.graphml`

Final review:

- `merge_decisions.jsonl`
- `reviewed_graph.graphml`
- `summary.json`

## Notes

- The pipeline is generic; there is no domain or corpus hardcoding in `hpc/`.
- The shard splitter is intentionally simple: it partitions by count, not by estimated runtime.
- `review_final_merges.py` only runs LLM checks after deterministic candidate generation from the graph.
- Use the repo virtualenv for commands: `.venv/bin/python -m ...`.
