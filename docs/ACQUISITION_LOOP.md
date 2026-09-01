# The Acquisition Control Loop

Status: **amended 2026-08-28; incidence migration in progress.** The 4A--4E
build established the composed `Episode` method. The current method uses
incidence samples, exact rolling rarefaction, a generic role-based
`IncidenceEstimate`, bias-corrected incidence Chao2 as the current
reachable-total estimator, and a versioned numerical controller. Build and
live-verification state are tracked in `docs/CONTROL_LAYER_BUILD.md`.

This is the governing design for the acquisition span — everything between
"what should we try next" and "did that produce a datapoint we were aiming
at". Where any other document describes the flow or estimator differently,
this document wins and the other statement is historical or stale. Build state
is tracked in `docs/CONTROL_LAYER_BUILD.md`.

Build phases and owners are tracked in `docs/CONTROL_LAYER_BUILD.md` (the
4-series rows). Evidence standards are `docs/CONTROL_LAYER_EXPERIMENTS.md`.

## The design rule

Control of acquisition is one span:

> feature decision → search strategy → what counts as a value → extract →
> count over time → a rarefaction signal **in numbers** decides
> continue / stop / switch.

That span is a **closed loop, and the loop is a first-class modular
function** — not a sequence of pipeline phases. The same loop runs at every
acquisition surface: provider (firecrawl) search, GASL graph walking, and
strategy selection above both. Broad searches and broad walks are the intended
mode of operation; they are safe *because* the numbers say when to quit, so
nothing needs to pre-narrow a search to control cost.

```
THE ACQUISITION EPISODE (one generic Episode, instantiated at every surface):

   strategy ──► unit source ──► unit ──► extract ──► credit against
   (what to     (search hits /          (values)     declared targets
    try next)    walk frontier)                           │
      ▲             ▲                                     ▼
      │             │                            incidence samples by channel:
      │             │                            Q1, Q2, rarefaction, Chao2 —
      │             │                            NUMBERS, measured only
      │             │                                     │
      └──── switch ─┴──── continue / stop ◄─── verdict ───┘

 NESTING:  item-loop  ⊂  search-loop  ⊂  strategy-loop      (provider surface)
           iteration-loop  ⊂  walk-loop  ⊂  query-loop      (GASL surface)
           — the same kernel at every grain; credits fan upward through scopes
```

Concretely, on the provider surface: one Firecrawl search may batch many
results, but **each returned item is processed one at a time**. Fetch and judge
one item, extract from its chunks, persist and accept any evidence-backed
criterion assertions, project those accepted stable identities into channel
incidence, then update the rolling rarefaction and Chao2 numbers before pulling
the next buffered item. Provider batching is an acquisition optimization; it
is never a processing count or stop rule. The per-search verdict decides
whether to keep consuming that result list; the per-strategy verdict decides
whether that strategy family is locally saturated; and the run verdict decides
whether the whole declared scope has converged. Graph enrichment happens as a
post-verdict side effect and never as a precondition of crediting. On the GASL
surface, each walk unit reports incidence the same way, and the walk quits on
the numerical verdict, not on a fixed unit cap.

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
| Inside one provider search | one fetched page or document | non-trivial values credited to declared columns, and rows completed | stop consuming that result list |
| Inside one seed expansion (GASL surface) | one depth step (hop level) | node encounters at that depth | stop deepening from that seed (today: runs to its caps, disclosed) |
| Inside one GASL walk | one seed expansion (a completed seed loop) | that seed's node encounters | quit the walk |
| Inside one GASL query | one completed walk | that walk's encounters | stop walking for that query |
| Search arc / strategy (above both surfaces) | one completed search query or walk — each mutated query nested below is one unit | the identities that search contributed | abandon the arc; move to an untried, semantically distant strategy — a big mutation, a new idea |

A grain not in this table gets its row by the same derivation, and a
surface that cannot name its unit and its credit has not bound to the loop.

## The statistical contract

The method is incidence-based. For one exact `(scope_path, epoch, channel)`,
one eligible loop unit contributes an immutable **set** of accepted stable
identities. Repeats inside that unit collapse to one incidence. The same
identity in a later unit is a recurrence: it does not increase observed
richness, but it does increase that identity's incidence frequency and changes
`Q1`, `Q2`, rarefaction, and Chao2.

The channel schema is frozen for an estimator epoch and contains no task
vocabulary. A question binding declares ordinary criterion-ID channels for
each real result column, a completed-row-ID channel, and, where declared,
separate accepted `BestGuessCell` channels. The Episode method core derives
the overall ordinary-criterion union; an application cannot submit a pooled
channel that hides a weak required column. Required channels are conjoined by
the controller and are never averaged or summed.

### Rolling exact rarefaction

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

### Reachable total: the fixed estimator role, currently Chao2

The reachable-total estimator uses **all eligible incidence samples in the
current statistical epoch**, not only the rolling window. Let `T` be their
count, `D` the observed distinct identities, `Q1` the identities occurring in
exactly one sample, `Q2` those occurring in exactly two, and `A=(T-1)/T`.

```
unseen_hat     = A * Q1 * (Q1 - 1) / (2 * (Q2 + 1))
expected_hat   = D + unseen_hat
remaining_hat  = max(0, expected_hat - D)
```

The current implementation is bias-corrected incidence Chao2. It estimates
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

`IncidenceEstimator` owns the calculation and exposes one role-based
`IncidenceEstimate` per channel. Bias-corrected incidence Chao2 is the current
versioned internal calculation filling the numeric `expected_results` and
`remaining_results`
roles. A future reachable-total calculation fills those same roles under a new
estimator version and experiment while preserving the `IncidenceEstimate`
contract.

### Generic numeric estimate roles and special states

The interface is role-based. Every channel `IncidenceEstimate` carries the
same typed `NumericBand` shape and must fill these required roles:

- `observed_results` — cumulative exact `D` in the epoch;
- `rarefied_results` — exact `R_W(m)` for the current window;
- `expected_results` — the active reachable-total estimator's estimate;
- `remaining_results` — derived `max(0, expected_results-observed_results)`;

It also carries exact `window_observed_results=S_W`, `W`, `m`, incidence sample
count, scope/epoch/channel identity, and method/component versions. Additional
statistics use a generic typed numeric-diagnostic collection with stable names
and formula versions; they do not enlarge the required estimator interface.
The current controller records `rarefaction_tail_yield` there.

Each band contains numeric `value`, `lower`, `upper`, `status_code`,
`uncertainty_code`, and `alpha`. Normal finite values use `status_code=0`.
The special codes are fixed:

- `-1`: insufficient eligible observations;
- `-2`: enough observations exist, but a finite total is not identifiable by
  this method.

For a coded band, `value=lower=upper=status_code`; `uncertainty_code=-1` and
`alpha=-1`. Observed richness is never coded. A controller-derived tail yield
is never `-2`.
With `T<2`, total and remaining are `-1`. With `T>=2` and `D=0`, total and
remaining are `-2`: an all-empty incidence history cannot distinguish an empty
reachable universe from one the active distribution has not found. A normal
band is finite and non-negative with `lower <= value <= upper`; no record may
contain `null`, NaN, infinity, or prose in a numeric field. Boundary validation
rejects malformed inputs rather than laundering them into another status.

### Current versioned arithmetic controller

The controller is a versioned numerical component over an
`IncidenceEstimate`.
Every controller version declares the estimate roles and numeric thresholds it
consumes, consumes the `rarefied_results` role, and emits its arithmetic and
derived diagnostics for recomputation.

The current controller version derives tail yield from the rarefied role and
window metadata. For each required channel `c`, configuration declares numeric thresholds
`gamma_c` (tail yield), `rho_c` (remaining findings), and a positive integer
streak length `K`. On each eligible observation:

```
flat_c = tail.status_code == 0 and tail.upper <= gamma_c
done_c = flat_c
         and remaining.status_code == 0
         and remaining.upper <= rho_c
```

One epoch-scope controller owns `flat_streak` and `done_streak`; channels do
not keep independent stop streaks. Any required `-1` resets both and continues.
If not all required channels are flat, both reset and acquisition continues.
If all are flat but any total is `-2` or any remaining upper bound exceeds its
threshold, `flat_streak` advances and `done_streak` resets. If every channel is
done, both advance.

At `done_streak >= K`, a non-root episode returns local convergence to its
parent and a root episode records whole-scope convergence. At
`flat_streak >= K` without `done`, a non-root episode returns local saturation
so its parent can mutate or switch. The same condition at the root starts a
new statistical epoch if an admissible distribution-changing mutation exists;
otherwise it terminates with a typed incomplete result. It never masquerades
as whole-scope convergence. Coverage may be emitted as a diagnostic, but it is
not an independent decision edge.

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
  credit  : str            # one sentence: what one credit IS at this grain
  channels: ChannelSchema  # fixed, versioned channel declarations
  control : NumericalControllerConfig
                           # version, declared input roles, numeric thresholds;
                           # never a surface stop callback

Episode[Unit, Extracted]                 # one instance of one grain
  grain   : Grain
  key     : str            # this instance's scope key (task id, strategy
                           #   id, walk id); its scope is the complete ancestry
                           #   Path ending in (grain.name, key)
  source  : UnitSource     # next(view) -> Unit | None. `view` is the
                           #   parent's read-only running state: records so
                           #   far, curve, verdict. A plain list is wrapped
                           #   as a source that ignores the view. A proposer
                           #   (the switch edge) reads the view. For an outer
                           #   grain, a Unit is a child Episode
  extract : Extractor      # Unit -> Extracted. String work may live here:
                           #   fetch + judge + extract on the provider
                           #   surface; pure expansion on the graph surface
  credit  : Crediter       # (Unit, Extracted) -> accepted assertion records.
                           #   It cannot construct incidence samples, set
                           #   eligibility, pool channels, or return a verdict
  on_unit : Hook?          # receives the immutable post-verdict record.
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
        contribution = unit.acquire(ctx)  # ONE path: a Leaf runs extract then
                                          #   credit; an Episode runs the inner
                                          #   loop and carries its own record
        sample = incidence.sample(        # core-owned within-unit dedupe,
            grain.channels, contribution # channel union and eligibility
        )
        unit_yield = scoped.observe(scope, epoch, sample)
        curve = scoped.curve(scope)
        verdict = numerical_controller.evaluate(curve)
        record = UnitRecord(unit, contribution, unit_yield, curve, verdict)
        on_unit(unit, contribution, record)  # post-verdict publication only
        if verdict.ends_episode:          end = verdict.end_reason; break
    return EpisodeRecord(grain, key, epoch_records, units, end, estimates, verdict)
    #   a child episode's record hangs on ITS unit's record (UnitRecord.child):
    #   one representation of the tree, built by the loop that owns it
```

Fixed in the Episode method core: the step order; safety is checked before a
unit is pulled; accepted identities are deduplicated into incidence by the
core; `IncidenceEstimator` emits its complete role-based `IncidenceEstimate`
after every eligible unit; the arithmetic verdict is evaluated before a hook
can observe the record; epoch
transitions and streaks have one owner; and a child episode is one unit of its
parent. Records nest as episodes do. The method core calls no model and does no
I/O — whether an injected `extract` fetches a page is invisible to it.

Bound at the method level: `source`, `extract`, the deterministic acceptance
projection, the post-verdict observation hook, explicit safety boundary,
incidence estimator, numerical controller, fixed channel declarations, and
numeric thresholds. The current estimator binding is incidence rarefaction
plus bias-corrected incidence Chao2 and fills the stable `IncidenceEstimate`
roles. A replacement estimator fills those same roles under a new registered
experiment. The numerical controller can also be versioned, but must
declare and consume the required rarefaction role and emit recomputable
arithmetic rather than becoming an arbitrary stop function. Python code remains editable, but this class makes the
correct method the obvious path and makes an alternative stop rule require a
visible rewrite rather than a harmless-looking configuration change.

Fixed in `Episode`: order of operations, eligibility handling, identity,
nesting, fan-up, record shape, and epoch lifecycle. Rarefaction is one attached
numerical component. It never owns the method that calls it.

### Fan-up, stated

A parent observes the eligible child's **distinct accepted identities by
channel**, each once. It does not receive the child's encounter multiplicity
or a precomputed scalar. At the parent, an identity's incidence frequency is
the number of eligible children that contributed it: at the strategy grain,
`Q1` means identities found by exactly one completed search and `Q2` means
identities found by exactly two. Each grain deduplicates its own unit, so an
identity new within one child can correctly be a recurrence at the parent.

The full child record always remains nested and auditable. A child enters the
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
source is a **proposer** that reads the run's view (the finished strategy
episodes' records, as text) and samples an untried, semantically distant
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
accepted identities -> incidence -> estimates -> arithmetic verdict
                                                  |
                                                  v
                              post-verdict typed learning observation
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
  -> accept the real table cell
  -> emit the stable accepted identity into its declared channel
```

Every accepted credit therefore carries at least the stable criterion ID,
typed value and unit, assertion/version ID, source ID, source content hash or
version ID, chunk/span locator, supporting-text hash/reference, and acceptance
rule version. A graph edge, `source_ref`, populated value, candidate, or model
claim cannot substitute for this chain.

Three credit kinds are accumulated separately:

1. **Ordinary per-column criterion credits.** Each declared real result column
   has its own channel. The identity is the accepted stable criterion ID, not
   `table|column|normalized value`; changing an extracted spelling does not
   mint a new finding. The method core also derives an overall union of these
   ordinary channels for reporting, never as a replacement for their separate
   verdicts.
2. **Row-completeness credits.** A separate channel receives the stable row or
   subject identity once when every required real column has an accepted cell.
   Re-finding that row does not mint it again. A row can include an anchored
   accepted best guess where its contract allows one, but the record must
   disclose which cells were direct and which were derived.
3. **Best-guess credits.** Best guessing is a mandatory real-column mechanism,
   not optional metadata. For each enabled real column, an accepted
   `BestGuessCell.id` enters a separate best-guess channel, while the accepted
   criterion ID also enters that column's ordinary channel and the overall
   union. Candidate generation alone earns nothing. Acceptance requires an
   acyclic derivation terminating in persisted direct assertions: named and
   versioned rule, exact input assertion IDs, typed inputs and output, unit,
   deterministic recomputation, and source/span traceability. A model may
   extract a relation or propose a derivation string; deterministic code
   performs the numerical transformation.

The mapping from an extracted field to a declared column is contract data:
declared names, aliases, types, units, and criterion IDs. Any fallback matcher
is disclosed by rule version and measured in the live run. Acquisition
incidence is control telemetry—where accepted findings are still arriving—not
scalar reward. Reward may consume a transition only through its own evidence,
identity, attribution, and cost contract; it never scores raw incidence volume.

### Cost has one owner

Cost is metered by `question_pipeline/costs.py` (phase 1B) at the
`SOURCE`/`SEARCH` scopes, which are the provider surface's units; the
episode carries no meter of its own. A ledger writer joins a unit's cost
record to its `UnitRecord` by scope key. `gasl/` has no cost metering
today; its units carry no cost, disclosed as such until 1B's owner is
extended there — never by a second meter.

### The compositions

| Surface | Composition (outer ⊃ inner) | The unit at each grain |
| --- | --- | --- |
| Provider (re-bound in 4E-c) | run ⊃ strategy ⊃ search ⊃ page | a proposed strategy Episode ⊃ a search Episode ⊃ one fetched page or document |
| GASL walk (4B, one grain bound) | query ⊃ walk ⊃ seed | a walk Episode ⊃ one seed expansion; the depth steps inside a seed run to their disclosed caps (4E-b registers whether a depth-step verdict would have changed anything, and binds it if so) |

A search returns pages, so the page is the provider surface's natural unit;
chunks are how a page is fed to extraction, not a grain. The strategy grain
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

### Current migration sequence

The historical 4A--4E sequence established the Episode composition and is
complete as structural evidence. The current sequence is deliberately atomic
at the live boundary:

1. land the generic incidence sample and estimator records with no controller,
   Episode wiring, or second live path;
2. replace the current estimator/controller inputs to `Episode` with that
   estimator and the numerical controller in the same phase;
3. bind evidence-first accepted identities and the frozen per-column channel
   schema;
4. verify the complete composition with a registered live Firecrawl plus LLM
   run that continues until the numerical verdict ends it.

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

`rarefaction/` owns only incidence-estimator mathematics and its typed numeric
contract. It does not own Episode identity, scope lifecycle, nesting, control,
memory, persistence, or a surface. This is not a restoration of the pruned
`cd44ebb` `question_pipeline/rarefaction.py`.

| Module | Owns |
| --- | --- |
| `method_loop/episode.py` | The single composable loop: safety check → pull one unit → extract → accept → construct incidence sample → estimate → arithmetic verdict → publish post-verdict observation. It owns Episode/unit identities, nesting, fan-up, and records |
| `method_loop/runtime.py` | Path/epoch state that attaches the estimator and controller to each Episode scope |
| `method_loop/controller.py` | The versioned numerical controller over the estimator's stable `IncidenceEstimate` roles |
| `rarefaction/accumulator.py` | `IncidenceEstimator`: immutable per-unit incidence sets, within-unit deduplication, `T`, `D`, `Q1`, `Q2`, exact rolling rarefaction and pairwise uncertainty, and the current bias-corrected incidence Chao2 reachable-total estimate |

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

`gasl/` may import `method_loop/` for the generic Episode method and
`rarefaction/` for its estimator contract. This is not a weakening of the
layering rule in `docs/RUNTIME_INVARIANTS.md`: both are lower, schema-agnostic
layers over opaque identity tokens. The
frozen-inventory checker (`tools/check_runtime_invariants.py`) was amended in
phase 4A to admit `rarefaction` as a permitted lower layer; the
`nano_graphrag`/`question_pipeline` prohibition is unchanged.

## Surface bindings

1. **Provider search** — `question_pipeline/acquisition.py`. Unit = one
   fetched item (page/paper). Firecrawl may return a large batch, but the
   Episode pulls and processes buffered items one by one: fetch → relevance
   judge → extract → persist evidence → accept → incidence → estimate →
   verdict. The per-search verdict stops consuming that result list; the
   per-strategy verdict decides when to switch strategy; the root verdict is
   the only convergence of the whole run. Graph enrichment is a post-verdict
   side effect. No page count or search count is the method stop rule.
2. **GASL walking** — `gasl/commands/graph_nav.py`. Unit = one seed
   expansion. Credits = the distinct opaque node identities encountered by
   that eligible seed expansion; recurrence across expansions supplies
   incidence. The GASL binding moves through the same Episode
   estimator/controller boundary. GASL stays schema-agnostic: it counts opaque identities; it
   never knows what a result column is.
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
- The harvester's inline item loop in `question_pipeline/search.py` and the
  hand-kept fan-up in `AcquisitionController` (`_search_new`,
  `close_search`) — 4C's first binding — are replaced by an `Episode`
  composition (phase 4E). The controller survives as the thing that builds
  the composition and writes ledger decisions from episode records.
- The historical `rarefaction/stop_rule.py` and its exports and configuration fields are
  deleted in the atomic Episode migration.
- `IncidenceEstimator` and `IncidenceEstimate` are the single estimator and
  decision-facing output names for incidence rarefaction.
- `question_pipeline/reward.py` stops re-deriving credit at round end and
  consumes episode ledgers. The reward's definition of a datapoint (real,
  evidenced, never operational volume) is unchanged.

What survives, deliberately: the per-source extraction ledger in
`_ingest_papers` — the recorded distinction between "extraction ran and found
nothing" and "extraction never ran" — is necessary to determine sample
eligibility. The acceptance/relevance machinery in `question_pipeline/search.py`
survives as unit acquisition.

## What this does not change

- **No source filters.** Verdicts judge measured yield, never domains or
  allowlists. Content-based judging stays where it is.
- **No truncation.** Curves and ledgers are windowed with disclosure when
  payload limits bite, never sliced silently.
- **No test suite.** The method core is pure arithmetic, and the temptation to
  unit-test it will be strong. Verification is still a live run designed as
  an experiment, per `CLAUDE.md` and `docs/CONTROL_LAYER_EXPERIMENTS.md`.
