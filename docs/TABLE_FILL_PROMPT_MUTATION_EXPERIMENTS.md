# Table-Fill Prompt-Mutation Experiments

> **STATUS (amended 2026-08-28): historical mechanism design context; flow and
> estimator superseded.** The
> prompt-mutation design here stands, but the surrounding flow it assumes —
> phase-batched rounds, round-end crediting, registry-based rarefaction — is
> superseded by `docs/ACQUISITION_LOOP.md`. Strategy-level continue-or-switch
> is now a measured verdict at the strategy grain of the acquisition loop
> (phase 4D). Mutation may consume only post-verdict typed observations when
> proposing future strings; it cannot change the current incidence sample,
> estimate, or verdict. `IncidenceEstimator`, configured by a fixed
> `ChannelSchema`, produces the generic role-based decision-facing
> `IncidenceEstimate`; its rarefied role is required, and bias-corrected
> incidence Chao2 internally fills the expected and remaining roles. Read
> mutation ideas from here and the method from the charter.
>
> Historical sequences below that ingest provider results into a graph, invoke
> GASL afterward, or place table materialization inside one round are not
> implementation instructions. In the current method, Firecrawl and GASL are
> peer search types; graph addition is a separate human-mediated completed-run
> merge boundary; table compilation is a versioned state transformation, not
> an Episode.
>
> Round removal (2026-08-31): the round concept is deleted from the live tree.
> Where this file speaks of rounds or per-round artifacts, the live semantics
> are Episode identity and Episode-owned attribution per the charter.

## Purpose

This is the implementation checklist for converting target-deficit search from
isolated query generation into prompt-mutation experiments.

The design is generic. It applies to any table-fill question, table contract,
target deficit, and source corpus. Search prompts and runtime code must derive
task-specific words from the question, table specs, current criteria snapshot,
accepted sources, and observed deficits rather than embedding question-specific
vocabulary in code.

## Semantic Contract

Prompt mutation operates on criteria, not record cardinality. The semantic
goodness and scalar reward units are membership-projected supported and
unresolved claims plus bounded semantic-claim/canonical-source pairs backed by
exact registered support. Source-local support that cannot project under the
declared membership remains diagnostic. Operational table records,
search-hit counts, accepted-source counts, graph deltas, path scores, and
best-guess candidate counts are diagnostics and cost observations only.

The active graph anchor is the earthquake two-grain contract: event-level
impact measures joined to country-year context. A single dense country or
period may serve as a debugging branch across events, scales, and time
periods, but it is never a separate or exclusive use case — the design is
generic over any declared table contract, and an earlier anchor on a
different subject domain is retained only as read-only history. The mature
legacy GraphML remains read-only retrieval and path context. Merged nodes, edges, `source_refs`, and `source_chunks` from that
graph are not evidence. Direct graph edges from fresh extraction are also
discovery links, not assertion support; only reified registry assertions and
their exact evidence joins can support criteria.

Evidence is first-class in `evidence_registry_v2`: source documents and
versions, aliases, evidence items, source-local observations, and field and
relationship assertions have immutable content-derived identities. The
registry rejects a conflicting payload for an existing identity. Schema
`merge_policy` is explicit: `exact` concepts merge only on the same normalized
display name and never enter fuzzy, substring, abbreviation, or synonym
matching; only `canonical` concepts are fuzzy-merge eligible, and source-local
or immutable records do not concept-merge. Alias records aid lookup, but DOI,
PMID, URL, and other aliases do not yet have a complete equivalence resolver. A
criterion is supported only when
`criteria_projection_v10` resolves its exact field and value through the same
observation's assertion and evidence item to an active versioned canonical
source document. The registry must also derive the reported observation's
cross-version `semantic_claim_id` from the canonical document, observation
type, and exact anchor checksum; a copied snapshot or sidecar cannot mint it.
`criteria_transition_v7` is the corresponding transition version and reward
version. `project_criteria()` accepts only a live `EvidenceRegistry` as support
authority; missing or mapping-shaped registries fail closed. Deserialized
snapshots clear serialized support, carry
`criteria_projection_v10:unvalidated_replay`, and are audit-only. Reward v7
returns unknown status, zero score, and no transition or components for that
version mismatch; offline scoring requires authoritative reprojection first.

The extraction prompt requires a source-local observation name to copy one
contiguous source phrase. The collector must locate that quote uniquely in the
content-hashed chunk before it records an `observation_clause_exact` anchor.
For types with schema-declared `association_fields`, every association value
must be a recognizable scalar and each unique nested field quote must contain
its own value plus every association-tuple fragment. Numeric and measure guards
reject extra or ambiguous claims. Accepted spans are
`field_quote_exact:<field>` evidence. Nearby text and repeated, differently
anchored, coordinated, or multi-claim quotes do not ground the field.
Descriptions and attributes without exact grounding, and source-extracted
semantic `RelationshipAssertion` records, remain `candidate_unverified`. This
is typed lexical atomic grounding, not semantic entailment. Novel text-only
measure notation that the typed guard does not recognize and comparisons spread
across multiple caption sentences deliberately remain candidate-only.

Each `FieldAssertion` stores the `typed_exact_tuple_v2` contract and stable
acceptance or rejection reasons. Those are immutable diagnostics of the
grounding outcome, not a complete replay record: the registry does not persist
the full rejected occurrence, schema snapshot, or every alternative quote span.

Phrases containing `respectively` fail closed. Literal spans for every list
member do not establish their ordered association, so even a correct parallel
enumeration remains unresolved until a typed ordered-list or tuple assertion is
implemented. Literal grounding also proves only that the immediate source
version contains the statement. The registry has no typed
primary-versus-secondary citation role; a secondary document therefore cannot
establish that the statement is primary-study evidence.

A subject-bound partial operational record supports only fields with
independent registered assertion support; an unbound record cannot create a
semantic subject. A present but unsourced value alone remains unresolved; an unsourced
alternate does not veto an independently source-supported value. Conflicting
sourced values remain unresolved.

The artifacts described below reflect the historical implementation. In the
active target design, an enabled best-guess field is a real declared result
column. It can be accepted only through an acyclic, named, versioned,
deterministically recomputable derivation whose exact direct input assertions
retain source-version and text-span traceability. Candidate generation alone
earns no acceptance, incidence, or semantic support. A standalone or malformed
sidecar cannot close a criterion.

`criteria_projection_v10` gives every multi-key subject a required
`__subject_identity__` criterion. Raw key fields must resolve through
registered assertions on a common source-local observation; a shared
`(evidence_item_id, source_id)` pair alone is insufficient. Aggregate
membership and source rarefaction use the same joint-identity boundary.
Individually evidenced key components remain supported while an unbound tuple
stays unresolved. Raw
non-key fields must join an exact registered assertion on the observation that
establishes the subject. Sourced or row-level complete markers do not close
evidence or task coverage.
Version 2 construction rejects operational transport fields configured as
semantic keys or non-nullable criteria. The explicit version 1 compatibility
path instead demotes affected fields to nullable diagnostics, records the
migration, and does not invent a semantic key. The projector enforces the same
semantic filter for direct and replay callers.
Derived `best_guess` columns also cannot be keys. Missing or corrected derived
keys require a future provisional-subject identity, typed derived analysis,
and typed rekey transition; historical specs using them must declare stable
reported semantic keys.

PROCESS normalization cannot close a criterion from row-level provenance. The
materialization validator strips model-emitted provenance and preserves only a
pre-registered binding containing the exact assertion, evidence item,
versioned canonical source document, field, typed value, and matching
observation or subject anchor. Merged graph source references never become
field support. Prior semantic values and authoritative bindings are monotone;
operational partial/gap markers are contract-relative and may be archived and
recomputed for a nonempty required-field contract. Renamed, normalized, or
generated fields fail closed unless an already registered typed derived
assertion exists; otherwise the field lacks authoritative support and remains
unresolved. PROCESS serializes validated provenance under
`assertion_bindings`, which is the container consumed by
`criteria_projection_v10`; PROCESS never closes coverage. Recomputed operational
`completeness` and `evidence_gap` markers have no semantic authority by
themselves. The projector still requires exact current bindings, and typed
derived resolution remains unimplemented for transformations without them.

Prompt experiments must use `gasl_process_execution_v5` under
`gasl_process_execution_policy_v5`. A PROCESS action declares exactly one of
`semantic_filter/zero_to_n`, `eligible_materialization/zero_to_n`, or
`exact_enrichment/exactly_input`; supplies structured `REQUIRED_FIELDS`; and is
bounded to 72 inputs and eight logical model calls: at most five primary batches
of 15 plus three repair-reserved calls.
`gasl_process_required_field_roles_v2` makes each required entry exactly a
source-bound semantic assertion, declared-grain identity, registry-metadata
field, or authoritative binding container. Semantic fields need exact active
FieldAssertions; identity fields must be exact declared source grain keys.
Registry metadata and `field_evidence` must exist in the exact durable source
schema and use deterministic nonsemantic authority, not fictitious assertions.
FIND grain `id` therefore cannot satisfy required identity `observation_id`.
Reserved, assertion, criterion, unknown, and other operational containers fail closed.
Zero filter output is successful zero output. Only exact enrichment preserves
one output per input, and unprocessed input is exposed under the named
`__unresolved` continuation rather than silently dropped or repopulated. The
`__unresolved` and `__unsupported` suffixes are runtime-reserved. Their exact
contracts are `process_unresolved_inputs` / `usable_by=["PROCESS"]` and
`unsupported_process_outputs` / `usable_by=["SHOW"]`, respectively.

`gasl_process_operational_row_token_v1` binds every model-visible source and
response row to an opaque hash of its exact ordered, typed declared grain.
Prompt trials must preserve the token exactly. Alias, string coercion, ordinal
fallback, mismatch, and actual duplicate grain tuples fail closed. Duplicate
grains are a noncontinuable upstream producer defect, and tokens are operational
parent attribution rather than evidence or semantic identity.
`target_row_count` and every other PROCESS count are execution observations,
not prompt reward, semantic goodness, or completion.
`gasl_process_declared_grain_authority_v2` records the accepted row's exact
grain type/keys/values and parent token; prompts cannot author or alter it, and
it is not a FieldAssertion.

Prompt plans may consume a durable output only when its exact
`gasl_deterministic_producer_contract_v1` projection of payload, schema, grain,
multiplicity, `usable_by`, and evidence state admits the command. Planner and
runtime projections must agree; the planner, compiler, executor, runtime,
and StateStore enforce the same rule. Same-type DECLARE preserves that contract.
A defined empty FIND or retained PROJECT, COLLAPSE, GRAPHWALK, JOIN, MERGE, or
SELECT is successful durable output, not an automatic repair trial. Empty
SELECT, PROJECT, COLLAPSE, and GRAPHWALK carry declared schemas. JOIN requires
its key in both input schemas and emits the deterministic joined
union-plus-identity schema even when empty; empty MERGE may retain only the
deterministic union of available source schemas. On the
in-scope NetworkX backend, `gasl_graphwalk_limits_v1` enforces depth 1--8, a
deterministic 100-source slice, the first 50 deterministic incident edges per
node, and a prospective global cap of 10,000 unique declared-grain
queued/emitted rows; emitted rows are a deduplicated subset within that cap.
Ordered typed truncation reasons make the result partial,
non-search-actionable, non-continuable, and unable to close coverage. There is
no truncation continuation. Narrowing or replanning is experiment guidance, not
automatic executor repair: a successful truncated walk may clean-finalize
operationally, but cannot close criteria. These are explicit liveness/cost
limits, not experiment success or semantic support. Neo4j `id_filter` and
source/target filtering remains an out-of-scope backend residual.

Graph prompt values preserve declared type and grain. FIND nodes use `id`, edges
use `(src_id,tgt_id,relation_type)`, paths use `path_id`, and GRAPHWALK adds
`path_depth`; alias conflicts and duplicates fail closed. Bare `a`, `an`, `any`,
`all`, and `*` are relationship wildcards. Literal collisions, strings looking
numeric/boolean, values containing `,` or `|`, and values beginning
`relation_type=` or `relationship_name=` must be JSON quoted.

The execution boundary uses `gasl_process_execution_persistence_v9`, with
`gasl_traversal_execution_v1` state and a read-only
`gasl_execution_recovery_ownership_v1` check before wrapper seeding. Each
in-flight action uses `gasl_process_attempt_snapshot_v4` to preserve exact prior
input, target, unresolved, and unsupported state before the pre-call
started/pending target-plus-sidecars triple. Both sidecars carry the exact
incoming `row_schema`; the target carries the deterministic PROCESS target
schema extending it with required, grain, parent, row, completeness, gap, and
unsupported fields. Grain type/keys/multiplicity and action/family identity are
shared, while StateStore validates distinct exact target and sidecar
projections.
`gasl_process_fail_stop_restoration_v3` restores
that exact bundle and keeps a changed-family conflict separate from the active
interruption reason. The authoritative
`gasl_process_call_ledger_v4` is stored inside the run at
`answers/gasl_artifacts/process_call_ledger`; it has no external fallback and
binds exact state/artifact/checkpoint, run/job/query, persistence,
source/target/command, occurrence, and attempt identity. Each logical PROCESS model call, including
retries and missing-row repair, has a per-call durable reservation and terminal
record there. Symbol and plan provider calls instead consume a durable outer
traversal-iteration reservation. Trace and prompt-observation streams are
auxiliary audit sinks. These records have `semantic_evidence: false` and cannot
become reward labels. Active or terminal ownership resumes without reseeding
under an exact job/query match. Terminal GASL answers remain redeliverable until
an outer acknowledgement; question-pipeline does not currently claim that
acknowledgement. Standalone diagnostic final synthesis is the sole documented
unreserved provider-call residual, so its repetition is not an experiment
success. A plan-backed terminal answer uses one shared nonempty
`terminal_final_answer_at` value written identically to its completed plan and
linked traversal in one StateStore save; recovery and acknowledgement reject a
missing or unequal pair. `gasl_plan_action_commit_v1` atomically persists
history, summaries, artifacts, materializations, PROCESS retirement, and
cursor under `gasl_plan_action_state_transaction_v1`. Persisted owners use
`gasl_plan_execution_v1`, `gasl_plan_outer_disposition_v1`, and
`gasl_final_answer_disposition_v1`. `gasl_plan_resume_preflight_v1` proves the
exact committed prefix and
returns the first uncommitted step; `gasl_process_resume_admission_v1` admits a
staged nonactionable sidecar only for its exact active v4 snapshot. Empty-query
adoption rejects all prior PROCESS/plan/traversal ownership, family-bound
variables, and nonempty or malformed canonical ledger state.
The ledger additionally requires one exact contiguous completed-batch/digest
prefix, recomputes every batch-file hash, and binds canonical unsupported and
terminal unresolved-row digests. A partial remainder must be the exact ordered
unprocessed-token suffix. A mismatch fails closed; hashes are not external
authentication and the ledger stays audit-only/nonsemantic.

Completed outer dispositions atomically own a separate
`gasl_process_outcome_reconciliation_v4` audit. Clean execution keeps
`outer_failure_summary == {}` and requires `needs_repair: false`, zero live
incidents, empty top/item live code and incident-ID lists, and no structural
defects. Repair and fail-stop failure summaries remain the sole owners of live
reasons under exactly `needs_repair` or `repair_budget_exhausted`. The audit
must exactly match their count-aligned
`(reason_code, gasl_outcome_incident_id_v1)` set. PROCESS owners are unique by
target/family; globally disjoint item pairs must equal all PROCESS-tagged top
pairs. Each item ID also binds target, family, and final writer, so equal codes
cannot collapse distinct families. Each PROCESS item records predecessor-plan ownership and exact
final status, resolved/live codes and IDs, structural and durable
row/sidecar/missing-binding diagnostics, exact result-index/command/occurrence/
attempt action entries, and prior/carried/retired/re-keyed incident IDs. The exact v4 transitions are
`current_plan_family`, `carried_clean`, `carried_unchanged`,
`partially_retired`, `resolved`, `final_writer_rekeyed`, `reevaluated`,
`reevaluated_clean`, `superseded_family`, and `structural_mismatch`;
supersession names its replacement family and input actions. Successor
creation atomically snapshots and consumes one exact predecessor with reverse
linkage, and recovery requires byte-equivalent copied failure/audit state. A
restored PROCESS fail-stop has one classified item/pair. A non-PROCESS fail-stop
has an empty PROCESS reconciliation list only if no live committed PROCESS owner
exists; otherwise every owner remains represented and its separate incident is
top-level. The audit is nonsemantic. Any non-v9 persisted execution is
deliberately nonresumable, except pristine unversioned empty state adopting its
first query.

These v9/v4 prompt and persistence claims have source-review clearance only.
They remain unvalidated by a fresh real execution.

Continuation trials use a query-bound
`gasl_process_continuation_family_v4`, separate from attempt lineage, and exact
`gasl_process_declared_grain_identity_v1` grain type, keys, and multiplicity.
Family v4 binds the exact role map, canonical budget-free v5 semantic-family
projection, and
`gasl_process_source_role_contract_v2` projection of deterministic-producer
version, schema, grain, multiplicity, evidence state, and token version.
The semantic-family projection excludes per-occurrence input and model-call
budgets.
It also binds persistence, state/artifact path, job, query digest, target, and
semantic operation; prompts must not treat a family ID as global. Missing or
ambiguous identity or producer drift fails closed. Prior semantic field values and
authoritative bindings are monotone and never overwritten. An exact-identity
collision may add an authoritatively bound missing field or union an
authoritative same-value binding. New identities append and conflicting values
cannot replace prior values. For a nonempty contract, replacement, new, and
collision records archive superseded partial diagnostics, re-evaluate existing exact
REQUIRED_FIELDS bindings, and recompute current gaps and completeness;
`REQUIRED_FIELDS []` is a no-op. Operational diagnostics may therefore change
without weakening prior semantic values or bindings. Current unresolved remainder replaces prior
unresolved state. Unsupported audit records deduplicate and accumulate, but the
contract reports historical count, current-action delta (including a repeated
current defect whose audit record deduplicates), and persisted total separately,
and historical-only audit cannot trigger repair. The carried, new,
deduplicated, augmented, conflicting, binding-union, and identity-conflict
counts are execution diagnostics rather than experiment reward. An unresolved
sidecar is consumable only by the direct same-target
`PROCESS <target>__unresolved ... AS <target>` continuation with the same stable
family and semantic contract. Every other consumer or target fails closed;
unsupported sidecars are SHOW-only audit state.

PROCESS control identity is not an inheritable prompt or data feature.
`without_process_execution_metadata()` removes occurrence, attempt, call-budget,
and terminal fields from every non-PROCESS result and rebound context contract;
StateStore applies the same central sanitization to non-PROCESS summaries,
materializations, and artifacts before atomically committing output and cursor.
A downstream `MERGE` is valid only when it commits once and advances once,
without carrying the prior PROCESS occurrence.

Repeated execution exceptions are observations, not additional prompt trials.
`gasl_active_plan_interruption_v2` persists per-signature counts across
interleaving plus a separate active-action/plan total. The third occurrence of
one exact signature terminalizes with
`active_plan_identical_interruption_recovery_exhausted`; eight total
interruptions terminalize with
`active_plan_total_interruption_recovery_exhausted`. This bounds only trace
growth attributable to one repeated signature and total recovery for that
active action; it is not a global trace byte cap. The fail-stop prevents one
execution loop from inflating learning data. No prompt experiment outcome is
interpretable without a non-seed terminal criteria snapshot and transition,
corresponding reward artifact, and final-answer artifact.

Saved source lineage is explicit selective replay, not corpus discovery or a
KG rebuild. Only caller-selected source IDs already referenced by the seed
graph are resolved to an unambiguous saved body and freshly extracted. Omitted
legacy sources remain candidates/context, and full legacy migration is not yet
implemented. Content hashes and exact spans ground only what that selected
local body contains; the replay path does not independently authenticate it as
the claimed external publication.

Completion state cannot close by omission either. Underexplored bins and
estimate issues persist by stable ID until the same ID receives an accepted,
deferred, out-of-scope, or resolved status. A lower aggregate expected count is
rejected in favor of the conservative prior floor unless an explicit,
source-supported `target_revision` joins the prior target/count to the revised
count; accepted and rejected supersessions remain in transition history.

The aggregate estimator is also fail closed by contract. Table-spec version 4
retains the semantic membership contract, migrates version 1 operational keys
and required transport columns to nullable
diagnostics, records that compatibility migration, and does not invent a
semantic key. Version 3 added explicit task-owned
`criterion_contract_id` and `required_criterion_families`. Each family declares
its stable ID, rule version, exact accepted observation types, required fields,
target adapter, and any required runtime capability. Version 4 adds optional
exact author-owned `required_field_values`; their keys must be required fields,
and every constrained value must be supported on the same registry claim.
Families and predicates are authored from the question and are never inferred
from tables, descriptions, records, model routing, aliases, or keys.

Projection recomputes every family even when its adapter table is empty. One
bound observation with all required fields on one accepted semantic claim is an
existence witness only, never coverage. Missing capabilities produce structural,
non-search-actionable deficits. Required-family assessments emit no source or
evidence support units and are filtered from membership, rarefaction, and scalar
reward; only the underlying atomic field criteria receive source-grounded
credit. Missing supported predicate fields yield
`required_family_field_values_unresolved`; supported values that differ from
the normalized exact task literals yield
`required_family_field_values_mismatched`. Under `semantic_membership_v2`, only a validated
`semantic_signature` whose declared signature fields share one observation and
canonical source is eligible for
`supported_semantic_signature_chao1_v1`. A `source_observation` table defines
source-local occurrence grain. Its registry-owned `semantic_claim_id` can enter
semantic criterion projection and reward, but it does not define cross-source
species or overlap and therefore remains unestimated by Chao1. A missing claim
ID stays unprojected. Unconfigured or invalid membership remains unestimated
and receives zero reward with explicit projection diagnostics. Raw
source-by-subject incidence is not a universal fallback.

Reward version `criteria_transition_v7` receives the membership modes and
signature columns and records a separate `semantic_transition_id`. Under
`semantic_signature`, novelty is member field/value signature plus criterion
field/value; under `source_observation`, it is `semantic_claim_id` plus criterion
field/value. The source-local transition and support pairs remain attribution
diagnostics where they do not project into that semantic transition.

Persisted completion state version 2 replays only under an exact
`criteria_completion_state_v2` match over table-spec ID, criteria projection,
membership contract, and estimator contract. Legacy or mismatched state drops
its semantic completion fields and creates an open high-severity migration
issue. No automatic semantic completion-state migration is implemented. Search
diagnostics cannot satisfy that issue or close a criterion.

## Round Definition

`round` means the largest table-fill loop only.

One round includes:

1. completion assessment
2. deficit selection
3. search planning
4. search execution and source acquisition
5. source ingestion into the graph
6. graph traversal and operational table materialization
7. best-guess action and candidate diagnostics; typed derived evidence remains
   future work
8. criteria projection and transition
9. criteria reward and diagnostic scoring
10. durable memory update
11. next-frontier scheduling

Smaller loops are not rounds. Use these names instead:

- `evolution`: one prompt-mutation planning step for one target deficit
- `prompt_arm`: one named prompt delta inside an evolution
- `query_attempt`: one concrete external search emitted by a prompt arm
- `search_batch`: the bounded set of concrete query attempts sent to the
  harvester together
- `best_guess_batch`: a bounded group of unresolved declared derived criteria

## Core Definitions

### Strategy attempt

A search strategy attempt is one prompt-mutation experiment for one target
deficit at one evolution step.

It contains:

- a stable `strategy_attempt_id`
- the outer `round_index`
- the `target_id` for the deficit being attacked
- the `evolution_index` inside that target deficit
- several named `prompt_arm` records
- several concrete query attempts per arm
- immediate search observations per query
- candidate URL fates per query
- delayed graph diagnostics and criteria-transition yield after materialization

### Prompt arm

A prompt arm is a small, named prompt delta plus a hypothesis about how that
delta should alter query generation.

Each arm records:

- `prompt_arm_id`
- `name`
- `prompt_delta`
- `hypothesis`
- `expected_source_shape`
- `query_attempts`

### Pseudo-gradient

The pseudo-gradient is contrastive inference-time evidence over prompt arms.

It is not training and it is not reinforcement learning. It is the compact
comparison that tells the next planner prompt which prompt deltas found
non-overlapping useful evidence, which deltas returned only duplicates, and
which deltas found promising sources that failed to support the target
criteria.

## Durable Identifiers

Every concrete `SearchTask` emitted by the target-deficit planner must carry
these metadata fields:

- `control_decision_id`
- `control_action_id`
- `decision_snapshot_id`
- `target_basis_snapshot_id`
- `fill_deficit_id`
- `criterion_ids`
- `subject_ids`
- `strategy_attempt_id`
- `target_id`
- `target_table`
- `evolution_index`
- `prompt_arm_id`
- `prompt_arm_name`
- `prompt_arm_index`
- `query_index`

Those identifiers must flow into:

- `SearchOutcome`
- candidate URL fates
- accepted source records
- graph ingestion diagnostics
- criterion evidence and criteria transitions only when exact registered
  assertion/evidence/versioned-source joins resolve
- best-guess decisions and candidates as operational diagnostics
- prompt-arm scores
- compact search memory

The harvester must not infer prompt-arm provenance from query text.

## Implementation Checklist

1. Read the current partial edits in `question_pipeline/search.py`,
   `search_memory.py`, `strategy.py`, `strategy_state.py`, and `pipeline.py`
   and identify the pieces to keep, rename, or replace.
2. Patch this staging design so a strategy attempt is one prompt-mutation
   experiment for one target deficit at one evolution step.
3. Define the prompt-mutation experiment artifact schema with outer round,
   target deficit, evolution step, arm, and concrete query identifiers.
4. Replace generic search-wave naming in the partial harvester edits with
   prompt-mutation experiment and prompt-arm naming.
5. Extend `SearchTask` metadata so every concrete query carries decision,
   action, decision-snapshot, target-basis-snapshot, criterion, experiment,
   target-deficit, evolution, arm, and query-index provenance.
6. Extend `SearchOutcome` so zero-hit counts, result observations, candidate
   fates, accepted sources, duplicate URLs, and acquisition costs are grouped under
   the originating arm.
7. Persist per-query raw outcomes for replay without losing arm grouping.
8. Persist per-arm summaries under the current outer round artifact directory.
9. Update `SearchMemory.from_outcomes()` to fold query outcomes into
   per-target prompt-arm experiment histories.
10. Store immediate arm observations separately from delayed criteria-transition
    observations and operational materialization diagnostics.
11. Store arm-level contrast records that compare arms tried in the same
    target-deficit evolution step.
12. Update the target-deficit planner output contract so it emits named prompt
    arms with prompt deltas, hypotheses, and several concrete queries per arm.
13. Update the target-deficit planner prompt so it sees prior arm contrast and
    asks for deliberate prompt mutations rather than another isolated query.
14. Update the target-deficit parser and validation path to reject malformed
    arms while preserving valid sibling arms.
15. Add a bounded target-deficit evolution loop inside the outer round that can
    request another prompt-mutation experiment for the same deficit after
    immediate arm contrast is available.
16. Thread prompt-arm metadata through `SearchFrontier` enqueueing so the
    harvester does not need to infer provenance from query text.
17. Run prompt-arm searches through the external-search harvester.
18. Record candidate URL fates including duplicate, blocked, too short, too
    large, extraction failure, and accepted.
19. Keep accepted source IDs linked to the arm that found them through paper
    writing and graph ingestion.
20. Attribute graph node and edge deltas back to accepted sources and therefore
    back to prompt arms as diagnostics.
21. Attribute source-local supported criterion IDs and exact registered support
    units back to accepted sources and prompt arms as audit diagnostics; also
    join the reward-v7 semantic transition before treating that yield as
    goodness.
22. Preserve best-guess results as operational candidates. Do not credit an arm
    unless a future typed derived-analysis assertion passes the ordinary
    criteria transition after projection.
23. Score each prompt arm from reward-v7 supported/resolved semantic-claim yield
    and bounded semantic-claim/canonical-source yield, with duplicate and cost
    penalties. Do not score operational record, accepted-source,
    graph-delta, source-local-only, or best-guess counts as goodness.
24. Write arm scores into durable target search memory for the next evolution
    step in the same outer round.
25. Write arm scores and their stable transition joins into durable target
    search memory for the next outer round.
26. Update `strategy_state` routing to consume reward-v7 semantic arm contrast
    and choose the next mutation family from productive and unproductive arm
    evidence.
27. Close each outer round by refreshing completion, rebuilding deficits from
    the latest criteria snapshot, and scheduling work from arm-scored memory for
    remaining task-level deficits.
28. Rename any remaining inner-loop fields that call subactions rounds so
    `round` means only the full outer loop.
29. Replay prompt-arm experiment artifacts only from real prior rounds; do not
    use synthetic fixtures, mocked services, or mechanics-only smoke checks.
30. Run a real external table-fill round that evaluates arm generation, search
    harvesting, ingestion, materialization, delayed attribution, and
    next-evolution use of contrast through supported/unresolved criterion
    outcomes.

## Implementation Status

| Step | Status | Notes |
| --- | --- | --- |
| 1-5 | Coded | `control.py` and `search_planning.py` now isolate validated search candidates, policy-state manifests, decisions, and actions. Search tasks carry stable control decision/action IDs, policy-state IDs, decision and target-basis snapshot IDs, criterion/subject IDs, and the existing strategy-attempt, evolution, prompt-arm, and query-index joins into the harvester. |
| 6-8 | Coded | Search outcomes now keep compact result observations, candidate URL fates, per-batch arm summaries, and raw per-query outcomes for replay. |
| 9-13 | Coded | Search memory now folds concrete query attempts into target-level strategy attempts with nested prompt arms and arm contrast; the target-deficit prompt asks for named prompt-arm experiments. |
| 14 | Coded | The parser accepts the new `experiments[].arms[].queries[]` shape while retaining the legacy flat `queries` shape. |
| 15-18 | Coded; observed in real continuations | Real continuations exercised bounded same-deficit evolution after zero accepted sources. This is an execution observation, not evidence that the policy improves supported/unresolved criterion outcomes. |
| 19 | Coded | Accepted source IDs are recorded on the originating concrete query outcome and preserved in arm summaries. |
| 20 | Partial | The current diagnostic still stores graph node and edge deltas at target-outcome granularity; exact source-to-graph attribution is still a follow-up. |
| 21-22 | Partial: reported-assertion attribution and PROCESS preservation are coded; semantic best guess is not | After GASL, newly supported criteria can be attributed only through registered reported assertions and exact assertion/evidence/versioned-source support units. `static_best_guess_v2`, `best_guess_binding_v4`, `in_process_v1`, and `persisted_action_join_v1` preserve operational decisions, candidates, and ledger joins, but no typed derived analysis or derived assertion is registered, so these artifacts do not currently enter semantic support. PROCESS preserves only an already registered exact field/value/anchor binding; it does not create one. Transformations, best-guess rekey, and derived supersession remain fail-closed and unimplemented. |
| 23 | Partial; not reward-v7 aligned | Prompt arms are currently scored from target-bound source-local criterion and canonical-source-pair hits. The reward-v7 semantic transition is not yet joined to each arm, so unprojected local support can affect this heuristic. Duplicate and action-cost penalties are also absent. |
| 24 | Coded | Prompt-arm scores and contrasts are persisted in target search memory for the next evolution. |
| 25 | Coded | Search memory is refreshed after immediate search and again after delayed criteria-transition attribution. |
| 26 | Partial | Target-operator routing consumes aggregate source-local criterion/pair yield for the latest attempt. It does not consume reward-v7 semantic yield or choose a mutation family from nested arm contrast. |
| 27 | Coded | Each outer round rebuilds task-level deficits from the latest criteria snapshot and schedules remaining unfulfilled criterion targets. |
| 28 | Partial | New code uses outer `round`, `evolution`, `prompt_arm`, and `query_attempt`; older persisted artifacts may still contain historical `strategy_wave_id` compatibility fields. |
| 29 | Required evidence policy | Synthetic fixtures, mocked services, smoke tests, and mechanics-only checks are prohibited as evidence. Replay must use real prior artifacts. |
| 30 | Real-run evidence incomplete | Real direct-OpenAI continuations and a real Firecrawl/OpenAI probe exercised the control and attribution path, but no claim of effectiveness follows without the corresponding supported/unresolved criterion transitions. Fresh accepted-source ingestion under the final per-target cap patch is still pending. |

The current output boundary is `declared_table_export_v2`,
`criteria_input_materialization_v2`, `criteria_guarded_final_synthesis_v4`, and
`table_fill_replay_v4`. Prompt-arm or PROCESS observations cannot bypass it:
only exact live registry bindings enter criteria, semantic stop consumes the
criteria goal state rather than row gaps, and raw GASL prose remains a labeled
diagnostic outside the user-facing table answer. These are source-cleared
contracts, not evidence that the pending fresh real suite rerun succeeds.

## Live Validation Notes

These observations predate the final v10 evidence boundary and concern selected
execution paths only. No fresh full-corpus end-to-end run is claimed to have
validated the current evidence refactor, selective replay, PROCESS contract,
and criteria transition together.

- A historical direct one-round continuation with three arms per evolution
  recorded newly planned target searches carrying `strategy_attempt_id`,
  `evolution_index`, `prompt_arm_id`, `prompt_arm_index`, `prompt_delta`,
  `prompt_hypothesis`, `expected_source_shape`, and `query_index` into
  `search_outcomes.jsonl`.
- That same run exposed two defects that were patched before commit: the parser
  trusted duplicated experiment blocks from the planner and Firecrawl result
  observations could copy nested provider metadata into durable prompt-arm
  samples.
- A historical direct harvester probe with one real Firecrawl hit and one real
  OpenAI progress judgment recorded compact search observations that preserved
  scalar hit metadata, persisted candidate fates, wrote prompt-arm summaries,
  and omitted nested provider metadata.
- A historical follow-up one-round continuation with one allowed same-round
  target evolution recorded that carried legacy target searches did not consume
  the prompt-mutation cap. The round drained nine carried searches, generated one
  prompt-arm experiment with two arms and three concrete fresh queries, exported
  arm-yield diagnostics, and finished the outer-round execution.

These historical observations concern execution and attribution plumbing. Their
search, source, graph, or operational-record counts do not by themselves prove
semantic progress; that requires the corresponding criteria snapshot and
transition.

Execution and goal outcomes must also remain separate. `execution_status`
records whether the process finished, halted on a frontier/paper/round budget,
or ended in an execution error. `table_fill_gasl_runtime_status_v1` accepts a
terminal GASL result only when its persistence/ledger, current job/query,
durable answer, exact terminal traversal, disposition mode, plan/iteration
cursor, and owner-local reason agree, with no active PROCESS owner or competing
outstanding plan. Clean completion requires one linked
`llm_analysis` clean-finalize plan. Defect mode requires either one linked
repair-exhausted plan and its summary or the exact plan-less terminal traversal
and its own pre-plan summary; no global failure-summary fallback is allowed.
The pipeline then uses an orchestration-owned `halted_execution_error` stop with
the exact reason, bypassing replaceable policy logic. That branch outranks
budgets and forces reported goal incompleteness without modifying criteria or
reward. A skipped GASL round records `not_run` and its reason; final-round and
last-observed GASL statuses remain separately labeled. A malformed result or
final-state container becomes a typed execution error with an empty operational
export input rather than crashing before the stop artifact. A required empty
frontier is likewise an orchestration-owned terminal condition, so a custom
policy cannot leave a recorded `continue` on loop exit. A bootstrap universe
gap returns only on a terminal decision; actionable frontier and paper budget
carry a nonterminal decision into the normal round/search path. At the hard
outer-round cap, a custom nonterminal decision is overridden to
`round_budget_exhausted`. Finalization canonicalizes an impossible zero-round
nonterminal return, rejects other premature nonterminal returns, and repeats
the fixed-length-loop invariant, while a bound execution error retains
priority. Without an execution error, `goal_status` is fulfilled only when
required criteria are supported; a budget-halted execution with unresolved
criteria remains incomplete.

## Evidence Bar

Implementation status and evidence of effectiveness are separate:

- `coded` means only that an implementation exists;
- real-artifact replay can inspect an actual prior trajectory;
- a real external run can observe current search, acquisition, ingestion, and
  criterion transitions;
- effectiveness requires the intended supported/unresolved criterion outcomes
  with exact decision/action attribution.

Synthetic fixtures, mocked services, smoke tests, and mechanics-only checks do
not constitute progress or evidence that the code works. Operational counts
from a real run are observations, not goodness; only the resulting criterion
state and transition can establish task progress.
