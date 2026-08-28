# AGENTS

This file is for repository-local agent instructions. It is not end-user
documentation.

Active work is the question pipeline (`question_pipeline/`) and the GASL
engine (`gasl/`). The visualization and demo-video layer is dormant — no
commits since 2026-06-04 — and its procedures are not documented here. If demo
work restarts, recover them from `git show 92f8e64:AGENTS.md`, which has the
verified safe-launcher and cinematic-pipeline rules.

## Rules for every agent in this repo

These are the operator's instructions, and each agent definition under
`.claude/agents/` restates the ones that apply to its role.

- **Read files whole.** To learn what a file says, read it in full with the
  Read tool and derive every claim from the full text; to find where
  something lives, read the candidate files. Regex and grep searches are not
  used on this team, because a pattern match returns the lines that fit the
  pattern and hides the ones that did not, and the picture acted on becomes
  the pattern's rather than the file's.
- **Decide with numbers; use models for strings.** Every stop, continue,
  switch, when-to-mutate, and what-counts decision is a numerical rule over
  measured counts with a written threshold. Model calls extract values, fill
  cells, sample new prompt and query strings, and judge semantic distance and
  content relevance. Not numerical plus a model: a model handed a curve or a
  count and asked to decide is on a decision edge. Charter:
  `docs/ACQUISITION_LOOP.md` §"Decisions are numerical"; the stewards veto it.
- **Compose the loop; do not write it.** The acquisition loop is one class
  (`Episode`) with swappable parts; a surface declares its grains and parts
  and composes them. The template and its rules are stated once, in
  `docs/ACQUISITION_LOOP.md` §"The template"; build and review from there,
  not from a copy. A recurring pattern in the code is the signal to lift it
  into a template with swappable parts, the way a team lead lays out a class
  for the team.
- **Run experiments in full.** Duration and spend are never a reason to
  shrink, defer, or reorder a registered run; the stop rules decide when a
  run ends.
- **State what to do, and why; keep the boundary.** Instructions in this
  repo lead with the action and its reason, and carry the boundary that goes
  with it. A boundary alone leaves every other wrong option open; an action
  alone drops the edge that the boundary marked. Both, in that order.
- **Work serially.** One phase at a time, one live pipeline process at a
  time, one step at a time — "care taken over each part". The build
  orchestrator (`.claude/agents/build-orchestrator.md`) is dispatched as a
  fresh agent that runs the team and is never a fork of the launching
  session, because a fork executes directly and does not dispatch.
- **Verify with live runs designed as experiments.** There is no test suite
  and none is to be created; there is no replay of recorded artifacts. See
  `CLAUDE.md` §Checks.

## Question pipeline runs

> **Runs at this commit — re-verified 2026-08-17.** The previous banner here
> said `run_question_pipeline.py` raised `TypeError` before any search ran,
> because it passed four keys `PipelineConfig` did not accept. That is no longer
> true and has not been for some time: `evidence_corpus_roots` is now a real
> `PipelineConfig` field that the runner passes correctly, and the other three
> (`goal_catalog_search_tasks`, `goal_catalog_evolutions_per_round`,
> `evidence_replay_source_ids`) are no longer passed at all.
>
> Re-verified by building a config through the runner's own `main()` argument
> parser and stopping at `build_config`:
> `--question probe --pipeline-mode table-fill --max-rounds 5` yields
> `max_rounds=5, pipeline_mode=table_fill, answer_mode=table`. The examples
> below execute as written.
>
> Recorded because the stale banner was actively harmful rather than merely
> out of date: it told every agent that live runs were impossible, which is a
> false blocker on exactly the work that needs authorizing. A doc that says
> "you cannot run" is worse than no doc.

`run_question_pipeline.py` drives the question-driven search/extract/answer loop
in `question_pipeline/`. Its module docstring carries current, working examples;
prefer those over reconstructing flags.

- Runs write to `question_runs/<run_name>/`, containing `answers/` (`tables`,
  `table_specs`, `goals`, `derived`), `fetched_papers/`, `graphs/`, and
  `final_answer.json`.
- Pass `--schema <name>` to reuse a committed schema from `domain_schemas/`
  instead of paying for synthesis on every run.
- `--pipeline-mode table-fill` is the aggregation loop. Continue prior work with
  `--graph-path`, `--seed-tables-dir`, and `--seed-sources-dir` pointed at an
  earlier run rather than starting over.
- Search requires `FIRECRAWL_API_KEY`.

### Module boundaries

The package was nineteen modules at the baseline (`92f8e64`), tabled below.
Each docstring states its own boundary; respect them. The build has since
added `control`, `criteria`, `costs`, `path_features`, `path_gate`,
`acquisition`, `provenance`, `prompt_log`, and `windowing` (what each owns:
`.claude/agents/question-pipeline.md` §"Module boundaries"). Check the
directory before relying on either list.

| Module | Lines | Owns |
| --- | --- | --- |
| `pipeline.py` | 4437 | Episode composition only. The round loop is **gone** (phase 4E-c): it declares the run/strategy/search parts, hosts the leaf's `extract` and the three hooks, and calls `Episode.run_async` once. A round is a completed strategy. Changes that reintroduce phase-batched round structure are rejected |
| `goals.py` | 1838 | Fill targets, deficits, goal-completion state |
| `best_guess.py` | 1359 | Derived candidate values |
| `search.py` | 1308 | Task, frontier, and page-acquisition mechanics. Holds **no loop over units**: the harvest loops and `SearchBatch` are deleted, the frontier gained `next_for(family)` and lost `next_wave`/`requeue_front`, and a search episode is the frontier's consumer |
| `estimator.py` | 1153 | Universe and count estimation |
| `table_specs.py` | 841 | Table contracts (serialized as version 1) |
| `search_memory.py` | 840 | Durable per-target memory |
| `strategy_state.py` | 758 | Mutation state and arm records |
| `numeric_candidates.py` | 678 | Numeric candidate extraction |
| `reward.py` | 554 | Scoring (`REWARD_VERSION = "criterion_yield_v1"`) |
| `completion.py` | 548 | Completeness state |
| `strategy.py` | 454 | Mutation routing |
| `derived_context.py` | 442 | Assessment inputs |
| `schema_synthesis.py` | 378 | Schema generation |
| `tables.py` | 247 | Table materialization |
| `progress_judge.py` | 200 | The page gate's one model call: score a page against the declared contract. It no longer judges the run's progress — the payload is (question, declared columns, page text) and the response carries one score and six prose lists, with no decision field. The module name is a disclosed residual |
| `extraction.py` | 166 | Text to typed records |
| `__init__.py` | 113 | Package surface |
| `llm_utils.py` | 65 | The provider boundary |

`llm_utils.py` is the only module holding provider access. Four modules consume
it through `ask_json`: `schema_synthesis.py`, `strategy.py`, `estimator.py`,
`progress_judge.py`. (`pipeline.py` imports it too, for tiering and client
construction — `for_tier`, `instrument_client`, `register_call_site_tier` — and
not as a fifth `ask_json` site.) Any further consumer needs a stated reason why
the work is not a pure function over data another module already produced.
`acquisition.py` and `best_guess.py` deliberately receive **callables** and
never a client, which is what keeps them exercisable in isolation.

### Model tiering

A call site never names a model. It declares a `ModelTier` — a typed default
next to the call, registered through `llm_utils.register_call_site_tier` — and
`ask_json` resolves that tier to a client. Which concrete model fills each tier
is configuration: `--model` for `REASONING`, `--fast-model` for `FAST`, both
carried on `PipelineConfig` and resolved once in `QuestionPipeline.__init__`.

A tier is set by experiment, never by judgement about which call "looks easy".
The 0M campaign ran one equivalence experiment per call site — same inputs,
only the model varying, semantic comparison by a blind third-model comparator
with its own sensitivity controls — and each site's number, threshold and
decision is in `experiments/log/0M-<site>.md`, indexed by
`experiments/log/0M-campaign.md`. A call site not named there is untested and
stays on `REASONING`: leaving a call site alone needs no evidence, only moving
it does.

Every run records what actually served it in
`final_answer.json["model_tiers"]`. A run's costs are uninterpretable without
that block, so do not drop it.

### Modules that do not exist at baseline

**This list is no longer accurate and is corrected inline.** `criteria`,
`control`, and `reward` now EXIST in the tree — `question_pipeline/criteria.py`
is the row-to-criterion projection with stable criterion and snapshot IDs, and
downstream joins depend on it. Two agents reasoned from the false "absent"
listing and lost work; verify against the tree before relying on any entry here.

Still absent as `question_pipeline` modules, and to be re-checked rather than
trusted: `evidence_registry`, `expectations`, `rarefaction`, and
`search_planning`. These were written in the WIP snapshot `cd44ebb` and
removed by the prune back to `92f8e64`.

Their design intent is readable at `git show cd44ebb:question_pipeline/<name>.py`
and may be consulted as reference. Do not restore them wholesale — that code is
unvalidated, and reintroducing it silently undoes the prune. A module from that
list enters the tree only as the deliverable of a build phase that owns it, with
its own charter and tracker row.

**`rarefaction` has entered the tree that way, as a *top-level* package** —
`rarefaction/` (accumulator, stop rule, scopes, episode driver), not a
`question_pipeline` module and not a restoration of the `cd44ebb` file. Its
charter is `docs/ACQUISITION_LOOP.md`; tracker row 4A in
`docs/CONTROL_LAYER_BUILD.md` is Confirmed (2026-08-24). Two consumers bind
it: `gasl/commands/graph_nav.py` (4B, Diagnosed) and
`question_pipeline/acquisition.py` (4C, Coded, live verification pending).

### Evidence rules at baseline

`question_pipeline/evidence_registry.py` is the durable acceptance boundary.
It commits the exact source blob plus source/version/chunk/span/assertion
candidates before appending deterministic direct acceptances. Acquisition and
criteria may credit only identities whose complete accepted chain resolves in
that registry.

**Criteria snapshots DO exist and this paragraph previously denied it.**
`CriteriaSnapshot`, `criteria_snapshot`, and `snapshot_id` are live in
`question_pipeline/criteria.py` and are the join key the control ledger, the
reward chain, and path selection all use. The claim below that `criteria` are
merely goal-completion flags describes `goals.py` only, and must not be read as
a statement about the package.

Graph content, raw values, `source_refs`, and best guesses do not mint
incidence. Best guesses have a stable cell address; their derivation and
acceptance route is a later phase.

`docs/MEMORY.md` describes the registry contract and version 3/4 table specs as
current. That describes `cd44ebb`, not this tree; the sections are banner-marked
accordingly. Read it as design intent for work not yet done.

Keep the design generic. Search prompts and runtime code derive task-specific
vocabulary from the question, table specs, criteria snapshot, accepted sources,
and observed deficits — never from question-specific words baked into code.

Design context: `docs/ACQUISITION_LOOP.md` is the governing design for the
acquisition span — the flow is a first-class per-unit loop
(acquire → extract → credit → count → verdict), not phase-batched rounds, and
`pipeline.py`'s "orchestration and round structure" role in the table above is
being rebuilt into episode composition under that charter.
`docs/TABLE_FILL_PATH_SELECTION.md` and
`docs/TABLE_FILL_PROMPT_MUTATION_EXPERIMENTS.md` remain the design context for
path scoring and prompt mutation; where they assume the phase-batched round
shape, `docs/ACQUISITION_LOOP.md` wins.

## Stable corpus run procedure

In this environment, use this exact detached launch method unless the repo
itself changes in a way that invalidates it. Choose transport explicitly with
`--transport direct` or `--transport shim`; do not rely on shell env. (As of
2026-08-24 the shim's upstream tunnel is down and the operator has set it
aside; `direct` with `LLM_API_KEY` in `.env` is the working transport for the
question pipeline. Confirm with a one-token completion before a long run.)

```bash
run_id=corpus_YYYYMMDD_view_balanced_72
mkdir -p benchmark_results/$run_id
setsid .venv/bin/python visualization/scripts/run_trace_corpus.py \
  --transport shim \
  --per-graph 18 \
  --question-file visualization/question_sets/haiqu_view_balanced_18_per_graph.json \
  --run-id "$run_id" \
  > benchmark_results/$run_id/runner.log 2>&1 < /dev/null &
echo $! > benchmark_results/$run_id/worker.pid
```

Do not invent alternate wrappers once this has been proven in-session.

## First-run validation

Before trusting a fresh corpus run, verify q001 has all of these:

- OpenAI `200 OK` on the first planner call
- `planner_prompt`
- `planner_response`
- `planner_plan`
- at least one `command_result`

Check these artifacts line by line:

- `benchmark_results/<run_id>/q001/gasl_artifacts/traces/q001.jsonl`
- `benchmark_results/<run_id>/q001/gasl_artifacts/prompt_observations.jsonl`
- `benchmark_results/<run_id>/q001/gasl_state.json`

If the worker is dead, `runner.log` is empty, or q001 stops before
`planner_response`, the run is invalid. Fix the launch method first. Do not
debug GASL from an invalid run.

## Runtime workflow checklist

For a healthy GASL run, the trace should show:

- planner prompt emitted
- planner response emitted
- planner plan parsed
- command start/result for each executed step
- command-local repair response for commands that return `error` or `empty`
- iteration failure summary when an iteration completes with defects
- plan-iteration prompt/response when iteration-level defects remain after
  command-local repair
- produced artifacts recorded when commands materialize reusable state
- final answer response emitted

## Analysis rule

For every analysis, separate outcomes from interpretation.

Use a compact table or equivalent structure with:

- outcome
- what it means
- interpretation

Also mark whether each observed outcome is:

- in scope for the tested mechanism
- out of scope for the tested mechanism

Do not treat out-of-scope defects as evidence against the target mechanism.

## Directory discipline

Before creating, using, or writing into any existing directory in this repo:

- Establish the directory's purpose from its contents, not its name. List it
  first. If it holds 20 files or fewer, read them. If it holds more — 
  `question_runs/` and `benchmark_results/` each hold well over a hundred — read
  a sample of at least five spanning oldest and newest, plus any README,
  manifest, or summary file, and stop there. Do not read a run-output directory
  exhaustively; it is a context sink and tells you nothing the sample does not.
- Do not repurpose an existing directory unless its contents confirm the intended use.
- If the purpose is still unclear after that sampling, create a new neutral
  directory instead. Ambiguity resolves toward a new directory, never toward
  more reading.
- In status updates before writing files, state which directory will be used and what existing-file evidence justified that choice.
