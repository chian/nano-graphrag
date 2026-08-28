# Next step — read this first in a new session

Written 2026-08-28. Replace this file when the next structural component is
complete.

## Do this now

Begin phase 4G-b only: refactor the existing numerical decision slot to consume
the required roles on `IncidenceEstimate`, then migrate the live `Episode` path
atomically so no second controller or loop remains. Report the result and
method-loop diagram before beginning the evidence-first acceptance phase.

The completed 4G-a implementation owns:

- immutable incidence samples with within-sample deduplication and recurrence
  across eligible samples;
- frozen generic channel declarations and scope/epoch identity;
- scope-opening creation of every declared channel estimator, including
  zero-unit and all-disabled histories, with kernel-derived union membership;
- exact rolling rarefaction count, full-window observed count, and pairwise
  uncertainty;
- numeric bands and the `0`, `-1`, `-2` status/uncertainty contract;
- a versioned reachable-total calculation filling the expected and remaining
  roles;
- bias-corrected incidence Chao2 as the sole current implementation of that
  role, including total and remaining uncertainty.

Phase 4G-a ends at `ChannelSchema`, `IncidenceEstimator`, and
`IncidenceEstimate`, including the run-start binding that carries a surface's
fixed generic declaration into every scope before observation. Phase 4G-b owns
the numerical controller and its application wiring. Its review must verify
that `Episode`, `ScopedYield`, child fan-up, and nested records retain their
existing boundaries while the controller consumes typed estimate roles.

## State

- Removed `papers_per_query`, `papers_per_strategy`, and
  `searches_per_strategy`. Firecrawl may return a large provider batch, but
  buffered results are processed one by one. No processed-page or issued-search
  count is the method stop rule. The explicit run-wide `max_papers` safety
  boundary remains and must report `bound_hit`, never convergence.
- `docs/ACQUISITION_LOOP.md` is authoritative. The method uses exact rolling
  incidence rarefaction, the generic role-based `IncidenceEstimate` output contract,
  bias-corrected incidence Chao2 as the current reachable-total estimator, and
  a versioned numerical per-channel controller.
- Phase 4G-a is implemented and independently reviewed. The Episode path binds
  the frozen channel schema and carries incidence estimates. The modularity
  steward passed the required-role, frozen-schema, nesting, and eligible fan-up
  boundaries; the reward-design steward passed the incidence, numeric-band,
  estimator-arithmetic, and reward-isolation boundaries.
- No current live Firecrawl-plus-LLM experiment has verified the amended method.
  Verification belongs after 4G-b atomically removes the legacy live path and
  wires the new one.

## The generic `IncidenceEstimate`

For each `(scope_path, epoch, channel)`, the controller-facing record contains
numeric bands for:

- `observed_results`;
- `rarefied_results`;
- `expected_results`;
- `remaining_results`.

It also carries exact `window_observed_results`, estimator/component versions,
declared parameters, incidence sample count, and numeric uncertainty/status
fields. Extra statistics use typed, versioned numeric diagnostics rather than
new required fields. The current numerical controller derives
`rarefaction_tail_yield` as one such diagnostic; it is not hardened into the
estimate interface. Chao2 fills the current
expected/remaining bands, but is not exposed as the decision interface. A
future reachable-total estimator must fill the same role and record through a
new version and registered experiment; it cannot alter rarefaction, membership,
epochs, or verdicts.

## Next phases, serially

1. 4G-b — wire the numerical controller to `IncidenceEstimate`; retire the replaced
   decision module, exports, configuration, and
   second driver path after all consumers move.
2. Evidence-first acceptance registry and stable per-column/row/best-guess
   identities with exact source-version and text-span traceability.
3. Mandatory enabled best-guess columns with deterministic, acyclic derivation
   provenance.
4. Post-verdict typed learning observations for future query/strategy proposal.
5. Register and run one real Firecrawl-plus-LLM experiment in full, one live
   pipeline process at a time, until the numerical method stops or a typed
   safety/dependency outcome cuts it.

After every structural phase, report the files changed, the steward verdict,
what remains unverified, and an ASCII diagram of the method loop.
