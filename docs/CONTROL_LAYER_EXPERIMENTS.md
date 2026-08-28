# Control Layer Experiments

What counts as evidence in this build, and how each phase earns it.

> **Acquisition-method amendment — 2026-08-28.** Historical 4A--4E runs below
> supply evidence about Episode composition, nesting, one-unit processing,
> and typed end reasons. `docs/ACQUISITION_LOOP.md` defines the current
> estimator contract. The next acquisition registration is §4G: real
> Firecrawl search results, real LLM extraction, evidence-first
> acceptance, fixed `ChannelSchema` declarations, per-channel incidence, the
> generic role-based `IncidenceEstimate` produced by `IncidenceEstimator`,
> bias-corrected incidence Chao2 internally filling the expected and remaining
> roles, and the numerical controller.

## 4G — incidence estimator and composed stopping method

4G-a replaces the existing `YieldAccumulator` and `YieldCurve` behind the
current `ScopedYield.observe()` boundary with `ChannelSchema`,
`IncidenceEstimator`, and `IncidenceEstimate`. `Episode`, child fan-up, and
nested records remain unchanged. 4G-b wires the numerical controller to that
estimate and then runs the registered live experiment.

The registration must freeze, before the first provider call:

- the question, committed table schema, fixed channel declarations, evidence
  acceptance version, stable identity projection, epoch rule, rolling `W` and
  `m`, `alpha`, per-channel `gamma_c` and `rho_c`, streak length `K`, and any
  explicit run-wide safety boundary;
- the Firecrawl request shape, including its provider batch size, while
  predicting that buffered results are processed one by one and that no
  provider batch count acts as a stop rule;
- exact artifact paths for source/version/span evidence, accepted assertion
  IDs, per-unit incidence sets, `T/D/Q1/Q2`, rarefaction bands, Chao2 bands,
  controller predicates, streaks, epoch transitions, nested child records,
  and post-verdict learning observations;
- independent checks that duplicate findings inside a page do not increase
  its incidence, recurrence across eligible pages changes incidence frequency
  without increasing observed richness, and an eligible child contributes its
  distinct accepted IDs once to its parent;
- a two-sided prediction for each required channel: whether its trailing
  rarefaction upper bound and Chao2 remaining upper bound should cross their
  registered thresholds sooner, later, or not at all relative to another
  channel, with no averaging across channels;
- confirmation that the live decision path consists of accepted incidence,
  typed estimate roles, declared numerical controller inputs and thresholds,
  and recomputable arithmetic verdicts;
- the falsifier that the controller reads Chao2 internals instead of typed
  `IncidenceEstimate` roles, that a controller can decide without declaring and
  consuming the required rarefied role, or that the internal Chao2 calculation
  can emit a verdict, mutate incidence/epoch state, or replace rolling
  rarefaction;
- the falsifier that a bound-hit, failed, or dependency-unavailable child
  enters parent incidence, or that an accepted assertion lacks its exact
  source-version and text-span traceability.

The run proceeds in full until the registered numerical method ends it or an
explicit safety/dependency outcome cuts it. Duration, spend, or a convenient
sample count never shrink or reorder it. Analysis reports each outcome with
what it means, interpretation, and whether it is in scope for the tested
mechanism.

This document is the definition of done. It replaced an earlier per-phase
unit-test contract: `tests/` was deleted and no suite, smoke test, or
plumbing check is to be created (`CLAUDE.md` §Checks). The only mechanical
check is
`tools/check_runtime_invariants.py`; everything else a phase claims is settled
by a live run designed as described here.

## The distinction

A check asserts a value. An experiment manipulates a condition and predicts the
direction of the result before running it.

`assert dedupe(a, a) == [a]` passes on a function that returns its first
argument. The experiment that establishes deduplication works is three
conditions with a predicted ordering: the same query run twice (expect near
100% deduplicated), queries on unrelated topics (expect near 0%), and queries
that are related but distinct (expect somewhere between). Nothing there asserts
a number. What makes it evidence is that the ordering is predicted in advance
and the mechanism has no way to produce it by accident.

Pass criteria here are directional and relational. "Is this sensible, in the
direction we said it would be?" — not "does this equal 7."

The corollary, which is the part that gets skipped: a claim about the pipeline's
own output is the pipeline grading itself. "Datapoints added" means nothing
until a sample has been independently re-derived from the source chunk by
something that did not produce it.

## Knowledge means independent confirmation

Move with knowledge. Knowledge is a claim confirmed through **independent
routes** — different instruments, different failure modes, agreeing.

**Direct repetition is the weakest form of confirmation.** It controls for
provider nondeterminism and nothing else: a mechanism that is wrong in a
systematic way is wrong identically on every repetition. Use repetition only
when no orthogonal route exists, and say so explicitly when you do.

Prefer, in rough order of strength:

1. **Ground-truth route.** An independent instrument re-derives the fact from
   source. Blind — the verifier must not see the pipeline's answer before
   producing its own, or agreement is inflated by anchoring.
2. **Mechanism route.** If the mechanism works, an internal prediction distinct
   from the outcome must also hold. Test the internal, not the output.
3. **Counterfactual route.** Perturb the input signal in a targeted way on a
   live run — a registered condition that differs from the base condition in
   that signal only — and check the decision changes in the predicted
   direction. (Not on recorded data: re-running the decision over a prior
   run's record measures the tree that produced the record.)
4. **Dose-response route.** Vary the amount of the causal ingredient; expect a
   graded response, not a step.
5. **Direct repetition.** Same conditions, again.

Two agreeing routes is the minimum for a claim to be called confirmed. One route
plus repetition is not two routes.

## Register predictions before running

Every experiment records, in `experiments/log/<experiment-id>.md`, **before the
run**: the claim, the conditions, the predicted direction for each, and what
result would falsify the claim.

**Registration must be machine-enforced, in every phase, not only phases that
use the 0E harness.** Carry the `<!-- registered: -->` marker and a spec
fingerprint, and run `assert_prediction_registered` before the first provider
call. A prose sentence asserting "this was written first" is not a timestamp,
and a phase that skips the marker leaves its headline numbers resting on
self-assertion. Any mid-stream narrowing of the sampled population is itself a
registered clause, not a note.

**Register every instrument parameter that can move the result** — sample size,
truncation limits, batch shape, the comparator's model. A parameter first
disclosed in the failure protocol was characterised after the result. Where a
parameter's effect is measured, measure it on **every arm**: a confound
quantified on one condition tells you nothing about a separation. An experiment that cannot state a falsifying
result is not an experiment, and the `experiment-steward` rejects it.

**No tuning to green.** A result contradicting the prediction is a finding. It
is recorded as a finding. It is not made to go away by adjusting weights,
thresholds, or conditions and re-running until the direction flips. Re-running
the same experiment with modified parameters to chase a predicted direction is
the single most damaging thing an unattended agent can do here, because the
resulting number looks like a result and carries no information.

If a parameter genuinely needs to change, that is a new prediction, registered
before the new run, with the old result retained in the log.

**Withdrawing a criterion after the fact: direction decides it.** Sometimes a
registered criterion turns out to be unusable — a threshold that was never
quantified, a measure that graded nothing. Withdrawing it is legitimate *only*
when it is a criterion that **passed**, i.e. one counted in the claim's favour.
Withdrawing one that **failed** is dropping a falsifier after seeing it trip, and
is rejected outright.

The same reasoning, one step to the left, is a violation. So state the direction
explicitly when withdrawing anything, and leave failed criteria standing and
recorded as failed, with any artifact explanation kept separate from the
criterion itself.

Note the three-way choice when a criterion has no registered threshold: setting
a number now is forbidden — a threshold set afterward describes what happened
rather than deciding anything; keeping it undefined and continuing to count it
repeats the original error; withdrawing it is the only consistent option, and
only in the safe direction above.

**Never substitute a control that passed for one that tripped.** The specific
form: an earlier-registered gate fails, a later-registered control passes, and
the later one is quietly used to interpret numbers the failed gate had already
declared uninterpretable. This is the forbidden withdrawal in disguise — it
recovers the evidence, it moves in the direction that favours the claim, and it
is usually never labelled a withdrawal at all, so it evades the rule above.

Controls test different things and do not substitute for each other. A
sensitivity control tests the instrument's **floor** — can it detect a
difference that is really there. A ceiling control tests its **headroom** — how
well the instrument agrees with itself at best. Passing the second says nothing
about the first. Establish sensitivity before interpreting equivalence, in that
order, always.

If a per-site or per-condition log says a number is not interpreted, no summary
or index may interpret it. An index that contradicts the logs it indexes is
reporting a conclusion its own evidence disowns.

**A withdrawn criterion does not carry forward as an unstated pass condition.**
If a later phase wants the same measure to grade something, its tolerance is
registered in *that* phase's registration block, before *that* run.

## When an experiment fails

A failed prediction means you have learned that something in the chain is not
what you thought. It does not tell you which thing. The discipline:

1. **Enumerate candidate causes.** Several. If you can only think of one, you
   have not thought about it.
2. **Design a discriminating sub-experiment for each** — one whose result comes
   out *differently* depending on which cause is real. A sub-experiment
   consistent with every hypothesis tells you nothing.
3. **Order them cheapest-and-most-invalidating first.** A broken join
   invalidates every other hypothesis, so test it before anything subtle.
   **No replay.** A sub-experiment does not run against recorded run data; when
   a full run is too expensive, run a smaller live one — fewer sources, one
   table, one round.
4. **Verify the cause before fixing it.** Do not assume the cause you thought of
   first is the real one. This is the whole difference between an experimental
   approach and a guess: the fix is justified by a sub-experiment that
   distinguished its cause from the alternatives, not by plausibility.
5. **Record the verified cause** in the experiment log, then fix.

Worked example. E1 predicts that `path_score` falls as `evidence_gap` rate
rises, and the result is flat across quintiles. Candidate causes:

| Hypothesis | Discriminating sub-experiment | Cost |
| --- | --- | --- |
| Score/row join is broken — we correlated against the wrong rows | Open the run's own ledger and sample rows; verify the join by ID by hand | reading only |
| A feature is degenerate on this graph (e.g. nearly all routes are depth 2) | Read each feature's distribution from the numbers the run emitted | reading only |
| One feature's scale swamps the others | A small live run per feature with that feature's weight registered at zero, predicting which one moves the gradient | one short live run per feature |
| `evidence_gap` is a bad outcome measure — written for reasons unrelated to path quality | Blind-classify a sample of records as weak/strong context from the chunk; correlate score against that instead | one verifier pass |
| The features genuinely carry no signal for this task | Survives only if all of the above are ruled out | — |

The first two are readings of what the run recorded about itself — analysis
of an outcome, which is what rich capture is for. The third re-runs the
scorer, so it is a live run: recomputing over the recorded rows would score
the old tree and call it the new one (`CLAUDE.md` §Checks, no replay).

## When the instrument fails, go look at the data

A metric that comes back uninterpretable is a fact about your instrument, not
about the world. The wrong response is another metric on the same unit. The
right one is to open the raw outputs and read them.

This is the fallback whenever a measurement cannot be interpreted: when
controls do not discriminate, when a comparator scores the crippled condition
as highly as the real one, when agreement is dominated by items the instrument
could not align rather than by items it judged different. In every one of those
cases the numbers have stopped carrying information and only direct inspection
will say why.

**How much to read depends on which half of the instrument failed, and the two
cases are opposite.**

*If the judgment is unreliable* — the comparator aligned items but graded them
badly — pairs exist and sampling works. Twenty to thirty pairs read properly
beats a thousand scored automatically. Sample deliberately, including cases
that agreed and cases that diverged most, and state how you chose.

*If the matching is broken* — the instrument could not align items at all —
**you cannot sample, because sampling pairs presupposes the pairing that
failed.** Read the whole unmatched set, in both directions, and match it by
hand. That exhaustive pass is the work. Then ask whether your best manual
matching holds up, or whether a different scheme does better.

Two structures worth trying when hand-matching a large residue. Match **within
type** first: it makes the problem tractable, and it turns a type mismatch on
the same referent into a finding rather than an unmatched pair — different
failures the naive instrument collapses. Then treat matching as the
entity-resolution problem it is and use **community detection** over a
similarity graph across both outputs, taking co-membership as a candidate
match. What stays singleton after that is the genuinely unmatched residue.

**Then read what merged.** A merge signal is a hypothesis about identity, not a
verdict, and the reason to believe this matcher when the last one was wrong is
that you inspected its output. Quote both sides verbatim. Do not summarise into
a score.

**Frame it as what it is.** Direct inspection is observational and
hypothesis-generating, not hypothesis-testing. It carries no registered
prediction, produces no rate, and licenses no decision on its own; any
hypothesis it suggests needs its own registered test. What it does give you,
and no metric can, is whether your measurement unit was ever the right one —
and what the right one would be.

## Diagnostic scaffolding is temporary

Investigating a failure means adding code to isolate the thing you suspect.
That code is an instrument, not a feature. **It is removed when the experiment
concludes.** Monitoring code left in place is how a codebase silts up: every
future reader has to work out whether a probe is load-bearing, and every future
change has to preserve it.

Built to be removable, by construction:

- Diagnostic code lives in `experiments/`, in a module named for its experiment.
  It imports the pipeline. **The pipeline never imports it.** A one-way
  dependency makes teardown a deletion rather than a merge.
- Prefer reading the recorded trace, ledger, and cost fields over adding an
  inline probe. This is what phases 1B and 1C are for — the ledger is the
  observation instrument that keeps diagnostics external. If you find yourself
  wanting a probe inside `pipeline.py`, first ask whether the ledger should have
  recorded it.
- Where an inline probe is genuinely unavoidable, it sits behind one named flag
  and is registered in the experiment's teardown list in the log.
- **Teardown is part of done.** After the experiment concludes: execute the
  teardown, run `tools/check_runtime_invariants.py`, and confirm `git diff`
  against the pre-experiment commit shows only the permanent change the
  finding justified. A phase is not done with scaffolding still in the tree.
- **Results are not instruments and must survive teardown.** Raw verdict data
  from a ground-truth route — the verifier's per-packet answers, the packets as
  dispatched, the captured run records — is the evidence for the phase's
  headline number. Delete the analysis code; keep the data under
  `experiments/runs/<id>/`. A phase that tears down its verdicts makes its own
  result unauditable, and review can then check the reasoning but never the
  measurement.

What persists is the **experiment log**, not the machinery. The log is the
durable artifact of this build; the instruments that produced it are disposable.

## Equivalence campaigns

Most experiments here try to detect a difference. Some try to establish there
isn't one — is a cheap model as good as an expensive one at this call site, is
this refactor behavior-preserving. That is a different shape and it fails
differently.

**The trap: a blunt instrument finds no difference anywhere.** A 95% agreement
rate is meaningless on its own, because a lenient comparator returns 95% for
everything including output you know to be bad.

So an equivalence claim requires a **sensitivity control**: a condition whose
output is known to be worse — a markedly weaker model, deliberately truncated
input — with the prediction that the comparator scores it clearly lower. If the
crippled condition scores near the condition under test, the comparator is not
measuring and neither number means what it appears to.

Establish sensitivity before interpreting equivalence. In that order, always.

**The comparator is itself an instrument** whenever the comparison is a judgment
rather than an identity check. Hold it to instrument standards: blind to which
condition produced which output, symmetric under swapping the two, consistent
when re-run on the same pair, and never the same model that is under test.

**Register the threshold first.** What agreement rate would license the switch,
decided before results are seen. A threshold set afterward is a description of
what happened, not a decision rule.

## Per-phase experiment contracts

Real runs against real providers and real search, on a declared table task.
Phases 0E–3B ran on an earlier measure / subject / country / time contract
(named in each phase's own log); the 1D-a and
4-series runs use the earthquake two-grain contract
(`experiments/runs/earthquake-impact/two_grain_table_spec.yaml`). The task is
a condition of the experiment, named in its registration. There is no budget
cap: run until a provider returns out-of-budget, then record what was
collected, mark the experiment incomplete, and continue.

### Model selection

Phase 0M settled model tiering by experiment before any phase experiment ran
(one equivalence campaign per call site; `experiments/log/0M-campaign.md`).
Every run since executes on a known per-call-site configuration, recorded in
`final_answer.json["model_tiers"]`, and a run's costs are uninterpretable
without that block. A call site not named in the campaign stays on the
reasoning tier until its own registered experiment moves it.

### 0E — experiment harness

Claim: the apparatus measures what it says it measures.

Validated against an answer already known — deduplication, three conditions:
identical query twice (predicted near 100% deduplicated), unrelated topics
(near 0%), related but distinct (between, and ordered between the other two).
The claim is the ordering, not any number.

A harness that cannot reproduce an ordering this obvious cannot be trusted on
path scores or arm contrast. If the ordering fails, run the failure protocol —
do not adjust the similarity threshold until it appears, which would bias every
experiment downstream from the instrument outward.

### 0M — model tiering

A campaign, not a single experiment: one equivalence question per call site,
because the answers differ and deciding them together averages away the
distinction being sought.

Worked case, extraction: hold chunks and graph schema fixed, vary only the
model, compare the final cleaned-up JSON entity by entity and relationship by
relationship. Semantic comparison, not verbatim — same referent, same type, same
essential attributes; wording and ordering differences are not disagreements.
Tally agreement over matched entities plus the unmatched on each side, since
missing entities defeat equivalence even when everything produced agrees.

Every call site carries its own sensitivity control per §"Equivalence
campaigns", and its own threshold registered in advance. Call sites where
reasoning proves necessary are recorded as documented negatives — that is the
point of running them.

### 1A — `control.py`

No experiment. It is vocabulary with no behavioral claim, and inventing one for
it would be theater.

1A is confirmed **through its consumers**: it holds when 1C's ledger joins on
its IDs and 2C's outcomes join across rounds on the same IDs. If those joins
work on real runs, the vocabulary works. If 1A is wrong, they will not.

### 1B — cost fields

Claim: recorded costs correspond to reality, and recording changes nothing.

- **Ground truth.** Compare recorded wall-clock against the run's own elapsed
  time, and recorded token counts against the provider's reported usage. These
  are independently observable; predicted agreement within measurement noise.
- **Mechanism / A-A ablation.** Same run, recording on and off. Predicted:
  **identical action sequence.** A null result is the correct outcome, and it is
  the one that matters — if instrumentation moves behavior, every later
  measurement is against a shifted baseline.

### 1C — decision ledger

Claim: the trace can answer what was decided, what was rejected, and what
followed — on a real run, not a fixture.

- **Ground truth.** Reconstruct from the ledger alone which decision produced
  which action for a sample of real rounds; check against the run's own
  artifacts. Predicted: complete reconstruction, including rejected candidates.
- **Mechanism.** Kill a real run mid-flight and resume. Predicted: decisions
  already made keep their IDs, order is preserved, nothing is renumbered.

### 1D — criteria projection

Claim: what it marks supported is really supported, and what it marks unresolved
really is not. Both directions matter, and the second is the one that gets
skipped.

- **Ground truth, positive.** Blind verifier re-derives a sample of `supported`
  criteria from their source chunks. Predicted: high agreement.
- **Ground truth, negative.** Blind verifier attempts to derive a sample of
  `unresolved` criteria from the accepted sources. Predicted: it mostly cannot.
  If it can, the projection is under-detecting and every yield number in this
  build is understated in a way no positive test would reveal.
- **Mechanism.** Transitions across rounds should track newly ingested sources.
  Predicted: a round that ingests nothing produces no supported transitions.

### 2A / 2B — path scoring and gate

Claim: a cheap deterministic score predicts the expensive LLM's later verdict.
`docs/TABLE_FILL_PATH_SELECTION.md` states the engine currently discovers a weak
route only after normalization writes an `evidence_gap` — so the score should
anticipate it.

- **Mechanism.** On a real run, score every route and let them all through.
  Measure `evidence_gap` rate by `path_score` quintile. Predicted: monotone
  decreasing. Flat means the six features are decoration, and no check of their
  arithmetic would have told you.
- **Ground truth.** Blind-classify a sample of routes as weak or strong context
  from the chunks; correlate against `path_score`. Independent of
  `evidence_gap`, so it also tests whether that outcome measure was any good.
- **Non-goal control.** Gate on versus off, counting records with some fields
  supported and others unresolved. Predicted: **identical**. The gate demotes
  routes; it must not delete records expressing real missing evidence.

### 2C — path memory

Claim: the five outcomes are real and distinguishable in practice.

- **Mechanism.** Do all five occur across real runs? An outcome class that never
  fires is either impossible or misdefined; either way it is not doing work.
- **Ground truth.** Blind classification of what actually happened for a sample
  of accepted sources, compared against the recorded outcome. Predicted: high
  agreement.
- **Negative control.** A round that ingests no new sources must produce no
  outcome-5 classifications.

### 3A — costed reward

**State: Confirmed.** Full registration, results, and teardown in
`experiments/log/3A.md`; raw output in `experiments/runs/3A/`.

Claim: reward tracks real datapoints per unit cost, and is indifferent to
operational volume.

- **Mechanism.** Two real runs where volume and yield decouple: high row,
  source, and node counts with few criterion transitions, versus low volume with
  real transitions. Predicted: reward(low-volume) > reward(high-volume).
- **Dose-response.** Hold transitions fixed and vary volume. Predicted: reward
  approximately flat. This is the assertion that cannot be constructed honestly
  with fixtures, because fixtures let you stipulate the decoupling you are
  supposed to be measuring.
- **Ground truth.** The transitions being credited are 1D's, already verified
  against chunks. Reward inherits that anchor rather than asserting its own.

Both routes were run by computing `criteria.project_rows` and
`reward.score_criterion_yield` over the recorded tables of two real corpora
(`question_runs/round24_...` and `question_runs/round27b_...`), not fixtures.
Recorded as it happened: under the no-replay rule adopted since
(`CLAUDE.md` §Checks), that is code re-run over a prior run's artifacts and
would today be a live run; the result stands as 3A's record, and the reward's
live evidence arrives with 4C's episode ledgers (§4C).
Mechanism held; dose-response's literal round-set prediction was falsified and
traced to the first-harvest credit window crediting a delayed harvest (real
mechanism, not volume buying credit) — see `experiments/log/3A.md` for the
falsified sub-prediction and its diagnosis. **Caveat carried forward to 3B:**
no run under `question_runs/` yet carries `cost_records.jsonl` (1B has
registered its own experiment but not executed it live), so `reward.score`
(the cost-divided figure) is `None` on every real run available today; what
was confirmed here is the yield numerator's independence from volume. The
division step has no live evidence at all: the unit test that once covered it
(`tests/test_reward.py`) was deleted with the suite, so it is unverified until
a costed real run exercises it end-to-end.

### 3B — arm tuning

The build's deliverable, and the one that needs the most control. Claim: prompts
mutate, contrast routes the next mutation, and search gets better at the task.

Three conditions, same seed corpus, same round budget:

- **A** — mutation off, fixed prompt repeated. Baseline.
- **B** — mutation on, routing randomized. Arms generated, contrast computed,
  next family chosen at random.
- **C** — full mechanism, contrast-routed.

**B is the ablation that carries the design.** Without it, "more query diversity
helps" is an uncontrolled confound and C-beats-A says nothing about the
pseudo-gradient. Predicted: C > B > A in real datapoints per unit cost. If
C ≈ B, the routing is decoration — report that.

Confirmation routes for the same claim:

- **Ground truth.** Blind verifier re-derives a sample of accepted datapoints
  from their chunks: does the chunk state that value, for that subject and
  those qualifiers (the task's measure, subject, place, and period)? Report
  agreement. A low rate voids every other number in the run, so run this
  before trusting the rest.
- **Mechanism.** If routing is real, the selected mutation family should track
  the deficit present at that round — broader source families when nothing was
  found, narrower terminology when sources were found but supported nothing.
  Tests the internal decision rather than the outcome.
- **Counterfactual.** Routing is deterministic. Perturb an input in a targeted
  way — flip which arm had duplicate yield — and re-run **live at reduced
  scale**, checking the selected family changes in the predicted direction.
  This route costs provider calls; the recorded-contrast version of it is
  banned. Budget for it or choose a different second route.
- **Dose-response.** Vary arm count (2, 4, 8). If contrast carries signal,
  predicted graded improvement with diminishing returns; flat means it does not.
- **Internals, recorded regardless.** Did prompts textually differ between arms,
  or did the mechanism emit distinct arm IDs over near-identical text? Did the
  selected family change across rounds or lock onto one? Did the best-scoring
  arm's delta carry forward?

Direct repetition is the fallback here, used only for whichever comparisons have
no second route.

### 1D-a — declared subject identity (amendment to 1D)

**Current registration: v3**, `experiments/log/1D-a-live-declared-identity-v3.md`
(fingerprint `31e0db0a74968d6a30284651cd1c834c`), spec
`experiments/runs/1da-live/spec_v3.json`. The v1 and v2 registrations
below and beside it **must not run**: v1 (fingerprint `9e54978`) was returned
**UNFALSIFIABLE** by a dispatched `experiment-steward` and v2
**UNCONTROLLED** by the same. Both are retained verbatim with their verdicts.
The predictions listed below are v1's and are kept only as the record of what
was rejected; **v3's predictions live in its own log and that log is the
authority.** Claim: with a declared `subject_key_columns` in the table spec
and a canonical-slot resolver shared by `table_specs.py` and `criteria.py`, a
live continuation round binds subject identity from the declaration — a
pure function of declared columns, never of planner prose. This is the
what-counts decision made numerical (`docs/ACQUISITION_LOOP.md` §"Decisions
are numerical"): 1D's live diagnosis found identity re-rolling each round
because it came from model-emitted text.

- **P-L1, route 1 (declaration exported).** The run's exported specs carry
  the declared key columns for both tables. Falsifier: absent or different.
- **P-L2, route 1 (projection binds live).** At least one control decision
  or criteria snapshot carries non-empty `subject_ids`/`criterion_ids`
  derived from the declaration, against the 1D-a baseline of 0/21.
- **P-L3, route 2 (identity is declared, not prose).** `criteria.subject_key`
  recomputed offline from each exported row's own values and the exported
  spec is non-None and byte-identical across two interpreter processes.

Conditions: one live continuation round from the clean r4 checkpoint, four
queries, current tree, hash-guarded. Four executions have been recorded
invalid (two interrupted, one provider refusal mid-run, one duplicate
launch); none is cited. Required verdicts: `experiment-steward`,
`modularity-steward`, `reward-design-steward`.

**What v3 changed, and the ceiling it registers in advance.** v3 controls
against the exported spec with `subject_key_columns` stripped and
`key_columns` retained — isolating the manipulated ingredient, where v2
compared against no spec at all and could not. It registers `differs == 0`
as a **confirmed negative** with its derivation, demotes two analytic clauses
to disclosures, registers P4b's expected inertness with its derivation, and
implements the adjudication rule inside the hashed instrument so the verdict
is computed by fingerprinted code rather than chosen once the numbers are in.
Its declared ceiling: **route 2 is predicted to carry nothing, so the
reachable best case is incomplete-on-routes, not `Confirmed`.** That is a
property of this contract, not of the instrument —
`two_grain_table_spec.yaml` declares `key_columns` on both tables
(`:38-41`, `:180-182`), and `criteria.py:1529-1532` fills the identity field
from `subject_key_columns` **or** `key_columns`, so the amendment's
ingredient is semantically inert here by construction. The contract where
1D-a's defect was originally found declared no `key_columns` at all.

### 4A — the `rarefaction/` kernel

`experiments/log/4A-kernel.md`. No experiment of its own: a pure kernel
produces no run evidence, so it closes through its consumers' registered
live runs — 4B first, 4C for the shared-across-surfaces claim. What 4A
asserts, and what each consumer run therefore has to show: every number the
kernel emits is arithmetic over observed credits (measured, never asked);
a re-observed identity feeds encounters and f1/f2 and never the new count;
a disabled crediter announces itself; a cap ends as `bound_hit`, distinct
from `yield_stop`; and the verdict is reproducible offline from the emitted
per-unit counts to four decimals (the kernel's route 2 on every surface).
Required verdict: `modularity-steward`, on the kernel being one function
with typed data in and typed verdicts out.

### 4B — walk yield binding (GASL surface)

Registered: `experiments/log/4B-walk-yield.md` (fingerprint `f389cf28`);
sub-experiment `experiments/log/4B-D4B1-redundant-seeds.md`. Claim:
GRAPHWALK's seed expansion runs through `rarefaction.drive_episode` — unit =
one seed expansion, credits = neighbor-node encounters — emits its yield in
the command's result data, ends by the measured verdict when marginal seeds
stop producing new nodes, and keeps caps only as disclosed bounds.

- **P4B-1** numbers emitted and self-consistent on every walk (`units` ==
  seeds expanded, `distinct` ≤ `encounters`, `f1 + 2·f2` ≤ `encounters`,
  Chao1 with a disclosure). **P4B-2** a redundant broad walk ends
  `yield_stop` before exhausting its seeds. **P4B-3** a capped walk ends
  `bound_hit`, never `yield_stop`. **P4B-4, route 2** the verdict recomputes
  offline from the emitted counts. **P4B-5** a walk under `min_observations`
  never yield-stops.
- Result: P4B-1/3/4/5 held; P4B-2 failed as registered. Diagnosis by D4B-1,
  registered before running: on the sparse r4 graph the "redundant" seed set
  was not redundant (393 distinct nodes from 40 seeds) and no single hub
  could supply the 17 units the default policy needs to fire. On a dense
  real graph (20,519 nodes) the verdict fired at unit 17 exactly as
  predicted, the two-sided control held, and one window miss on the
  duplicate-seed condition was traced to a registration arithmetic error and
  confirmed on route 2. **Diagnosed.** Required verdicts:
  `experiment-steward`, `modularity-steward`, `gasl-design-steward` — the
  ones in the log were the fork-orchestrator's readings of the charter files
  and are owed as dispatched reviews.

### 4C — acquisition surface inversion (provider surface)

Registered: `experiments/log/4C-acquisition-surface.md` (v1, predictions)
and `4C-acquisition-surface-v2.md` (binding fingerprint `66941a4d`, after a
pre-run matcher fix). Claim: the provider surface runs the loop per item —
fetch → judge → extract inline → credit against declared non-key contract
columns → observe — with the per-search verdict existing while the search's
remaining items are still unfetched, cutting result-list consumption as a
disclosed decision, and all arithmetic flowing through the one kernel.

- **P4C-1** every sink-wired search outcome carries one `item_yield` entry
  per accepted source, in acceptance order. **P4C-2, two-sided** where the
  item policy fires offline at unit k before the items ran out, the outcome
  records a `yield_stop` skip and a `SEARCH_ITEM_YIELD` ledger decision; where
  it never fires, no such skip appears. **P4C-3, route 2** every per-search
  verdict recomputes offline to four decimals. **P4C-4** the credit basis is
  disclosed: the declared credit columns are named, and every zero-credit
  unit distinguishes `crediting_disabled` from judged-barren. **P4C-5** a
  strategy scope exists per executed `expansion_op` and no strategy verdict
  acts in this run (that is 4D's).
- The run is the same live execution as 1D-a (`1da-live/launch.sh`); the two
  registrations' hash sets are disjoint. Disclosed and open for the live run
  to quantify: the name matcher can credit sibling columns from one field
  (`urban_population_pct` → `population`). Deferred, gated on
  `reward-design-steward` with the run in hand: pointing `reward.py` at the
  episode ledgers. Required verdicts: `experiment-steward`,
  `modularity-steward` (including the one-kernel condition on this second
  surface and the driver instantiation with its declared unit and credit),
  `reward-design-steward`.

### 4D — strategy grain

Registered: `experiments/log/4D-strategy-grain.md` (v1) and
`4D-strategy-grain-v2.md` (binding fingerprint `2e078aa6`). Claim:
completed searches are the strategy grain's units; a strategy whose measured
verdict says stop has its queued tasks demoted within the round — executed
after live strategies' tasks or under a disclosed all-stopped override, never
deleted, never domain-filtered — with every hold and override a ledger
`PolicyDecision` carrying its numbers. Under the default policy the gate is
inert until a strategy has closed eight searches.

- **P4D-1** on the shrunk one-round run every strategy scope has units < 8,
  no `STRATEGY_YIELD` decision appears, and no task is held — inertness
  proven, not assumed. **P4D-2, two-sided** on the three-round run
  (`experiments/runs/4d-live/launch.sh`): where the strategy policy fires
  offline at search k, a matching `STRATEGY_YIELD` decision exists no later
  than the following wave and later waves order that strategy's tasks after
  live ones or record the override; where it never fires, no hold appears.
  **P4D-3, route 2** every strategy verdict recomputes offline.
- This is the mutate/switch decision made numerical: the verdict decides
  *that* a strategy is exhausted; sampling the distant replacement is the
  model's string work afterward (`prompt-mutation-steward` reviews that
  boundary). Required verdicts: `experiment-steward`, `modularity-steward`,
  `reward-design-steward`, `prompt-mutation-steward`.
- **Superseded by design, before any run.** The registered semantics
  (within-round demotion with an all-stopped override) interleave searches
  across strategies, which the composition in `docs/ACQUISITION_LOOP.md`
  §"The template" does not do. 4D re-registers under §4E-c to the composed
  semantics; P4D-1..3 stand as the shape of the predictions, with the
  routing predicate replaced by "the strategy episode ends by its verdict
  and the `run` source proposes next".

### 4E — episode composition (the refactor)

Charter: `docs/ACQUISITION_LOOP.md` §"The template". Claim: the loop is one
class, `Episode`, whose nesting and fan-up are properties of the class, and
each surface is a composition of it with no loop of its own. The claim is
structural *and* behavioral, and each half has its own route.

- **4E-a, the class.** No experiment. `modularity-steward` reviews the
  template design before code (slots, nesting contract, record nesting,
  fan-up rule) and the code after; the class closes through 4E-b/4E-c.
- **4E-b, the walk as a composition.** Mechanism route — the D4B-1a
  condition (dense real graph, 40 spoke seeds) re-run live on the composed
  walk predicts the identical firing point (unit 17) and identical emitted
  curve; a D4B-1c-style control predicts no yield stop. Route 2 — the
  verdict recomputes offline from the nested records. Structural — the walk
  handler contains no loop that reads a verdict; `gasl-design-steward`
  confirms the accepted input set is unchanged. Registered before running.
  Whether the hop-level grain binds is decided here by a registered
  prediction about what a depth-step verdict would have done on the same
  graph (the numbers are in the emitted encounters), not by preference.
- **4E-c, the provider surface as a composition.** Structural — the
  harvester's page loop and the controller's `_search_new`/`close_search`
  are gone; `modularity-steward` cites the composition (run ⊃ strategy ⊃
  search ⊃ page), each grain's declared unit and credit, the one policy
  owner (`Grain`), and the one cost owner (`costs.py`). Behavioral — 4C's
  P4C-1..5 re-register as v3 against the composed tree, same predictions
  verbatim, plus: parent unit counts equal completed child episodes; every
  parent's credits recompute from its children's records (route 2 at every
  grain from one export); a child ended by `bound_hit` never enters a
  parent's stop history; per-column accumulators exist for every declared
  target column and a row-completeness accumulator exists per table, each
  with its own curve. 4D re-registers to the composed semantics (a strategy
  episode ends by its verdict; the `run` proposer yields a strategy whose
  model-reported distance clears the registered threshold; the run stops
  proposing when its own verdict fires), predicted in numbers on the full
  multi-round run. `prompt-mutation-steward` reviews the `run` grain's
  source — the switch edge — for the model sitting only in string sampling
  and distance reporting, never in the accept/reject rule.

## Phase states

`Coded` is no longer a terminal state. It means an implementation exists.

| State | Meaning |
| --- | --- |
| `Coded` | Implementation exists; the invariant checker passes. Not evidence. |
| `Confirmed` | The phase's claim held on at least two independent routes. |
| `Diagnosed` | The claim failed, and a discriminating sub-experiment verified why. |
| `Open` | The claim failed and the cause is not yet isolated. |

`Diagnosed` is a legitimate terminal state and a successful outcome — "3B is
correctly implemented and the routing does not carry signal, because X, verified
by Y" is knowledge, and it is worth more than a green suite. A phase may end at
`Confirmed` or `Diagnosed`.

`Open` is not a terminal state. A phase sitting at `Open` has an unfinished
investigation, and the run continues working it until it reaches `Diagnosed` or
provider budget is exhausted.
