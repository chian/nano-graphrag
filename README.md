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
composed recursively at several levels. Each Episode chooses and processes one
unit at a time, measures what that unit added, and uses its numerical component
to decide whether to continue. A unit can be an ordinary item or another
Episode.

```text
  +------------------------------------------------------------------+
  |                                                                  |
  v                                                                  |
source reads this Episode's request, compact updates, and control state
  |                                                                  |
  v                                                                  |
choose the next unit                                                  |
  |                                                                  |
  +-- no unit left ------------------------> publish Episode record   |
  |                                                                  |
  +-- ordinary item -> run tool -> accept and store results --+      |
  |                                                           |      |
  +-- child Episode -> run child loop -> receive results ------+      |
                                                              |      |
                                                              v      |
                                             results from one unit   |
                                                              |      |
                                                              v      |
                                      send result to bound controller |
                                      update its numbers and decision |
                                                              |      |
                                                              v      |
                                      save record; update memory      |
                                                              |      |
                                      +-- stop --> publish record     |
                                      |                               |
                                      +-- continue -------------------+
```

The numerical component is attached to the method; it does not contain the
method. `rarefaction/` owns the paired incidence estimator and numerical
controller. `method_loop/` owns iteration, nesting, stable record keys, and the
Episode record tree.

For table filling, a counted result means that one subject has an accepted
value in one declared result column. A directly reported value and a best guess
for that same subject and column count as the same result, so they cannot be
double counted. Finding the same result in another source is recorded as a
repeat.

The table-fill numerical component keeps a separate count and estimate for
each result column, then combines them into one hypervolume credit. The
predicted credit from the next unit is the single number used to stop or
continue. The per-column estimates remain visible so people and future search
strategies can see which columns are still sparse.

Every attempted unit records whether it was successfully evaluated. A unit
that was evaluated and found nothing is a real zero. A failed tool call or
failed evaluation is not treated as evidence that no useful result existed.

## The nesting

An Episode can process an ordinary item or run another Episode. A child
finishes its own loop and becomes one unit of its parent. The current
Firecrawl table-fill binding has this shape:

```text
run Episode
└── strategy Episode
    └── search Episode
        └── page Episode
            └── lexical-probe Episode
                └── process one chunk
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
            │   ├── chunk 52 -> fills magnitude, deaths, injuries,
            │   │              displacement, and damage fields
            │   ├── chunk 53 -> fills more fields and repeats some findings
            │   └── ... the numerical decision ends this probe
            └── next lexical probe, if the page verdict requests one,
                ranks only the chunks that remain unprocessed
```

Each level answers a different question with the same method:

| Episode level | One unit | What ending the Episode means |
| --- | --- | --- |
| lexical probe | one previously unprocessed ranked chunk | return control to the page so it can propose another vocabulary over the remaining chunks |
| page | one completed lexical-probe Episode | finish this document and return its distinct findings to the search |
| search | one fetched page or document | stop consuming that Firecrawl result list |
| strategy | one completed search Episode | stop pursuing that strategy family |
| run | one completed strategy Episode | end the declared acquisition run |

The table binding's child update carries distinct accepted results by column.
The parent treats the completed child as one unit and recalculates its own
counts, estimates, and decision. It does not add together the child's
hypervolume and its own. The full child record is retained only in the trace;
the running parent receives a compact `EpisodeUpdate`.

```text
PARENT EPISODE                         CHILD EPISODE

choose the child --------------------> run the child's own loop
                                                |
                                                v
                                      write the full child trace
                                      and build EpisodeUpdate
                                                |
                  <-----------------------------+
                  |
                  v
       send EpisodeUpdate.controller_input to
       the parent's own controller
                  |
                  v
       update the parent's estimates and decision
                  |
                  v
       expose only EpisodeUpdate.prompt_context
       to the parent's next source call
                  |
             +----+----+
             |         |
         continue     stop
             |         |
             v         v
       choose the    close this Episode and build
       next unit     its own compact EpisodeUpdate
```

Information moves up one level whenever a child finishes:

```text
chunk completes          -> lexical-probe view updates locally
lexical probe closes     -> page receives its distinct results
page closes              -> search receives its distinct results
search closes            -> strategy receives its distinct results
strategy closes          -> run receives its distinct results
```

Each source sees the compact child updates and opaque controller state from its
own Episode. It can use that history to propose different work next time. For
example, a page can replace an unproductive lexical query with abbreviations
found in the document, while a strategy can replace a saturated Web search
with a different search angle. The model proposes the next string; the
numerical component decides whether there should be another attempt.

## Adding a new Episode type

A new Episode type is made by connecting new work to `Episode`; it does not
need a new loop.

First, declare the level. State plainly what one turn processes and what useful
result one turn can add:

```python
grain = Grain(
    name="document_search",
    unit="one document returned by this search",
    result="the binding-defined result returned by one document",
    controller=controller_function,
)
```

Next, write a source that uses the Episode's history to return one item at a
time. Return `None` when there are no more items:

```python
class ToolSource:
    def next(self, view):
        # view.updates contains compact messages from completed children.
        return choose_next_item(view)
```

Bind the work performed on each item:

```python
source = leaves(
    units=ToolSource(),
    extract=run_tool,
    accept=validate_and_store_results,
    result=make_controller_input,
    label=lambda item: item.stable_name,
)

episode = Episode(
    grain=grain,
    key="search-1",
    source=source,
    on_unit=update_search_memory,
)
```

These functions have separate jobs:

| Function | Job |
| --- | --- |
| `next(view)` | choose the next item using the work already completed at this level |
| `extract(item)` | run the tool and produce candidate results |
| `accept(item, results)` | validate and store results that are supported by evidence |
| `result(item, accepted)` | build the input expected by this Grain's controller |
| `on_unit(...)` | update memory or write logs after the numerical decision has been recorded |
| `on_close(record)` | write this Episode's own full trace or checkpoint without giving it to the parent |

For the table-fill binding, `result` returns an `IncidenceObservation` whose
identities are separated by logical result column. A different Episode type may
bind a different result type and controller.
When the outer Episode uses `run_async()`, the source and bound functions may
also be asynchronous.

A stable result key names a subject and result column. The same result found
again must return the same key, so the estimator records a repeat instead of a
new finding. For example, every supported value for the deaths field of the
same earthquake uses the same result key whether it came from a reported value
or an accepted best guess.

To nest Episodes, make the parent's source return a child `Episode` instead of
an ordinary item:

```python
class ChildEpisodeSource:
    def next(self, view):
        return build_next_child_episode(view)  # or None when finished
```

The child also needs a `to_parent` function. It converts the full child trace
into the compact message the parent actually needs:

```python
child = Episode(
    grain=child_grain,
    key="child-1",
    source=child_source,
    to_parent=lambda record: EpisodeUpdate(
        record_id=record.episode_id,
        controller_input=combine_child_results(record),
        prompt_context=summarize_for_parent_prompt(record),
    ),
)
```

The parent receives that update as one unit. The full `EpisodeRecord` remains
in the recursive trace for audit but is not placed in the parent's source view
or prompt. Do not write a loop around either Episode; calling `run()` or
`run_async()` on the outer Episode runs the complete nested tree.

Finally, create one `Context` for the run and list the permitted nesting order
from outermost to innermost. Controller configuration is already captured by
each Grain's controller function; `Context` does not know its schema:

```python
ctx = Context(
    run_id="run-1",
    order=(run_grain, strategy_grain, search_grain),
)

record = await run_episode.run_async(ctx)
```

Tool calls and model calls belong in `next` or `extract`. Evidence checking and
storage belong in `accept`. Counting must be a direct calculation from the
accepted stored results. The estimator and controller make the numerical
continue-or-stop decision.

The complete method contract is
[docs/ACQUISITION_LOOP.md](docs/ACQUISITION_LOOP.md). Where another document
describes a phase-batched round loop or gives the numerical component ownership
of `Episode`, that description is stale.

## Repository layout

```text
method_loop/             generic Episode method: iteration, nesting, runtime
                         identity, scope routing, child-to-parent results,
                         and record trees
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
or rounds control.

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
