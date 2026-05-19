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

## Enforcement

Before merging generic-runtime changes:

1. run the invariant checker: `python3 tools/check_runtime_invariants.py`
   - this checker intentionally targets generic runtime paths (`gasl/` and
     selected runtime entry points), not ingestion/storage/benchmark modules
2. run the focused invariant tests: `pytest -q tests/test_runtime_invariants.py`
3. if the checker needs a new allowed exception, document the reason in both the
   checker and this file

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
