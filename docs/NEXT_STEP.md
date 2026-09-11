# Next Step: Estimator-Controller Boundary

Status: **failure-aware numerical component and the approved
single-hypervolume-credit correction are implemented as an unvalidated draft**.

The attempted V22 numerical shadow replay is not validation. V22 did not
record service failures in the form required by the new observation model, so
it cannot test the failure-aware estimator or its controller. No numerical
result from that replay is evidence for or against the new component.

The current work is review of the structure-first replacement of the numerical
control component used by `Episode`. The governing method design is
`docs/ACQUISITION_LOOP.md`.

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

The threshold adapter is injected at composition:

```python
threshold_adapter(report, current_thresholds) -> updated_thresholds
```

The initial adapter returns the current thresholds unchanged. Its presence is
the extension boundary for a future adaptive numerical policy; no adaptive
formula is declared in this phase. Every returned threshold is validated and
recorded with the verdict that used it.

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
   controller arithmetic. The combined component moves under
   `question_pipeline/rarefaction/`;
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
observation statuses are present. The adaptive-threshold hook currently keeps
the configured thresholds unchanged. The estimator arithmetic, controller
statistic, uncertainty calculation, and threshold values remain unvalidated.

## Binding decomposition before the next live run

The six binding levels now live in one `*_binding.py` module per Episode type
under `question_pipeline/episode_bindings/`. Reused ranking, extraction,
checkpoint, record, runtime, and composition support lives under
`episode_bindings/shared/`.

1. Move table-supported logical-slot projection into `result_projection.py`
   and acquisition trace/checkpoint/export formatting into
   `acquisition_records.py`.
2. Keep the chunk Leaf, lexical-probe, page, web-search, strategy, and run
   bindings in their episode-named modules.
3. Link the types only in `episode_bindings/shared/composition.py`, which declares the
   nesting and `Context` order, constructs the root Episode, and invokes it
   once.
4. Split the dormant GASL query/walk bindings by Episode type when they are
   integrated; standalone `gasl/` remains independent.

This is a structure-only migration. Credit identities, observation status,
controller inputs, thresholds, hooks, checkpoint payloads, and emitted records
remain unchanged until the split passes its live experiment.

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
