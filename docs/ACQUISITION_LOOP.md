# The Acquisition Control Loop

Status: **amended 2026-09-06; failure-aware estimator-controller replacement
implemented as an unvalidated draft.** The composed `Episode` method is
established. One opaque estimator-controller implementation owns estimation,
threshold state, and the resulting verdict. Review and validation state are
tracked in `docs/NEXT_STEP.md`.

This is the governing design for the acquisition span — everything between
"what should we try next" and "did that produce a datapoint we were aiming
at". Where any other document describes the flow or estimator differently,
this document wins and the other statement is historical or stale. Build state
is tracked in `docs/CONTROL_LAYER_BUILD.md`.

Build phases and owners are tracked in `docs/CONTROL_LAYER_BUILD.md` (the
4-series rows). Evidence standards are `docs/CONTROL_LAYER_EXPERIMENTS.md`.

## The design rule

Control of acquisition is one span:

> feature decision → search strategy → extract → accept evidence →
> write typed result state → assign credit once → count over time →
> a rarefaction signal **in numbers** decides
> continue / stop / switch.

That span is a **closed loop, and the loop is a first-class modular
function** — not a sequence of pipeline phases. The same loop runs at every
acquisition surface: provider (firecrawl) search, GASL graph walking, and
strategy selection above both. Broad searches and broad walks are the intended
mode of operation; they are safe *because* the numbers say when to quit, so
nothing needs to pre-narrow a search to control cost.

```
THE ACQUISITION EPISODE (one generic Episode, instantiated at every surface):

   strategy ──► unit source ──► unit ──► extract ──► accept evidence
   (what to     (search hits /          (values)              │
    try next)    walk frontier)                               ▼
      ▲             ▲                         typed result state
      │             │                                  │
      │             │                                  ▼
      │             │                         ONE credit assignment
      │             │                                  │
      │             │                                  ▼
      │             │                          numerical control component:
      │             │                          estimate → threshold → verdict
      │             │                            NUMBERS, measured only
      │             │                                     │
      └──── switch ─┴──── continue / stop ◄─── verdict ───┘

 NESTING:  table-query Leaf ⊂ table ─┐
                                    ├─⊂ page ⊂ search ⊂ strategy ⊂ run
           chunk Leaf ⊂ lexical-probe┘
                                                               (provider surface)
           seed ⊂ walk ⊂ query                                (future GASL binding)
           — the same method at every grain; compact updates pass between scopes
```

Concretely, on the provider surface: one Firecrawl search may batch many
results, but **each returned item is processed one at a time**. Fetch and judge
one item, extract from its chunks, persist and accept any evidence-backed
criterion assertions, write the accepted values into the typed result state,
and assign credit from that resulting state. The same stable assignment
identities enter channel incidence, then the bound estimator-controller
transition runs before pulling
the next buffered item. Provider batching is an acquisition optimization; it
is never a processing count or stop rule. The per-search verdict decides
whether to keep consuming that result list; the per-strategy verdict decides
whether that strategy family is locally saturated; and the run verdict decides
whether the whole declared scope has converged. Acquisition never mutates a
graph. A completed run may emit a separately reviewable graph-addition proposal
for a later explicit merge. On the GASL surface, each walk unit reports
incidence the same way, and the walk quits on the numerical verdict, not on a
fixed unit cap.

## Credit has one owner

Evidence acceptance establishes that a value has a valid source chain; it does
not itself earn method credit. The accepted value is first written into the
binding's typed result state. The bound projector then emits the stable
one-dimensional identities that the resulting state actually contains,
separated by column. Those identities feed incidence and parent fan-up. The
paired numerical component is the one owner that assigns method credit from
the resulting vector. Learning and reward/cost reports consume that recorded
credit; they do not assign another one.

For table-fill bindings the result state is the declared table. Therefore an
accepted registry cell that was not materialized in that table cannot enter a
table-fill incidence sample. Reported and best-guess alternatives share their
declared logical value-slot identity. Reappearance of that identity in another
eligible unit remains recurrence for incidence estimation; it is not a second
distinct finding.

The accepted identities are one-dimensional contributions, separated by
declared result column. The numerical component retains that complete vector,
normalizes every axis by its own reachable-total estimate, and reduces the
vector to marginal dominated hypervolume. That scalar is the method's **only
credit**. It is recorded for learning and routing, and its predicted value for
the next unit is the controller's sole stop statistic. Per-column incidence and
uncertainty remain visible because they explain the scalar and identify where
future search should concentrate; they are not parallel credits or parallel
stop rules. If any required normalization is unavailable, the hypervolume
credit carries numeric insufficient-information status rather than selecting a
fallback scale.

## Decisions are numerical; LLMs are string experts

This is the central design theme of every agentic workflow in this repo,
stated by the operator, and repeated because it has been violated before.

**The principle.** A decision is a branch taken on numbers; a model is an
operator on strings. So every decision edge in every loop is a numerical
rule over measured counts, and every model call sits on a string task whose
output the rules consume as data. The test for any operation: if its output
is a branch or a number that steers the loop, it is a rule; if its output is
a string produced from strings, it may be a model.

**Decision edges — numerical rules.** The `verdict → continue / stop / switch`
edge in the diagram; when to mutate; which strategy family comes next;
which columns and rows count toward a target. Each is an explicit rule with
its inputs and threshold written down, recomputable by hand from the
emitted numbers. A rule whose inputs are not measurable marks a measurement
gap, and the fix is to measure. The boundaries, stated because they are
where the design has failed before: **a decision is numerical only — not
numerical plus a model.** Passing a curve, a fit, or a table of counts to a
model and asking it to decide is the same violation as asking it outright.
A model never emits a count, an estimate, or a verdict that a branch
consumes.

**String tasks — models.** Extracting values from text; filling a cell from
its source; sampling a new prompt or query string (mutation — a model is an
expert at sampling new strings); judging how far apart two strings are
semantically; judging the content of a text for relevance. These are
instances, not the list: any task whose input and output are strings and
whose quality is a property of strings belongs here. Where a model returns a
number (a semantic distance, a relevance grade), the number is data for a
rule with a written threshold; the model does not also decide what the
number means for the loop.

**The unit of accumulation is the loop's unit at each grain.** A rate needs a
denominator, and the denominator is whatever one turn of that grain's loop
consumes. To derive it for any grain: name the thing one iteration pulls
(the unit), name what an iteration can add toward the declared targets (the
credit), and the stop rule's threshold follows over credits per unit. Every
grain in the nesting has its own unit, its own accumulator, and its own
verdict; credits fan upward through the scopes so an outer grain's unit is
one completed inner loop. The two landed surfaces, as instances:

| Grain | Unit that advances the count | Credit | What "stop" means |
| --- | --- | --- | --- |
| Inside one provider search | one fetched page or document | accepted typed logical value-slot identities | stop consuming that result list |
| Inside one seed expansion (GASL surface) | one depth step (hop level) | node encounters at that depth | stop deepening from that seed (today: runs to its caps, disclosed) |
| Inside one GASL walk | one seed expansion (a completed seed loop) | that seed's node encounters | quit the walk |
| Inside one GASL query | one completed GASL operation track — a graph-reading operation: a GRAPHWALK as a completed walk episode, or a FIND / SUBGRAPH / GRAPHCONNECT / GRAPHPATTERN leaf; pure state transforms ride inside the source and are never units | the distinct opaque node identities that operation encountered, each once | stop executing further operations for that query |
| Search arc / strategy (above both surfaces) | one completed search query or walk — each mutated query nested below is one unit | the identities that search contributed | abandon the arc; move to an untried, semantically distant strategy — a big mutation, a new idea |

A grain not in this table gets its row by the same derivation, and a
surface that cannot name its unit and its credit has not bound to the loop.

## The statistical contract

The numerical method is incidence-based. For one exact
`(scope_path, epoch, channel)`, one observed loop unit contributes an immutable
**set** of accepted stable identities. Repeats inside that unit collapse to
one incidence. The same identity in a later unit is a recurrence: it does not
increase observed richness, but it remains part of the estimator's recurrence
history.

Every attempted unit reaches the numerical component with a typed observation
status. `observed` means acquisition and evaluation completed; its identity set
may contain new findings, repeats, or nothing. `failed` means the attempt did
not produce an evaluable observation and must remain visible to failure-aware
estimation. `excluded` means the unit was invalidated and does not enter the
estimator. Failure is never silently converted into successful zero yield.

The channel schema is frozen for an estimator epoch and contains no task
vocabulary. A question binding declares one channel for each logical result
slot. A reported column and its best-guess alternative occupy that same slot;
they are evidence routes, not separate incidence dimensions. Row completion is
a diagnostic projection of those slots and is not a channel. The bound
rarefaction component derives the overall logical-slot union; the generic
Episode method never sees a column or channel. Required channels are conjoined
by the controller and are never averaged or summed.

### Active enclosed estimator arithmetic

The active paired component is the joint preferential new-incidence model
specified in `docs/TABLE_FILL_POLICY_LEARNING_WHITEPAPER.tex` under "Active
numerical amendment". For every channel, a successfully evaluated unit enters
with its number of newly observed stable identities, including a real zero;
repeated identities do not increase that count. A compute, provider, decoding,
or evaluation failure enters the coupled observation process without inventing
a zero yield. Excluded units enter neither process.

The model emits `expected_next_discoveries` for every column. The paired
component combines those bands with per-column observed and reachable richness
to predict the next unit's marginal hypervolume credit. Its scalar upper bound
is compared with one `gamma`; no column can independently stop the scope.
`remaining_results` labels that stop as convergence or
saturation/incompleteness; it is not a second stop gate. Every observed or
failed attempt recomputes the numeric report, method credit, and verdict. The
Episode sees only that generic transition.

### V22 comparison estimator arithmetic

The following rolling rarefaction and Chao2 calculations describe the V22
comparison implementation. They remain here as the historical mathematical
record; they are not the active estimator. The recorded V22 stream lacks the
service-failure observations required to validate the active estimator.

#### Rolling exact rarefaction

Let the trailing window contain `W` eligible incidence samples and let `m`
satisfy `W >= 2` and `1 <= m < W`. For identity `i`, let `y_i` be the number
of window samples containing it, and let `S_W` be the distinct identities in
the full window. The emitted rarefaction count is

```
R_W(m) = sum_i [1 - C(W - y_i, m) / C(W, m)]
```

This is the real expected distinct count at subsample size `m`, conditional on
the observed trailing window. The method record exposes this rarefied estimate,
the exact full-window observed count `S_W`, and `W/m`. The current controller
version derives the rolling tail-yield diagnostic

```
g_W(m) = (S_W - R_W(m)) / (W - m)
```

It is the average expected new-identity yield per remaining sample across the
observed tail of the rarefaction curve. It is deliberately named
`rarefaction_tail_yield`, not a generic marginal: `R(m)-R(m-1)` is a different
local-slope statistic and is not the current controller's calculation. Tail
yield is derived controller telemetry, not a required estimator role. The window advances by one
eligible unit and is recomputed each time; windows are rolling, never disjoint.
`W` and `m` are analytical parameters, not page, search, or strategy caps.

Exact conditional uncertainty retains pairwise incidence. Define

```
a_i  = C(W - |A_i|, m) / C(W, m)
a_ij = C(W - |A_i union A_j|, m) / C(W, m)

V_R = sum_i a_i(1-a_i)
      + 2 sum_{i<j} (a_ij - a_i*a_j)

V_g = V_R / (W-m)^2
```

where `A_i` is the set of window sample indices containing identity `i`.
At declared tail probability `alpha`, the conservative Chebyshev radius is
`sqrt(V/alpha)`. The rarefaction record and any controller-derived diagnostic
label their bounds numerically; neither is described as an exact confidence or
prediction interval. A full empty window has `R_W(m)=0` and the current
controller derives `rarefaction_tail_yield=0` exactly. Before a full window
exists, rarefaction is insufficient and any dependent diagnostic is likewise
numeric status `-1`.

#### Reachable total: V22 Chao2 implementation

The reachable-total estimator uses **all eligible incidence samples in the
current statistical epoch**, not only the rolling window. Let `T` be their
count, `D` the observed distinct identities, `Q1` the identities occurring in
exactly one sample, `Q2` those occurring in exactly two, and `A=(T-1)/T`.

```
unseen_hat     = A * Q1 * (Q1 - 1) / (2 * (Q2 + 1))
expected_hat   = D + unseen_hat
remaining_hat  = max(0, expected_hat - D)
```

The V22 implementation is bias-corrected incidence Chao2. It estimates
richness reachable under
the current scope, epoch, acquisition distribution, acceptance boundary, and
channel—not a timeless global universe. `Q2=0` remains finite under the bias
correction.

The estimator owns its equations directly. Its variance input is computed as

```
V = unseen_hat
    + A^2 * Q1 * (2*Q1 - 1)^2 / (4 * (Q2 + 1)^2)
    + A^2 * Q1^2 * Q2 * (Q1 - 1)^2 / (4 * (Q2 + 1)^4)
```

The Chao2 band uses the same declared Chebyshev tail probability and radius
`sqrt(V/alpha)`, clipped so the total lower bound is never below `D`.
Remaining bounds are derived exactly from the total bounds and `D`; they are
not estimated independently. Its uncertainty behavior is part of the live
experiment and changes only through a newly registered method version.

That historical estimator exposed the same role-based `IncidenceEstimate` per
channel. The active preferential estimator fills `expected_results` and
`remaining_results` under a new version while preserving the
`IncidenceEstimate` contract.

### Method-facing numeric report

Every channel report carries the same typed `NumericBand` shape and fills
these generic result roles:

- `observed_results` — cumulative exact `D` in the epoch;
- `expected_results` — the active estimator's reachable-result estimate;
- `remaining_results` — derived `max(0, expected_results-observed_results)`;

The report also carries incidence sample count, scope/epoch/channel identity,
and method/component versions. Estimator-specific control statistics and
diagnostics use generic mappings of stable names to numeric bands or finite
numbers. The active preferential implementation records fitted observation and
discovery parameters, attempt counts, fit state, and
`expected_next_discoveries` there. Those names do not enlarge the
method-facing interface.

Each band contains numeric `value`, `lower`, `upper`, `status_code`,
`uncertainty_code`, and `alpha`. Normal finite values use `status_code=0`.
The special codes are fixed:

- `-1`: insufficient eligible observations;
- `-2`: enough observations exist, but a finite total is not identifiable by
  this method.

For a coded band, `value=lower=upper=status_code`; `uncertainty_code=-1` and
`alpha=-1`. Observed richness is never coded. A normal band is finite and
non-negative with `lower <= value <= upper`; no record may contain `null`, NaN,
infinity, or prose in a numeric field. Boundary validation rejects malformed
inputs rather than laundering them into another status.

### Combined estimator-controller transition

The estimator and its numerical controller form one opaque component. For one
unit, that component updates every channel estimator, produces one immutable
numeric report, reduces its vector to realized and predicted marginal
hypervolume, applies its injected threshold adapter, and calculates the verdict
as one atomic transition. `Episode` cannot join estimator output to a
separately constructed controller or interpret an estimator-specific control
statistic.

The threshold adapter receives the immutable report and current thresholds and
returns the thresholds used by that transition. Its initial implementation is
the identity operation: thresholds remain fixed. The hook exists so a later
approved numerical adaptation rule can be supplied by composition without
changing `Episode`. Returned thresholds are validated and recorded with the
verdict.

For required channels `C`, let `D_tc` be cumulative distinct accepted
identities after unit `t`, `N_tc` the channel's current reachable-total
estimate, and `g_(t+1)c` its expected new identities in the next attempted
unit. The controller preserves the vector and computes

```
p_tc       = min(1, D_tc / N_tc)
p_next_c   = min(1, (D_tc + g_(t+1)c) / N_tc)
expected_next_hypervolume_credit
           = product_c(p_next_c) - product_c(p_tc)
```

A zero estimated population with zero observations is a completed axis with
coordinate one. A positive observation against a zero denominator is
unidentifiable. The component propagates the numeric bands on `N` and `g` into
a conservative numeric band on expected next hypervolume credit and records
the per-axis inputs beside it.

Configuration declares one numeric `gamma` for expected next hypervolume
credit, per-column `rho_c` values used only to label a stopped scope's remaining
state, and a positive integer streak length `K`. On each eligible observation:

```
flat = expected_next_hypervolume_credit.status_code == 0
       and expected_next_hypervolume_credit.upper <= gamma
done_c = remaining_c.status_code == 0
         and remaining_c.upper <= rho_c
```

One epoch-scope controller owns `flat_streak`. An unavailable hypervolume band
resets it and continues. A non-flat scalar likewise resets it. A flat scalar
advances it.

At `flat_streak >= K`, the episode stops. If every required column is also
labelled done at that transition, a non-root episode returns local convergence
and a root episode records whole-scope convergence. Otherwise a non-root
episode returns local saturation so its parent can mutate or switch. The same
condition at the root starts a new statistical epoch if an admissible
distribution-changing mutation exists; otherwise it terminates with a typed
incomplete result. Coverage may be emitted as a diagnostic, but it is not an
independent decision edge.

A mutation that changes the query or strategy distribution closes the current
epoch and opens a deterministically identified new one. `Episode` owns that
transition and the streak reset; a source can request a mutation but cannot
erase or merge statistical history.

**Two rules every binding carries, both numerical.** (1) Which columns and
rows count toward a target: declared targets and the criteria projection —
which is why crediting depends on declared identity (tracker row 1D-a; its
live diagnosis found identity coming from model-emitted planner prose that
re-rolled each round, the exact violation this section names). (2) How a
strategy is accumulating: credits per unit at the grain above it, so the
strategy verdict reads the same numbers the inner loops emitted.

## The template: one `Episode`, composed

The same seven-step pattern recurs at every grain and on every surface. That
repetition is the signal that there is one higher-order structure with
swappable parts, and that a surface binds to the loop by **composing
instances of it**, never by writing the loop again. This section is the
class template the team builds to and the only place its rules are stated;
every other document points here. `method_loop/episode.py::Episode` owns the
single loop body and template method (phase 4E); nested grains reach that same
body through `Episode.run` or `Episode.run_async`.

### The class

```
Grain                                    # one level of the loop, declared once
  name    : str            # "search", "strategy", "walk", "seed", "run", ...
  unit    : str            # one sentence: what one unit IS at this grain
  result  : str            # one sentence: what one result IS at this grain
  controller: Path -> Controller
                           # a binding-supplied function that constructs one
                           # controller for this Episode path

Episode[Unit, Extracted]                 # one instance of one grain
  grain   : Grain
  key     : str            # this instance's scope key (task id, strategy
                           #   id, walk id); its scope is the complete ancestry
                           #   Path ending in (grain.name, key)
  request : EpisodeRequest # compact parent -> child input
  source  : UnitSource     # next(view) -> Unit | None. `view` carries the
                           #   request, prior compact child updates, and the
                           #   opaque current controller state. It never
                           #   carries full child traces
  extract : Extractor      # Unit -> Extracted. String work may live here:
                           #   fetch + judge + extract on the provider
                           #   surface; pure expansion on the graph surface
  result  : ResultProjector# (Unit, Extracted) -> controller-specific input.
                           #   The method treats that input as opaque
  to_parent: Compressor?   # EpisodeRecord -> EpisodeUpdate. The binding
                           #   decides what the parent controller and prompt need
  on_close: TraceHook?     # receives this Episode's own completed record for
                           #   audit/checkpoint work; never feeds the parent
  on_unit : Hook?          # receives the compact result and controller step.
                           #   Learning memory, graph enrichment and ledgers
                           #   live here; the return is discarded and cannot
                           #   change the current unit's verdict
  safety  : SafetyBoundary?# explicit operator/run boundary only; absent by
                           #   default and never an acquisition stop policy

  run(ctx) -> EpisodeRecord:             # and run_async, same step order
    while True:
        if safety reached:                end = bound_hit;  break   # before pulling
        unit = source.next(view)          # pull
        if unit is None:                  end = exhausted;  break
        if unit is a SourceEnd:           end = unit.kind;  break   # rule 6
        contribution = unit.acquire(ctx)  # a Leaf projects a result; a child
                                          #   Episode returns EpisodeUpdate
        control_step = controller.observe(contribution.controller_input)
        record = UnitRecord(unit, contribution, control_step)
        on_unit(unit, contribution, UnitView(record))
        if verdict.ends_episode:          end = verdict.end_reason; break
    episode_record = EpisodeRecord(grain, key, units, end, controller_state)
    on_close(episode_record)             # child-owned trace publication
    return episode_record
    # EpisodeRecord keeps the complete recursive trace for audit. The running
    # parent sees EpisodeUpdate, not that trace.
```

Fixed in the Episode method core: the step order; safety is checked before a
unit is pulled; one controller function is opened for each Episode path; the
controller returns one internally consistent step after every unit; the
arithmetic verdict is evaluated before a hook can observe the result; epoch
transitions and streaks have one owner; and a child episode is one unit of its
parent. Records nest as episodes do. The method core calls no model and does no
I/O — whether an injected `extract` fetches a page is invisible to it.

Bound at the method level: `source`, `extract`, the result projector, the
controller function, compact request/update construction, the post-controller
hook, and an explicit safety boundary. The controller owns its input shape,
statistics, thresholds, and arithmetic. The table binding supplies incidence
vectors and hypervolume; another binding may supply an entirely different
numeric controller without changing `Episode` or `Context`.

Fixed in `Episode`: order of operations, identity, nesting, full trace shape,
compact message routing, and epoch lifecycle. Rarefaction is one attached
numerical component. It never owns the method that calls it.

### Binding modules and composition

Implement one acquisition level per reusable binding module. An Episode
binding owns that type's `Grain` and controller declaration, unit/source types,
Episode builder, local hooks, and `EpisodeUpdate` compression. When its units
are child Episodes, it accepts a child builder callable. It does not import a
concrete child binding and thereby choose its own place in the tree. The chunk
module owns the Leaf's unit and extract/accept/result wiring; it does not
declare a Grain or pretend the Leaf is an Episode.

The question-pipeline layout is:

```text
question_pipeline/
├── pipeline.py
├── episode_binding/
│   ├── chunk_binding.py
│   ├── lexical_probe_binding.py
│   ├── page_binding.py
│   ├── table_binding.py
│   ├── web_search_binding.py
│   ├── strategy_binding.py
│   ├── run_binding.py
│   └── provider_binding.py
└── utilities/
    ├── acquisition.py
    ├── evidence.py
    ├── extraction.py
    ├── model.py
    ├── rarefaction.py
    ├── replay.py
    ├── search.py
    └── tables.py
```

`episode_binding/__init__.py` links the Episode-specific binding classes into
one provider surface. `pipeline.py` supplies the configured collaborators and
starts the root Episode once. A page may open either a table Episode or a
lexical-probe Episode. Extraction, evidence, table projection, numerical
control, search, and checkpoints remain in their named utility modules.

Do not replace episode-owned bindings with a monolithic context/services object.
Each binding receives only the collaborators it directly calls; new Episode
types and cross-grain responsibilities do not enter shared support.

### Fan-up, stated

A binding converts the completed child into an `EpisodeUpdate`. For the table
binding, its controller input contains the eligible child's **distinct accepted
identities by channel**, each once. It does not carry child-scale hypervolume.
The parent updates its own per-column vector and recomputes marginal
hypervolume on its own reachable-total scale. At the parent, an identity's incidence frequency is
the number of eligible children that contributed it: at the strategy grain,
`Q1` means identities found by exactly one completed search and `Q2` means
identities found by exactly two. Each grain deduplicates its own unit, so an
identity new within one child can correctly be a recurrence at the parent.

The full child `EpisodeRecord` remains nested and auditable in the trace tree.
Its `record_id` joins audit artifacts to the compact update; it is not a route
for parent steering code to recover the trace. The
`EpisodeUpdate.prompt_context` is a binding-specific compression containing
only what the next parent proposal needs. A child enters the
parent's incidence history only when it completed as `exhausted` or by its own
rarefaction convergence/saturation verdict. A child ended by `bound_hit`,
`source_failed`, dependency unavailability, or another invalidating cut does
not enter the parent's incidence sample at all. Its accepted assertions remain
real in the evidence and child records, but treating the partial child as a
parent sample would change the parent's sampling-unit definition and make a
failure or cap look like measured barrenness.

### The switch edge is a source

"Stop" at a grain ends that episode. What to try next is the `source` of
the grain above: at the top of the provider composition the `run` grain's
source is a **proposer** that reads the run's compact strategy updates and
samples an untried, semantically distant
strategy — model string work — yielding it as the next child. The model
returns the candidate strings and a distance number; the rule that accepts
a candidate as "distant enough" is a written threshold on that number. The
decision to ask for another strategy at all is the `run` grain's own
verdict: when strategies stop contributing new identities to the run, the
run stops proposing.

The source may learn from prior work through a separate typed observation
channel. After the current unit's verdict is fixed, the hook may publish
queries attempted, accepted and rejected sources, extracted terms/entities/
relations, declared deficits, costs, provenance references, and the immutable
numeric estimator/verdict record. A later source or query proposer may consume
that history to sample future strings. This channel never adds a credit,
changes eligibility, rewrites the current sample, or changes the current
verdict. The separation is deliberate:

```
accepted identities by column -> incidence vectors -> hypervolume credit
                                                        |
                                                        v
                                       arithmetic scalar verdict
                                                        |
                                                        v
                         post-verdict credit + vector learning observation
                                                        |
                                                        v
                                      future source/query proposal only
```

### Credits — the what-counts rule

The acceptance projection is deterministic over extracted candidates and the
declared target contract. A candidate value earns no incidence. Credit exists
only after the acceptance boundary has durably persisted a source-versioned
assertion and validated the exact criterion binding.

Required order:

```
persist source/version/chunk/span anchor and assertion
  -> validate direct or derived acceptance
  -> materialize the accepted real table cell in typed storage
  -> project typed storage into canonical logical slots
  -> emit each stable logical-slot identity into its one declared channel
```

Every accepted credit therefore carries at least the stable criterion ID,
typed value and unit, assertion/version ID, source ID, source content hash or
version ID, chunk/span locator, supporting-text hash/reference, and acceptance
rule version. A graph edge, `source_ref`, populated value, candidate, or model
claim cannot substitute for this chain.

One typed contribution form constructs the estimator vector: a stable subject
occupying one declared logical result slot in accepted typed storage. Reported
and best-guess columns that share a `value_slot` map to the same identity and
the same channel, so filling both never doubles incidence. Direct evidence is
preferred for presentation when both routes exist. The physical route remains
visible as metadata, including the full anchored derivation for a best guess.

The same canonical projection determines whether a subject occupies every
required logical slot. That row-complete flag is export and learning context,
not another identity, channel, credit, or stop input. Evidence acceptance does
not compute it, and an exporter does not reconstruct it from physical columns.

The method credit is then derived once:

```
accepted typed contributions by column
  -> unique identity sets by column
  -> cumulative per-column richness and estimator bands
  -> normalized column vector
  -> marginal hypervolume
  -> one scalar method credit and one scalar controller statistic
```

The mapping from an extracted field to a declared column is contract data:
declared names, aliases, types, units, and criterion IDs. Any fallback matcher
is disclosed by rule version and measured in the live run. Acquisition
incidence is control telemetry—where accepted findings are still arriving—not
scalar reward. Reward may consume a transition only through its own evidence,
identity, attribution, and cost contract; it never scores raw incidence volume.

### Cost has one owner

Cost is metered by `question_pipeline/utilities/acquisition.py` (phase 1B) at the
`SOURCE`/`SEARCH` scopes, which are the provider surface's units; the
episode carries no meter of its own. A ledger writer joins a unit's cost
record to its `UnitRecord` by scope key. `gasl/` has no cost metering
today; its units carry no cost, disclosed as such until 1B's owner is
extended there — never by a second meter.

### The compositions

| Surface | Composition (outer ⊃ inner) | The unit at each grain |
| --- | --- | --- |
| Provider | run ⊃ strategy ⊃ search ⊃ page ⊃ (table ⊃ table-query Leaf OR lexical probe ⊃ chunk Leaf) | a proposed strategy Episode ⊃ a search Episode ⊃ a fetched page Episode ⊃ either one parsed-table query or one ranked non-table chunk |
| Future GASL binding | query ⊃ walk ⊃ seed | an operation-track unit ⊃ a walk Episode ⊃ one seed expansion; standalone GASL remains independent of this composition |

A search returns pages, so the page is the search grain's natural unit. A page
may open table Episodes over detected structured regions and lexical-probe
Episodes over the remaining text. Each table Episode queries parsed rows;
each lexical-probe Episode consumes previously unprocessed chunks as Leaves.
The two bindings share evidence acceptance and result projection, not source
units or extraction paths. A chunk is a Leaf, not another Episode grain. The strategy grain
(4D) is the `strategy` row: a strategy is an episode of searches that ends
by its own verdict, and the `run` source proposes the next. That is a
change from 4D as first registered (within-round demotion of a stopped
strategy's tasks with an all-stopped override): interleaving searches across
strategies inside a round is not a feature of this design, the override is
replaced by the `run` grain's own verdict, and 4D re-registers to these
semantics.

### Rules the stewards hold every composition to

1. **No loop is written on a surface.** A `for` over units that reads a
   verdict, keeps a per-scope list, or calls `scoped.observe` outside
   `Episode.run` is the loop re-implemented. The provider binding as coded in
   4C is the example:
   its harvester loops inline and consults a controller between pages.
2. **Fan-up is automatic.** A parent never keeps its own list of a child's
   identities (4C's `_search_new` is the example).
3. **A model appears only inside a `source` or an `extract`** — never in
   acceptance, incidence, the arithmetic controller, or anything that reads a
   curve.
4. **Every grain is declared once**: unit sentence, credit sentence, channel
   schema, and numerical thresholds in its `Grain`; the registry of scopes is
   built from the grains.
5. **Records nest as episodes do**, so every verdict recomputes from the
   leaves up — route 2 at every grain from one export.
6. **Every early end is named by the loop, not by a wrapper.** A source
   that stops yielding for a reason other than exhaustion (a node budget, a
   fetch failure) reports that reason into the record; the loop never
   records `exhausted` for a cut. `Episode` checks its declared bound before a
   pull, and a source reports any other cut as a typed `SourceEnd`; every
   binding is checked for the same shape.
7. **`extract` and the hooks share no mutable state.** The 4B walk's
   `expand` reads `len(walked_data)` while `collect` writes it; the
   extractor's behavior then depends on the effect's. 4E-b separates them,
   and a review of any binding looks for a closure that both read and
   write.
8. **One acquisition level, one binding module.** An Episode module owns that
   type's declaration and local behavior; the chunk module owns the terminal
   Leaf binding. The composition file alone chooses parent and child. Shared
   table projection and recording services are not Episode bindings and do not
   live in one.

### Current migration sequence

Split the provider binding bottom-up into individual Episode-type modules,
leaving behavior unchanged at each move. Then link those types in the dedicated
composition module and verify the complete composition in a newly registered
live Firecrawl plus LLM run.

## Why this is a rebuild, not an insertion

The pre-charter flow was phase-batched:

```
WHAT THE CODE WAS (one round, phase-batched):

  plan deficits ─► search ALL tasks ─► accept ALL items ─► extract ALL papers
                   (harvest, full       (relevance judge,   (a phase later)
                    result lists)        caps only)              │
                                                                 │
        reward/credit at ROUND END  ◄─ export ◄─ GASL ◄──────────┘
        (two phases after every keep-going decision
         has already been made)
```

Three structural facts made insertion impossible and mandated the rebuild:

1. **The decision signal was computed after the decision points were gone.**
   Whether extracted values counted toward target columns was derived at round
   end, in the reward exports. Per-item and per-search rarefaction cannot
   exist in that shape: the credits needed to decide "keep pulling items from
   this search?" do not exist while items are being pulled. Feedback reached
   the frontier at round granularity, one round late.
2. **The first implementation did not represent the required statistical
   sample.** It helped expose the correct Episode boundary, but the current
   method needs immutable incidence samples, per-channel rarefaction counts,
   reachable totals, and a role-based numerical controller.
3. **Every bound in the tree was a cap, not a verdict.** Walks had node/seed
   budgets; searches had paper budgets. A cap answers "how much am I allowed",
   never "is this still producing".

## Method composition and numerical components

`method_loop/` owns the generic method and tree. It has no provider access and
no model calls. A surface composes its source, extraction, acceptance,
post-verdict learning, persistence, and safety bindings around `Episode`.

`question_pipeline/utilities/rarefaction.py` owns the paired incidence estimator, its
matching numerical controller, threshold state and adaptation hook used by
question-pipeline Episode types, and their typed numeric contract. It does not
own Episode identity, scope lifecycle, nesting, memory, persistence, or a
surface.

| Module | Owns |
| --- | --- |
| `method_loop/episode.py` | The single composable loop, Episode/unit identities, compact `EpisodeRequest`/`EpisodeUpdate` routing, and the full recursive `EpisodeRecord` trace |
| `method_loop/runtime.py` | Path routing that opens and calls the controller function supplied by each `Grain`; it knows no controller schema |
| `question_pipeline/utilities/rarefaction.py` | The question pipeline's controller implementation: incidence observation, paired estimator-controller transition, numeric report, threshold adapter, and estimator-specific arithmetic |

`stop_rule.py` is removed when the upgraded `accumulator.py` and
`controller.py` are wired. `Episode` is the sole owner of the composed loop
body.

Semantics the kernel enforces, all of which are standing rules of this repo:

- **Measured, never asked.** Every number is arithmetic over observed
  credits. No model emits a count, an estimate, or a verdict.
- **Repeats are incidence, not new richness.** A credit identity counts as
  *new* once in an epoch. It appears at most once inside a sample; recurrence
  across eligible samples changes `Q1`, `Q2`, rarefaction, and Chao2 without
  increasing `D`.
- **No silent failures.** A disabled or unwired crediter must announce itself
  in the emitted record (`crediting_disabled`), because a stream of
  zero-credit units that merely *looks* barren would drive a false stop.
  Every verdict is a typed record carrying the numbers that produced it.
- **Caps become verdicts.** Budget caps survive only as safety bounds and
  must be reported as `bound_hit`, distinct from a yield stop.

## Layering

Standalone `gasl/` is an independent graph query engine and imports neither
`method_loop` nor `question_pipeline`. The future question-pipeline GASL
Episode bindings import the generic method, the local rarefaction component,
and GASL's graph interfaces from above those packages. This keeps numerical
policy out of the graph engine itself.

## Surface bindings

1. **Provider search** — composed from the individual modules under
   `question_pipeline/episode_binding/`. Unit = one
   fetched item (page/paper). Firecrawl may return a large batch, but the
   Episode pulls and processes buffered items one by one: fetch → relevance
   judge → extract → persist evidence → accept → incidence → estimate →
   verdict. The per-search verdict stops consuming that result list; the
   per-strategy verdict decides when to switch strategy; the root verdict is
   the only convergence of the whole run. Graph enrichment is a post-verdict
   side effect. No page count or search count is the method stop rule.
2. **Future GASL search episodes** —
   `question_pipeline/episode_binding/gasl_binding.py`. These bindings can present GASL graph
   operations as nested Episode types and attach the same question-pipeline
   numerical boundary. They are not connected to the current acquisition
   composition. `gasl/commands/graph_nav.py` remains a direct graph operation
   and knows nothing about rarefaction or result columns.
3. **Strategy grain** — phase 4D. A strategy is an Episode whose units are
   search Episodes; credits = the identities each search contributed. Its
   verdict ends the strategy, recorded as a `PolicyDecision` in the control
   ledger; the `run` grain's source then proposes an untried, semantically
   distant strategy (§"The switch edge is a source"). The verdict decides
   *that* a big mutation is due; the model does the string work of sampling
   it (`prompt-mutation-steward` reviews that boundary).

## Teardown

- The phase-batched round core of `question_pipeline/pipeline.py`
  (search-all → ingest-all → credit-at-round-end) is replaced by episode
  composition. `pipeline.py` composes episodes; it no longer sequences
  phases.
- The harvester's inline item loop now recorded in
  `question_pipeline/utilities/search.py` and the
  hand-kept fan-up in `AcquisitionController` (`_search_new`,
  `close_search`) — 4C's first binding — are replaced by an `Episode`
  composition (phase 4E). The controller survives as the thing that builds
  the composition and writes ledger decisions from episode records.
- The historical `rarefaction/stop_rule.py` and its exports and configuration fields are
  deleted in the atomic Episode migration.
- The reward section of `question_pipeline/utilities/search.py` stops
  re-deriving credit at round end and
  consumes episode ledgers. The reward's definition of a datapoint (real,
  evidenced, never operational volume) is unchanged.

What survives, deliberately: the per-source extraction ledger in
`_ingest_papers` — the recorded distinction between "extraction ran and found
nothing" and "extraction never ran" — is necessary to determine sample
eligibility. The acceptance/relevance machinery in
`question_pipeline/utilities/search.py`
survives as unit acquisition.

## What this does not change

- **No source filters.** Verdicts judge measured yield, never domains or
  allowlists. Content-based judging stays where it is.
- **No truncation.** Curves and ledgers are windowed with disclosure when
  payload limits bite, never sliced silently.
- **No test suite.** The method core is pure arithmetic, and the temptation to
  unit-test it will be strong. Verification is still a live run designed as
  an experiment, per `CLAUDE.md` and `docs/CONTROL_LAYER_EXPERIMENTS.md`.
