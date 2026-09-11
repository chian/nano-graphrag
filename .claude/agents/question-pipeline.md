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
semantic distance and content relevance — and go through `utilities/model.py`.
Charter: `docs/ACQUISITION_LOOP.md` §"Decisions are numerical".

## Two modes

- `answer` — the normal question-answer loop. Gap assessment feeds the next
  round of search. Search frontier defaults to `batch`.
- `table-fill` — an aggregation loop that materializes answer tables, estimates
  the answer universe, tracks supported and unresolved criteria, and keeps a
  persistent search frontier aimed at missing table facts. Search frontier
  defaults to `persistent`.

## Module boundaries

`question_pipeline/pipeline.py` is the visible entry point and owns
configuration, composition, root launch, and final output. Concrete Episode
types live one-per-module in `question_pipeline/episode_binding/`. Supporting
implementation is grouped by responsibility in `question_pipeline/utilities/`:
`acquisition`, `evidence`, `extraction`, `model`, `rarefaction`, `replay`,
`search`, and `tables`. Do not recreate the prior flat collection of narrowly
sliced utility modules.

The generic Episode method remains the top-level `method_loop/` package. The
question-pipeline numerical component is `utilities/rarefaction.py`; it is an
attached implementation and does not own Episode.

## Episode binding ownership

Create one reusable module under `question_pipeline/episode_binding/` for the
`chunk` Leaf and each Episode type: `lexical_probe`, `page`, `web_search`,
`strategy`, and `run`. An Episode binding owns that type's grain/controller
declaration, source and unit types, Episode builder, local hooks, and compact
parent update. It accepts a child builder callable and therefore does not
choose its own child Episode type. The chunk module owns the Leaf's
unit/extract/accept/result wiring and declares no Grain.

The package initializer assembles the provider binding from those types;
`pipeline.py` connects its configured collaborators and starts the root once.
Keep table projection in `utilities/tables.py`, evidence records in
`utilities/evidence.py`, and checkpoints in `utilities/acquisition.py`. Do not
replace explicit collaborators with a shared context object handed wholesale
to every binding. Future GASL query and walk bindings follow the same
module-per-type rule and remain outside standalone `gasl/`.

## Required reading before non-trivial changes

- `docs/MEMORY.md` — historical completion and evidence design, banner-marked
  where it describes the pruned `cd44ebb` snapshot. The current durable
acceptance boundary is `question_pipeline/utilities/evidence.py`: criteria
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
