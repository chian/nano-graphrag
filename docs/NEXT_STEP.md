# Next Step: Estimator-Controller Boundary

Status: **failure-aware numerical control, single hypervolume credit, and the
approved adaptive marginal-credit threshold are implemented as an unvalidated
draft**.

The attempted V22 numerical shadow replay is not validation. V22 did not
record service failures in the form required by the new observation model, so
it cannot test the failure-aware estimator or its controller. No numerical
result from that replay is evidence for or against the new component.

The current work is review of the structure-first replacement of the numerical
control component used by `Episode`. The governing method design is
`docs/ACQUISITION_LOOP.md`.

## Continuation safety

**IMPLEMENTED; LIVE INTERRUPT-AND-CONTINUE VALIDATION PENDING 2026-09-16.**
Continuation now requires a `VerifiedCheckpoint` before `QuestionPipeline` is
constructed. One checkpoint generation uses one commit identity and records
fingerprints for every state file plus the live Goal, evidence, source, and
completed-Episode artifacts. The Firecrawl binding checkpoints each completed
page with its exact provider result buffer and next rank, so continuation does
not repeat the search call or replay already completed pages. Seed imports are
not continuation state and are no longer loaded on the continuation path.

The previous `episode_checkpoint_v1` artifacts cannot establish this
coherence and are refused. The known mixed-state earthquake run was used only
for a non-mutating rejection check: the new gate rejected it before pipeline
construction and its checkpoint hash did not change. The remaining validation
is one newly registered real Firecrawl run, interrupted after a page
checkpoint and continued from that same checkpoint. It must preserve the Goal
row count and evidence identities, resume at the recorded next result rank,
and keep the controller history continuous.

## Approved structure

One opaque estimator-controller component owns the complete numerical
transition for one Episode scope:

```text
accepted evidence
          |
          v
write the binding's typed result state
          |
          v
project unique accepted identities by column
          |
          v
classify the unit observation
          |
          v
update every column estimator
          |
          v
emit the immutable column vector and numeric bands
          |
          v
reduce the vector to realized and predicted marginal hypervolume
          |
          v
apply the injected threshold adapter
          |
          v
calculate the verdict from predicted future hypervolume credit
```

The estimator and controller are coded together because the stopping rule is
defined over that estimator's statistics. Estimator-specific statistics and
threshold arithmetic remain inside the component. `Episode` invokes one
control transition and does not interpret those statistics.

The method-facing operation is:

```python
advance(
    unit_label,
    identities_by_channel,
    observation_status,
) -> ControlStep
```

`ControlStep` carries the unit yield, the complete generic numeric report, the
sole scalar method credit, and the verdict from the same transition. The report
exposes generic observed, expected, and remaining-result bands per column;
estimator-specific numeric control statistics and diagnostics are mappings
rather than fields in the shared contract. The controller predicts the next
unit's marginal hypervolume from that vector and compares only its upper band
with the scalar stop threshold.

The threshold adapter is injected at composition and runs inside the combined
numerical transition:

```python
threshold_adapter(context) -> ThresholdUpdate
```

For the adaptive question-pipeline grains, the context carries the immutable
numeric report, the current thresholds, the recent realized method-credit
window, and the last identifiable productive-unit baseline. The adapter sets

```text
one_result_resolution = smallest positive hypervolume change obtained by
                        adding one identity to one open required channel
productive_baseline   = median(nonzero realized hypervolume credits in the
                               trailing estimator window)
gamma                 = max(one_result_resolution,
                            0.1 * productive_baseline)
```

The one-result counterfactual respects discrete identities: an open axis uses
at least `observed + 1` as its reachable-total denominator. A fitted total of
`observed + epsilon` cannot make one possible identity worth only epsilon and
cannot drag the threshold toward zero alongside the predicted yield. Realized
credit likewise uses a denominator no smaller than the post-unit observed
count.

If the current trailing window has no productive units, the last identifiable
productive baseline is carried. Either identifiable component may determine
`gamma`; if neither is identifiable, the transition records
`threshold_insufficient` and cannot advance the stop streak. The adapter
records both components, the fraction, window counts, carry state, and the
validated threshold with the verdict that used it. The lexical-probe/chunk
grain retains its separately calibrated fixed threshold for the first live
comparison.

## Priority correction: single method-credit boundary

V22 exposed a structural violation: the provider binding converted accepted
registry cells directly into incidence credit, while the post-strategy reward
path independently assigned credit from later criteria transitions. The active
fix removes that split. Evidence acceptance remains its own swappable policy;
typed result storage follows it; one projector reads the resulting state and
emits stable identities by column. Those identities are estimator inputs. The
paired numerical component assigns marginal hypervolume once as the sole
method credit, which later learning and yield/cost reporting consume.

**IMPLEMENTED AS AN UNVALIDATED DRAFT 2026-09-09.** The table binding now has
one post-storage logical-slot projection. It is the sole source of stable
per-slot identities, reported/best-guess alternative occupancy, and row
completion. Incidence channels and hypervolume consume its slot identities;
export/search completeness consumes its row state. Row completion is diagnostic
only and no longer exists in the evidence registry or as a channel. Physical
column availability remains metadata and cannot assign credit or declare a row
complete.

## Execution order

1. Correct the ownership boundary while preserving the current estimator and
   controller arithmetic. The combined component lives in
   `question_pipeline/utilities/rarefaction.py`;
   `method_loop` retains Episode execution, nesting, scope routing, identity,
   and records.
2. Verify that identical observations produce identical counts and verdicts
   through the new boundary.
3. **IMPLEMENTED AS AN UNVALIDATED DRAFT 2026-09-06.** Replace the paired
   numerical implementation with the selected joint preferential-sampling
   framework and its matching controller. The joint
   model represents evaluability and discovery through shared latent state, so
   failures are not assumed random and are not converted into successful empty
   samples. The observation input distinguishes observed, failed, and excluded
   attempts; successful observations may contain new identities, repeated
   identities, or no identities. Every declared result column retains its own
   estimator state. The general framework was selected with the operator. The
   operational equations and implementation choices were then translated into
   code without obtaining separate operator approval and are under review now.
4. After operator review of the implementation choices, update the surface
   bindings only where they must supply observation status and per-channel
   identities, then verify the complete nesting and control history in one
   newly registered real Firecrawl acquisition run that records the required
   failure observations.

## Replay record

The V22 numerical shadow replay was run before establishing whether V22 had
recorded the inputs required by the new model. It had not: its stream contains
no usable service-failure observations. The replay artifacts are therefore
inadmissible as estimator or controller validation and must not be used to set
thresholds or claim behavior.

The separately authorized saved-source replay reran lexical ranking, chunk
Episodes, model extraction, evidence acceptance, typed storage, credit
assignment, and numerical control on the saved earthquake PDF. It was stopped
on operator instruction before the source Episode closed. Because neither it
nor the corresponding V22 source Episode wrote final post-storage credit
records, it does not provide a finalized-credit comparison. The operator has
accepted its similar partial evidence yield in substantially less elapsed time
as sufficient practical evidence for the corrected source-processing path at
this stage. That acceptance is not validation of the new failure-aware
estimator-controller.

## Structural gate

**PASS 2026-09-06.** `method_loop` no longer constructs or joins an estimator
and numerical controller separately. `Episode` receives one `ControlStep` from
the combined transition. Nine fixed-threshold observations across three
channels produced the same estimator numbers and controller verdicts before
and after the ownership move; the runtime invariant checker also passed.

The generic report boundary and explicit `observed` / `failed` / `excluded`
observation statuses are present. The adaptive-threshold rule is wired for the
source-table, page, search, strategy, and run grains and records its inputs at
each verdict; the lexical-probe/chunk grain keeps its calibrated fixed rule.
The estimator arithmetic, controller statistic, uncertainty calculation, and
adaptive threshold behavior remain unvalidated until the fresh live run.

## Current code organization before the next live run

`question_pipeline/pipeline.py` is the visible entry point. Episode behavior
lives one type per module under `question_pipeline/episode_binding/`; its
package initializer assembles the provider binding. Supporting implementation
is grouped by responsibility under `question_pipeline/utilities/`:
acquisition, evidence, extraction, model, rarefaction, replay, search, and
tables. Standalone `gasl/` remains independent.

The organization change is structural. Credit identities, observation status,
controller inputs, thresholds, hooks, checkpoint payloads, and emitted records
are intended to remain unchanged and still require the registered live
validation described above.

**APPROVED AND IMPLEMENTED 2026-09-06; LIVE VALIDATION PENDING.** Accepted stable table-slot identities are
one-dimensional contributions separated by column. They form the complete
column vector; they are not independent method credits. Every axis uses
cumulative observed richness and its own reachable-total estimate. Marginal
dominated hypervolume is the sole scalar method credit, recorded on
`ControlStep` and `UnitRecord` for control and learning. The controller uses the
predicted next marginal hypervolume band as its sole stop statistic. A parent
receives the child's distinct identities by column and recomputes hypervolume
on the parent's scale; it never sums child hypervolumes. An unavailable
required denominator produces numeric insufficient-information status without
a fallback normalization.
