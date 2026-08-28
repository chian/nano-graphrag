# Next step — read this first in a new session

Written 2026-08-28. Replace this file when the first foundational live
experiment is complete.

## Do this now

Register and run the first foundational live Firecrawl-plus-LLM experiment.
This is the immediate next phase; do not open best-guess or learning-memory
work first.

The obsolete raw/guess `ColumnProjection.identities()` credit path has been
deleted. The independent modularity re-review and independent evidence/reward
rereview are both PASS. Preserve that closure: every candidate, raw-value,
provenance-only, and unaccepted best-guess route to incidence must remain
structurally absent.

The run must exercise actual provider search, the real per-result relevance and
extraction calls, durable evidence acceptance, incidence, and the numerical
controller. Run one pipeline process only and let its own numerical or typed
safety/dependency end finish it.

## Current state

| Component | State | What that state means |
| --- | --- | --- |
| 4G-a — incidence estimator | Structurally implemented and independently reviewed | Frozen channel declarations and role-based incidence estimates exist; live Firecrawl-plus-LLM verification is still pending |
| 4G-b — numerical controller migration | Structural implementation and reviews complete | The live Episode path consumes the role-based incidence estimates through the versioned numerical controller; legacy controller/driver teardown is complete, but no current live experiment has verified the composition |
| Evidence acceptance | **Coded — modularity and evidence/reward reviews PASS; live verification pending** | Exact source/version/chunk/span assertions and deterministic direct acceptances feed accepted-cell and row-completion incidence; structural review is closed and the foundational live experiment is next |

## Method boundary the live experiment must exercise

Evidence acceptance ends at durable accepted cells and first row-completion
transitions feeding incidence.

The ordered path is:

```text
Firecrawl returns a provider-owned batch
  -> PageSource pulls one buffered result
  -> relevance model scores that result
  -> extraction model returns candidates from its exact chunks
  -> persist source blob/version/chunk/span/assertion candidates
  -> deterministically accept direct cells
  -> emit accepted criterion IDs and first row-completion IDs by channel
  -> incidence estimator updates
  -> numerical controller decides continue / local saturation / convergence
  -> immutable post-verdict Episode record is published
```

Provider batching is allowed and desired. Results are processed one by one,
with a numerical verdict between pulls. No page count, provider batch size, or
issued-search count is the method stop rule. No `papers_per_strategy` cap or
replacement processed-page cap may exist. The explicit run-wide `max_papers`
boundary remains a safety boundary and reports `bound_hit`, never convergence.
If a dynamic verdict ends a search while provider results remain buffered,
those results receive no relevance, extraction, best-guess, or other page LLM
processing.

An extracted value, graph edge, populated cell, `source_ref`, model statement,
or best-guess candidate earns no incidence. A direct cell may feed incidence
only after its complete durable accepted chain resolves. Row completion is a
transition over accepted required cells, emitted once for the stable subject.

## First foundational live experiment

Register predictions and receive experiment-steward approval before any paid
call, including a credential probe. Use current direct transport and the
repository's credential owner. Establish that no `run_question_pipeline`
process is live before launch, then run exactly one process to its own end.

Firecrawl is the only acquisition source for this first implementation
experiment. It may return many results in one provider-owned batch, while the
Episode composition processes exactly one page/result at a time through
`run -> strategy -> search -> page`. Each processed result must traverse real
LLM extraction and durable evidence acceptance before accepted identities may
enter incidence. No page count, search count, or provider batch size is the
method stop rule; the run continues until the numerical verdict or a typed
safety/dependency end.

The experiment tests wiring, not whether the current estimator or controller
is the best statistical method. It must distinguish outcomes from
interpretation and mark each one in or out of scope. Its registered checks must
cover at least:

1. a real Firecrawl response records the provider batch while `PageSource`
   pulls and processes results one at a time;
2. every processed page traverses the real relevance and extraction path;
3. accepted incidence identities resolve through the persisted source version,
   exact chunk/span, assertion, and acceptance records;
4. raw candidates and rejected assertions mint no incidence;
5. completed-row incidence occurs only on the first transition to all required
   ordinary cells accepted;
6. the numerical verdict is recomputable from emitted incidence estimates and
   controller arithmetic;
7. any buffered remainder after a dynamic verdict has no page-level LLM work;
8. a run-wide `max_papers` cut, if it occurs, is reported as `bound_hit` and is
   not interpreted as convergence.

## Later phases, serially

1. **Mandatory best-guess derivation and acceptance.** Build accepted
   `BestGuessCell` values for enabled real columns. Each derivation must be
   deterministic, acyclic, versioned, recomputable from typed inputs, and
   terminate in persisted direct assertions with exact source/span
   traceability. Candidate generation alone earns nothing.
2. **Typed learning memory.** Consume the existing immutable post-verdict
   Episode records. This component owns compression and retained history for
   future query/strategy string generation only; it cannot change accepted
   evidence, incidence, eligibility, the completed unit's estimates, or its
   verdict.
3. **Learning-specific live experiment.** Register and run a later real
   Firecrawl-plus-LLM experiment that tests whether the typed memory changes
   future proposal strings as declared, without changing the evidence or
   numerical decision boundaries.

After each structural phase, report files changed, independent steward
verdicts, what remains unverified, and a concise method-loop diagram. Do not
open phases in parallel.
