---
name: model-tiering
description: Phase 0M. Determines per call site where a non-reasoning model gives equivalent output to a reasoning one, then implements the tiering that decision supports.
---

# Model Tiering

At baseline there was no tiering: `pipeline.py` built one
`ArgoBridgeLLM(model=config.model)` for the whole pipeline from a single
`--model` flag defaulting to `gpt-5.5`; `llm_utils.ask_json` took no model
parameter, so every consumer shared it, extraction included. Every call ran on
one model whether or not reasoning earned its cost there.

0M is Diagnosed: tiering exists (`ModelTier` declared per call site through
`llm_utils.register_call_site_tier`, `--model` for `REASONING`, `--fast-model`
for `FAST`, recorded per run in `final_answer.json["model_tiers"]` — see
`AGENTS.md` §"Model tiering"), and each call site's number, threshold, and
decision is in `experiments/log/0M-<site>.md`. This file stays as the method
for any call site that is added or re-examined: find out by experiment where
a cheaper model is equivalent, then implement what the results support.

The shape of the decision follows the repo's rule (`docs/ACQUISITION_LOOP.md`
§"Decisions are numerical"): the comparator does string work — judging
whether two outputs hold the same information — and returns a rate; the
decision to move a call site is a registered threshold applied to that rate.
The comparator never decides the tier.

Read `docs/CONTROL_LAYER_EXPERIMENTS.md`, especially §"Equivalence campaigns".

Depends on 0E. Runs before 1B, so the cost fields that phase records describe
the configuration everything afterward uses.

## This is a campaign, not an experiment

Each call site is its own question and the answers will differ. Chunk extraction
and reasoning-free batch classification are where a cheap model most plausibly
matches; arm generation and estimation are where it most plausibly does not.
Deciding them together would average away exactly the distinction you are trying
to find.

Enumerate the call sites first from the tree rather than from this list. Known
at baseline: extraction via `nano_graphrag`'s typed module (the volume leader),
`schema_synthesis`, `strategy`, `estimator`, `progress_judge`, the
`best_guess` LLM operators, and GASL's `process` and `classify` batches.

## The shape, using extraction as the worked case

Hold the input fixed: the same chunks and the same graph schema. Vary only the
model. Compare the **final cleaned-up JSON** — the end of the extraction path,
not an intermediate — entity by entity and relationship by relationship.

Comparison is **semantic, not verbatim**. The question is whether an entity in
one output holds the same key information as its counterpart in the other:
same referent, same type, same essential attributes. Differences in wording,
ordering, or surface form are not disagreements. Tally an agreement rate over
matched entities plus the unmatched ones on each side, since an output that
misses entities is not equivalent even if everything it did produce agrees.

Register the decision rule before running. Roughly 95% agreement supports
switching that call site; whatever number you register, register it first, and
if you find yourself revising it after seeing results, that is a new prediction
with the old result kept.

## Equivalence needs a sensitivity control

The trap specific to this campaign: you are trying to *fail to find* a
difference, and a blunt comparator fails to find differences everywhere. A 95%
agreement rate means nothing on its own.

So every call site's comparison includes a condition where output is known to be
worse — a markedly weaker model, or the same model on deliberately truncated
chunks. Predicted: the comparator scores that condition **clearly lower**. If it
scores the crippled condition at 93% while the cheap model gets 95%, your
comparator is not measuring anything and neither number means what it looks
like. Establish sensitivity before you interpret equivalence.

## The comparator is an instrument

Entity-by-entity semantic matching is a judgment task, so the comparator is
itself a measuring device and gets held to instrument standards:

- **Blind.** It must not know which condition produced which output. Label them
  neutrally and keep the mapping outside the comparison.
- **Symmetric.** Comparing A against B and B against A gives the same rate.
  Check it; an asymmetry means the comparator has a preferred direction.
- **Consistent.** The same pair judged twice gives the same verdict.
- **Not the model under test.** Run the comparator on a strong model regardless
  of what you are evaluating, or you are asking a cheap model to certify cheap
  models.

## Then implement

Where the evidence supports a cheaper model, implement the tiering: per-call-site
model selection, defaults chosen from your results, overridable by config. Where
it does not, leave the call site alone and record why — a documented negative is
the point of having run it.

`llm_utils.ask_json` currently takes no model parameter. Threading one through is
the natural mechanism; keep it a typed parameter with a declared default per
call site, not a string assembled at the call.

## This changes behavior deliberately

Tiering is a real behavior change, which is why it lands here and not later.
Phase 1's claim is that instrumentation is inert; a model change riding inside it
would corrupt that A/A ablation. Land tiering, record the configuration, and
let every later phase hold it fixed.

Record the resulting per-call-site configuration where later experiments will
find it — a run's costs are uninterpretable without knowing which model served
which call.

## Done when

Every enumerated call site has a registered prediction and a result, each with
its sensitivity control, the tiering the results support is implemented, and
`tools/check_runtime_invariants.py` passes. Call sites where reasoning proved
necessary are recorded as such. There is no suite and no plumbing check
(`CLAUDE.md` §Checks).

Report done to the orchestrator with the files you touched and your experiment
log path. You do not invoke stewards, run your own review, or edit the tracker.

Read every file you change or cite in full with the Read tool; regex and grep
searches are not used on this team.
