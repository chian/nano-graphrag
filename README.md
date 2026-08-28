# nano-graphrag

<p align="center">
  <img src="docs/assets/nano-graphrag-logo.png" alt="nano-graphrag logo" width="164">
</p>

`nano-graphrag` is a question-driven graph QA workbench. The active work is a
**table-fill control loop**: given a question and a declared table contract, it
searches for sources, extracts typed values, builds a knowledge graph, runs
GASL (a graph query language) over it, and fills tables with evidenced
datapoints — deciding *numerically* when to keep going and when to change
strategy.

## The central design: the acquisition control loop

Everything in acquisition — provider search, GASL graph walking, strategy
selection — is one repeated loop, and the loop is one class (`Episode`) with
swappable parts — unit source, extractor, crediting rule, hooks, safety
bound — whose source may yield child episodes, so a surface is a
composition of grains rather than a loop of its own. The full charter
is [docs/ACQUISITION_LOOP.md](docs/ACQUISITION_LOOP.md) (§"The template" for
the class); wherever any other document disagrees with it, that document is
stale.

```
THE ACQUISITION EPISODE (one generic driver, instantiated at every surface):

   strategy ──► unit source ──► unit ──► extract ──► credit against
   (what to     (search hits /          (values)     declared targets
    try next)    walk frontier)                           │
      ▲             ▲                                     ▼
      │             │                            accumulate: new/repeat,
      │             │                            f1, f2, Chao1, curve —
      │             │                            NUMBERS, measured only
      │             │                                     │
      └──── switch ─┴──── continue / stop ◄─── verdict ───┘

 NESTING:  item-loop  ⊂  search-loop  ⊂  strategy-loop      (provider surface)
           iteration-loop  ⊂  walk-loop  ⊂  query-loop      (GASL surface)
           — the same kernel at every grain; credits fan upward through scopes
```

The consequences that matter:

- **Broad searches are the intended mode.** Nothing pre-narrows a search to
  control cost; the rarefaction numbers say when a search, a walk, or a whole
  strategy has stopped producing and should be cut.
- **Caps are not decisions.** Budget bounds survive only as safety rails and
  are reported as such. Continue/stop/switch comes from a measured verdict —
  a Beta-posterior over per-unit productivity plus a rarefaction curve
  (new-per-unit, singletons/doubletons, Chao1 over the observed sample).
- **Decisions are numerical; models are string experts.** Every stop,
  continue, switch, and when-to-mutate decision is a rule over measured
  credits with a written threshold — never a model, and never a model handed
  the curve and asked. Models do the string work: extracting values from
  text, filling cells, sampling new query and prompt strings, judging
  semantic distance. Repeated values are treated as propagation of one
  source, never as independent replication. Charter section:
  [Decisions are numerical](docs/ACQUISITION_LOOP.md#decisions-are-numerical-llms-are-string-experts).

## Layout

```text
question_pipeline/       the table-fill control loop: search, extraction,
                         crediting, goals, reward, strategy state
run_question_pipeline.py CLI entry for the loop
gasl/                    the GASL engine: parser, executor, commands, state,
                         adapters, answer layer (schema-agnostic)
rarefaction/             the pure counting/decision kernel every acquisition
                         surface shares: accumulator, stop rule, scopes, and
                         the episode driver (phase 4A, Confirmed)
nano_graphrag/           ingestion and graph construction substrate
domain_schemas/          reusable typed schemas for extraction
experiments/             registered predictions, run captures, diagnostic
                         scaffolding — the pipeline never imports from here
docs/                    design charters, build tracker, invariants
visualization/           browser UI and demo launchers — dormant since
                         2026-06-04; frozen unless that work reopens
```

## Running the loop

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# search requires FIRECRAWL_API_KEY in the environment
.venv/bin/python run_question_pipeline.py \
  --question "<your question>" \
  --pipeline-mode table-fill \
  --schema <name-from-domain_schemas/> \
  --max-rounds 5
```

The module docstring of `run_question_pipeline.py` carries current, working
examples — prefer those over reconstructing flags. Runs write to
`question_runs/<run_name>/` with tables, goals, fetched sources, graphs, and
`final_answer.json`. `AGENTS.md` holds the operational rules for runs.

## Verification stance

**There is no test suite in this repository, and none may be created.**
Verification is a live run on current code, designed as an experiment: a
registered claim, a falsifier, and evidence confirmed on independent routes.
See `CLAUDE.md`, `docs/CONTROL_LAYER_EXPERIMENTS.md`, and
`experiments/README.md` for the reasoning and the procedure. For generic GASL
runtime changes, the static invariant checker applies:
`.venv/bin/python tools/check_runtime_invariants.py`.

## Documentation

- [The Acquisition Control Loop](docs/ACQUISITION_LOOP.md) — the governing
  design for the acquisition span
- [Control Layer Build Tracker](docs/CONTROL_LAYER_BUILD.md) — phases, gates,
  owners
- [Control Layer Experiments](docs/CONTROL_LAYER_EXPERIMENTS.md) — what counts
  as evidence
- [Runtime Invariants](docs/RUNTIME_INVARIANTS.md) — schema-agnostic rules for
  the GASL engine, and the layering rules
- [GASL Guide](docs/GASL_GUIDE.md) — the language and its commands
- [Graph Building](docs/GRAPH_BUILDING.md) — the ingestion substrate

## Dormant: the visualization surface

`visualization/` is a browser UI (RAG and GASL query modes, trace and prompt
inspection) that has been dormant since 2026-06-04. It is not covered by the
runtime invariants and is frozen unless that work reopens. Its operating
procedures live in git history (`git show 92f8e64:AGENTS.md`).
