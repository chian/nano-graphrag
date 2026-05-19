---
name: gasl-general-qa
description: Use when changing GASL runtime or answer-layer code. GASL is a general QA system over knowledge graphs; generic code must prefer state-driven, slot-based, schema-agnostic workflows and may use only canonical engine slots as literals.
---

# GASL General QA

Use this skill when editing generic GASL runtime code.

## Invariant

GASL is a general QA system over knowledge graphs.

- Do not hard-code domain fields, ontology labels, or source-specific properties
  into generic runtime paths.
- Canonical engine slots are allowed literals:
  `id`, `name`, `entity_type`, `relation_type`, `source`, `target`, `src_id`,
  `tgt_id`.
- Answer families should work from state data using semantic slots, not
  domain-specific field names.

## Workflow

1. Read [docs/RUNTIME_INVARIANTS.md](../../../docs/RUNTIME_INVARIANTS.md).
2. Before patching, identify whether the change is:
   - generic runtime
   - graph/source-specific ingestion
   - demo/benchmark/visualization only
3. In generic runtime:
   - prefer state-driven and slot-based designs
   - use graph-first retrieval, then provenance/chunk augmentation if needed
   - keep domain literals out of generic layers
4. Before finishing:
   - run `python3 tools/check_runtime_invariants.py`
   - run `pytest -q tests/test_runtime_invariants.py`

## Scope

This skill is a guardrail for generic GASL engineering. It does not restrict
graph-specific ingestion, benchmarking, or visualization modules when those
modules are intentionally scoped to a particular graph family.
