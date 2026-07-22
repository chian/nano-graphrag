# Table-Fill Prompt-Mutation Experiments

## Purpose

This is the implementation checklist for converting target-deficit search from
isolated query generation into prompt-mutation experiments.

The design is generic. It applies to any table-fill question, table contract,
target deficit, and source corpus. Search prompts and runtime code must derive
task-specific words from the question, table specs, current rows, accepted
sources, and observed deficits rather than embedding question-specific
vocabulary in code.

## Round Definition

`round` means the largest table-fill loop only.

One round includes:

1. completion assessment
2. deficit selection
3. search planning
4. search execution and source gating
5. source ingestion into the graph
6. graph traversal and table materialization
7. best-guess sidecar recovery
8. reward and diagnostic scoring
9. durable memory update
10. next-frontier scheduling

Smaller loops are not rounds. Use these names instead:

- `evolution`: one prompt-mutation planning step for one target deficit
- `prompt_arm`: one named prompt delta inside an evolution
- `query_attempt`: one concrete external search emitted by a prompt arm
- `search_batch`: the bounded set of concrete query attempts sent to the
  harvester together
- `best_guess_batch`: a bounded group of missing sidecar slots

## Core Definitions

### Strategy attempt

A search strategy attempt is one prompt-mutation experiment for one target
deficit at one evolution step.

It contains:

- a stable `strategy_attempt_id`
- the outer `round_index`
- the `target_id` for the deficit being attacked
- the `evolution_index` inside that target deficit
- several named `prompt_arm` records
- several concrete query attempts per arm
- immediate search observations per query
- candidate URL fates per query
- delayed graph, table, and sidecar yield after materialization

### Prompt arm

A prompt arm is a small, named prompt delta plus a hypothesis about how that
delta should alter query generation.

Each arm records:

- `prompt_arm_id`
- `name`
- `prompt_delta`
- `hypothesis`
- `expected_source_shape`
- `query_attempts`

### Pseudo-gradient

The pseudo-gradient is contrastive inference-time evidence over prompt arms.

It is not training and it is not reinforcement learning. It is the compact
comparison that tells the next planner prompt which prompt deltas found
non-overlapping useful evidence, which deltas returned only duplicates, which
deltas drifted off axis, and which deltas found promising sources that failed
to materialize target slots.

## Durable Identifiers

Every concrete `SearchTask` emitted by the target-deficit planner must carry
these metadata fields:

- `strategy_attempt_id`
- `target_id`
- `target_table`
- `evolution_index`
- `prompt_arm_id`
- `prompt_arm_name`
- `prompt_arm_index`
- `query_index`

Those identifiers must flow into:

- `SearchOutcome`
- candidate URL fates
- accepted source records
- graph ingestion diagnostics
- table rows when source refs can be joined
- best-guess accepted sidecars when source refs can be joined
- prompt-arm scores
- compact search memory

The harvester must not infer prompt-arm provenance from query text.

## Implementation Checklist

1. Read the current partial edits in `question_pipeline/search.py`,
   `search_memory.py`, `strategy.py`, `strategy_state.py`, and `pipeline.py`
   and identify the pieces to keep, rename, or replace.
2. Patch this staging design so a strategy attempt is one prompt-mutation
   experiment for one target deficit at one evolution step.
3. Define the prompt-mutation experiment artifact schema with outer round,
   target deficit, evolution step, arm, and concrete query identifiers.
4. Replace generic search-wave naming in the partial harvester edits with
   prompt-mutation experiment and prompt-arm naming.
5. Extend `SearchTask` metadata so every concrete query carries experiment,
   target-deficit, evolution, arm, and query-index provenance.
6. Extend `SearchOutcome` so zero-hit counts, result observations, candidate
   fates, accepted sources, duplicate URLs, and gate costs are grouped under
   the originating arm.
7. Persist per-query raw outcomes for replay without losing arm grouping.
8. Persist per-arm summaries under the current outer round artifact directory.
9. Update `SearchMemory.from_outcomes()` to fold query outcomes into
   per-target prompt-arm experiment histories.
10. Store immediate arm observations separately from delayed materialization
    observations.
11. Store arm-level contrast records that compare arms tried in the same
    target-deficit evolution step.
12. Update the target-deficit planner output contract so it emits named prompt
    arms with prompt deltas, hypotheses, and several concrete queries per arm.
13. Update the target-deficit planner prompt so it sees prior arm contrast and
    asks for deliberate prompt mutations rather than another isolated query.
14. Update the target-deficit parser and validation path to reject malformed
    arms while preserving valid sibling arms.
15. Add a bounded target-deficit evolution loop inside the outer round that can
    request another prompt-mutation experiment for the same deficit after
    immediate arm contrast is available.
16. Thread prompt-arm metadata through `SearchFrontier` enqueueing so the
    harvester does not need to infer provenance from query text.
17. Run prompt-arm searches through the existing external-search harvester and
    source relevance gate.
18. Record candidate URL fates including duplicate, blocked, too short, too
    large, off-axis by gate, and accepted.
19. Keep accepted source IDs linked to the arm that found them through paper
    writing and graph ingestion.
20. Attribute graph node and edge deltas back to accepted sources and therefore
    back to prompt arms.
21. Attribute table rows and source refs back to accepted sources and therefore
    back to prompt arms.
22. Attribute best-guess sidecar fills back to rows, source refs, and prompt
    arms where a source linkage exists.
23. Score each prompt arm with immediate search metrics, delayed table metrics,
    best-guess metrics, duplicate penalties, off-axis penalties, and cost
    proxies.
24. Write arm scores into durable target search memory for the next evolution
    step in the same outer round.
25. Write arm scores into durable target search memory for the next outer
    round.
26. Update `strategy_state` routing to consume arm contrast and choose the next
    mutation family from productive and unproductive arm evidence.
27. Close each outer round by refreshing completion, rebuilding deficits from
    the latest carried-forward tables, and scheduling work from arm-scored
    memory for remaining task-level deficits.
28. Rename any remaining inner-loop fields that call subactions rounds so
    `round` means only the full outer loop.
29. Add focused checks for serialization and replay of prompt-arm experiment
    artifacts using real prior round artifacts.
30. Run syntax and import validation for `question_pipeline`.
31. Run a real external table-fill round that verifies arm generation, search
    harvesting, ingestion, materialization, delayed attribution, and
    next-evolution use of contrast.

## Implementation Status

| Step | Status | Notes |
| --- | --- | --- |
| 1-5 | Coded | Search tasks now carry `strategy_attempt_id`, `evolution_index`, `prompt_arm_id`, `prompt_arm_index`, and `query_index` from the target-deficit planner into the harvester. |
| 6-8 | Coded | Search outcomes now keep compact result observations, candidate URL fates, per-batch arm summaries, and raw per-query outcomes for replay. |
| 9-13 | Coded | Search memory now folds concrete query attempts into target-level strategy attempts with nested prompt arms and arm contrast; the target-deficit prompt asks for named prompt-arm experiments. |
| 14 | Coded | The parser accepts the new `experiments[].arms[].queries[]` shape while retaining the legacy flat `queries` shape. |
| 15-18 | Coded + focused-tested + partially corpus-validated | The outer round can run bounded same-deficit evolutions after target-deficit attempts get zero accepted sources; the cap is counted per target prompt-mutation attempt so carried legacy searches do not consume the same-round prompt-arm budget. All new attempts still flow through the existing harvester and relevance gate. |
| 19 | Coded | Accepted source IDs are recorded on the originating concrete query outcome and preserved in arm summaries. |
| 20 | Partial | The current diagnostic still stores graph node and edge deltas at target-outcome granularity; exact source-to-graph attribution is still a follow-up. |
| 21-24 | Coded | After GASL and best-guess recovery, accepted source IDs are joined back to materialized rows and best-guess sidecar rows and written to arm-yield artifacts. |
| 25 | Coded | Search memory is refreshed after immediate search and again after delayed row and sidecar attribution. |
| 26 | Coded | Target-operator routing sees per-attempt table and sidecar yield before classifying failed attempts. |
| 27 | Coded | Each outer round rebuilds task-level deficits from carried-forward tables and schedules remaining unfulfilled target deficits. |
| 28 | Partial | New code uses outer `round`, `evolution`, `prompt_arm`, and `query_attempt`; older persisted artifacts may still contain historical `strategy_wave_id` compatibility fields. |
| 29 | Deferred | Offline fake tests were removed; replay checks should use real prior artifacts if this gets local artifact-only coverage later. The current validation path uses direct external Firecrawl/OpenAI calls. |
| 30 | Coded | The changed modules compile in the project venv. |
| 31 | Partially corpus-validated | Real direct-OpenAI continuations validated prompt-arm provenance, parser-side arm/query caps, bounded evolution after carried frontier tasks, prompt-arm yield export, and search-memory folding. A real Firecrawl plus OpenAI harvester probe validated compact Firecrawl result observations and candidate fates. Fresh accepted-source ingestion under the final per-target cap patch is still pending. |

## Live Validation Notes

- A direct one-round continuation with three arms per evolution validated that
  newly planned target searches carry `strategy_attempt_id`,
  `evolution_index`, `prompt_arm_id`, `prompt_arm_index`, `prompt_delta`,
  `prompt_hypothesis`, `expected_source_shape`, and `query_index` into
  `search_outcomes.jsonl`.
- That same run exposed two defects that were patched before commit: the parser
  trusted duplicated experiment blocks from the planner and Firecrawl result
  observations could copy nested provider metadata into durable prompt-arm
  samples.
- A direct harvester probe with one real Firecrawl hit and one real OpenAI
  progress judgment validated that compact search observations preserve scalar
  hit metadata, persist candidate fates, write prompt-arm summaries, and do not
  retain nested provider metadata.
- A follow-up one-round continuation with one allowed same-round target
  evolution validated that carried legacy target searches do not consume the
  prompt-mutation cap. The round drained nine carried searches, generated one
  prompt-arm experiment with two arms and three concrete fresh queries, exported
  arm-yield diagnostics, and completed the outer round.

## Validation Bar

The change is complete only when it is:

- coded
- focused-tested
- committed
- corpus-validated

Until the real external round has run, this is only coded and focused-tested at
most. Offline artifact replay can validate serialization and attribution over
real prior data, but it cannot validate source search and gating behavior.
