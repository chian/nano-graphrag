# nano-graphrag

<p align="center">
  <img src="docs/assets/nano-graphrag-logo.png" alt="nano-graphrag logo" width="164">
</p>

`nano-graphrag` is a research workbench for iterative evidence acquisition and
graph-guided question answering. Its current development focus is a table-fill
pipeline that can search broadly, preserve source-level evidence, and decide
numerically whether another unit of acquisition is likely to be useful.

The repository keeps two search media conceptually separate:

- The current table-fill acquisition binding searches the Web through
  Firecrawl, processes returned sources one at a time, and writes accepted
  evidence into typed result tables.
- GASL is a query language and execution engine for searching an explicitly
  supplied, immutable knowledge-graph revision. It lets an LLM use graph
  operations and interpret their results without treating the graph as a bag
  of retrieved text.

Firecrawl and GASL are peer search types in the method design. Searching the
Web does not automatically add its results to a graph, and running GASL does
not imply that a graph was updated. The first live experiments exercise the
Firecrawl binding so that nesting, accumulation, and search adaptation can be
measured without graph construction confounding the result.

## The acquisition method

Acquisition is one generic method, implemented by `method_loop.Episode` and
composed recursively at several grains. A binding supplies the source of
units, leaf extraction and acceptance functions, post-verdict hooks, and an
optional safety boundary. The Episode owns the order of operations.

```text
ONE EPISODE: ITS LOCAL LOOP

       +------------------------------------------------------------+
       |                                                            |
       v                                                            |
  check declared safety bound -- hit ----------------> EpisodeRecord|
       | not hit                                                    |
       v                                                            |
  source.next(this Episode's read-only EpisodeView)                 |
       |                                                            |
       +-- exhausted or source failure -------------> EpisodeRecord|
       | one unit                                                   |
       v                                                            |
  acquire through the bound leaf parts                              |
  extract -> accept -> project credit                               |
       |                                                            |
       v                                                            |
  opaque stable identities grouped by declared channels            |
       |                                                            |
       v                                                            |
  attached numerical component                                     |
  estimate -> scalar statistic -> fixed verdict                     |
       |                                                            |
       v                                                            |
  append UnitRecord -> run post-verdict hook                        |
  (the hook can inform future units but cannot change this verdict) |
       |                                                            |
       +-- numerical stop --------------------------> EpisodeRecord|
       | continue: build updated EpisodeView                         |
       +------------------------------------------------------------+
```

The numerical component is attached to the method; it does not contain the
method. `rarefaction/` owns the paired incidence estimator and numerical
controller. `method_loop/` owns iteration, nesting, identities, fan-up, and
the Episode record tree.

For table filling, a credited identity means that a stable subject occupies a
declared logical value slot in accepted typed storage. Directly reported and
anchored best-guess values for the same slot share one identity, so they cannot
double count. Row completion is an export and learning diagnostic, not another
credit.

In the current table-fill numerical binding, the estimator retains a vector of
distinct identities by result column. Its controller normalizes those axes by
their respective reachable-result estimates and reduces their progress to one
marginal relaxed-geometric hypervolume credit. The predicted next marginal
credit is that binding's sole stop statistic. Per-column estimates remain
visible for interpretation and future search planning, but they are not
independent stop rules.

Every attempted unit is explicitly recorded as successfully observed, failed,
or excluded. A successfully evaluated unit with no findings is a real zero; a
provider, compute, decoding, or evaluation failure is not silently converted
into zero yield. Safety bounds are likewise reported as `bound_hit`, never as
statistical convergence.

## The nesting

An Episode can pull a leaf or another Episode. The child completes its own
loop and becomes one unit of its parent. The current Firecrawl table-fill
binding has this shape:

```text
run Episode
└── strategy Episode
    └── search Episode
        └── page Episode
            └── lexical-probe Episode
                └── chunk Leaf
```

Here is the same tree using the real CATDAT document and recorded chunk
outcomes from the earthquake experiment. The row-native probe string was
supplied explicitly for the numerical replay, so this example demonstrates
the composition without claiming that the live model generated that exact
string:

```text
run: fatal-earthquake table
└── strategy: search annual earthquake-loss compilations
    └── search: "CATDAT damaging earthquakes year in review"
        └── page: CATDAT 2012 report
            ├── lexical probe: "Mw MMI USD"
            │   ├── chunk 52 -> accepted magnitude, death, injury,
            │   │              displacement, and damage slots
            │   ├── chunk 53 -> more accepted slots plus recurrences
            │   └── ... numerical saturation ends this probe
            └── next lexical probe, if the page verdict requests one,
                ranks only the chunks that remain unprocessed
```

Each level answers a different question with the same method:

| Episode grain | One unit | What ending the Episode means |
| --- | --- | --- |
| lexical probe | one previously unprocessed ranked chunk | return control to the page so it can propose another vocabulary over the remaining chunks |
| page | one completed lexical-probe Episode | finish this document and return its distinct findings to the search |
| search | one fetched page or document | stop consuming that Firecrawl result list |
| strategy | one completed search Episode | stop pursuing that strategy family |
| run | one completed strategy Episode | end the declared acquisition run |

The child passes its distinct accepted identities upward by column, once per
identity. A parent never sums child hypervolumes. It treats the completed child
as one incidence sample, deduplicates on the parent's scale, and recomputes its
own attached numerical statistic and verdict. In the current table-fill
binding, that statistic is marginal hypervolume. The full child record remains
nested beneath the parent's unit record for audit.

```text
WHEN A CHILD EPISODE CLOSES INTO ITS PARENT

  child runs its own local loop, possibly for many units
       |
       |  parent receives no ordinary fan-up sample yet
       v
  child EpisodeRecord
       |
       +---------------- full record ---------------------+
       |                                                  |
       v                                                  v
  child contribution                               nested under the
  - distinct identities by channel                 parent's UnitRecord
  - child eligibility                              for context and audit
       |
       v
  one unit in the immediate parent Episode
       |
       v
  parent deduplicates on its own scale
  -> parent numerical transition
  -> parent UnitRecord
  -> parent post-verdict hook
       |
       +-- parent continues
       |      |
       |      v
       |   parent.source.next(updated parent EpisodeView)
       |
       +-- parent closes
              |
              v
           the same handoff repeats to the grandparent
```

Applied to the Firecrawl composition, propagation is therefore staged rather
than broadcast through the whole tree:

```text
chunk completes          -> lexical-probe view updates locally
lexical probe closes     -> page receives one probe contribution
page closes              -> search receives one page contribution
search closes            -> strategy receives one search contribution
strategy closes          -> run receives one strategy contribution
```

This architecture combines recursive decomposition with scoped in-context
adaptation. A source can read the completed child records, numerical outcomes,
and compressed learning context available at its own level, then use an LLM to
propose a different string for the next unit. For example, a page can replace
an unproductive conceptual probe with document-native abbreviations, while a
strategy can replace a saturated search query with a different search angle.
The LLM proposes strings; the numerical estimator/controller decides whether
another proposal is due. The architecture enables this feedback, while live
experiments determine whether a particular prompt actually learns well.

The complete method contract is
[docs/ACQUISITION_LOOP.md](docs/ACQUISITION_LOOP.md). Where another document
describes a phase-batched round loop or gives the numerical component ownership
of `Episode`, that description is stale.

## Repository layout

```text
method_loop/             generic Episode method: iteration, nesting, runtime
                         identity, scope routing, fan-up, and record trees
rarefaction/             paired incidence estimator and numerical controller;
                         threshold state and typed numerical reports
question_pipeline/       Firecrawl/table-fill binding: search proposals,
                         chunk retrieval, extraction, evidence acceptance,
                         typed tables, learning context, and persistence
run_question_pipeline.py command-line entry point
gasl/                    graph query language and execution engine over an
                         explicitly supplied graph revision
nano_graphrag/           graph ingestion and construction substrate
domain_schemas/          reusable typed extraction schemas
experiments/             registered predictions and experimental records;
                         production code never imports from here
question_runs/           local run artifacts; not committed to GitHub
docs/                    design charters, build trackers, and invariants
visualization/           dormant browser/demo surface
```

## Running a Firecrawl table-fill acquisition

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

FIRECRAWL_API_KEY=... LLM_API_KEY=... \
  .venv/bin/python run_question_pipeline.py \
    --pipeline-mode table-fill \
    --question "Which fatal earthquakes since 1900 have reported magnitude, deaths, injuries, displacement, and economic damage?" \
    --schema earthquake_impact_two_grain \
    --output-dir question_runs/earthquake_example
```

Firecrawl may return many results in one provider response, but that response
is only a buffer. The search Episode pulls, fetches, extracts, accepts, credits,
and evaluates one source before pulling the next. There is no papers-per-query
or rounds control. `--max-source-units 0`, the default, is unbounded; if an
operator supplies a positive value, it is a disclosed safety boundary rather
than a convergence rule.

Resume a durable Episode checkpoint with:

```bash
.venv/bin/python run_question_pipeline.py \
  --continue question_runs/earthquake_example
```

The module docstring and `--help` output of `run_question_pipeline.py` are the
authoritative CLI references. Runs write source material, evidence-registry
records, typed tables, Episode trees, numerical verdicts, learning records,
and `checkpoint.json` beneath their output directory. `AGENTS.md` contains the
operator rules for live runs.

## GASL

GASL provides explicit graph operations rather than treating graph context as
ordinary retrieved prose. It can traverse, connect, filter, and inspect graph
structure, then let an LLM interpret the returned subgraph for a scientific
question. Its value is reuse of previously structured evidence, relationship
analysis, and inspectable graph operations. GASL uses only the graph revision
given to it; graph enrichment is a separate, reviewable workflow.

See [docs/GASL_GUIDE.md](docs/GASL_GUIDE.md) for the language and
[docs/RUNTIME_INVARIANTS.md](docs/RUNTIME_INVARIANTS.md) for its runtime
boundaries.

## Verification stance

There is no test suite in this repository, and none is to be created.
Behavior is verified with registered live experiments on the real provider and
model interfaces. Each experiment states its claim, numerical measurements,
and falsifier, and reports out-of-scope failures separately from the mechanism
being tested. Numerical-only shadow recalibration can replay immutable observed
identities through a controller without pretending to re-run acquisition.

See [docs/CONTROL_LAYER_EXPERIMENTS.md](docs/CONTROL_LAYER_EXPERIMENTS.md) and
`experiments/README.md` for the evidence standard. Generic GASL runtime changes
also use `.venv/bin/python tools/check_runtime_invariants.py`.

## Documentation

- [The Acquisition Control Loop](docs/ACQUISITION_LOOP.md) — governing method
  and numerical-control design
- [Next Step](docs/NEXT_STEP.md) — current implementation and experimental
  handoff
- [Control Layer Build Tracker](docs/CONTROL_LAYER_BUILD.md) — implementation
  phases and gates
- [Control Layer Experiments](docs/CONTROL_LAYER_EXPERIMENTS.md) — live-run
  evidence requirements
- [Runtime Invariants](docs/RUNTIME_INVARIANTS.md) — GASL layering and runtime
  rules
- [GASL Guide](docs/GASL_GUIDE.md) — language and commands
- [Graph Building](docs/GRAPH_BUILDING.md) — explicit graph-ingestion substrate

## Dormant visualization surface

`visualization/` has been dormant since 2026-06-04 and is frozen unless that
work reopens. Its operating procedures remain available in repository history
at `git show 92f8e64:AGENTS.md`.
