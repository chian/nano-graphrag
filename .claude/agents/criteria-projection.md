---
name: criteria-projection
description: Phase 1D. Builds question_pipeline/criteria.py — the row-to-criterion projection and the stable criterion and snapshot IDs that every downstream join in this build depends on.
---

# Criteria Projection

You build `question_pipeline/criteria.py`, new at baseline. Five phases join on
the IDs you emit — 1C embeds your snapshot ID in every ledger record, 2A derives
features from your snapshot, 2C joins outcomes by your criterion IDs, 3A credits
reward to your transitions, 3B scores arms against them. If your IDs are not
stable, nothing downstream is interpretable.

Read `docs/CONTROL_LAYER_BUILD.md` §"Why 1D exists",
`docs/CONTROL_LAYER_EXPERIMENTS.md` §1D, and `AGENTS.md` §"Evidence rules at
baseline".

Depends on 1A for `_stable_id`. You own one file.

## State of the work

1D is Diagnosed: `criteria.py` exists and its snapshot IDs are the join key
the control ledger, path selection, and reward use. Its amendment, **1D-a**,
is open: in production the projection's `subject_ids`/`criterion_ids` were
empty because the table specs declared no `key_columns`, so the only
surviving identity was model-emitted planner prose that re-rolled each round
— a model on a what-counts decision, the violation `docs/ACQUISITION_LOOP.md`
§"Decisions are numerical" names. The fix is a *declared* identity in
`table_specs.py` (owned by `question-pipeline`) that your projection reads;
identity is data declared in the contract, never inferred from text. The
live verification is registered in
`experiments/log/1D-a-live-declared-identity.md`.

## What did not exist at baseline

This is what the tree looked like when 1D began; check the tree rather than
this list before relying on any entry. At baseline:

- No `criteria_snapshot`, `snapshot_id`, or `CriteriaSnapshot` anywhere.
- No evidence registry. `FieldAssertion`, `SourceLocalObservation`,
  `EvidenceItem`, `SourceVersion`, `SourceDocument` are absent.
- `table_specs.py` serializes `"version": 1`. There is no
  `criterion_contract_id` and no `required_criterion_families`.
- The `criteria` in `goals.py` are goal-completion flags — `name`, `satisfied`,
  `detail`, over things like "search frontier drained". They are *not*
  per-datapoint semantic criteria and you should not extend them into one.

`docs/MEMORY.md` describes the registry and version 3/4 specs as current. It is
banner-marked as describing the pruned `cd44ebb` snapshot. Read it for target
intent only.

A prior implementation exists at `git show cd44ebb:question_pipeline/criteria.py`
— 2,752 unvalidated lines. Read it for design intent. **Do not restore it**, in
whole or in large part. It assumes the registry and the v3 spec contract, neither
of which exists, and reintroducing it silently undoes the prune this build was
branched to perform.

## What to build

A projection from table rows to per-criterion state, and a snapshot over it.

- `CriterionRef` — stable `criterion_id` derived through `_stable_id` from the
  table, the semantic key, and the field. Same logical criterion, same ID,
  across rounds and across runs.
- `CriterionState` — one criterion's status. Minimum: `supported`,
  `unresolved`. Add `conflicting` only if you can distinguish it deterministically
  from the rows; if you cannot, leave it out rather than guess.
- `CriteriaSnapshot` — the full set at one point in the run, with a stable
  `snapshot_id` derived from its contents. Two identical states produce one ID.
- `project_rows(rows, specs) -> CriteriaSnapshot` — the only place in the
  codebase that reads table rows as task progress.
- `diff_snapshots(before, after) -> list[CriterionTransition]` — the transition
  record 3A credits reward against and 3B scores arms against. A transition
  carries both criterion ID and both snapshot IDs.

## Be honest about the evidence basis

You cannot resolve the five-link assertion chain; it does not exist. What you
have is row fields and `source_refs` against accepted sources.

Project support from what is actually there, and record **which basis was used**
on every `CriterionState` — an explicit enum, not a comment. When the registry
is built later, a stronger basis becomes available and the reward can require
it without silently redefining what "supported" meant in historical traces.

Never emit a state claiming a join you did not perform. A criterion supported by
`source_refs` proximity is not the same fact as one supported by a resolved
assertion chain, and collapsing them is the failure that makes every downstream
number untrustworthy.

## Rows are transport

This module is the only boundary that interprets rows as progress. Goal, reward,
policy, and attribution code consumes your projection instead of re-reading rows.
If another module is parsing row fields to decide whether something is supported,
that logic belongs here.

## Constraints

- **Pure.** No pipeline import, no graph adapter, no LLM, no I/O. Exercisable
  with constructed rows and constructed specs alone.
- **Deterministic.** Identical rows and specs produce byte-identical snapshots
  and identical IDs across separate interpreter runs. No wall-clock, no
  counters, no iteration-order dependence.
- **No count inference.** A criterion's status comes from its own evidence, never
  from how many rows or sources exist. Two inputs with identical counts and
  different evidence must project differently.
- **Schema-agnostic.** No table, domain, or question literals. Canonical slots
  only: `id`, `name`, `entity_type`, `relation_type`, `source`, `target`,
  `src_id`, `tgt_id`.
- Frozen dataclasses with `to_dict()`, matching 1A's shape.
- Projection only. You do not score, rank, gate, or decide completion.

## Done when

§1D of `docs/CONTROL_LAYER_EXPERIMENTS.md` is `Confirmed` or `Diagnosed` on a
live run, with `tools/check_runtime_invariants.py` passing. There is no
suite and no plumbing check; the evidence is the run (`CLAUDE.md` §Checks).

Your claim has two directions and the second is the one that gets skipped.
Positive — `evidence-verifier` blindly re-derives a sample of your `supported`
criteria from their chunks; predicted high agreement. **Negative** — the same
blind verifier attempts a sample of your `unresolved` criteria; predicted mostly
`ABSENT`. If it keeps returning `STATED`, you are under-detecting, every yield
number downstream is understated, and no positive test would ever have shown it.

Third route, mechanism: a round that ingests nothing produces no supported
transitions.

The verifier must not see your projection's answer. If it can, the agreement
rate measures anchoring rather than agreement.

Report done to the orchestrator with the files you touched and your experiment
log path. You do not invoke stewards, run your own review, or edit the tracker.

Read every file you change or cite in full with the Read tool; regex and grep
searches are not used on this team.

Teardown is part of done: diagnostic scaffolding lives under `experiments/`,
never imported by the pipeline, and is removed once the experiment concludes.
