---
name: path-memory
description: Phase 2C. Records which of five path outcomes each accepted source produced per target family, joined by stable IDs, so the next round searches differently.
---

# Path Memory

You make failure informative. A round that learns "no criteria delta" knows
nothing useful; a round that learns *where* the chain broke knows what to change.

Read `docs/TABLE_FILL_PATH_SELECTION.md` §3 and §4, and
`docs/CONTROL_LAYER_EXPERIMENTS.md` §2C.

Depends on 2A (and through it, 1D). Files:
`question_pipeline/search_memory.py`, `strategy_state.py`.

Outcome 5 turns on a criterion transition, and transitions are 1D's
`diff_snapshots` output — imported, not recomputed here. "Target family" means
1D's criterion grouping; the `required_criterion_families` of the version 3
table-spec contract do not exist at baseline, so do not reach for them.

## The five outcomes

Per accepted source, per target family, exactly one:

1. no graph evidence
2. graph evidence, but all routes scored low
3. high-scoring routes, but no candidate evidence for the target criterion
4. candidate evidence, but no newly supported or resolved criterion
5. newly supported or resolved semantic claims, with attributable
   semantic-claim/canonical-source pairs

Each implies a different next action — broader source families, more direct
terminology, narrower subject anchors, or provenance repair. That mapping is
why the distinction is worth recording.

Where this sits in the acquisition loop (`docs/ACQUISITION_LOOP.md`): the
outcome is classified per accepted source by a deterministic rule over the
IDs above, after the source's page episode completes. It is a *diagnosis*
of the source, not the loop's credit — the loop credits non-trivial column
values and completed rows at fetch time (§"Credits"), and outcome 5 is the
later, stricter statement that a criterion transition was attributed.
The five outcomes are recorded so the `run` grain's proposer can read *why*
a strategy stopped yielding when it samples the next one; the decision to
stop a strategy reads only the credits.

## Joins

By stable criterion, snapshot, decision, action, task, and source IDs. Never
inferred from record counts, timing, or text matching.

**Count inference is the failure mode to guard against.** Two inputs with
identical record counts but different criterion transitions must produce
different outcomes. If your classifier can be fooled by counts, it is measuring
volume and will report a busy round as a productive one.

Delayed attribution is normal — a source accepted this round may support a
criterion two rounds later. The join must survive that gap, which is why it is
by ID and not by proximity.

## Constraints

- Outcome 5 requires the semantic criteria transition. Source-local hits,
  accepted sources, and graph deltas do not qualify — those are outcome 4 at
  best.
- Typed records only. No generated prose steering downstream behavior; a reason
  string may be recorded as a diagnostic but nothing branches on its wording.
- Deterministic classification.
- Recording only. The decision to keep or abandon a strategy is the strategy
  grain's numerical verdict (phase 4D); which mutation family comes next is
  3B's routing rule. Neither lives here.

## Done when

§2C of `docs/CONTROL_LAYER_EXPERIMENTS.md` is `Confirmed` or `Diagnosed` on a
live run, with `tools/check_runtime_invariants.py` passing. There is no suite
and no plumbing check (`CLAUDE.md` §Checks).

Your claim: the five outcomes are real and distinguishable in practice.
Mechanism route — do all five actually occur across real runs? An outcome class
that never fires is impossible or misdefined, and either way is doing no work.
Ground-truth route — blind classification of what actually happened for a sample
of accepted sources, compared against your recorded outcome. Negative control —
a round ingesting no new sources produces no outcome-5 classifications.

Report done to the orchestrator with the files you touched and your experiment
log path. You do not invoke stewards, run your own review, or edit the tracker.

Read every file you change or cite in full with the Read tool; regex and grep
searches are not used on this team.

Teardown is part of done: diagnostic scaffolding lives under `experiments/`,
never imported by the pipeline, and is removed once the experiment concludes.
