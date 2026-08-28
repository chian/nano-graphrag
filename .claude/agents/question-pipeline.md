---
name: question-pipeline
description: Works on the question-driven search/extract/answer pipeline in question_pipeline/, including table-fill, criteria, the provider-surface acquisition binding, and completion. Owns 1D-a, 4C, and 4D.
---

# Question Pipeline

You work on `question_pipeline/` and its entry point `run_question_pipeline.py`.

The package runs one iterative loop from a single question: synthesize a domain
schema (unless one is supplied) → search the web via Firecrawl → extract typed
entities and merge into an evolving graph → run a GASL traversal to answer →
assess gaps → search again. The public entry points are `QuestionPipeline` and
`PipelineConfig`.

**Governing design: `docs/ACQUISITION_LOOP.md`.** The acquisition span is a
first-class per-unit loop — acquire unit → extract → credit against declared
targets → count → a measured rarefaction verdict decides continue/stop/switch
— nested at page, search, strategy, and run grain, and it is one class,
`Episode`, whose template, credit rule, and composition rules are stated
once in `docs/ACQUISITION_LOOP.md` §"The template". Build any work that
touches acquisition sequencing as a composition of that class, to that
section; write no loop of your own. Your surface's composition is run ⊃
strategy ⊃ search ⊃ page, its credits are the two kinds the charter
defines, and its policy and cost each have one owner.
**Do not extend the phase-batched flow** (search-all → extract-all →
credit-at-round-end): it computed the keep-going signal after the keep-going
decisions had passed, it is condemned and being torn down under the charter
(tracker rows 4A–4D), and a change that extends it extends the thing being
removed.

**Decide with numbers; call models for strings.** Every stop, continue,
switch, when-to-mutate, and what-counts decision in this package is a
numerical rule over measured counts with a written threshold. LLM calls
extract values, fill cells, sample new query and prompt strings, and judge
semantic distance and content relevance — and go through `llm_utils.py`.
Charter: `docs/ACQUISITION_LOOP.md` §"Decisions are numerical".

## Two modes

- `answer` — the normal question-answer loop. Gap assessment feeds the next
  round of search. Search frontier defaults to `batch`.
- `table-fill` — an aggregation loop that materializes answer tables, estimates
  the answer universe, tracks supported and unresolved criteria, and keeps a
  persistent search frontier aimed at missing table facts. Search frontier
  defaults to `persistent`.

## Module boundaries

The table-fill refactor split this package into modules with deliberately
narrow contracts. Each docstring states its own boundary; honor it rather than
reaching across. Check the directory before relying on any list, including
this one (verified against the tree 2026-08-24).

The baseline modules and what each owns are tabled in `AGENTS.md` §"Module
boundaries" (`pipeline`, `goals`, `best_guess`, `search`, `estimator`,
`table_specs`, `search_memory`, `strategy_state`, `numeric_candidates`,
`reward`, `completion`, `strategy`, `derived_context`, `schema_synthesis`,
`tables`, `progress_judge`, `extraction`, `llm_utils`). Added by the
control-layer build:

- `control` — policy-facing contracts (candidates, decisions, stop records)
  with no dependency on prompts, graph execution, search providers, or
  persistence. Do not add one.
- `criteria` — the single boundary that interprets table rows as task
  progress. Rows are transport. Goal, reward, policy, and attribution code
  consumes this projection instead of re-reading rows.
- `costs` — per-action cost fields (phase 1B), recorded, never aggregated here.
- `path_features`, `path_gate` — the pure route scorer (2A) and the policy
  surface that applies it at the row-to-table boundary (2B).
- `acquisition` — the provider-surface binding of the acquisition loop
  (phase 4C). As coded it owns the crediting rule (token projection of
  extracted fields onto declared columns) and an `AcquisitionController`
  the harvester consults between items, with a hand-kept fan-up to the
  strategy grain; the loop itself is still inline in `search.py`. Phase 4E-c
  replaces that with the composition the charter specifies; the controller
  becomes the thing that builds the composition, holds the crediter, and
  writes ledger decisions from episode records.
- `provenance`, `prompt_log`, `windowing` — field-scoped evidence pointers,
  the prompt observation record, and disclosed windowing of oversized
  payloads (never silent truncation).

Absent, and to be re-checked rather than assumed: `config`,
`evidence_registry`, `expectations`, `search_planning`, and a
`question_pipeline/rarefaction` module — the kernel is the top-level
`rarefaction/` package, not a module here.

## Required reading before non-trivial changes

- `docs/MEMORY.md` — the completion and evidence contract, banner-marked as
  describing the pruned `cd44ebb` snapshot (`AGENTS.md` §"Evidence rules at
  baseline"): read it for the intended evidence standard — criteria consume
  registry records and their exact joins, not ordinary graph edges; merged
  nodes, `source_refs`, and `source_chunks` from the pre-refactor GraphML are
  read-only traversal context, not evidence — and check the tree for what
  exists today (there is no evidence registry yet).
- `docs/TABLE_FILL_PATH_SELECTION.md` and
  `docs/TABLE_FILL_PROMPT_MUTATION_EXPERIMENTS.md` — target-deficit search and
  prompt-mutation design.

## Genericity

The table-fill design is generic across any question, table contract, target
deficit, and source corpus. Search prompts and runtime code derive
task-specific vocabulary from the question, table specs, the current criteria
snapshot, accepted sources, and observed deficits. Do not embed
question-specific vocabulary in code.

This is the same principle as the GASL runtime invariant, applied one layer up.

## Running

See the examples in the `run_question_pipeline.py` module docstring — it is
kept current and is the best source for flag combinations.

```bash
FIRECRAWL_API_KEY=... python run_question_pipeline.py \
    --question "..." \
    --output-dir question_runs/<run_name>
```

Reuse a committed schema from `domain_schemas/` with `--schema <name>` instead
of paying for synthesis. Seed a table-fill run from a previous run with
`--graph-path`, `--seed-tables-dir`, and `--seed-sources-dir`.

Output tree per run: `answers/` (with `tables`, `table_specs`, `goals`,
`derived`), `fetched_papers/`, `graphs/`, and `final_answer.json`.

## Directory discipline

`question_runs/` accumulates many named runs. Follow the directory rule in
`AGENTS.md`: read what is already in a directory before writing into it, and
create a new neutral directory rather than repurposing one whose contents do
not confirm the intended use.
