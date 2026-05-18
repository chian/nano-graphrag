# GASL Behavior Evaluation

This repo should debug GASL with behavior traces, not answer-overlap tables.

## Rule

Do not use exact-string RAG-vs-GASL answer scoring to drive debugging changes.
For debugging and iteration, the primary unit of evaluation is the GASL run trace:

- planner stability
- command execution health
- state/shape discipline
- PROCESS behavior
- termination integrity

## Behavior Rubric

Per query, capture at least:

- planner iterations
- history length
- command error count
- command empty count
- PROCESS status counts
- error-category histogram
- validation hint
- trace event count
- trace PROCESS step count

## Error Categories

Current common categories:

- `process_output_shape_mismatch`
- `missing_handler_show`
- `aggregate_field_resolution`
- `path_semantics_validator`
- `llm_judge_validation`

## Initial Trace Baseline

From the first six completed engineering-controls traces (`q001`..`q006`):

- planner iterations average: `5.0`
- total executed commands: `92`
- command errors: `16`
- command error rate: `17.4%`
- PROCESS statuses:
  - success: `12`
  - empty: `12`
  - error: `8`
- recurring error families:
  - `process_output_shape_mismatch`: `7`
  - `missing_handler_show`: `3`
  - `aggregate_field_resolution`: `3`
  - `path_semantics_validator`: `2`

These fixes were taken because the dominant debugging signal was contract
mismatch, not answer quality:

- `PROCESS` exposed wrapper objects instead of rows
- batched `PROCESS` replaced row records with tally placeholders
- `SHOW` was advertised by the planner but not dispatched by the executor

## Interpretation

- `PROCESS` should expose row/list outputs to downstream commands.
- Batched `PROCESS` may persist compact tallies for diagnostics, but downstream
  commands must still be able to access row-level outputs.
- Handler availability is part of the planner/executor contract. If the planner
  can emit `SHOW`, the executor must actually dispatch `SHOW`.
- Aggregate failures should first be checked for upstream shape corruption before
  changing the aggregate validator.

## Implementation Notes

- The trace corpus runner writes `behavior_summary.json`.
- Per-query `gasl.json` includes a `behavior` block.
- Use the behavior summary to decide central fixes, then commit, rerun, and
  compare behavior deltas across the next corpus.
