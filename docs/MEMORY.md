# Completion, Evidence, and Replay Memory

> **STATUS (amended 2026-08-28):** the sections below marked "Not in the tree"
> describe the pruned `cd44ebb` snapshot, as before. Additionally, all
> rarefaction and completion-estimation semantics in this file are superseded
> where they conflict with `docs/ACQUISITION_LOOP.md`, which charters the
> `Episode` method core with fixed `ChannelSchema` declarations and
> `IncidenceEstimator` as the single owner of immutable incidence samples and
> the generic role-based `IncidenceEstimate`. Bias-corrected incidence Chao2
> internally fills the expected and remaining roles; verdicts remain arithmetic
> and per-channel.

The table-fill completion system estimates the expected size of declared
aggregate criterion families without treating operational record cardinality
as evidence of completeness.

## Active Use Case and Graph Boundary

The active graph is the **earthquake two-grain** graph: event-level impact
measures joined to country-year context. A dense country or period is the
branch used to expose missing coverage across events, measurement scales,
time periods, and reporting contexts; it is not a single-country schema. The
shared schema keeps distinct measures as different observation types and
attaches subject, place, scale, time, method, and source context to the
observation that actually reports them. An earlier anchor on a different
subject domain survives only as read-only history.

The mature pre-refactor GraphML is read-only candidate and traversal context.
Its merged nodes, edges, `source_refs`, and `source_chunks` are not evidence.
Direct graph edges, including edges produced by fresh extraction, are discovery
links rather than assertion support. The evidence registry projects claims into
the graph as reified records, but criteria consume the registry records and
their exact joins, not an ordinary graph edge.
Legacy source evidence is admitted only through explicit selective replay:
the caller names source IDs already present in the seed-graph lineage, the
runtime resolves an unambiguous saved source body, and that body is freshly
extracted into the evidence registry. Omitted sources remain retrieval
candidates. This is neither corpus discovery nor a knowledge-graph rebuild,
and full migration of the legacy graph has not been implemented. The resulting
content hash and exact spans attest only what the selected local saved body
contains. The replay path does not independently authenticate that body as the
claimed external publication.

## Current Evidence Contract

> **Not in the tree.** This section describes the WIP snapshot `cd44ebb`, which
> the prune back to `92f8e64` removed. `question_pipeline/evidence_registry.py`
> does not exist; `FieldAssertion`, `SourceLocalObservation`, `EvidenceItem`,
> `SourceVersion`, and `SourceDocument` have zero occurrences at baseline. Read
> this as the target contract, not as available API. See `AGENTS.md` §"Evidence
> rules at baseline" for what the tree actually supports.

`evidence_registry_v2` makes `SourceDocument`, `SourceVersion`, `SourceAlias`,
`EvidenceItem`, `SourceLocalObservation`, `FieldAssertion`, and
`RelationshipAssertion` first-class records. Their identifiers derive from
immutable record content, and the append-only registry rejects a conflicting
payload for an existing identifier. Source-local observations and assertions
therefore cannot be collapsed by graph edge overwrite or concept merging.

Concept merging follows the schema's explicit `merge_policy`. An `exact`
concept merges only on the same lower-cased, trimmed display name; it never uses
fuzzy similarity, abbreviation, substring, or synonym matching. A `canonical`
concept remains eligible for those legacy merge heuristics, while
`source_local` and `immutable` records never concept-merge. The active schema
uses `exact` for subject, event, measure, scale, geography, time, method, and
other identifier-like concepts.
`SourceAlias` records aid lookup, but DOI, PMID, URL, and other aliases do not
yet have a complete source-equivalence resolver.

Extraction prompts require each source-local observation name to be one
contiguous phrase copied from the source. The collector must resolve that quote
uniquely inside the content-hashed chunk before it records an
`observation_clause_exact` anchor. For an observation type with schema-declared
`association_fields`, every association value must be a single recognizable
scalar, and each field quote must be unique within the anchor and contain both
its own value and every association-tuple fragment. Numeric and measure guards
reject extra or ambiguous values. Accepted field spans are recorded as
`field_quote_exact:<field>` evidence items.

Missing, repeated, differently anchored, coordinated, or structurally
multi-claim quotes fail closed as `candidate_unverified`; nearby context is
insufficient. Source-extracted semantic `RelationshipAssertion` records also
remain candidates. This is typed lexical atomic grounding, not semantic
entailment. Novel text-only measure notation that the typed guard does not
recognize and comparisons spread across multiple caption sentences deliberately
remain candidate-only.

Every `FieldAssertion` records `typed_exact_tuple_v2` plus stable acceptance or
rejection reason codes. Those fields preserve the policy result for audit; they
are not a fully replayable grounding decision. The registry does not persist the
complete rejected extraction occurrence, schema snapshot, or all alternative
quote spans needed to recompute the decision. A future first-class immutable
grounding-decision record is still required for policy replay.

Literal co-occurrence does not establish an ordered association. Observation
phrases containing `respectively` fail closed even when every listed value is
present, because assigning list members to one another requires a future typed
ordered-list or tuple assertion. This deliberately leaves correct parallel
enumerations unresolved instead of permitting cross-pair support.

`criteria_projection_v10` supports a field only when it resolves the complete
registered chain

`FieldAssertion -> SourceLocalObservation -> EvidenceItem -> SourceVersion -> SourceDocument`

for the exact field and normalized value. The cited assertion, evidence item,
versioned source, and observation anchor must agree. For a reported assertion,
the registry also derives a `semantic_claim_id` from the canonical source
document, observation type, and exact anchor checksum. Only the registry may
confer that cross-version claim identity; a copied snapshot or sidecar cannot
mint it. A URL, source ID, graph `source_ref`, chunk ID, populated cell, or
row-level completeness marker cannot substitute for that chain.
`project_criteria()` accepts only a live `EvidenceRegistry` object as authority;
a missing registry or a registry-shaped mapping fails closed.
`criteria_transition_v7` compares those immutable supported/unresolved states
and their exact assertion/evidence/canonical-source support units, including the
registry-owned semantic claim identity where present.

Serialized criteria snapshots are audit records, not replay authority.
`CriteriaSnapshot.from_dict()` clears serialized support, marks the snapshot
`criteria_projection_v10:unvalidated_replay`, records
`replay_requires_authoritative_registry`, and computes a new replay-audit ID.
Reward v7 refuses such snapshots: it returns `status: unknown`, zero score, no
components or transition, and the expected and observed projection versions.
Offline semantic reward replay must first reproject the underlying operational
records through the live registry.
The chain establishes only that this version of the registered document
contains the literal statement. No typed primary-versus-secondary citation-role
assertion exists yet, so a review or other secondary document cannot establish
that its literal statement is primary-study evidence.
This section describes the implemented contract. It is not a claim that a
fresh end-to-end full-corpus continuation has validated the refactor.

## Current Implementation

> **Not in the tree.** Describes `cd44ebb`. At baseline `92f8e64`,
> `table_specs.py:236` serializes `"version": 1`. The version 3 criterion
> contract — `criterion_contract_id`, `required_criterion_families` — and the
> version 4 `required_field_values` are design targets, not available fields.
> Any phase depending on criterion families depends on work that must be built
> first; see `docs/CONTROL_LAYER_BUILD.md` Phase 1D.

Table specifications serialize as version 4 contracts. When loading a version 1
spec, the compatibility migration
`table_spec_v1_operational_columns_to_diagnostics_v2` removes operational
transport columns from semantic keys, relaxes affected non-nullable columns to
nullable diagnostics, and records the changed columns in
`compatibility_migrations`. It does not invent a semantic replacement key.
Compatibility-migration diagnostics are excluded from the semantic table-spec
payload and therefore do not change the table-spec identity by themselves.
Invalid derived keys still fail explicitly and require an author-reviewed
migration.

Version 3 added an explicit task-owned criterion contract. A table specification
may declare one stable `criterion_contract_id` and a list of
`required_criterion_families`. Each family fixes a stable `family_id`, exact
accepted source-local observation types, required semantic fields,
`rule_version`, target table adapter, and optional runtime capability. Families
are authored from the question; they are never generated from table names,
table presence, keys, or observed records. If a criterion contract is present,
every deliverable table must have an explicit family declaration.

Version 4 adds optional author-owned `required_field_values` to a family. Each
key must also be a required semantic field, and the normalized exact task value
must be supported on the same registry claim as the rest of the family. These
predicates are part of the family semantic payload; they are not inferred from
table names, descriptions, model routing, aliases, or entity resolution.
Changing a predicate requires a new `rule_version`.

`criteria_projection_v10` recomputes each required family dynamically. A family
is supported only when one bound subject has every required atomic field
supported on the same registry-owned semantic claim and an accepted exact
observation type. This is an existence or capability witness only; one witness
does not establish coverage of a subject universe, country set, or result
family. Empty tables produce an explicit unresolved task criterion rather than
making the family disappear. Missing runtime capabilities produce structural,
non-search-actionable deficits. For the active design-held country comparison
and country/time trend types, the absent
`authoritative_country_resolution_v1` capability yields
`country_resolver_unavailable`.

A supported family carries `existence_only_not_scope_complete` and
`system_derived_from_atomic_criteria`. Evidence-side failures remain explicit as
`required_family_subject_unavailable`, `required_family_fields_unresolved`,
`required_family_field_values_unresolved`,
`required_family_field_values_mismatched`,
`required_family_observation_type_unaccepted`, or
`required_family_joint_observation_claim_unavailable`. Changing accepted types,
required fields, required field values, or capability semantics requires a new `rule_version`; it is
not an in-place reinterpretation of the old family criterion.

Required-family assessments are deterministic task-level gates, not reported
facts. They emit no source IDs, evidence IDs, `CriterionEvidence`, or support
units and are excluded from semantic membership, rarefaction, and scalar reward.
Only their underlying atomic field criteria receive source-grounded reward. A
family can block fulfillment and its versioned transition remains auditable
without double-counting the evidence that established it.

`semantic_membership_v2` requires each deliverable table to declare its member
grain. In `semantic_signature` mode, `member_signature_columns` must include
every semantic key, and all signature fields must resolve on one common
source-local observation and canonical source before they form one cross-source
member signature. In `source_observation` mode, a registry-validated
`semantic_claim_id` can identify the same exact source observation across
content versions for semantic criterion projection and reward. That occurrence
identity still does not define cross-source species or cross-source overlap, so
it is not count-estimator eligible. A supported binding without that registry
claim ID remains unprojected. Missing or invalid membership configuration is
likewise not inferred from `key_columns` and cannot enter semantic reward.

Reward version `criteria_transition_v7` receives the explicit membership modes
and signature columns and emits a separate `semantic_transition_id` alongside
the source-local criteria-transition ID. For `semantic_signature`, novelty is a
reviewed member field/value signature plus criterion field/value. For
`source_observation`, novelty is the registry-owned `semantic_claim_id` plus
criterion field/value. Missing membership configuration or a missing claim ID
keeps otherwise source-local support out of scalar reward and exposes it through
projection diagnostics. Positive and negative reward terms therefore operate
on semantic claims and addresses, never operational records or occurrences;
provider and wall-time costs are still future reward work.

> **Superseded estimator record.** The following paragraph describes the
> removed `cd44ebb` design and is retained only to explain persisted historical
> artifacts. It must not be restored or used as an implementation reference.

`question_pipeline/expectations.py` implemented
`supported_semantic_signature_chao1_v1`. Chao1 runs only for an eligible
`semantic_signature` family with a nonempty signature, at least one supported
semantic member, more than one contributing source unit, and an estimate no
smaller than the observed supported count. `source_observation` families remain
unestimated with `source_observation_cross_source_overlap_undefined`; missing or
invalid membership remains unestimated with
`semantic_membership_contract_unconfigured`. Raw source-by-subject incidence is
therefore not a universal estimator. These fail-closed states are implemented
behavior, not future estimator policy.

For a multi-key identity, `criteria_projection_v10` emits a required
`__subject_identity__` criterion. Raw key fields must resolve through registered
assertions on a common source-local observation; matching only an
`(evidence_item_id, source_id)` pair is insufficient. Aggregate membership and
source rarefaction use that joint identity contract. Individually evidenced key
components remain supported even while the tuple is unresolved. A raw non-key
field must also attach to the subject's resolved observation. A sourced or
row-level `complete` marker does not close evidence or task coverage.
Operational transport fields are rejected as configured keys or non-nullable
criteria, and the projector filters them again for direct/replay callers.
Derived `best_guess` columns are also rejected as keys. Supporting missing or
corrected derived keys requires a future provisional-subject identity and typed
rekey transition; neither is implemented. Best-guess actions, candidates, and
sidecars are currently operational diagnostics because the runtime does not yet
register a typed derived analysis and its derived `FieldAssertion` chain.
Decision-bound derived supersession/retraction is also not implemented.
Historical specs using derived keys must therefore be migrated to stable
reported semantic keys rather than being silently reinterpreted.

`PROCESS` is a provenance-preserving transform, not an evidence creator. It can
copy only a pre-registered assertion/evidence/source binding whose field,
typed value, and observation or subject anchor exactly match the materialized
output. It strips model-emitted provenance and rejects merged graph source
references. Renaming, normalization, and generation fail closed unless an
already registered typed derived assertion exists. A semantic field without an
exact authoritative binding remains unresolved. Operational completeness and
top-level gap markers are contract-relative, not semantic state: for a nonempty
required-field contract, superseded partial diagnostics are archived and the
current gap/completeness view is recomputed from exact bindings. PROCESS never
marks task coverage complete. Validated field records expose their exact
provenance under `assertion_bindings`, the container consumed by
`criteria_projection_v10`.

The executable PROCESS surface is `gasl_process_execution_v5` under
`gasl_process_execution_policy_v5`. Every command declares one of three exact
mode/cardinality pairs: `semantic_filter/zero_to_n`,
`eligible_materialization/zero_to_n`, or
`exact_enrichment/exactly_input`. `REQUIRED_FIELDS` is structured execution
metadata, not prose. A command is capped at 72 input items and eight logical
model calls: at most five primary batches of 15 plus three calls reserved for
repair. Under
`gasl_process_required_field_roles_v2`, each required entry is exactly a
source-bound `semantic_field_assertion`, a `declared_grain_identity`,
`registry_metadata`, or an `authoritative_binding_container`. Semantic fields
need exact active FieldAssertions; identity fields must be exact declared source
grain keys. Registry metadata and `field_evidence` must be present in the exact
durable source `row_schema`; their deterministic nonsemantic authority does not
mint a fictitious assertion. For example, FIND nodes declare grain `id`, so
`observation_id` is not a valid identity requirement for that source. Reserved,
assertion, criterion, unknown, and other operational containers fail closed.
Excess input is preserved in the
output's `__unresolved` continuation. A successful zero-result filter remains
zero. Only exact enrichment preserves one output per input, and even then it
cannot turn a model-generated value or source alias into registered support.
The `__unresolved` and `__unsupported` suffixes are runtime-reserved rather than
planner-owned outputs. Their exact contracts are respectively
`process_unresolved_inputs` with `usable_by=["PROCESS"]` and
`unsupported_process_outputs` with `usable_by=["SHOW"]`.

Execution v5 includes `gasl_process_operational_row_token_v1`, an opaque SHA-256
over each row's exact ordered, typed declared-grain tuple. Boolean, integer,
finite-float, and string values remain distinct; alias, string-coercion, and
ordinal fallback are invalid. The runtime re-tokenizes all source rows and
rejects supplied-token mismatch or duplicate declared-grain tuples. Duplicate
grains are a noncontinuable upstream producer defect to repair before a new
family. Tokens establish operational parent attribution only, never evidence,
criterion support, or completeness.
`target_row_count` and the other PROCESS counts are operational audit
cardinality, not goodness or completion.
`gasl_process_declared_grain_authority_v2` records the exact grain type, keys,
parent values, token, and authoritative parent-token list restored on an
accepted row; it is operational identity authority, not a FieldAssertion.

All retained durable outputs project
`gasl_deterministic_producer_contract_v1`: payload kind, row schema, grain type
and keys, multiplicity, `usable_by`, and evidence state. Planner simulation and
runtime production must agree exactly. The planner, compiler, executor, runtime,
and StateStore enforce producer-owned `usable_by` through exact command
membership. Same-type DECLARE preserves that full contract. A defined empty FIND
or retained PROJECT, COLLAPSE, GRAPHWALK, JOIN, MERGE, or SELECT succeeds with a
durable empty list; only missing or invalid inputs are errors. Empty SELECT,
PROJECT, COLLAPSE, and GRAPHWALK outputs replace stale structural metadata with
their declared schemas. JOIN requires its key in both declared input schemas
and projects a deterministic joined union-plus-identity schema even for an empty
result. Empty MERGE may retain only the deterministic union of available source
schemas. On the in-scope NetworkX backend,
`gasl_graphwalk_limits_v1` enforces depth 1--8, a deterministic 100-source slice,
the first 50 deterministic incident edges per node, and a prospective global cap
of 10,000 unique declared-grain queued/emitted rows. Its deduplicated emitted
subset cannot exceed that cap. Ordered truncation reasons mark evidence partial,
non-search-actionable, non-continuable, and unable to close coverage; there is no
truncation continuation. Narrowing or replanning is guidance rather than
automatic executor repair: a successful truncated walk may clean-finalize
operationally, but cannot close criteria. These conservative empty-schema and
bounded-walk cases are liveness/cost limits, never semantic support or coverage.
Neo4j `id_filter` and source/target filtering remains an out-of-scope backend
residual.

Graph identity is typed and declared: FIND nodes use `node(id)`, edges use
`edge(src_id,tgt_id,relation_type)`, paths use `path(path_id)`, and GRAPHWALK
uses `edge(src_id,tgt_id,relation_type,path_depth)`. Alias conflicts and
duplicate grains fail closed. Bare relationship controls `a`, `an`, `any`,
`all`, and `*` are wildcards. Literal values colliding with them, looking
numeric/boolean, containing `,` or `|`, or beginning `relation_type=` or
`relationship_name=` must be JSON quoted in planner prompts.

Crash recovery is separately versioned as
`gasl_process_execution_persistence_v9`. A
`gasl_traversal_execution_v1` record and read-only
`gasl_execution_recovery_ownership_v1` view own active plans, pending outer
dispositions, pre-plan work, exhausted traversals, and terminal answers. The
question-pipeline wrapper checks that ownership before writing source or table
seeds; owned state must match the exact job and reconstructed task/spec query
and is resumed without reseeding. In-flight PROCESS state uses
`gasl_process_attempt_snapshot_v4` to capture exact prior input, target,
unresolved, and unsupported existence, rows, contracts, and digest before the
pre-call started/pending target-plus-sidecars triple. Both sidecars carry the
exact incoming `row_schema`; the target carries the deterministic PROCESS target
schema, which extends it with required, grain, parent, row, completeness, gap,
and unsupported fields. All three share grain type/keys/multiplicity and
action/family identity, and StateStore validates their distinct exact
projections as one complete triple.
`gasl_process_fail_stop_restoration_v3`
restores that bundle; a changed-family target restores the prior family and
records the attempted family only as audit. The authoritative
`gasl_process_call_ledger_v4` lives under the run's
`answers/gasl_artifacts/process_call_ledger` directory; there is no
repository-global or external fallback. Its ownership and open/completed records
bind exact version/persistence/job, state and artifact roots, checkpoint path,
query and digest, authoritative/audit/nonsemantic flags, and the
source/target/command/occurrence/attempt identities. Each logical PROCESS model
call, including retries and missing-row repair, has a durable reservation and
terminal record there. Symbol and plan provider calls instead consume one
durable outer traversal-iteration reservation. Trace and prompt-observation
streams are auxiliary audit sinks rather than reservation authority; all of
these execution records are nonsemantic. Terminal answers remain redeliverable
until an outer caller explicitly acknowledges them. The current
question-pipeline path deliberately does not claim that acknowledgement.
Standalone diagnostic final synthesis is the sole documented unreserved
provider-call residual, so it may repeat without acquiring criteria or evidence
authority. For a plan-backed terminal answer, StateStore writes one nonempty
`terminal_final_answer_at` value identically to the completed plan and linked
traversal in one save; recovery and acknowledgement require exact equality.
Completed batch indices and digest keys must form the same contiguous prefix;
each owned file digest is recomputed. Canonical digests also bind unsupported
rows and the terminal exact ordered unresolved-token suffix. Mismatch is
fail-closed, but the hashes are not external authentication against an actor
able to rewrite both files and digests.
`gasl_plan_action_commit_v1` atomically owns history, summaries, artifacts,
materializations, PROCESS retirement, and cursor movement under
`gasl_plan_action_state_transaction_v1`. Persisted ownership uses
`gasl_plan_execution_v1`, `gasl_plan_outer_disposition_v1`, and
`gasl_final_answer_disposition_v1`.
`gasl_plan_resume_preflight_v1` verifies the exact plan and committed prefix and
runs semantic input preflight only from its first uncommitted step. The
read-only `gasl_process_resume_admission_v1` admits a staged nonactionable
continuation only for its exact active v4 snapshot and never makes it generally
actionable. Empty-query adoption additionally rejects every prior PROCESS,
plan, traversal, family-bound variable, or nonempty/malformed canonical ledger;
only pristine state can take a first query.

The same outer-disposition transaction owns a separate
`gasl_process_outcome_reconciliation_v4` audit. Clean completion still requires
`outer_failure_summary == {}`; its audit must report `needs_repair: false`, zero
live incidents, empty top/item live code and incident-ID lists, and no structural
defects. Repair and fail-stop summaries alone own live failure reasons under
exactly `needs_repair` or `repair_budget_exhausted`. Their
count-aligned audit `(reason_code, gasl_outcome_incident_id_v1)` pairs must match
exactly. PROCESS owners are unique by target/family, their item pair sets are
globally disjoint, and their union equals the PROCESS-tagged authoritative
failure pairs. PROCESS IDs bind target, continuation family, and final writer as
well as the code, preventing equal codes from collapsing distinct families;
non-PROCESS IDs bind canonical reason payload plus ordinal and remain top-level.
Every PROCESS item binds final writer/status, resolved/live codes and IDs,
structural and durable row/sidecar/missing-binding diagnostics, and reconciled
action entries consisting exactly of result index plus command, occurrence, and
attempt IDs. It records predecessor-plan ownership and an exact partition of prior incident IDs
into carried, retired, or same-code re-keyed IDs. The exact v4 transition
classes are `current_plan_family`, `carried_clean`, `carried_unchanged`,
`partially_retired`, `resolved`, `final_writer_rekeyed`, `reevaluated`,
`reevaluated_clean`, `superseded_family`, and `structural_mismatch`.
Supersession names the replacing family and its exact input actions. Successor
creation atomically snapshots and consumes one exact
predecessor with forward/reverse links; recovery requires byte-equivalent copied
failure and audit state, preventing untouched families from disappearing.
PROCESS restoration records one restored-bundle item/pair. A non-PROCESS
fail-stop has an empty PROCESS reconciliation list only when there is no live
committed PROCESS owner; otherwise every owner remains represented and the
separate non-PROCESS pair remains top-level. The audit is nonsemantic. Any
non-v9 persisted execution fails the recovery fence except pristine unversioned
empty state adopting its first query.

This v9/v4 boundary has source-review clearance only. A fresh real execution is
still required for runtime and semantic validation.

Same-target continuation is governed by a query-bound
`gasl_process_continuation_family_v4`, separate from attempt audit lineage, and
the exact `gasl_process_declared_grain_identity_v1` type, keys, and multiplicity
contract. Its family digest includes the exact required-field role version and
map plus the canonical budget-free v5 semantic-family projection and
`gasl_process_source_role_contract_v2`. The semantic-family projection binds
version, token and uniqueness policy, mode, cardinality, required fields and
roles, and output shape while excluding per-occurrence input and model-call
budgets. The exact source-role projection binds
the deterministic-producer version, row schema, grain, multiplicity, evidence
state, and operational-token version. Family v4 also binds persistence,
state/artifact path, job, query digest, target, and semantic-operation identity;
it is query/run-bound rather than global. Missing or ambiguous identity or producer
drift fails closed. Prior semantic field values
and authoritative bindings are monotone and never overwritten. An exact-identity
collision may add a missing field with an authoritative binding or union an
authoritative same-value binding; new identities append and conflicting values
do not replace prior values. For a nonempty contract, replacement, new, and
collision records archive superseded partial diagnostics, re-evaluate existing exact
REQUIRED_FIELDS bindings, and recompute current gaps and completeness;
`REQUIRED_FIELDS []` is a no-op. Operational diagnostics may therefore change
without weakening prior semantic values or bindings. The unresolved sidecar is replaced by the current
remainder. Unsupported audit records instead
deduplicate and accumulate, with historical count, current-action delta
(including a repeated current defect whose audit record deduplicates), and
persisted total reported separately; historical-only audit does not drive
repair. Carried, new, deduplicated, augmented, conflicting, binding-union, and
identity-conflict counts are operational diagnostics, not semantic progress.
The unresolved sidecar is not a general retained-command input: only direct
`PROCESS <target>__unresolved ... AS <target>` consumption is legal, with the
same stable family and semantic contract. Every other consumer or target fails
closed; unsupported sidecars are SHOW-only audit state.

PROCESS occurrence, attempt, call-budget, and terminal fields are action-local
control identity. `PROCESS_EXECUTION_METADATA_FIELDS` and
`without_process_execution_metadata()` define one central removal boundary:
the executor strips those fields from every non-PROCESS result before rebinding
context outputs, and StateStore strips non-PROCESS summaries,
materializations, and artifacts again at durable commit. `commit_plan_action()`
then commits materialization, history, action identity, and cursor advancement
together. A downstream `MERGE` must therefore commit once and advance once; it
cannot inherit or retire the preceding PROCESS occurrence.

Unexpected plan-action failures are also fail-stop bounded.
`gasl_active_plan_interruption_v2` persists counts for each exact
action/cursor/error signature across interleaving and a separate total for the
active action/plan. The third occurrence of one signature produces terminal
`active_plan_interruption_halted` /
`active_plan_identical_interruption_recovery_exhausted` state; eight total
interruptions produce `active_plan_total_interruption_recovery_exhausted`.
This bounds recurrence of one defect and alternating-defect recovery, not global
trace bytes. A run that does not subsequently emit a non-seed terminal criteria
snapshot and transition, the corresponding reward artifact, and a final-answer
artifact is invalid and incomplete; seed artifacts cannot support a semantic
judgment about that run.

Table accumulation is monotone with respect to semantic field values and
authoritative bindings, not raw operational diagnostic strings. For a nonempty
required-field contract, recomputation archives superseded partial diagnostics
and may replace a stale top-level `evidence_gap` or `completeness` marker with the
current contract-relative view. That row-level marker cannot itself resolve a
criterion; the projector still requires exact current authoritative bindings.
Typed derived resolution remains future work for transformations that do not
already have such bindings.

The estimate is a separate completion input. `completion.py` considers it
actionable only when it contains count targets, its scope state is `estimated`,
and no blocking issue or underexplored bin remains. Persisted search-space
probes can inform those scope diagnostics, but probe count is not currently an
actionability threshold and no search diagnostic can support or resolve a
criterion.

Persisted completion replay uses state version 2 and the
`criteria_completion_state_v2` contract. The contract binds the state to the
exact table-spec ID, criteria-projection version, membership-contract version,
and estimator-contract version. A legacy state, wrong state version, or
contract mismatch is not replayed as active completion state: its semantic
fields are discarded, an open high-severity
`completion_state_contract_migration_required` issue is recorded, and scope
remains `insufficient_evidence` until a fresh compatible state is produced. No
automatic semantic completion-state migration is implemented.

Completion blockers are lifecycle records. Underexplored bins and estimate
issues merge by stable ID, so omission or an empty replacement cannot clear a
prior blocker. It becomes nonblocking only when a record with the same ID has
status `accepted`, `deferred`, `out_of_scope`, or `resolved`.

Aggregate count targets are also monotone by default. If a fresh estimate
proposes a lower expected count, the merge retains the prior expected-count
floor unless a `target_revision` identifies the prior target and count, names
the revised count, has status `accepted`, `supported`, or `resolved`, and cites
supporting sources already present on the merged target. `target_transitions`
records whether that supersession was accepted or rejected.

## Acquisition Estimate and Search Memory

The expected-result estimate is numerical method output, not a model-synthesized
expectation. For each frozen `(scope_path, epoch, channel)`,
`IncidenceEstimator`, configured by a frozen `ChannelSchema`, emits an
`IncidenceEstimate` with the required numeric roles `observed_results`,
`rarefied_results`, `expected_results`, and `remaining_results`, each with the
band and status contract in `docs/ACQUISITION_LOOP.md`. It also emits exact
`window_observed_results` and declared parameters needed for controller
arithmetic. Extra estimator statistics use typed, versioned numeric
diagnostics. The current controller derives `rarefaction_tail_yield` and may
emit it as a typed, versioned controller diagnostic; it is not an
`IncidenceEstimate` field. Bias-corrected incidence Chao2 internally fills the
`expected_results` and `remaining_results` roles. The controller sees only
typed estimate roles, never Chao-specific state. A future
`IncidenceEstimator` version may replace that internal calculation while
filling the same numeric bands under a new version and experiment; it cannot
alter rolling rarefaction or emit the verdict. Models never author or revise
any of those values.

Search planning remains adaptive, but uses a different channel. After a unit's
incidence sample, estimates, and arithmetic verdict are immutable, the
post-verdict hook may publish typed learning observations: queries attempted,
accepted and rejected sources, extracted terms/entities/relations, unresolved
criteria and columns, costs, provenance references, and the estimator/verdict
record. A future strategy source may read those observations to propose new
query strings. It cannot alter the current sample, status, estimate, threshold,
streak, or verdict.

The design is task-generic. Channel declarations come from the table/criterion
contract; query vocabulary comes from the question, current deficits, accepted
evidence, and prior typed observations. No domain term is baked into estimator
or controller code. Strategy mutation starts a new deterministic epoch so a
changed acquisition distribution is not silently mixed into one Chao2
population.

Semantic fulfillment and acquisition convergence remain distinct. An
acquisition scope may end locally because all required channels meet their
registered rarefaction and remaining-richness thresholds; only the root may
call the whole acquisition run converged. A safety bound, provider failure,
dependency failure, or exhausted frontier while criteria remain unresolved is
typed incomplete, never fulfilled. Operational row counts, provider-result
counts, and model prose cannot satisfy a goal.

Runtime termination and semantic completion are reported separately.
`table_fill_gasl_runtime_status_v1` projects only a durable terminal GASL
owner bundle into `semantic_stop_context_v3` / `stop_policy_state_v3`. The
bundle requires PROCESS persistence v9 and run-local call-ledger v4, exact
current job/query, the durable answer disposition, one linked terminal traversal,
and the matching
terminal plan for either clean synthesis or a plan defect. Active PROCESS
owners and competing pending/disposition plan owners must be absent. A
plan-less pre-plan
defect must instead use that traversal's own failure summary; no global summary
fallback is accepted. Clean completion additionally requires `llm_analysis`, a
`clean_finalize` / `final_synthesis` plan, and agreeing durable answer status.
A terminal runtime defect reports `execution_status:
halted_execution_error` plus its exact `execution_error_reason`. This stop is an
orchestration guard that bypasses replaceable policy logic and precedes
fulfilled, frontier, paper, and round-budget stops, so a budget cannot mask it.
Its reported `goal_status` remains `incomplete`. This operational status does
not revise the criteria snapshot, transition, or reward.
Malformed GASL result/final-state containers are projected as typed execution
errors and normalized to an empty operational export input so they still reach
the guarded stop and final artifact. A required empty search frontier is also
an orchestration-owned terminal condition; a custom policy cannot record
`continue` while the loop exits for lack of an executable action. A bootstrap
universe gap returns early only on a terminal decision; when frontier and paper
budget remain actionable, a nonterminal decision enters the normal round/search
path. At the hard outer-round cap, a custom nonterminal decision is likewise
replaced by the orchestration-owned `round_budget_exhausted` stop. Finalization
reasserts this invariant before serialization, canonicalizes an otherwise
impossible zero-round nonterminal return to the same halt, and rejects any
other premature nonterminal return, while preserving any higher-priority
execution error.

Every round artifact carries runtime-status v1. A round that does not invoke
GASL records `status: not_run` and its skip reason. In `final_answer.json`,
`gasl_runtime_status` is explicitly the final-round status; a separately
labeled last-observed status and round may describe the most recent actual GASL
execution without becoming the current stop authority. Without an execution
error, `execution_status` says whether execution finished or halted on a
budget/frontier, while `goal_status` is `fulfilled` only when the
supported/unresolved criteria contract is satisfied.

The table-mode handoff is also explicit. `declared_table_export_v2` exports only
declared deliverable variables and preserves partial records.
`criteria_input_materialization_v2` strips model provenance and restores only
live registry bindings for the exact observation, field, and normalized value.
`criteria_guarded_final_synthesis_v4` renders the user-facing answer only from
source-supported semantic criteria and unresolved/conflict/structural-family
status, labels an execution-error result, and carries its operational status and
typed reason; raw GASL prose is retained only as a labeled diagnostic.
`table_fill_replay_v4` binds those artifacts together. None of these contracts
turns an operational row, PROCESS result, or natural-language answer into
semantic support, and the cleared source still requires a fresh real rerun for
end-to-end evidence.
