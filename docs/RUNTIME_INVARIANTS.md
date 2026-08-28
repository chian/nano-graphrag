# Runtime Invariants

These are the invariants for generic GASL runtime code review and refactors.

## System identity

GASL is a **general question-answering system over knowledge graphs**.

- It is not a domain-specific QA implementation.
- Generic runtime code must prefer **state-driven**, **slot-based**, and
  **schema-agnostic** workflows.
- Answer families may depend on semantic slots such as `subject`, `outcome`,
  `measure`, `support`, or `uncertainty`, but they must not assume
  domain-specific field names in generic runtime code.

## Canonical graph abstraction keys

These are allowed as code literals in generic runtime code because they are part
of the engine's canonical graph abstraction rather than domain- or source-
specific schema:

- `id`
- `name`
- `entity_type`
- `relation_type`
- `source`
- `target`
- `src_id`
- `tgt_id`

## Non-canonical keys

These must not be assumed as generic runtime literals. They must come from
runtime metadata, contracts, prompt output, or source-specific mapping:

- domain-specific feature names
- source-graph-specific property names
- query-family keywords steering runtime behavior
- ontology-specific fallback fields
- feature-specific fields such as `source_papers`, `alternative_names`, etc.

## Review rule

For every string-key access in runtime code:

1. Is this key part of the canonical graph abstraction above?
   - yes: literal is allowed
   - no: derive it from runtime metadata / contracts / planner output / source mapping

2. Demo, benchmark, and visualization code may be graph-specific.
   Core runtime code may not.

## Layering

`gasl/` is the generic query engine. It must not import `nano_graphrag/`
(ingestion), `query_generation/`, or `question_pipeline/`. The dependency runs
the other way.

This is enforced structurally by `tools/check_runtime_invariants.py`, and it is
enforced because the literal scan could not see the defect that motivated it:
`gasl/commands/data_transform.py` and `gasl/commands/contrastive.py` imported
`get_source_refs` from `nano_graphrag.graph_slots`, whose fallback reads
`source_papers` — named as forbidden in the list above. Every `COLLAPSE`,
`PROJECT` and `AGGREGATE` reached it transitively while the checker reported a
clean tree, because the literal lives outside the scanned paths.

Provenance accessors now live in `gasl/provenance.py`, **without the legacy
aliases**. A graph that stores provenance under another key declares where via
the contract's `source_ref_field`; it does not get a hardcoded guess. If a
source graph genuinely uses a different key, that mapping belongs in the
adapter.

The checker carries a frozen inventory, `KNOWN_OUTBOUND_IMPORTS`, of the
outbound imports that predate this rule (all `nano_graphrag.prompt_system`, plus
one `query_generation.graph_validator`). They are **not blessed** — the
inventory exists so that a *new* outbound import fails the check rather than
hiding among them. It may shrink. It must not grow.

The operator's stated goal (2026-08-24) is strict dependency linearity —
`rarefaction/` below `gasl/` below `question_pipeline/`, with ingestion
beside the pipeline and nothing importing upward. So the inventory is debt:
a phase that edits a file carrying one of these imports removes the import
as part of the phase, and the steward reviewing that phase asks why if it
did not.

**Permitted lower layer (phase 4A, landed 2026-08-24):** `gasl/` may import
the `rarefaction/` package. This is not growth of the outbound inventory and
not a weakening of this rule: the rule keeps the engine from importing the
ingestion and control layers *above* it, and `rarefaction/` is a *lower*
layer — pure stdlib arithmetic over opaque identity tokens, importing
nothing, schema-agnostic by construction. The checker carries an explicit
permitted-lower-layer entry for it, with this paragraph as the documented
reason. Charter: `docs/ACQUISITION_LOOP.md`. The binding that uses it is
`gasl/commands/graph_nav.py` (phase 4B): the walk reports yield in numbers
and quits on the kernel's verdict; it passes the kernel opaque identities
only, so the engine stays schema-agnostic.

## Enforcement

Before merging generic-runtime changes:

1. run the invariant checker: `.venv/bin/python tools/check_runtime_invariants.py`
   - this checker intentionally targets generic runtime paths (`gasl/` and
     selected runtime entry points), not ingestion/storage/benchmark modules
2. if the checker needs a new allowed exception, document the reason in both the
   checker and this file

(An earlier revision listed a `pytest` invariant-test step here. `tests/` has
been deleted and no suite may be created; the static checker is the only
mechanical check. Behavioral verification is a live run — see `CLAUDE.md`
§Checks.)

## Variable-access rule

Generic runtime code still needs variables and field access. The rule is not
"avoid field names entirely." The rule is:

- canonical graph-access field names are allowed because they are how the engine
  retrieves values that will later be carried forward as variables
- the value retrieved through a canonical field may absolutely be used later for
  planning, filtering, graph walking, grouping, or answer construction
- the bug is not "using a field name"; the bug is baking in non-canonical,
  feature-specific assumptions as if they were universal

Examples:

- allowed: `row["entity_type"]` when `entity_type` is part of the engine's
  canonical graph abstraction
- allowed: using the returned `entity_type` value to drive later graph walking
- not allowed: assuming feature-specific fields such as `source_papers`,
  `alternative_names`, `importance_score`, or source-graph-specific properties
  are universally present in generic runtime code
