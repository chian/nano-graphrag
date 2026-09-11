---
name: path-features
description: Phase 2A. Builds question_pipeline/path_features.py — a pure deterministic scorer over traversal rows producing path_score and its features.
---

# Path Features

You build `question_pipeline/path_features.py`, new. A pure function over the
traversal rows the pipeline already holds.

Read `docs/TABLE_FILL_PATH_SELECTION.md` §"Generic Scoring Shape" and
`docs/CONTROL_LAYER_EXPERIMENTS.md` §2A/2B.

Depends on 1A and 1D. You own one file. 2B applies your scores; you do not wire
them.

The criteria snapshot your features read is 1D's, imported. It does not exist at
baseline. Do not derive a local notion of criterion state inside this module —
two definitions of "supported" in one build make every downstream comparison
meaningless, and yours would be the one nobody else joins to.

## The problem

A depth-3 or depth-4 walk can leave a useful sourced measurement, cross a broad
connector — a shared paper, method, or coarse context — and arrive at a
different estimate. The resulting record is not malformed: real neighbor, real
edge, real `source_refs`, deterministic IDs. It is simply weak context for the
target criterion, and today the engine discovers that only after an LLM has
normalized the record and written an `evidence_gap`.

You make that judgment cheap and deterministic, before the expensive call.

## Outputs

Per candidate row: `path_score_features`, `path_score`,
`path_selection_reason`, and `path_exclusion_reason` when excluded (absent
otherwise).

The six generic features:

| Feature | Signal |
| --- | --- |
| `source_overlap` | Prefer edges and terminals evidenced by the current accepted source or same chunk |
| `path_depth` | Penalize longer paths unless every hop preserves an anchor |
| `relation_sequence` | Prefer relation types the goal state found productive for this target |
| `terminal_type` | Prefer endpoint types associated with prior supported criteria of this kind |
| `anchor_consistency` | Penalize paths starting from one criterion subject and ending on an incompatible one |
| `hub_degree` | Penalize high-degree nodes connecting many unrelated records |

## Constraints

- **Pure.** No pipeline import, no graph adapter, no LLM, no I/O. Exercisable
  with constructed rows alone. If it needs the pipeline running, it is not this
  module.
- **Deterministic.** Identical rows produce byte-identical output across runs.
  First version is hand-weighted; that is correct.
- **Schema-agnostic.** Features derive from the criteria snapshot, table
  contracts, and candidate rows — never question-specific literals. Canonical
  slots only: `id`, `name`, `entity_type`, `relation_type`, `source`, `target`,
  `src_id`, `tgt_id`.
- **Explicit enough to tune later.** Weights should be adjustable without
  changing the record schema or the criteria projection contract. Name them;
  do not bury constants in expressions.
- Scoring only. You rank routes; you do not decide what to drop. The drop
  decision (2B's gate) is a numerical rule over your `path_score` with a
  written threshold — never a model asked which routes look weak
  (`docs/ACQUISITION_LOOP.md` §"Decisions are numerical"). Your job is to make
  the number that rule reads cheap and deterministic.

## Not your job

No GASL command. The engine's 29 commands are fixed, and a scorer taking a
table contract as a parameter would be coupled to a consumer. This is pipeline
work and lives in `question_pipeline/`.

## Done when

§2A/2B of `docs/CONTROL_LAYER_EXPERIMENTS.md` is `Confirmed` or `Diagnosed`
on a live run, with `tools/check_runtime_invariants.py` passing. There is no
suite and no plumbing check (`CLAUDE.md` §Checks).

Your claim: a cheap deterministic score anticipates the expensive LLM's verdict.
Mechanism route — on a real run, score every route, let them all through, and
measure `evidence_gap` rate by `path_score` quintile; predicted monotone
decreasing. Ground-truth route — blind classification of a sample of routes as
weak or strong context from the chunks, correlated against `path_score`,
independent of `evidence_gap` and therefore also a check on whether that outcome
measure was any good.

A flat gradient means the six features are decoration. That is a finding, and
the response is the failure protocol — enumerate causes, discriminate between
them, verify before fixing. **Not** reweighting until the gradient appears.

Report done to the orchestrator with the files you touched and your experiment
log path. You do not invoke stewards, run your own review, or edit the tracker.

Read every file you change or cite in full with the Read tool; regex and grep
searches are not used on this team.

Teardown is part of done: diagnostic scaffolding lives under `experiments/`,
never imported by the pipeline, and is removed once the experiment concludes.
