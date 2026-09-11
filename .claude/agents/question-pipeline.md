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
— nested at lexical-probe, page, search, strategy, and run grains, and it is
one class,
`Episode`, whose template, credit rule, and composition rules are stated
once in `docs/ACQUISITION_LOOP.md` §"The template". Build any work that
touches acquisition sequencing as a composition of that class, to that
section; write no loop of your own. Your surface's composition is run ⊃
strategy ⊃ search ⊃ page ⊃ lexical probe ⊃ chunk Leaf. Accepted stable
logical-slot identities remain separated by result column; their marginal
hypervolume is the one method credit. Policy and cost each have one owner.
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
- `acquisition` — a transitional monolith that currently contains all provider
  Episode bindings, result projection, learning/checkpoint state, and record
  writing. Split it according to "Episode binding ownership" below; do not add
  another grain or cross-grain responsibility to it.
- `provenance`, `prompt_log`, `windowing` — field-scoped evidence pointers,
  the prompt observation record, and disclosed windowing of oversized
  payloads (never silent truncation).

Absent, and to be re-checked rather than assumed: `config`, `expectations`,
and `search_planning`. The numerical component is the existing
`question_pipeline/rarefaction/` package; the generic Episode method is the
top-level `method_loop/` package.

## Episode binding ownership

Create one reusable module under `question_pipeline/episode_bindings/` for the
`chunk` Leaf and each Episode type: `lexical_probe`, `page`, `web_search`,
`strategy`, and `run`. An Episode binding owns that type's grain/controller
declaration, source and unit types, Episode builder, local hooks, and compact
parent update. It accepts a child builder callable and therefore does not
choose its own child Episode type. The chunk module owns the Leaf's
unit/extract/accept/result wiring and declares no Grain.

`question_pipeline/acquisition_composition.py` is the only owner of nesting.
It connects the child builders, declares `Context` order, builds the root, and
runs it once. Keep table-specific projection in `result_projection.py` and
trace/checkpoint/export formatting in `acquisition_records.py`. Do not replace
the current large `ProviderBinding` with a large shared context object; each
binding receives only the collaborators it calls. Future GASL query and walk
bindings follow the same module-per-type rule and remain outside standalone
`gasl/`.

## Required reading before non-trivial changes

- `docs/MEMORY.md` — historical completion and evidence design, banner-marked
  where it describes the pruned `cd44ebb` snapshot. The current durable
  acceptance boundary is `question_pipeline/evidence_registry.py`: criteria
  consume registry records and exact joins, not ordinary graph edges; merged
  nodes, `source_refs`, and `source_chunks` from pre-refactor GraphML remain
  read-only traversal context, not accepted evidence.
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
