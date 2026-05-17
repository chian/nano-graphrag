# GASL Resumable Batching — Implementation Plan

## Goal
Enable 1,000-node GASL queries to:
1. Resume from the last completed batch if interrupted
2. Never hold more than ~2 batches of raw items in memory simultaneously
3. Write progress to disk so restarts don't lose work

## Checkpoint File Layout

```
gasl_checkpoints/
  {job_id}_{var_name}.json            # manifest: tracks which batches are done
  {job_id}_{var_name}_batch_{n}.json  # result items for batch n
```

### Manifest format
```json
{
  "job_id": "...",
  "variable_name": "cognitive_domains",
  "command_type": "PROCESS",
  "instruction": "...",
  "total_items": 1000,
  "batch_size": 45,
  "total_batches": 23,
  "completed_batches": [0, 1, 5],
  "status": "in_progress",
  "created_at": "2026-05-16T...",
  "updated_at": "2026-05-16T..."
}
```

## Key Changes

### `gasl/micro_actions.py`
- [ ] Add `job_id` + `checkpoint_dir` params to `__init__` (defaults: None / `gasl_checkpoints`)
- [ ] Add helpers: `_load_checkpoint`, `_save_checkpoint`, `_save_batch_result`, `_load_batch_result`, `_iter_all_batch_results`
- [ ] In `execute_command_with_batching`:
  - On entry: load manifest if exists, skip already-completed batches
  - After each batch success: write `_batch_{n}.json` immediately, update manifest
  - After all batches: stream through batch files to build tally (never accumulate all 1k items)
  - On completion: set manifest status = "complete"
- [ ] In `_save_to_state`: store tally dict (not raw 1k items) so state/context stores stay small

### `gasl/executor.py`
- [ ] Pass `job_id` down to `MicroActionFramework` when creating commands

### `visualization/server.py`
- [ ] Pass job_id from the GASL job to the engine so checkpoints are keyed per-job

## Memory Model
- In-flight: max 1 batch (~45 items) in RAM at a time during processing
- After batch: write to disk, release from memory
- At end: stream batch files one-by-one to build tally dict {domain: count}
- State/context stores: tally dict only, not 1,000 raw dicts

## Resumption
- If server restarts while processing batch 7 of 23:
  - Batches 0–6 exist as `_batch_0.json` … `_batch_6.json`
  - Manifest lists `completed_batches: [0, 1, 2, 3, 4, 5, 6]`
  - On next run: batches 0–6 are skipped, processing resumes from batch 7

## Status Tracking
- [x] Step 1: Add checkpoint directory and manifest helpers
- [x] Step 2: Integrate resume logic into execute_command_with_batching
- [x] Step 3: Add streaming tally at end (replace in-memory accumulation)
- [x] Step 4: Pass job_id from executor to MicroActionFramework
- [ ] Step 5: Test end-to-end with 1,000 nodes, verify resumption works
