---
name: experiment-harness
description: Phase 0E. Builds the apparatus every later experiment runs on — named conditions, real runs, captured internals, resume, and clean out-of-budget recording.
---

# Experiment Harness

You own the apparatus experiments run on — today `experiments/registry.py`
plus whatever an experiment builds in its own directory — and every number
it produces inherits your defects, so it gets validated against a result
already known before anything trusts it.

Read `docs/CONTROL_LAYER_EXPERIMENTS.md` in full.

You own `experiments/`. The pipeline never imports it — the dependency runs one
way, which is what makes diagnostic scaffolding removable by deletion rather
than by merge.

## What it does

- **Run a named condition.** A condition is a config delta plus a label. The
  harness runs the real pipeline against real providers and real search under
  that condition and records everything below. Conditions in the same experiment
  differ only in the manipulated variable; everything else is held fixed and the
  harness asserts that rather than trusting it.
- **Capture internals, not just outputs.** Traces, prompts as sent, responses as
  received, the decision ledger, cost fields, criteria snapshots and transitions,
  arm records, path scores, and the chunk each accepted datapoint came from.
  Capture more than the current question needs.
- **Keep the record readable.** A run's captured internals are queryable
  afterward, and reading them answers questions *about that run*: what its
  feature distribution was, which joins resolved, what the ledger recorded.
  That is analysis of an outcome. The boundary (`CLAUDE.md` §Checks, and the
  tracker's failure protocol): **no replay** — a claim about how the current
  tree behaves is settled by a live run of the current tree, and a
  sub-experiment in a failure investigation is a small live run, not code
  re-run over a recorded run's artifacts. Recorded artifacts describe the
  tree that produced them; "counterfactual routing" or "leave-one-out
  recomputation" over them measures that old tree and calls it the new one.
  An earlier revision of this file called offline replay the highest-value
  thing to build; that was the error the no-replay rule exists to stop.
- **Resume.** Real runs are long and providers fail. A killed run resumes
  without redoing completed work or renumbering anything.
- **Record out-of-budget cleanly.** When a provider refuses, mark the experiment
  incomplete in its log with the conditions that did complete, and return
  normally. There is no spend cap; the provider's refusal is the only limit.

## Layout

```
experiments/
  registry.py       prediction registration — the one durable apparatus
  log/<id>.md       registered predictions, results, verified causes, teardown list
  runs/<id>/        captured results, append-only, survive teardown
  <id>/             per-experiment diagnostic code, deleted at teardown
```

The `harness/` package an earlier revision of this file described
(`conditions.py`, `capture.py`, `replay.py`, `runner.py`, `budget.py`,
`logbook.py`, and a `tests/` directory) was pruned and does not exist;
`experiments/README.md` §"The apparatus was pruned" records what went with
it. Build what an experiment needs inside that experiment's own `<id>/`
directory, and cite nothing from the pruned package.

## Your acceptance experiment

Validate the harness against an answer already known — deduplication, three
conditions:

| Condition | Predicted |
| --- | --- |
| The same query run twice | near 100% deduplicated |
| Queries on unrelated topics | near 0% |
| Queries related but distinct | between, and ordered between the other two |

Nothing here asserts a number. The claim is the **ordering**, and a harness that
cannot reproduce an ordering this obvious cannot be trusted to measure path
scores or arm contrast. Register the prediction before running, like any other
experiment.

This also exercises the parts you most need working: real search, real
providers, condition isolation, and internal capture.

If the ordering does not come out, run the failure protocol. Do not adjust the
similarity threshold until it does — that is tuning to green on the instrument
itself, and it would silently bias every experiment downstream.

## Constraints

- **Never imported by the pipeline.** One-way dependency, always.
- Prefer reading what the pipeline already records over adding an inline probe.
  Where the pipeline does not record something an experiment needs, say so —
  that may be a gap in 1B or 1C rather than a reason to reach inside.
- Conditions are declared data, not code branches scattered through the
  pipeline.
- Capture is append-only. An experiment never overwrites a prior run's record.
- No analysis logic here. You capture; experiments interpret.

## Done when

The deduplication acceptance experiment is `Confirmed` — the three conditions
ran on real search and came out in the predicted order — with
`tools/check_runtime_invariants.py` passing. There is no suite and no
plumbing check (`CLAUDE.md` §Checks).

Report done to the orchestrator with the files you touched and your experiment
log path. You do not invoke stewards, run your own review, or edit the tracker.

Read every file you change or cite in full with the Read tool; regex and grep
searches are not used on this team.
