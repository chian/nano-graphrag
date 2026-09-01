# Table-Fill Path Selection and Policy Learning

> **STATUS (amended 2026-08-28): historical mechanism design context; flow and
> estimator superseded.** The
> path-scoring and policy-learning mechanisms here stand, but the loop this
> document assumes — phase-batched rounds with round-end crediting, and an
> evidence registry that is not in the tree — is superseded by
> `docs/ACQUISITION_LOOP.md`: acquisition is a first-class per-unit loop
> (acquire → extract → credit → count → verdict) and rarefaction/crediting
> semantics are defined by that charter and the `Episode` method core. The
> decision-facing record is a generic role-based `IncidenceEstimate` produced
> by `IncidenceEstimator` from a fixed `ChannelSchema`; its rarefied role is
> required, and bias-corrected incidence Chao2 internally fills the expected
> and remaining roles. Read path-feature ideas from here and all acquisition
> flow, counting, evidence acceptance, and verdict rules from the charter.
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

## Technical Gap

The table-fill continuation loop can now do the right high-level sequence:

1. carry seed tables, search memory, and explicitly selected source-lineage
   replay forward
2. search for unresolved criterion and aggregate-target families
3. freshly extract newly accepted sources and selected saved source bodies into
   the versioned evidence registry and graph projection
4. scope GASL to newly evidenced graph neighborhoods
5. seed GASL with `round_source_nodes`
6. traverse paths
7. preserve candidate operational records through `PROJECT`, `PROCESS`,
   `COLLAPSE`, and table materialization
8. project exact registered assertion bindings into one supported/unresolved
   `CriteriaSnapshot`

The active substrate is the earthquake two-grain graph: event-level impact
measures joined to country-year context. A dense country or period is the
branch used to stress event, place, scale, and time coverage; it is not the
scope of the schema, and an earlier substrate on a different subject domain
survives only as read-only history. Concept merging follows the
schema's explicit policy: `exact` concepts merge only on the same normalized
display name and never take the fuzzy, substring, abbreviation, or synonym
path; only `canonical` concepts remain fuzzy-merge eligible. Source-local and
immutable records never concept-merge.

`evidence_registry_v2` keeps source documents and versions, aliases, evidence
items, source-local observations, and field and relationship assertions as
immutable, content-addressed records. The mature legacy GraphML is read-only
candidate/context data. Direct graph edges, whether legacy or freshly
extracted, are discovery links and do not support criteria; registry assertions
are reified records whose exact joins must survive projection. Saved source
lineage is replayed only for explicitly named source IDs with one unambiguous
stored body, followed by fresh extraction; this is not corpus discovery or KG
rebuilding. Full legacy migration has not been implemented.
Alias records aid lookup, but DOI, PMID, URL, and other aliases do not yet have
a complete source-equivalence resolver. Content hashing and exact extraction
ground claims in the selected local saved body; they do not independently
authenticate that body as the claimed external publication.

Source-local observation names are prompted as contiguous source phrases. The
collector requires one unique exact `observation_clause_exact` anchor. For an
observation type with schema-declared `association_fields`, each field quote
must be unique inside that anchor and contain its own scalar value plus every
typed association-tuple fragment; numeric and measure guards reject extra or
ambiguous claims. Accepted spans become `field_quote_exact:<field>` evidence
items. Nearby context, repeated or multi-claim quotes, ungrounded descriptions
or attributes, and source-extracted semantic `RelationshipAssertion` records
remain `candidate_unverified`. Parallel phrases containing `respectively` fail
closed: literal list membership does not bind an ordered tuple, and typed
ordered-list or tuple assertions are not implemented. This is typed lexical
atomic grounding, not semantic entailment. Novel text-only measure notation and
comparisons spread across multiple caption sentences deliberately remain
candidate-only.

`FieldAssertion` records the `typed_exact_tuple_v2` contract and stable
grounding reason codes. These are immutable audit diagnostics, not complete
replay inputs: rejected occurrence payloads, the schema snapshot, and all quote
alternatives are not persisted as a first-class grounding decision.

This grounding shows only what the immediate source version literally says.
There is no typed primary-versus-secondary citation-role assertion, so a
secondary source does not become evidence that its statement came from a
primary study.
No current real run has validated the proposed path scorer, which is not yet
implemented, or the complete evidence refactor end to end. Historical path and
materialization artifacts are design evidence and diagnostics only.

The remaining gap is between steps 6 and 7.

On the in-scope NetworkX backend, `gasl_graphwalk_limits_v1` constrains
`GRAPHWALK` by relationship names and depth 1--8, a deterministic 100-source
slice, the first 50 deterministic incident edges per node, and a prospective
global cap of 10,000 unique declared-grain queued/emitted rows. The deduplicated
emitted subset cannot exceed the cap. Ordered truncation reasons mark evidence
partial, non-search-actionable, non-continuable, and unable to close coverage;
there is no truncation continuation. Narrowing or replanning is planner/operator
guidance, not automatic executor repair: a successful truncated walk may
clean-finalize operationally, but cannot close criteria. GRAPHWALK is still not
scoring whether a path is semantically useful for an unresolved criterion. This
is a liveness/cost residual, not evidence of coverage. Once a path survives
traversal, the record-preserving table machinery treats it as an operational
candidate that must be retained, repaired, collapsed, or explicitly marked as a
gap. Neo4j `id_filter` and source/target filtering remains an out-of-scope
backend residual.

The graph planner uses exact typed declared grains: FIND nodes are `node(id)`,
edges are `edge(src_id,tgt_id,relation_type)`, paths are `path(path_id)`, and
GRAPHWALK is `edge(src_id,tgt_id,relation_type,path_depth)`. Alias conflicts and
duplicate grains fail closed; booleans, integers, finite floats, and strings do
not coerce across types. Bare relationship controls `a`, `an`, `any`, `all`, and
`*` are wildcards. Colliding literal strings, numeric/boolean-looking strings,
values containing `,` or `|`, and strings beginning `relation_type=` or
`relationship_name=` must be JSON quoted in planner prompts.

That materialization boundary is now executable only through
`gasl_process_execution_v5` and `gasl_process_execution_policy_v5`. PROCESS
must declare `semantic_filter/zero_to_n`,
`eligible_materialization/zero_to_n`, or
`exact_enrichment/exactly_input`, with a structured `REQUIRED_FIELDS` list and
hard limits of 72 inputs and eight logical model calls: at most five primary
batches of 15 plus three repair-reserved calls.
`gasl_process_required_field_roles_v2` assigns each required entry exactly one
role: source-bound semantic assertion, declared-grain identity, registry
metadata, or authoritative binding container. Semantic fields require active
FieldAssertions; identity fields must be exact declared source grain keys.
Registry metadata and `field_evidence` must exist in the exact durable source
schema and use deterministic nonsemantic authority rather than fictitious
assertions. Thus FIND grain `id` cannot admit required identity
`observation_id`. Unknown, reserved, and operational assertion/criterion
containers fail closed. Zero
selected rows are a valid filter result, not a reason to restore the input.
Only exact enrichment is row-preserving. Any remainder is explicit under
`<output>__unresolved`; a later continuation is another fully contracted
PROCESS action, not hidden batching or nested iteration. Both PROCESS sidecar
suffixes are runtime-reserved. Unresolved state is exact
`process_unresolved_inputs` with `usable_by=["PROCESS"]`; unsupported state is
exact `unsupported_process_outputs` with `usable_by=["SHOW"]`.

Every model-visible source and response row carries
`gasl_process_operational_row_token_v1`, an opaque hash of the exact ordered,
typed declared-grain tuple. The runtime recomputes it; aliases, coercion,
ordinals, supplied-token mismatch, and duplicate grain tuples fail closed.
Duplicate grains are a noncontinuable upstream producer defect. Tokens are
operational parent attribution, not evidence or semantic membership.
`target_row_count` and all other PROCESS counts remain operational path/audit
cardinality; criteria support and unresolved state measure semantic progress.
`gasl_process_declared_grain_authority_v2` binds the accepted row back to that
exact type/key/value/token parent tuple without pretending it is a
FieldAssertion.

Every durable retained-command output projects exact
`gasl_deterministic_producer_contract_v1` payload, row-schema, grain,
multiplicity, `usable_by`, and evidence-state fields. Planner simulation and
runtime production must agree. All planning and execution boundaries require membership
for the current consumer. FIND-node outputs admit GRAPHWALK; edge/path and row
outputs do not. Same-type DECLARE preserves the prior contract. A defined empty
FIND or valid retained transform is successful and durable rather than an
execution defect. Empty SELECT, PROJECT, COLLAPSE, and GRAPHWALK carry declared
schemas. JOIN requires its key in both input schemas and emits the deterministic
joined union-plus-identity schema even when empty; empty MERGE may retain only
the deterministic union of available source schemas. These operational schemas
can block later routing but cannot create semantic support.

`gasl_process_execution_persistence_v9` makes active traversal and PROCESS
state durable under `gasl_traversal_execution_v1` and the read-only
`gasl_execution_recovery_ownership_v1` boundary. The pipeline checks ownership,
job, and exact task/spec query before any source or table seed write. Active,
pending-disposition, pre-plan, exhausted, and terminal owners resume without
reseeding. In-flight PROCESS state uses `gasl_process_attempt_snapshot_v4` to
capture exact prior input, target, unresolved, and unsupported state before the
pre-call started/pending target-plus-sidecars triple. Both sidecars carry the
exact incoming `row_schema`; the target carries the deterministic PROCESS target
schema extending it with required, grain, parent, row, completeness, gap, and
unsupported fields. Grain type/keys/multiplicity and action/family identity are
shared, while StateStore validates the distinct exact projections as one
complete triple.
`gasl_process_fail_stop_restoration_v3`
restores that exact bundle and separates a changed-family conflict from the
active interruption reason.
The authoritative `gasl_process_call_ledger_v4` is persisted inside the run at
`answers/gasl_artifacts/process_call_ledger`, with exact state/artifact/checkpoint,
run/job/query, persistence, source/target/command, occurrence, and attempt
bindings, authoritative/audit/nonsemantic flags, and no external fallback. Each logical PROCESS model call, including
retries and missing-row repair, has a per-call durable reservation and terminal
record there; symbol and plan provider calls instead consume a durable outer
traversal-iteration reservation. Trace and prompt-observation streams are
auxiliary audit sinks, and none of these execution records has semantic
authority. Terminal answers are conservatively redeliverable because
question-pipeline does not yet perform the explicit post-artifact
acknowledgement. Standalone GASL final synthesis is the sole documented
unreserved provider-call residual; its possible repetition is a diagnostic
cost/liveness outcome, not a semantic result. One plan-backed terminal answer
uses a shared nonempty `terminal_final_answer_at` written identically to the
completed plan and linked traversal in one StateStore save; recovery and
acknowledgement require equality. `gasl_plan_action_commit_v1` atomically stores
history, summaries, artifacts, materializations, PROCESS retirement, and cursor
under `gasl_plan_action_state_transaction_v1`. Plan and disposition ownership
uses `gasl_plan_execution_v1`, `gasl_plan_outer_disposition_v1`, and
`gasl_final_answer_disposition_v1`.
`gasl_plan_resume_preflight_v1` proves the exact committed prefix and resumes
semantic validation at the first uncommitted step. Read-only
`gasl_process_resume_admission_v1` admits staged nonactionable continuation
state only for its exact active v4 snapshot. Query adoption rejects every prior
PROCESS/plan/traversal owner, family-bound variable, and nonempty or malformed
canonical ledger; only pristine state accepts a first query.
Completed batch indices and digest keys must be the same contiguous prefix;
owned batch digests are recomputed, and canonical digests bind unsupported rows
and the terminal exact ordered unresolved-token suffix. Mismatch fails closed;
these hashes are not external authentication and remain operational audit only.

Every completed outer disposition atomically owns a separate
`gasl_process_outcome_reconciliation_v4` audit. A clean disposition retains an
empty `outer_failure_summary` and accepts only `needs_repair: false`, zero live
incidents, empty top/item live code and incident-ID lists, and no structural
defects. Repair and fail-stop failure summaries alone own live reasons under
exactly `needs_repair` or `repair_budget_exhausted`. Exact
count-aligned `(reason_code, gasl_outcome_incident_id_v1)` audit pairs must match
them. PROCESS owners are target/family-unique, item pair sets are globally
disjoint, and their union equals the PROCESS-tagged authoritative failure pairs.
Their identities additionally bind target, family, and final writer and cannot
collapse equal codes across targets. Each item records its
final status, resolved/live codes and IDs, structural and durable
row/sidecar/missing-binding diagnostics, exact action entries
(`result_index`, command, occurrence, attempt), predecessor plan, and the exact
prior/carried/retired/re-keyed incident partition.
The exact v4 transitions are `current_plan_family`, `carried_clean`,
`carried_unchanged`, `partially_retired`, `resolved`,
`final_writer_rekeyed`, `reevaluated`, `reevaluated_clean`,
`superseded_family`, and `structural_mismatch`. Supersession names its replacing
family and input actions. Successor creation atomically snapshots and consumes
one exact predecessor with forward/reverse links; recovery requires the same
job/query and byte-equivalent copied failure/audit state. A restored PROCESS
fail-stop has one classified item/pair. A non-PROCESS fail-stop has an empty
PROCESS reconciliation list only when no live committed PROCESS owner exists;
otherwise all owners remain and the separate non-PROCESS pair is top-level. The
audit is nonsemantic. Any non-v9 persisted execution fails the recovery fence,
apart from pristine unversioned empty state adopting its first query.

This v9/v4 path boundary is source-cleared only; it remains awaiting a fresh
real execution and is not runtime or semantic validation.

Continuation uses a query-bound `gasl_process_continuation_family_v4`, distinct
from per-attempt audit lineage, and a
`gasl_process_declared_grain_identity_v1` contract for exact grain type, keys,
and multiplicity. Family v4 binds the exact required-field role map, canonical
budget-free v5 semantic-family projection, and
`gasl_process_source_role_contract_v2` projection of producer
version, schema, grain, multiplicity, evidence state, and token version. It also
binds persistence, state/artifact path, job, query digest, target, and
semantic operation, so it is not a global family ID. Missing or ambiguous
identity or producer drift fails closed. Per-occurrence input and model-call
budgets are excluded from family identity. Prior semantic
field values and authoritative bindings are monotone and never overwritten. An
exact-identity collision can add an authoritatively bound missing field or union
an authoritative same-value binding. New identities append; conflicting values
never replace prior values. For a nonempty contract, replacement, new, and
collision records archive superseded partial diagnostics, re-evaluate existing exact
REQUIRED_FIELDS bindings, and recompute current gaps and completeness;
`REQUIRED_FIELDS []` is a no-op. Operational diagnostics may therefore change
without weakening prior semantic values or bindings. Current
unresolved state replaces the prior remainder; unsupported audit state
deduplicates and accumulates while reporting historical, current-action delta
(including a repeated current defect whose audit record deduplicates), and
persisted-total counts separately. Historical-only unsupported audit does not
trigger repair. The recorded carried/new/deduplicated and
augmented/conflicting/binding-union/identity-conflict counts diagnose continuity;
they do not establish criterion support or coverage. An unresolved sidecar may
be consumed only as direct same-target
`PROCESS <target>__unresolved ... AS <target>` with the same stable family and
semantic contract. Every other consumer or target fails closed, and unsupported
sidecars are SHOW-only audit state.

PROCESS execution identity must end at that action boundary. The shared
`without_process_execution_metadata()` sanitizer removes occurrence, attempt,
call-budget, and terminal fields from every non-PROCESS result and rebound
context contract; StateStore repeats the removal for non-PROCESS summaries,
materializations, and artifacts before commit. The first downstream `MERGE`
must commit exactly once with its cursor advanced exactly once, never as a
terminal PROCESS occurrence.

If that or any other action fails before cursor commit,
`gasl_active_plan_interruption_v2` persists per-signature counts across
interleaving and a separate active-action/plan total. The third occurrence of
one exact signature terminalizes with
`active_plan_identical_interruption_recovery_exhausted`; eight total
interruptions terminalize with
`active_plan_total_interruption_recovery_exhausted`. Both are non-actionable
defects. This bounds recurrence attributable to one signature and alternating
failure recovery, not global trace bytes. Seed/bootstrap output is not a
completed path-selection episode: a non-seed terminal criteria snapshot and
transition, corresponding reward artifact, and final-answer artifact are
required before interpreting semantic behavior.

That behavior is correct for operational-record preservation but too weak for
candidate selection. The expensive LLM table passes should receive high-recall
candidate sets, not every weak route through broad graph context. Candidate
counts and path scores remain diagnostics. `criteria_projection_v10` and
`criteria_transition_v7` retain exact source-local support for audit, while
scalar goodness comes only from `semantic_membership_v2` claims and bounded
semantic-claim/canonical-source pairs. A reported binding receives a
cross-version `semantic_claim_id` only from the registry's canonical document,
observation type, and exact anchor checksum; a graph path or replayed snapshot
cannot mint it. Only a live `EvidenceRegistry` object can confer support;
missing or mapping-shaped registries fail closed. Deserialized criteria
snapshots are marked `criteria_projection_v10:unvalidated_replay`, have their
serialized support cleared, and are audit-only. Reward v7 reports their outcome
as unknown with zero score and no transition until authoritative reprojection.

Aggregate-deficit state has a separate contract. Table-spec version 4 retains
the version-2 semantic table boundary and adds task-owned
`criterion_contract_id` and `required_criterion_families`. Version-1 loading
migrates legacy operational keys/non-nullable transport columns to nullable diagnostics
and records that compatibility change; it does not infer a semantic key.
`semantic_membership_v2` permits Chao1 estimation under
`supported_semantic_signature_chao1_v1` only for a validated
`semantic_signature` and common-observation member binding.
`source_observation` may enter semantic reward through a registry-owned
`semantic_claim_id`, but it remains unestimated because cross-source overlap is
undefined. Unconfigured membership remains unprojected, unestimated, and
zero-reward; neither mode is a raw source-by-subject substitute. Persisted
completion state version 2 is
replayable only when its `criteria_completion_state_v2` contract exactly matches
the active table spec, criteria projection, membership contract, and estimator
contract; a mismatch creates a blocking migration issue, and no automatic
semantic completion-state migration is implemented.

Required families are explicit question contracts, never one-per-table
automation. Each fixes exact accepted observation types, required fields,
optional exact author-owned `required_field_values`, `family_id`,
`rule_version`, and any required runtime capability. The predicates are part of
the versioned task contract and cannot be inferred from a table name,
description, model routing, alias, or entity resolver. Projection
supports a family only when one source-local observation supplies all required
fields on one current registry semantic claim. That witness proves existence,
not task-universe coverage. Empty families remain visible as task-level
unresolved criteria; unavailable runtime capabilities become structural,
non-search-actionable deficits. These family gates emit no source/evidence
support units and are excluded from rarefaction and scalar reward, so the
underlying atomic field criteria remain the only source-grounded reward units.
For a constrained family, absent supported predicate fields yield
`required_family_field_values_unresolved`; supported values that do not equal
the normalized author literals yield `required_family_field_values_mismatched`.

## Observed Outcome

| outcome | what it means | interpretation |
| --- | --- | --- |
| Source-seeded graph walks now produce operational records from newly ingested sources | Continuation rounds can reach new evidence instead of only revisiting the old graph | In scope for source seeding; this is an execution outcome, not semantic reward |
| Long record-preserving table passes complete without losing omitted candidates | Candidate records can survive LLM batching, retry, collapse, and materialization | In scope for transport identity; record survival does not imply criterion support |
| Many materialized records are context-only or carry no source-supported field value | Traversal admits generic context nodes and source-neighborhood records that cannot support a declared criterion | Out of scope for record preservation; this is a path-selection defect |
| Some records report conflicting anchors, such as one place in the edge source and another in the neighbor label | Depth-limited walks can cross through shared source, location, method, or context hubs and produce conflicting candidate values | In scope for path scoring; the route should be penalized before `PROCESS`, and the affected criterion must remain unresolved |
| The LLM emits `evidence_gap` for many weak candidates | The finalizer can expose missing evidence after the fact | Out of scope for finalization; using the LLM as the first path filter burns calls, and an open gap remains an unresolved criterion |

## Failure Mode

The current graph scope is source-aware, but the path expansion is not
anchor-aware.

For example, a valid source-neighborhood graph can contain all of these
structures:

- direct measurement nodes
- context nodes
- method nodes
- source/document nodes
- chunk nodes
- broad geographic or categorical nodes

A depth-3 or depth-4 walk can move from a useful newly sourced measurement into
a broad connector, then into a different estimate that only shares a paper,
method, or coarse context. Bidirectional traversal increases recall, but it
also makes these bridge routes easier to traverse.

The resulting candidate record is not malformed as transport:

- it has a real neighbor node
- it has a real edge
- it has real `source_refs` / `source_chunks`
- it has a deterministic `src_id`, `tgt_id`, `edge_src_id`, and `edge_tgt_id`

Those properties establish a real traversal candidate, not evidence. The issue
is that the record is weak context for the target criterion. The
engine currently discovers that only after an LLM has normalized the record and
written an `evidence_gap` or anchor-conflict explanation. A present but
unsourced value alone must remain unresolved; an unsourced alternate does not
veto an independently source-supported value. Conflicting sourced values remain
unresolved. Support requires an exact, active
`FieldAssertion -> SourceLocalObservation -> EvidenceItem -> SourceVersion ->
SourceDocument` chain on the same source-local observation.

## What Fixing Path Selection Would Do

Fixing this local symptom should add a generic path-quality gate between graph
traversal and record-preserving extraction.

It would not delete partial records that express real missing evidence. A
partial record may support each independently sourced field while its other
criteria remain unresolved. The gate would filter or demote paths whose graph
route is too weak to provide evidence for the target criterion in the first
place.

Expected effects:

- fewer low-value operational records entering expensive `PROCESS` batches
- higher new-source to newly supported criterion yield
- fewer materialized records whose only useful content is `evidence_gap`
- fewer criteria made conflicting by paths that crossed a hub
- better deficit search memory, because failures would distinguish:
  - no source found
  - source accepted but no graph delta
  - graph delta found but no high-quality path
  - high-quality path found but no source-supported target criterion
- better stop criteria, because remaining gaps would more often reflect missing
  literature instead of traversal noise
- more useful best-guess candidate diagnostics, because candidates would come from
  stronger record contexts before entering the normal criteria projection

The fix would not make a task complete by itself. It only improves one local
decision: which graph records are worth sending to operational table formation.
Search still has to find the right sources, and the final table LLM still has to
normalize source-local wording into fields without inventing values. Completion
is decided later from supported and unresolved criteria, never from how many
records survived the gate.

That means path selection should be treated as one policy surface inside a
larger learning loop, not as a hand-built endpoint.

## Generic Scoring Shape

Path scoring should stay schema-agnostic. It should derive target criteria and
anchors from the current criteria snapshot, table contracts, and candidate
records rather than from query-specific literals.

Useful generic features:

| feature | signal |
| --- | --- |
| `source_overlap` | Prefer edges and terminal nodes evidenced by the current accepted source or the same source chunk |
| `path_depth` | Penalize longer paths unless every hop preserves an anchor |
| `relation_sequence` | Prefer relation types that the goal state has found productive for the target table |
| `terminal_type` | Prefer endpoint entity types associated with prior source-supported criteria of the requested kind |
| `anchor_consistency` | Penalize paths that start from one criterion subject but end on an incompatible subject |
| `hub_degree` | Penalize high-degree nodes that connect many unrelated candidate records |
| `generic_context_count` | Penalize routes that spend most hops on method/source/context nodes rather than direct evidence nodes |
| `criterion_support_potential` | Prefer records with fields and provenance likely to support currently unresolved criteria |
| `prior_operator_yield` | Prefer path shapes produced by actions that previously supported or resolved criteria |

The output should be stored with every candidate:

```json
{
  "path_score": 0.87,
  "path_score_features": {
    "source_overlap": 1.0,
    "path_depth": 1,
    "anchor_consistency": 1.0,
    "hub_penalty": 0.0
  },
  "path_selection_reason": "direct current-source edge with matching anchor"
}
```

Records that are kept only for recall should carry the reason too:

```json
{
  "path_score": 0.32,
  "path_selection_reason": "weak route through high-degree context node"
}
```

That gives later `PROCESS`, `COLLAPSE`, and search-memory stages a diagnostic
feature instead of forcing them to infer path quality from free-text gaps. A
path score is not evidence support and cannot close a criterion.

## Longer Project: Learn the Table-Fill Policy

The round-level problem is a sequential decision problem over expensive,
partially observed actions. Hand-written operators are useful as action
primitives, but the system should learn which primitive to use from prior
traces.

One episode is a table-fill continuation round. Its trace exposes much of the
state and outcome structure needed for offline learning, while uniform
action-level cost accounting and several policy joins remain incomplete:

1. the current criteria snapshot and unresolved criterion or aggregate targets
2. separately assessed universe estimates and completion-scope state
3. pending search frontier
4. generated search tasks with decision, action, snapshot, and target-basis IDs
5. Firecrawl hits, duplicates, scrape failures, and accepted sources
6. graph node/edge deltas from ingestion
7. GASL planner actions
8. graph-walk candidate records and record-preserving `PROCESS` outputs as
   operational diagnostics
9. best-guess action and candidate diagnostics; typed derived analyses and
   derived assertions are not implemented and therefore do not support criteria
10. the source-local criteria transition for audit and the reward-v7 semantic
    transition for goodness, including supported, resolved, regressed, removed,
    revised, and conflicting semantic claims or addresses
11. bounded semantic-claim/canonical-source pairs backed by exact registry
    support
12. partial token, Firecrawl, and wall-clock diagnostics; uniform action-level
    cost remains future work

### Action Space

| policy surface | actions to learn |
| --- | --- |
| Deficit selection | which unresolved criterion family, aggregate target, or anchor to attack next |
| Search operation | catalog search, target-deficit search, context-grain expansion, temporal-window expansion, source-family shift, terminology shift |
| Query construction | which known anchors, failed terms, productive source terms, and context tags to include |
| Source acceptance | whether a search hit is worth scraping, reducing, and ingesting |
| Graph scope | full graph, current-source graph, source hops, source seed count |
| Path selection | which path shapes are likely to provide evidence for unresolved criteria |
| Record formation | which operational table view to materialize and which normalization strategy to use |
| Retry and repair | retry unchanged, narrow the instruction, split the batch, or preserve an explicit unresolved-evidence record |
| Stop/continue | spend another round or declare the remaining gaps unsupported under the current budget |

### Reward Signals

The reward should not be "did the final prose answer look good". It must also
not be based on operational record, search-hit, accepted-source, graph-delta, or
best-guess-candidate counts. The positive semantic units are membership-projected
supported claims and bounded semantic-claim/canonical-source pairs backed by
exact registered support; unresolved addresses and regressions
provide the corresponding negative state:

| signal | sign |
| --- | --- |
| newly supported required semantic claims | positive |
| resolved required semantic claims | positive |
| newly supported or resolved optional semantic claims | positive, lower weight |
| new semantic-claim/canonical-source support, bounded by claim depth | positive |
| semantic claims or addresses that regress, disappear, are revised, or become conflicting | negative |
| repeated support beyond the useful depth target | negative |
| LLM tokens, Firecrawl calls, scrape bytes, and wall time | negative cost |

Search hits, duplicate URLs, accepted sources, graph deltas, path scores, and
operational record counts remain action observations and cost features. They may
explain why a strategy failed, but they cannot substitute for a criteria
transition and its membership-projected semantic transition. `execution_status`
likewise reports whether the run finished, halted on a budget, or ended in an
execution error; it is separate from `goal_status`, which remains incomplete
while required criteria are unresolved. A terminal GASL defect is projected by
`table_fill_gasl_runtime_status_v1` only after persistence/ledger, current
job/query, durable answer, terminal traversal, disposition mode, plan cursor,
iteration, and owner-local failure reason agree, with no active PROCESS owner or
competing outstanding plan. Clean completion requires its
single linked `llm_analysis` clean-finalize plan. A plan defect requires its
single linked repair-exhausted plan; a plan-less pre-plan defect requires the
exact terminal traversal's own failure summary, never a global fallback. The
orchestration-owned `halted_execution_error` stop bypasses custom policy logic,
outranks budget labels, and leaves the criteria transition and reward unchanged.
Skipped GASL rounds record runtime status `not_run`; the final-round status is
separate from a labeled last-observed GASL status and round. This reward
contract also fails malformed GASL containers into the typed error stop while
using an empty operational export input. An empty required frontier is a
terminal orchestration guard, so a custom policy cannot end the loop with a
recorded `continue`. A bootstrap universe gap exits only on a terminal decision;
an actionable frontier and paper budget carry a nonterminal decision into the
normal round/search path. A custom nonterminal decision at the hard outer-round
cap is overridden to `round_budget_exhausted`. Finalization also canonicalizes
an impossible zero-round nonterminal return, rejects other premature
nonterminal returns, and reasserts that a fixed-length completed loop cannot
serialize `running`; a bound execution error still has priority. These
boundaries let the system learn search and traversal policies without waiting
for a human to inspect a natural-language summary.

### Preference Optimization

The first learning layer can be offline preference optimization over traces:

1. convert each round into a compact trajectory record
2. compute deterministic metrics from the criteria transition, bounded
   semantic-claim/canonical-source pairs, path diagnostics, and cost
3. use a judge only for ambiguous trajectory pairs
4. train a policy or reranker to prefer the better next action from the same
   state
5. replay held-out traces to check whether the learned action would have picked
   a historically better branch

Good comparison units:

- two search tasks for the same deficit
- two source hits for the same query
- two graph scopes for the same source set
- two path candidates for the same unresolved criterion
- two table-normalization instructions for the same collapsed group
- stop vs continue for the same frontier and coverage state

### Why Path Scoring Still Matters

A deterministic path scorer is still useful, but mainly as instrumentation and
as a cheap baseline policy.

It gives the trajectory learner explicit features:

- which graph routes were weak
- why they were weak
- whether weak routes were still eventually useful
- which relation sequences produced supported or resolved criteria
- which source families produced independent criterion evidence

The long-term system can then learn the weights, override a bad deterministic
cutoff, or route low-confidence paths to exploration batches.

### Project Stages

1. Instrument every decision
2. Add deterministic path and source outcome scoring
3. Build trajectory records from real continuation rounds
4. Add pairwise trace comparison and deterministic preference labels
5. Train offline rerankers for search tasks, source hits, and path candidates
6. Run off-policy evaluation against historical traces
7. Add a cautious online bandit for low-risk choices
8. Let learned policies propose search and traversal actions under a budget
9. Keep human review for stop-rule failures and metric regressions

This should be budget-aware from the start. A policy that materializes ten more
operational records without supporting a criterion after another thousand
low-value searches is worse than a policy that learns it is looking in an
exhausted branch.

## Local Implementation Plan

### 1. Add path feature extraction

Build a small feature extractor over `walk_rows`.

Inputs:

- candidate-record fields from `GRAPHWALK`
- edge provenance fields
- graph degree metadata
- current source IDs
- target table contract and unresolved criterion IDs, if present

Outputs:

- `path_score_features`
- `path_score`
- `path_selection_reason`
- optional `path_exclusion_reason`

The first version can be deterministic. The features should be explicit enough
that later LLM or learned policies can tune weights without changing the
operational record schema or the criteria projection contract.

### 2. Add a score/filter command or PROCESS prefilter

There are two reasonable surfaces:

- a dedicated deterministic command, such as `SCORE_PATHS`
- an internal prefilter in `GRAPHWALK` when a contract says downstream records
  are table candidates

The dedicated command is easier to inspect and benchmark:

```gasl
SCORE_PATHS seeded_measure_paths FOR target_table AS scored_measure_paths
```

Then the planner can do:

```gasl
PROJECT scored_measure_paths GRAIN path FIELDS ... PRESERVE_MULTIPLICITY AS candidates
```

This scorer and command are proposed work, not implemented behavior. PROCESS
currently strips model-emitted provenance and preserves only pre-registered
bindings with exact field, typed value, and observation/subject anchor. It does
not mint evidence, promote graph `source_refs`, accept an unregistered rename
or normalization, or close coverage. Unsupported fields receive an operational
`evidence_gap` and remain field-locally unresolved. Validated bindings are
serialized under `assertion_bindings` for `criteria_projection_v10`. During
table accumulation, semantic values and authoritative bindings are monotone, but
operational gaps and completeness are contract-relative. A nonempty
required-field contract archives superseded partial diagnostics and recomputes
the current view from exact bindings. A `completeness: complete` marker has no
semantic authority by itself; typed derived resolution remains unimplemented for
transformations without an existing authoritative binding.

The downstream table contract is `declared_table_export_v2` followed by
`criteria_input_materialization_v2`. Export accepts exact declared deliverable
names rather than suffix heuristics, keeps partial records, and rehydrates only
registry-current exact observation/field/value bindings. Semantic stopping is
snapshot-bound and separate from an execution halt.
`criteria_guarded_final_synthesis_v4` excludes raw GASL prose from the
user-facing table answer and reports only supported criteria plus unresolved,
conflict, and structural-family status. It explicitly labels an operational
execution error and carries its typed reason without changing those criteria;
`table_fill_replay_v4` records that boundary. A fresh real continuation is still
required to validate the whole path end to end.

### 3. Thread scores into table-fill memory

Every accepted source should produce one of these outcomes per target family:

- no graph evidence
- graph evidence but all paths were low-score
- high-score paths but no candidate evidence for the target criterion
- candidate evidence but no newly supported or resolved criterion
- newly supported or resolved semantic claims, with attributable
  semantic-claim/canonical-source pairs

That outcome is more useful than a generic "no criteria delta" because it tells the
next search round whether to change search terms, graph schema, traversal, or
normalization. The transition must be joined by stable criterion, snapshot,
decision, action, task, and source IDs rather than inferred from record counts.

### 4. Route future searches from scored deficits

The deficit phase should generate different operations from the scored outcome:

| outcome | next action |
| --- | --- |
| no graph evidence | search broader source families |
| all paths low-score | search for sources with more direct terminology for the same unresolved criterion |
| no candidate criterion evidence | search narrower subject anchors or alternate criterion terms |
| candidate evidence but no supported criterion | keep the source context and repair provenance or normalization without inventing support |

### 5. Validate on real add-on rounds

The acceptance test should be a full real table-fill continuation, not a
synthetic unit test.

Track:

- accepted sources
- new graph nodes/edges
- candidate operational records before and after scoring
- candidates per source
- LLM batches per declared table
- source-local supported/resolved criterion IDs per accepted source as audit
  attribution
- reward-v7 supported/resolved semantic claim IDs and bounded
  semantic-claim/canonical-source pairs per accepted source
- best-guess actions and candidates as operational diagnostics; no derived
  semantic credit until a future typed derived-analysis assertion passes the
  ordinary criteria transition
- weak-path record fraction
- conflicting or regressed criteria

## Non-Goals

- Do not special-case a scientific field or metric name.
- Do not make operational records more "complete" by guessing values.
- Do not drop a registered-assertion-supported partial record just because some
  fields are null. Support only its independently registered fields and leave
  the others unresolved.
- Do not replace deficit search. Better path scoring only improves graph-local
  selection after new sources have been ingested.
- Do not treat best-guess sidecars as evidence. Typed derived analyses,
  provisional-subject rekey, decision-bound supersession/retraction, and full
  legacy evidence migration remain unimplemented.
