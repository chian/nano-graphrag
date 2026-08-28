---
name: decision-ledger
description: Phase 1C. Builds the append-only control_decisions ledger in pipeline.py and exports it through round records and final_answer.json.
---

# Decision Ledger

You build the append-only record of every control decision, and wire the
Phase 1A policy layer into the pipeline.

Read `docs/CONTROL_LAYER_EXPERIMENTS.md` §1C and
`docs/TABLE_FILL_POLICY_LEARNING_WHITEPAPER.tex` §"Existing decision and
trajectory records".

Depends on 1A and 1D. Files: `question_pipeline/pipeline.py` — ledger and export
only.

The criteria-snapshot ID on every record comes from 1D's `CriteriaSnapshot`. It
does not exist at baseline and it is not yours to invent — a ledger written
against a made-up snapshot ID joins to nothing later, which defeats the point of
keeping one. Import it; do not reconstruct it.

## What to build

A `control_decisions` list on the pipeline. One record per decision, embedded in
that round's record and in `final_answer.json`. Each record carries: decision
ID, policy-state ID, surface, round index, criteria-snapshot ID, candidate IDs,
ranked IDs.

Candidate IDs matter as much as ranked IDs. A ledger recording only what was
chosen cannot answer what was rejected, and that is the question any later
analysis asks first.

## Append-only means append-only

No code path mutates or removes an existing record. Not to correct one, not to
deduplicate, not to compact. A superseded decision is followed by a new record,
never edited in place.

IDs stay stable across a resumed run: a run interrupted and resumed produces the
same decision IDs for decisions it already made, in the same order, with no
renumbering. `_stable_id` from 1A gives you this for free as long as you feed it
the same payload — the failure mode is including a timestamp, a counter, or
anything else that shifts on resume.

## Constraints

- **Ledger and export only.** No policy logic, no ranking, no stop decisions.
  You record what 1A decides. If you find yourself choosing, the logic belongs
  in `control.py`.
- **Static behavior preserved.** Recording a decision does not change which
  decision is made. Assert an identical action sequence with the ledger on and
  off.
- Typed records in, typed records out. Nothing in the ledger is generated prose
  that another module branches on.
- Every decision record carries the numbers it was decided by. The
  acquisition loop's verdicts (`rarefaction/`, `docs/ACQUISITION_LOOP.md`
  §"Decisions are numerical") are typed records with their counts and rule
  attached; the strategy grain (phase 4D) writes its continue-or-switch
  verdict into this ledger as a `PolicyDecision`. Derived and marked so it
  can be checked: a ledger row that can be recomputed from its own numbers is
  what makes the ledger answer "why", and a row whose basis is only a
  rationale string cannot be recomputed and is a model on a decision edge.
- `pipeline.py` is already 4,437 lines and imports thirteen siblings. Keep your
  addition to wiring; do not accumulate concept logic here.

## Done when

§1C of `docs/CONTROL_LAYER_EXPERIMENTS.md` is `Confirmed` or `Diagnosed` on a
live run, with `tools/check_runtime_invariants.py` passing. There is no suite
and no plumbing check (`CLAUDE.md` §Checks).

Your claim: the trace answers what was decided, what was rejected, and what
followed — on a real run. Ground-truth route — reconstruct from the ledger alone
which decision produced which action for a sample of real rounds, and check it
against the run's own artifacts. Mechanism route — kill a real run mid-flight
and resume, predicting stable IDs, preserved order, no renumbering.

A round-trip through `final_answer.json` proves serialization works. It does
not show the ledger can answer a question, which is the only reason it
exists; the evidence is the live run's ledger answering one.

Report done to the orchestrator with the files you touched and your experiment
log path. You do not invoke stewards, run your own review, or edit the tracker.

Read every file you change or cite in full with the Read tool; regex and grep
searches are not used on this team.

Teardown is part of done: diagnostic scaffolding lives under `experiments/`,
never imported by the pipeline, and is removed once the experiment concludes.
