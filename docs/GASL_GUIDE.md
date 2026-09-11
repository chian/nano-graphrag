# GASL Guide

This guide describes the restart-safe GASL planner surface used by the current
executor. Parser compatibility for older commands does not make those commands
planner-visible or restart-safe.

## Execution boundary

Cross-step inputs are authoritative only when they exist in `StateStore`.
`ContextStore` is action-local and is not a durable planner symbol. A retained
producer must bind its reusable output with `AS`; the executor atomically stores
that output and its contract with action history and the completed-step cursor.

The accepted restart-safe command set is:

- `DECLARE`
- `FIND`
- `PROCESS`
- `PROJECT`
- `COLLAPSE`
- `GRAPHWALK`
- `JOIN`
- `MERGE`
- `SELECT`
- `SHOW`
- `INSPECT`

`AGGREGATE`, `COMPARE`, `RANK`, `UPDATE`, `COUNT`, `ON`, `ITERATE`, `SET`,
`ADD_FIELD`, graph mutation commands, and context-only graph commands are outside this surface.
They must not be emitted by the two-phase planner.

## Plan format

The planner returns JSON whose `commands` are GASL strings:

```json
{
  "plan_id": "example-plan",
  "why": "Retrieve and inspect grounded observations",
  "commands": [
    "FIND nodes with entity_type=OBSERVATION AS observations",
    "SHOW observations limit 10"
  ],
  "config": {
    "stop_on_error": true,
    "continue_on_empty": false
  }
}
```

The symbol phase may name only an existing durable input or a result produced
by one of the retained named-output commands. A model-declared input does not
prove that the value exists; validation checks the current `StateStore`.
Each reserved outer iteration makes a fresh versioned symbol decision using the
current failure context. An accepted plan atomically persists its exact symbol
table and digest in that plan occurrence. Hard-restart recovery reuses that
decision, while a successor repair iteration may replace it rather than mutate
its predecessor's table.

## Command reference

```text
DECLARE <var> AS DICT|LIST|COUNTER [WITH_DESCRIPTION "description"]
FIND nodes|edges|paths with <criteria> AS <var>
PROJECT <var> GRAIN node|edge|path|paper|chunk FIELDS <fields> [KEYS <fields>] [WEIGHT <field>] [PRESERVE_MULTIPLICITY] AS <result_var>
COLLAPSE <var> BY <field> [COUNT AS <weight_field>] AS <result_var>
GRAPHWALK from <var> follow <relationship> [depth <n>] AS <result_var>
JOIN <var1> with <var2> on <field> AS <result_var>
MERGE <var1>,<var2>,... AS <result_var>
SELECT <var> FIELDS <field1>,<field2>,... AS <result_var>
SHOW <var> [limit <n>]
INSPECT <var>
```

`FIND`, `PROJECT`, `COLLAPSE`, and `GRAPHWALK` unconditionally require explicit
named outputs in planner-visible retained plans. Retained handlers read the durable
value before any action-local compatibility value.

`DECLARE` is idempotent for an existing variable of the same durable type and
preserves its value and complete producer contract. A conflicting requested
type is a typed error. Every retained producer uses
`gasl_deterministic_producer_contract_v1`, whose exact projection is
`producer_contract_version`, `payload_kind`, `row_schema`, `grain_type`,
`grain_keys`, `multiplicity_preserved`, `usable_by`, and `evidence_state`.
Planner simulation and the runtime handler must produce that same projection.
Planner, compiler, executor, runtime, and StateStore admission require the
consuming command to appear in the producer-owned `usable_by` list; they do not
infer compatibility from a variable name or apparent row shape. FIND-node
outputs admit GRAPHWALK, while FIND-edge/path and retained row outputs do not.

`FIND` declares exact grains `node(id)`,
`edge(src_id,tgt_id,relation_type)`, and `path(path_id)`; GRAPHWALK declares
`edge(src_id,tgt_id,relation_type,path_depth)`. Identity comparisons preserve
the exact scalar type: booleans, integers, finite floats, and strings are not
interchangeable. Alias conflicts and duplicate declared grains fail closed.
In relationship position, bare `a`, `an`, `any`, `all`, and `*` are wildcard
controls. Literal strings that collide with those controls, contain `,` or `|`,
look numeric or boolean, or begin `relation_type=` or `relationship_name=` must
be JSON quoted; preserve string case and punctuation exactly.

`FIND` and `GRAPHWALK` use declared deterministic criteria and depth in this
surface. Command-local LLM refinement is disabled because an unreserved model
decision cannot change restartable retrieval rows. On the in-scope NetworkX
backend, `gasl_graphwalk_limits_v1` enforces depth 1--8, a deterministic
100-source slice, the first 50 deterministic incident edges per node, and a
prospective global cap of 10,000 unique declared-grain rows across queued and
emitted accounting; the deduplicated emitted subset cannot exceed that cap.
Truncation records ordered typed reasons from `source_cap_reached`,
`edge_cap_reached`, and `output_row_cap_reached`, and sets
`evidence_state=partial`, `search_actionable=false`,
`continuation_actionable=false`, `graphwalk_continuation_supported=false`, and
`may_close_coverage=false`. There is no truncation continuation. Narrowing or
replanning is guidance, not automatic executor repair: a successful truncated
walk may clean-finalize operationally, but it cannot close criteria. Neo4j
`id_filter` and source/target filter behavior is a separate out-of-scope backend
residual.

A defined empty FIND result or retained PROJECT, COLLAPSE, GRAPHWALK, JOIN,
MERGE, or SELECT result is durable `success` with `count=0` and `[]`; missing or
invalid inputs remain typed errors. Empty SELECT, PROJECT, COLLAPSE, and
GRAPHWALK outputs carry their declared field schemas and replace stale input
structural metadata.
JOIN requires its join key in both declared input schemas and projects the
deterministic joined union-plus-identity schema even when its result is empty.
An empty MERGE may retain only the deterministic union of available source
schemas because no output row adds further structure. These operational schemas
can limit later planning but cannot create semantic support.

## PROCESS v5

Every `PROCESS` action uses the full structured contract:

```text
PROCESS <input_var> CONTRACT gasl_process_execution_v5 MODE <mode> CARDINALITY <cardinality> MAX_INPUT_ITEMS <n> MAX_MODEL_CALLS <n> REQUIRED_FIELDS [field1,field2] WITH <instruction> AS <target_var>
```

Its exact serialized map is `version`, `operational_row_token_version`, `mode`,
`output_cardinality`, `max_input_items`, `max_model_calls`, `required_fields`,
`required_field_role_version`, and `required_field_roles`.

Modes and cardinality are explicit:

| Mode | Cardinality | Meaning |
| --- | --- | --- |
| `semantic_filter` | `zero_to_n` | Select zero or more exact input identities. |
| `eligible_materialization` | `zero_to_n` | Emit zero or one row per exact source token, with every required field. One-to-many needs an upstream producer with its own child grain. |
| `exact_enrichment` | `exactly_input` | Preserve one slot per input; this is the only mode that may repair missing rows or retain typed partial fallbacks. |

`required_fields` is a structured list, not a phrase interpreted from the
instruction. `gasl_process_required_field_roles_v2` classifies each entry as a
`semantic_field_assertion`, `declared_grain_identity`, `registry_metadata`, or
`authoritative_binding_container`. A semantic field requires an exact active
FieldAssertion for its field, value, and anchor. Grain identity must be an
exact declared source grain key. Registry metadata and the `field_evidence`
binding container must appear in the exact durable source `row_schema`; those
two roles use deterministic nonsemantic authority and never require or mint a
fictitious FieldAssertion. For example, `observation_id` is invalid for a FIND
node source whose declared grain is `id`. Reserved, assertion, criterion,
unknown, and other operational containers fail closed. Model text cannot create
provenance, a new assertion, or a supported field.
`semantic_filter` requires `REQUIRED_FIELDS []`; materialization and enrichment
require at least one structured required field.

Execution v5 also carries `gasl_process_operational_row_token_v1`. Each opaque
token is a SHA-256 over the exact ordered, typed declared-grain tuple, so string
`"1"`, integer `1`, and float `1.0` are distinct. The runtime recomputes every
token and rejects a supplied mismatch. Actual duplicate grain tuples are a
noncontinuable upstream producer defect: repair, rekey, or collapse that source
before starting a new family. Tokens prove operational parent attribution only;
they are neither semantic identity nor evidence.
`gasl_process_declared_grain_authority_v2` then records the exact grain type,
keys, restored parent values, token, and authoritative parent-token list on an
accepted row. It is deterministic operational authority for the identity role,
not a FieldAssertion or semantic-support record.

Example:

```text
FIND nodes with entity_type=PERSON AS people
PROCESS people CONTRACT gasl_process_execution_v5 MODE exact_enrichment CARDINALITY exactly_input MAX_INPUT_ITEMS 72 MAX_MODEL_CALLS 8 REQUIRED_FIELDS [first_name] WITH materialize the exact registered first_name binding AS enriched_people
SHOW enriched_people limit 10
```

The input cap and model-call cap are execution policy, not a semantic coverage
claim. Policy v5 permits at most five primary batches of up to 15 rows plus
three repair-reserved logical calls. Complete current exact
bindings are prioritized first, followed by
current partial bindings, source-local observations or current registry
candidates, and then legacy or unbound candidates in stable order.
`target_row_count` and every PROCESS count are operational audit cardinality;
supported and unresolved criteria remain the semantic completion measure.

Inputs beyond the current budget are written to
`<target_var>__unresolved`. Invalid or unmatched model outputs are written to
`<target_var>__unsupported`. Both sidecars are operational, non-reward, and
have no evidence authority. Their suffixes are runtime-reserved and cannot be
declared or used as explicit outputs. The unresolved sidecar has payload kind
`process_unresolved_inputs` and exact `usable_by=["PROCESS"]`; the unsupported
sidecar has payload kind `unsupported_process_outputs` and exact
`usable_by=["SHOW"]`. PROCESS continuation is another direct v5 action:

```text
PROCESS enriched_people__unresolved CONTRACT gasl_process_execution_v5 MODE exact_enrichment CARDINALITY exactly_input MAX_INPUT_ITEMS 72 MAX_MODEL_CALLS 8 REQUIRED_FIELDS [first_name] WITH continue the same exact registered enrichment AS enriched_people
```

Accumulation is enabled only by that exact same-target form: the source must be
`<target_var>__unresolved` and the output must be `<target_var>`. A different
consumer or target fails closed rather than starting replacement materialization.
The continuation must also match the persisted stable family, mode,
cardinality, required fields and their roles, and declared-grain identity. An
unsupported sidecar is SHOW-only audit state.

An operational remainder is `continuation_actionable=true` and
`search_actionable=false`; it does not request new evidence search. Explicit
valid empty `semantic_filter` output is successful. A malformed payload, wrong
top-level key, unmatched identity, missing required enrichment, or exhausted
call budget is a typed integrity or continuation outcome, never silent success.

## Identity and provenance

An existing row may retain an exact input identity. A novel composite row must
name validated exact `parent_item_ids`. Truncated IDs, normalized IDs, ordinal
fallbacks, or unmatched IDs never inherit provenance.

For existing fields, exact enrichment preserves semantic values and authoritative
input `field_evidence`, assertion bindings, and source metadata without
overwrite. Model-emitted provenance is ignored. A changed field without an exact
registered binding is excluded from semantic output and recorded as unsupported.
For a nonempty REQUIRED_FIELDS contract, replacement, new-identity, and
same-identity collision records archive superseded partial diagnostics and
recompute current gaps and completeness from exact authoritative bindings. An
empty REQUIRED_FIELDS list is a no-op. Thus semantic values and bindings are
monotone, while top-level operational gap/completeness markers may change.

The authoritative `gasl_process_call_ledger_v4` is stored inside the run at
`answers/gasl_artifacts/process_call_ledger`, with no repository-global or
external fallback. Its exact ownership record binds version, persistence,
job, state and artifact paths, checkpoint directory and relative path, query and
query digest, and authoritative/audit/nonsemantic flags. Each logical PROCESS
call records source/target, command occurrence, batch, stage, attempt, contract
and policy snapshot, budget, exact input identities and content digest, full
prompt and digest, raw response, parse or operational validation result, and
terminal reason. The durable reservation is written before provider dispatch.
Interrupted reservations remain charged and terminalize as indeterminate on
recovery; this is not an exactly-once provider guarantee.

Completed batch indices and digest keys must be the same exact contiguous
prefix. Every lower-case SHA-256 is recomputed from the owned batch file, and
canonical digests bind unsupported rows and the terminal unresolved list. A
partial remainder must be the exact ordered suffix of unprocessed operational
tokens under the same execution and continuation contracts. Ownership or digest
mismatch fails closed; there is no claim of cryptographic authenticity against
an actor able to rewrite artifacts and hashes. Ledger records are operational,
`audit_only`, `semantic_evidence: false`, and never semantic support.

## Restart persistence v9

The executor uses `gasl_process_execution_persistence_v9` and persists a
validated executable plan, current action, compiled arguments, action cursor,
outer traversal budget, and disposition. PROCESS also
persists a `gasl_process_attempt_snapshot_v4` occurrence-keyed exact input and
the prior target, unresolved, and unsupported existence, rows, contracts, and
digest before staging one exact target-plus-two-sidecar triple. In the pre-call
started/pending triple, both sidecars carry the exact incoming `row_schema`;
the target carries the deterministic PROCESS target schema, which extends the
incoming schema with required, grain, parent, row, completeness, gap, and
unsupported fields. All three share grain type/keys/multiplicity and
action/family identity. StateStore rejects sidecar-only replacement and
validates the distinct target and sidecar projections together with the same
occurrence, command, attempt, status, execution, policy, family, and identity.
Same-target actions share a query-bound
`gasl_process_continuation_family_v4` and exact
`gasl_process_declared_grain_identity_v1`; attempt audit lineage remains
separate. The family-v4 map binds persistence, state/artifact path, job, query
digest, target, semantic operation, declared-grain identity, the canonical
budget-free v5 semantic-family projection, and the exact
`gasl_process_source_role_contract_v2`. The semantic-family projection binds
version, token and uniqueness policy, mode, cardinality, required fields and
roles, and output shape; per-occurrence input and model-call budgets are not
family identity. The source-role map binds
the deterministic-producer version, row schema, grain, multiplicity, evidence
state, and operational-token version. Its canonical family hash prevents a
continuation from silently changing field roles, producer authority, or output
shape.
`gasl_process_fail_stop_restoration_v3` restores that exact atomic
bundle. If an attempted family differs from an existing target family, the old
target and both sidecars are restored, the attempted input remains audit-only,
and the family conflict is a separate non-PROCESS incident.

`gasl_plan_action_commit_v1` commits history, result summaries, produced
artifacts, durable materializations, PROCESS retirement, and cursor movement in
one `gasl_plan_action_state_transaction_v1`. Persisted plans and their outer
and terminal dispositions use `gasl_plan_execution_v1`,
`gasl_plan_outer_disposition_v1`, and `gasl_final_answer_disposition_v1`.
`gasl_plan_resume_preflight_v1` then verifies the exact plan,
digest, validation, symbol table, traversal, predecessor, ordered action
records, and committed compiled prefix, returning the first uncommitted step;
semantic input preflight runs only on that suffix. The read-only
`gasl_process_resume_admission_v1` admits a cleared/nonactionable continuation
sidecar only when an exact active v4 snapshot owns the started or staged
PROCESS. It never makes that sidecar generally actionable. A hard restart
therefore resumes the same plan/action instead of asking the planner again.
Action-local context is rolled back with a failed transaction and is never the
source of a resumed cross-step input.

An empty global query may adopt work only from pristine state: no active or
completed PROCESS, plan, or traversal record, no family-bound variable, and an
absent or exactly empty canonical ledger. Configure, recovery, and `set_query`
share this guard. A nonempty or malformed canonical ledger, or any prior owner,
fails closed rather than being rebound to a new query. Any non-v9 persisted
execution is nonresumable; only genuinely empty unversioned state may adopt its
first v9 query.

A completed plan keeps a durable `clean_finalize`, `needs_repair`, or
`repair_budget_exhausted` disposition. Terminal answers remain recovery-owned until the caller explicitly
acknowledges them, so a wrapper restart redelivers the result rather than
reseeding query variables. Current/max traversal iterations are durable; restart
does not grant a new provider budget. A plan-backed terminal answer is owned by
one shared nonempty `terminal_final_answer_at` value written identically to the
completed plan and linked traversal in the same StateStore save. Recovery and
acknowledgement reject a missing or unequal pair.

Each completed outer disposition atomically owns a separate
`gasl_process_outcome_reconciliation_v4` audit. A clean disposition keeps
`outer_failure_summary` exactly `{}` and requires the audit to report
`needs_repair: false`, zero live incidents, empty top/item live code and incident
ID lists, and no structural defects. Repair and fail-stop dispositions keep
their live reasons in `outer_failure_summary`; their disposition is exactly
`needs_repair` or `repair_budget_exhausted`. Each reason stores a
`gasl_outcome_incident_id_v1`; the count-aligned top audit pairs must exactly
match the authoritative `(reason_code, incident_id)` set. A PROCESS item ID
binds its code, target, continuation family, and final command, occurrence, and
attempt writer. PROCESS owners are unique by `(target, family)`, item pair sets
are globally disjoint, and their union equals the PROCESS-tagged top failure
pairs. A non-PROCESS ID binds the canonical reason payload and ordinal and
remains only at the top. Each PROCESS item
also records final writer/status, resolved/live codes and IDs, structural and
durable row/sidecar/missing-binding diagnostics, and exact reconciled actions.
Each action entry contains only `result_index`, `process_command_id`,
`process_command_occurrence_id`, and `process_attempt_id`. The item also
records its predecessor plan, prior, carried, retired, and re-keyed incident IDs
plus a transition classification. The v4 validator proves an
exact prior partition: `carried_unchanged` carries all prior IDs;
`partially_retired` carries a nonempty strict subset and retires the remainder;
the remaining exact classifications are `current_plan_family`, `carried_clean`,
`resolved`, `final_writer_rekeyed`, `reevaluated`, `reevaluated_clean`,
`superseded_family`, and `structural_mismatch`. Supersession names the new family
and its exact input actions. Successor creation atomically snapshots the predecessor
failure/audit, consumes that predecessor, and writes the forward and reverse
plan links. Recovery requires the exact job/query links and byte-equivalent
copied predecessor state, so untouched PROCESS families cannot disappear. A
restored PROCESS fail-stop records one restored-bundle item/pair. A non-PROCESS
fail-stop has an empty PROCESS reconciliation list only when no committed
PROCESS owner exists; otherwise those live owners remain represented and the
separate non-PROCESS pair stays at the top. This audit is nonsemantic. Any
non-v9 persisted execution is not resumable as v9.

These v9/v4 boundaries are source-review contracts awaiting a fresh real run;
they are not runtime or semantic validation.

## Evidence boundary

PROCESS contracts, sidecars, planner state, histories, audit ledgers, and final
GASL prose are operational artifacts. They cannot independently close a
criterion. Semantic support is projected only from authoritative registered
assertions and their exact field bindings.

The standalone diagnostic final-synthesis provider call is the one documented
exception to occurrence-reserved provider execution: a crash after its response
but before answer persistence may repeat that call. It has no criteria or
evidence authority. Answer-view selection is deterministic and makes no model
call on the restart-safe path.

## Failure interpretation

| Outcome | What it means | Interpretation | Scope |
| --- | --- | --- | --- |
| `success` with no sidecar remainder | The command completed its declared operational contract. | Inspect registered field bindings before claiming semantic support. | In scope for GASL execution. |
| Nonempty `__unresolved` | Bounded work remains or exact enrichment is incomplete. | Schedule a direct contracted continuation; do not search for evidence solely because of this backlog. | In scope for PROCESS control. |
| Nonempty `__unsupported` | A response violated identity, shape, field, or provenance rules. | Audit the call ledger; unsupported rows have no semantic binding. | In scope for PROCESS integrity. |
| Structural required-family hold | A required runtime capability, such as authoritative country resolution, is unavailable. | Keep completion unresolved; a PROCESS retry cannot provide the missing authority. | Out of scope for PROCESS execution. |
| Missing source evidence | No authoritative registered assertion supports the requested field. | This is an evidence/search deficit, not a PROCESS transport failure. | Out of scope for PROCESS execution. |

These categories must remain separate in status reports and learning signals.
