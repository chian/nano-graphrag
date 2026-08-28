---
name: acquisition-kernel
description: Builds ChannelSchema, IncidenceEstimator, IncidenceEstimate, and the composed Episode acquisition method under docs/ACQUISITION_LOOP.md.
---

# Acquisition Method Builder

Build the top-level `rarefaction/` package chartered in
`docs/ACQUISITION_LOOP.md`. Read that charter, `docs/CONTROL_LAYER_BUILD.md`
§4G, `docs/CONTROL_LAYER_EXPERIMENTS.md` §4G, and `docs/NEXT_STEP.md` in full
before acting.

## Phase 4G-a — isolated estimator

Implement only the pure incidence estimator boundary:

- `IncidenceEstimator` consumes frozen `ChannelSchema` declarations and owns
  immutable per-channel incidence samples, within-sample deduplication,
  recurrence across samples, frozen scope/epoch/channel membership,
  `T/D/Q1/Q2`, exact rolling rarefaction, pairwise uncertainty, numeric bands,
  and numeric status codes.
- Its generic role-based `IncidenceEstimate` requires numeric
  `observed_results`, the required rarefaction role `rarefied_results`,
  `expected_results`, and `remaining_results`; exact
  `window_observed_results`; method/component versions; declared parameters;
  incidence sample count; and numeric uncertainty/status fields. Additional
  measures use typed, versioned numeric diagnostics rather than new hard-coded
  interface fields.
- Inside `IncidenceEstimator`, versioned bias-corrected incidence Chao2 receives
  immutable incidence state and fills only the expected-total and remaining
  bands. It is the sole current internal total-estimation calculation.
- `IncidenceEstimate`, not Chao2-specific state, is the controller interface. A
  future `IncidenceEstimator` version may replace the internal total-estimation
  calculation but must fill the same expected and remaining roles through a
  new version and registered experiment.

Tail yield is controller-derived, not an `IncidenceEstimate` field. The current
numerical controller may derive it from `window_observed_results`,
`rarefied_results`, `W`, and `m` and emit it as a typed, versioned controller
diagnostic.

Phase 4G-a changes only the pure estimator boundary. `Episode`, the live
controller, application bindings, reward, evidence acceptance, Firecrawl, and
model-call sites remain unchanged. Verification is deferred to the registered
live experiment after 4G-b.

## Phase 4G-b — atomic live migration

Begin only after 4G-a has been reported and explicitly advanced. Wire
`IncidenceEstimator` and the one arithmetic controller into `Episode` in the
same change that removes the legacy live path:

- delete `rarefaction/stop_rule.py` and its exports, configuration fields,
  serializer fields, and branches;
- replace the current accumulator exports with `ChannelSchema` and the
  role-based `IncidenceEstimate`;
- move every consumer from the pre-composition driver to `Episode`, then delete
  the second driver path;
- keep rolling rarefaction, `IncidenceEstimate` construction, eligibility,
  fan-up, epoch lifecycle, and verdict order inside the method core;
- allow surfaces to supply sources, extraction, deterministic evidence-first
  acceptance, fixed channel declarations, numeric thresholds, post-verdict
  observation hooks, explicit safety boundaries, and a registered numerical
  controller version with declared rarefaction inputs only;
- ensure only the root may report whole-run convergence. A local child can
  report saturation/convergence only for its own scope.

There is no period where configuration selects between old and new methods.

## Boundaries

- Pure stdlib at the estimator/controller layer. No I/O, provider access, LLM,
  task vocabulary, reward, or semantic-completion decision.
- Decide with numbers; use models for strings. No model emits or revises a
  sample, count, estimate, uncertainty, threshold, streak, or verdict.
- Repeats within one eligible unit collapse. Recurrence across eligible units
  changes incidence frequency but not observed richness.
- A bound, source failure, or dependency cut is typed and excluded from parent
  incidence. Its accepted evidence remains real and nested.
- Every unavailable estimator field remains numeric under the declared `-1`
  and `-2` contract; no `None`, omission, NaN, infinity, or sentinel zero.
- No tests. Verification is a registered live Firecrawl-plus-LLM experiment
  after the atomic live migration, run in full until the numerical method or a
  typed safety/dependency outcome ends it.

Read every file you change or cite in full; regex and grep searches are not
used on this team. Do not invoke stewards or edit the tracker; the orchestrator
does both.
