# CLAUDE.md

Authoritative project instructions for Claude Code.

`AGENTS.md` holds the repository-local operational rules — question pipeline
runs, the stable corpus run procedure, first-run validation, the runtime
workflow checklist, the analysis rule, and directory discipline. Read it before
doing work in this repo. Tools that discover `AGENTS.md` on their own should
read this file too; neither file is a copy of the other.

## Where the work is

Active: `question_pipeline/` (table-fill, goals, reward, search memory) and
`gasl/`. Dormant: `visualization/`, untouched since 2026-06-04. Treat viz code
as frozen unless the user reopens that work.

Note the package inventory in `AGENTS.md` §"Module boundaries" before assuming a
module exists, and check the directory rather than any list. Several modules
described in earlier revisions of these docs were removed by the prune back
to `92f8e64`; some have since been rebuilt as build-phase deliverables
(`control`, `criteria`, `path_features`, `path_gate`, `costs`, `acquisition`
in `question_pipeline/`; `rarefaction/` at top level) and some are still
absent (`evidence_registry`, `expectations`, `search_planning`).

## The central design

The acquisition span — provider search, GASL graph walking, and strategy
selection — is one closed loop, and the loop is a first-class modular
function: acquire unit → extract → credit against declared targets → count →
a rarefaction verdict **in numbers** decides continue/stop/switch, nested at
every grain a surface declares (page ⊂ search ⊂ strategy ⊂ run on the
provider surface; seed ⊂ walk ⊂ query on the GASL surface). The loop is one
class, `Episode`, with swappable parts and a source that may yield child
episodes, and a surface binds by composing it — never by writing a loop.
The template, the credit rule, and the composition rules are stated once, in
the charter's §"The template"; every other document points there. Every
decision on that edge is a numerical rule; models do the string work —
extract, fill, mutate, compare. **`docs/ACQUISITION_LOOP.md`** is the charter; wherever
another document describes the flow differently, that document is stale. The
old phase-batched round flow (search-all → extract-all →
credit-at-round-end) is condemned and being torn down under that charter.

## The current build

The active project is the control-layer build: prompt mutation and tuning
against a costed reward, now including the acquisition-loop rebuild (the
4-series phases). Start at **`docs/CONTROL_LAYER_BUILD.md`** — phase
table, dependency graph, review gates, and the run protocol — then
**`docs/CONTROL_LAYER_EXPERIMENTS.md`**, which defines what counts as evidence
and what each phase must show.

**Plumbing checks are not evidence.** A shape check passes on a function that
returns its first argument. Phases close on experiments — real runs, real
search, real data, conditions manipulated and directions predicted in advance,
claims confirmed on two independent routes.

## Layout

- `question_pipeline/` + `run_question_pipeline.py` — question-driven
  search → extract → answer loop, with an aggregation `table-fill` mode.
  This is where most current work happens.
- `gasl/` — the GASL engine: parser, executor, commands, state, adapters.
  Generic runtime code here is schema-agnostic; see
  `docs/RUNTIME_INVARIANTS.md`.
- `rarefaction/` — the pure counting/decision kernel every acquisition
  surface shares: accumulator, stop rule, scopes, episode driver (phase 4A,
  Confirmed). Bottom layer; imports nothing. See `docs/ACQUISITION_LOOP.md`.
- `nano_graphrag/` — ingestion and graph construction.
- `domain_schemas/` — reusable typed schemas for extraction.
- `visualization/` — browser UI, demo launchers, benchmark runners. Dormant.
  May be graph-specific; the runtime invariants do not apply here.

## Checks

**Verify with a real run, designed as an experiment.** An experimental-design
agent states the claim, what would falsify it, and what evidence confirms it;
then the run happens on real providers, real search, real data, and the
result is judged against the registered prediction. **There is no test suite,
and none is to be created** — no smoke tests, no plumbing tests, no
regression tests, no tripwires, under any framing; `tests/` has been
removed. Why: a shape check passes on a function that returns its first
argument. When a cheap check feels unavoidable, that feeling is the cue to
dispatch an experiment, not to write a test.

**Verify on a live run of current code, every time. No replay:** do not
verify, calibrate, or measure by re-running code over a previous run's
recorded artifacts. Those artifacts describe the tree that produced them, and
the claim is about the tree being changed. When a full run costs too much,
run a smaller live one — fewer sources, one table, one round — never a
replay of an old one.

Verify at the consumer rather than by diff review, and reproduce a defect on a
live run before fixing it.

**Decide with numbers; use models for strings.** Every stop, continue, switch,
when-to-mutate, and what-counts decision is a numerical rule over measured
counts. LLM calls extract, fill, mutate, and compare strings. The charter
section is `docs/ACQUISITION_LOOP.md` §"Decisions are numerical"; the
stewards veto a model on a decision edge.

For generic GASL runtime changes, the static invariant checker still applies:

```bash
.venv/bin/python tools/check_runtime_invariants.py
```

`pytest` is not on `PATH` and is not used.

## Subagents

`.claude/agents/` holds four groups.

**Orchestrator** — `build-orchestrator`. The run-protocol role from
`docs/CONTROL_LAYER_BUILD.md` as an agent. **Dispatch it as a fresh agent,
and it works one phase at a time — both by the operator's instruction.** A
fresh agent holds the `Agent` tool and so can run the team (a fork executes
directly); serial is "care taken over each part". It dispatches the phase
agents and the steward agents, verifies claims itself, and is the only writer
of the tracker's phase table. The launching session writes the brief,
dispatches once, and relays the report.

**Layer agents** — `question-pipeline`, `gasl-runtime`, `corpus-runner`. Each
restates the rules for its layer and points at the governing doc.

**Design stewards** — `experiment-steward`, `modularity-steward`,
`reward-design-steward`, `prompt-mutation-steward`, `gasl-design-steward`.
Standing reviewers, by concern rather than by phase. They hold veto authority
and decide their own calls.

**Instruments** — `evidence-verifier`. Not a reviewer: a blind measuring device
that re-derives a claimed datapoint from its source chunk without seeing what
the pipeline concluded. Ground truth for the whole build depends on it staying
blind.

**Phase agents** — `experiment-harness` (0E), `model-tiering` (0M),
`control-architect` (1A), `cost-accountant` (1B), `decision-ledger` (1C),
`criteria-projection` (1D, and its amendment 1D-a), `path-features` (2A),
`path-gate` (2B), `path-memory` (2C), `reward-engineer` (3A), `arm-tuner`
(3B), `acquisition-kernel` (4A). 4B is owned by `gasl-runtime`; 4C and 4D by
`question-pipeline`. `iteration-driver` is a general research driver, used
when a question needs repeated sharpen-and-retest cycles rather than a phase.

Phase agents do not invoke their own stewards and do not edit the tracker. The
orchestrator verifies, dispatches reviewers, and writes rows.

Two rules bind every agent in this repo and are restated in each definition:
read files in full with the Read tool (regex and grep searches are not used
on this team), and lead every instruction with the action and its reason,
keeping the boundary that goes with it. `AGENTS.md` §"Rules for every agent"
carries the full list.
