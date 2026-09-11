# experiments/

Diagnostic scaffolding for the control-layer build. **The pipeline never imports
anything here.** The dependency runs one way, which is what makes teardown a
deletion rather than a merge.

```
log/<id>.md         registered predictions, results, verified causes, teardown lists
runs/<id>/          captured results, append-only, survive teardown
<id>/               per-experiment diagnostic code, deleted at that experiment's teardown
registry.py         prediction registration; the only durable apparatus
```

## There is no test suite, and none may be created

`tests/` was removed on the user's explicit direction. No smoke tests, no
plumbing tests, no regression tests, no tripwires, under any framing. The
reasoning is not stylistic: unmotivated tests here **codified defects** — three
tests in this codebase asserted buggy behaviour as correct, so fixing each bug
required deleting the test that "covered" it.

`pytest` **is** installed in `.venv`. The ban is therefore normative, not
mechanical, and nothing stops a suite from reappearing except this rule. No
collection of assertions run as a batch, whatever it is named.

The distinguishing property is not the runner:

> A test asserts a value the author chose. A partial run reproduces a value an
> earlier real run **recorded**, which the author could not choose.

Anything asserting an author-chosen constant is a test wearing a new coat.

## The apparatus was pruned

Earlier revisions of this file documented a `harness/` package — `conditions.py`,
`capture.py`, `replay.py`, `runner.py`, `budget.py`, `logbook.py` — with a table
headed "Owns", and instructed `pytest -q experiments/harness/tests`.

**None of it exists.** The package was pruned and this file was left behind. It
is recorded here rather than silently deleted because the stale version was
actively harmful: it advertised capabilities agents then designed against and
discovered missing mid-implementation, and its `pytest` line was an executable
instruction to reintroduce the suite.

One real capability went with it: `conditions.py`'s `assert_isolation`, the
offline-recomputable proof that only the manipulated keys differed between
conditions. Nothing replaces it automatically. An experiment needing that
guarantee builds and self-tests its own guard, and no design may cite
`assert_isolation` or assume an isolation assertion it did not build.

`registry.py` survives, works, and is the one apparatus dependency the standard
is permitted to have.

## Writing an experiment

1. Write the specification as committed, versioned data. It is the definition of
   the condition — cheap, text, joinable by ID, the same status as a reward
   version. A run citing spec v2 is comparable to another citing v2 and not to
   one citing v1.
2. Register the prediction in `log/<id>.md` — claim, conditions, predicted
   direction, falsifying result, and the confirmation routes — and stamp it with
   `registry.register`. The stamp without the prediction text is a timestamp on
   nothing; the text without the stamp proves no ordering. Both, in one file.
   `registry.assert_registered` refuses a run against an unregistered or drifted
   spec.
3. Everything that can move a result goes inside the fingerprint. Per
   `spec_fingerprint`'s own docstring: *"anything left out is, by construction,
   not covered by the guarantee."* The population statement and the cut are
   inside it — those are what moved in every broken measurement this repo has
   recorded.
4. Analyse from a live run. Never from a previous run's record.

## The implementation is disposable; the spec is not

Stability is guaranteed by the spec's identity, not by a file's continued
existence on disk. Two runs are comparable iff they cite the same spec id and
version — not iff they ran the same code.

So the run record carries the `sha256` of the implementation that produced it.
Two runs citing one spec version with different apparatus hashes are a
**disclosed re-derivation**, and any disagreement between them is a finding that
the spec was under-specified — not noise to average away. This is what makes a
spec earn its keep.

Disposable code lives in `experiments/<id>/`, never in `experiments/runs/<id>/`.
The `runs/` namespace holds results that must survive teardown, and disposable
code sitting in it is how teardown later becomes a merge instead of a deletion:
whoever tears down has to decide, file by file, which things under `runs/` are
evidence. It may import the pipeline; it may **not** import from
`experiments/runs/`, or the results namespace becomes load-bearing and
undeletable.

## Acquisition-method experiments

`docs/ACQUISITION_LOOP.md` governs the current method: incidence samples,
rolling exact rarefaction, a generic role-based `RarefactionMethod`
decision-facing record, incidence Chao2 as its current reachable-total
estimator, and a numerical controller.

The 4A--4E logs contain structural evidence about `Episode` composition, typed
ends, nesting, and fan-up. Phase 4G receives its own registered live experiment
after the estimator and controller are wired.
