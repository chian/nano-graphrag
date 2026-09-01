# Next step — read this first in a new session

Written 2026-08-31 by the takeover session (supersedes the 2026-08-28 revision;
that revision's foundational-experiment requirements are folded in below, not
dropped). Replace this file when the first foundational live experiment is
complete. This file is the complete operator instruction set for the work in
flight: a successor session (codex or Claude) must be able to execute from this
file plus the governing docs alone.

Read with this file: `AGENTS.md`, `CLAUDE.md`, `docs/ACQUISITION_LOOP.md` (the
charter — wins over any conflicting doc), `docs/CONTROL_LAYER_BUILD.md` (run
protocol, review gates, phase tracker). Repo rules bind every agent: read files
whole with the Read tool (no grep/regex), decisions are numerical / models do
string work, no test suite ever, no replay — verification is a live run designed
as an experiment, work serially, dispatched steward verdicts only (a self-review
does not satisfy a gate).

## OPERATOR RULING — the Episode code hierarchy is never changed (2026-09-01)

This replaces the earlier "stop and report if a change appears necessary"
escalation: there is no escalation path. `method_loop/` — `Episode`, `Leaf`,
`Grain`, `Context`, `ScopedYield`, `NumericalController`, the identities, the
grain-order enforcement, the fan-up and bound-leak rules, the record shapes —
is fixed, as is `rarefaction/`'s estimator math. No agent edits, extends,
subclasses-to-override, monkeypatches, or wraps-to-alter any of it, ever, for
any reason. A surface phase binds by COMPOSING the exported API exactly as it
stands at HEAD `9a3955b`. If a design cannot be expressed through composition
of the existing hierarchy, the design is wrong — redesign the surface side
until it composes; a genuinely uncomposable requirement is recorded in the
final report as a finding about the design, and the phase proceeds with what
does compose. "Report the need" is documentation, never a request for a
change. This ruling is restated in every phase-agent and steward dispatch.

## OPERATOR RULING — Phase G is binding layers to Episodes; that is all (2026-09-01)

The operator's words: "you should only have to bind layers. that's it. you
have gasl function and planning function and all function you need already.
if this gets complicated more than just binding layers to episodes, then come
back and discuss with me."

Concretely: the parts already exist — the two-phase planner (the query
grain's source), the command handlers (the extract work), `GraphWalkBinding`
(the walk child), the adapter, the state/trace machinery. Phase G WIRES these
existing functions into Episode grain declarations and one composition. It
does NOT build new modules, new input contracts, new runners, new fate
machinery, or rewrites of existing functions beyond what wiring strictly
requires. No new graph-revision contract module and no rewiring of
`gasl_main`'s loading path: use the graph the existing loader already
supplies, and RECORD the graph file's path and content digest in the emitted
records as disclosure — that is wiring, not building. The charter amendment
shrinks to the grain-table row the new binding factually declares. If any
step in design or implementation requires more than binding existing
functions to Episodes — a new module, a changed function signature outside
the binding file, machinery that doesn't exist — the phase STOPS THERE and
reports back for operator discussion; nothing beyond binding is built or
worked around. Small is the success condition.

## OPERATOR RULING — estimator mathematics remain frozen (2026-09-01)

The operator subsequently authorized the ownership correction explicitly:
`Episode`, scope/runtime composition, and the numerical controller were moved
from `rarefaction/` into `method_loop/`. `rarefaction/accumulator.py` remains
the unchanged estimator implementation. Future changes to estimator
mathematics still require explicit operator authorization and a written design.
The dependency direction is fixed: `method_loop.Episode` consumes a
rarefaction estimator; rarefaction never contains or owns the method loop.

> **Revert record — 2026-09-01.** An off-script codex session produced a large
> uncommitted delta on top of `7c22ab6` (+5,913/−3,885 across 34 files),
> including an unauthorized rewrite of the `rarefaction/` kernel, deletion of
> `gasl_main.py` and `gasl/commands/graph_nav.py` without landing replacements
> (GRAPHWALK left with no handler), and uncommitted charter/doc edits. On the
> operator's explicit order the ENTIRE tracked delta was reverted to `7c22ab6`
> — the last verified state — and verified
> (invariant checker passes, all packages parse, graph-nav → walk-binding
> wiring restored, de-rounded modules unchanged, `rarefaction/` byte-identical
> to HEAD). The standing `progress_judge.py` deletion was re-applied. Phases 2,
> 3, 4, 5 and the live experiments below remain OPEN
> and are re-implemented properly through the protocol.
>
> **Next phase in flight: Phase G — the GASL search binding** (operator-
> chartered 2026-09-01): bind the GASL surface's search layer as a peer Episode
> composition whose finest bound grain is one GASL operation track (an
> individual GRAPHWALK, FIND, or other graph-reading operation), nesting the
> bound walk ⊃ seed machinery beneath walk operations; the planner is the query
> grain's source; the numerical verdict replaces `max_gasl_iterations` as the
> continue/stop rule (the cap becomes a disclosed safety bound reporting
> `bound_hit`); credits stay opaque identities; every invocation reads one
> explicitly supplied immutable graph revision (id + content digest); zero
> `rarefaction/` changes. Charter amendment (operation grain row) and
> `gasl-design-steward` design review precedes code;
> a registered live GASL run closes it.

## State of the work (as of 2026-08-31, evening)

> **Closure update — 2026-08-31, later.** Phase 1 is closed **PASS** because
> direct verification found no global round identity. Phase R is also closed
> **PASS** after direct structural verification
> of the GASL walk-binding move and the provider-binding consolidation. The two
> phases are recorded in one combined closure commit because their reviewed
> changes are interleaved in `question_pipeline/acquisition.py` and
> `question_pipeline/pipeline.py`; calling that commit Phase-R-only would be
> false, while separating the hunks would not preserve a mechanically safe
> staged tree. Phase 2 is next and is limited to the event rabbit-hole check.

> **Superseded by the Phase 1 implementation dispatch (2026-08-31, later).**
> The dangling-reference inventory below is FIXED on disk: `pipeline.py` is
> operational again (verified by a zero-spend structural drive of a table-fill
> run with injected fakes at every provider boundary — one strategy Episode,
> Episode-named artifacts, zero hook failures, no round token in any emitted
> artifact), the runner's flags are `--max-source-units` /
> `--min-source-length` / `--max-source-length` /
> `--max-extraction-chars-per-source` with `--answer-mode` and
> `--best-guess-max-tasks` deleted, `question_pipeline/__init__.py` exports
> `aggregate_cost`, and `completion.py` / `table_specs.py` lost their last
> round-keyed fields and round-numbered-filename loaders. Full record:
> `experiments/log/round-removal-phase1.md`. The review gate below is still
> owed; nothing is committed.

A `build-orchestrator` agent team is mid-flight on **Phase 1 (rounds removal)**.
HEAD is `adec35a`; nothing is committed since (correct — a phase commits only
after its review gate). Verified on disk:

- **De-rounded and done**: `strategy_state.py`, `search_memory.py`, `reward.py`,
  `search.py` (zero round/paper tokens). `costs.py` (`cost_accounting_v2`) and
  `prompt_log.py` (`prompt_log_v2`) were already episode-keyed.
  `PipelineConfig` now carries `max_source_units` (the renamed bound) and
  `episode_unit_safety_cap = 1_000_000`.
- **`question_pipeline/pipeline.py` is mid-rewrite and non-operational.**
  Dangling references verified by full read + AST at the time of audit:
  `_open_strategy_ledger_window` and `_strategy_control_decisions` called but
  the definitions are still named `_open_round_ledger_window` /
  `_round_control_decisions` (~7667–7671); `_stop_context` (~7566–7600) passes
  `round_index`/`round_budget_available` to `StopContext` which no longer
  accepts them and reads deleted `config.max_rounds`;
  `_control_decision_context` (~7511) passes `round_index` to `DecisionContext`
  (now takes `episode_id`) and reads deleted `config.max_papers` (now
  `max_source_units`; same stale read near ~6241); `_target_search_candidate`
  (~7636) passes `round_index` into `SearchCandidate.create` (now takes
  `episode_id`); `_finalize` reads undefined `self.rounds` (~7877);
  `_record_run_residual_cost` reads undefined `self._last_round_index` and
  emits `round_index` (~7727); `_save_graph` still writes `round_{n}.graphml`
  (~7696). Earlier-found defects that may or may not be fixed yet — re-verify,
  do not assume: `cfg.queries_per_round` read in `run()`,
  `config.target_deficit_evolutions_per_round` (declared name is
  `target_deficit_max_evolutions`), `_cost_scope(round_index=...)` and
  `zero_cost(round_index=...)` TypeErrors, the reward cost join filtering
  `cost_records` on a `round_index` field v2 records don't carry, round-named
  artifacts `round_<n>.json`.
- **Untracked, adopt as-is**: `method_loop/identities.py`
  (EpisodeRef/UnitRef) and `question_pipeline/checkpoint.py` (280
  lines — already the simple atomic Episode-boundary checkpoint; unwired).
- `question_pipeline/progress_judge.py` is deleted deliberately (the
  source-relevance gate was removed in 4E-c revision 3). Do not restore it.

If resuming after a cut: re-derive state from disk first (git status/HEAD,
separate the team's changes from the pre-existing dirty worktree, confirm no
live `run_question_pipeline` process, run
`tools/check_runtime_invariants.py`). An interrupted dispatch produced no
verdict — nothing from it may be salvaged as if it reported.

## The build phases (serial; do not open N+1 before N passes its gate)

These are the operator's decisions and are AUTHORITATIVE over stale doc text.
Repository documentation still says "a round is a completed strategy" and
mentions `max_rounds`, round offsets, round filenames, and seed-based
continuation — all stale; update each stale statement in the phase that makes
it true (tracker line, `AGENTS.md`'s banner quoting `--max-rounds 5`,
`docs/MEMORY.md`, `TABLE_FILL_*` docs, module docstrings).

### Phase 1 — finish removing rounds (closed PASS)

There is no round concept. Remove structurally, never rename mechanically:
delete `round_index`, `round_offset`, `max_rounds`, `queries_per_round`,
`searches_per_strategy`, round-number continuation/filenames/cost/prompt/reward
attribution/search-memory state/source metadata, "round is a completed
strategy" comments, and loaders inferring continuation from numbered artifacts.
For each count ask: genuine local algorithmic bound (keep, generically named)
or old batch quota (delete). Rarefaction controls continuation. Tracking fields
are only: `run_id`, `episode_id`, `episode_path`, parent Episode identity where
required, `unit_index` local to its parent (never a continuation offset or
global artifact identity). Costs and prompts are owned by Episodes (strategy
proposal → run Episode; provider request → search Episode; page extraction →
that search Episode/unit; post-strategy work → strategy Episode; failed
attempts without a child → parent). Artifact names use Episode identity/path.
Reward/credit attribution uses evidence acceptance + Episode ancestry, never a
round window. Emergency bound stays internal (`episode_unit_safety_cap`,
~1,000,000, reports `bound_hit`, never exposed as CLI).

Reject the phase if it introduces: `searches_per_strategy`, fixed
provider-result quotas as stopping rules, a second acquisition loop, an
alternate stop callback, a causal event graph, or new modes/toggles for
always-required behavior.

**Parameter consolidation (operator-ruled, approved):**
- ONE operator bound: the pulled-unit bound (renamed generically; landed as
  `max_source_units`), default **unbounded** (charter: safety is absent by
  default), reports `bound_hit`. `max_rounds` stays deleted.
- Continuation flags collapse into `--continue` (lands with Phase 3):
  `--seed-tables-dir`, `--seed-sources-dir`, `--seed-frontier-path`,
  `--evidence-corpus-root`, and `--table-spec-path`'s adjacent-observed-spec
  loading are deleted. `--graph-path` survives only as the explicit immutable
  graph-revision input for the GASL peer; `--table-spec-path` survives only as
  the fresh-run contract input.
- `--answer-mode` deleted (derive from `--pipeline-mode`).
- `--task-goal-search-tasks` double duty split (deficit-task breadth vs.
  proposer sample n) — one name per concept; it and `table_gap_search_tasks`
  must be planner string-breadth parameters, never stop rules.
- One evolution cap, one name: `--target-deficit-max-evolutions`; the dangling
  `target_deficit_evolutions_per_round` read is fixed to it.
- `--best-guess-max-tasks` deleted (re-imposes a cell-selection cap the library
  deliberately removed).
- Ordinary params kept: schema/synthesis flags, chunking, extraction
  concurrency/timeout, min/max source length, per-source extraction chars,
  `--scrape-search-results`, `--max-gasl-iterations` (disclosed bound),
  `--model`/`--fast-model`, `--firecrawl-api-key`, best-guess
  batch/timeout/evidence-chars. `table_variables` is a deletion candidate where
  a spec exists.

**Phase 1 review gate** — direct structural verification establishes:
(1) no global round identity remains; (2) no fixed search-count quota replaced
the round quota; (3) Episode is the sole acquisition loop; (4) rarefaction
mandatory at every grain; (5) costs, prompts, memory, rewards, artifacts join
through Episode identity; (6) the emergency cap reports `bound_hit` and cannot
appear as convergence; (7) no event-sourcing/checkpoint rabbit hole; (8)
evidence and incidence semantics preserved. Then report exact changed files and
the verdict before Phase 2. Also run `tools/check_runtime_invariants.py`.
Commit the closed phase (one commit per phase; never commit before the gate).

### Vocabulary rules (operator-ruled, binding on every phase)

1. **No medium-specific words in generic code.** `max_papers` was rejected —
   "suggests we only work with papers." Generic surfaces use the method's own
   vocabulary: episode, grain, unit, source, credit, evidence, incidence,
   verdict, memory, frontier. Rename paper-flavored names doing generic work
   (`paper_count`, `papers_fetched`, `_accepted_papers`, `papers_dir` /
   `fetched_papers/`, `min/max_paper_length`, per-paper extraction chars)
   where a phase touches them; record untouched ones as named debt.
2. **Core components/modules carry ONLY generic vocabulary; surface-specific
   verbiage (search, strategy, paper, page / query, walk, seed) is RESERVED
   for the specific layer implementations of the method.** Grain names remain
   data a surface declares, never concepts the core knows. Checkpoint state
   roles are "frontier"/"memory"/"evidence", not "search frontier". Boundary
   test: if the GASL peer could not reuse a component without its name lying,
   the name is wrong for where it lives. Provider adapters
   (`paper_fetching/firecrawl_client.py`, preserved) keep provider-facing
   names; the generic layer must not inherit them. Deliberate exception:
   `costs.py`'s
   `ObservationKind` names the surfaces it meters, per the charter's "cost has
   one owner" — leave it.

### Phase 2 — event rabbit-hole check

The provider batch request simply belongs to the search Episode; each result is
processed one-by-one as a unit. No pre-unit source-pull Event type, no
causal-parent event graph. `EventContext` was already removed — verify stale
exports/imports are gone. `EventRef`/`UnitContext` remain only where they
connect an accepted piece of evidence to the result unit that produced it;
never expand into operational event sourcing.

### Phase R — binding-file consolidation and head diagrams (closed PASS 2026-08-31; sequenced AFTER Phase 1's gate)

Target concept: **each layer binding leads with an explicit ASCII-art diagram
of the nested episode loops, with that surface's vocabulary labels attached to
each level, in the head comment of the ONE file where that surface's binding
lives; core functions stay in separate generic files.** The design is thereby
consolidated to one place per surface, and the core/layer vocabulary boundary
coincides with the file boundary.

Audit result (2026-08-31, full-read audit; ~two-thirds already in place):
- Core boundary: `method_loop/*`, `rarefaction/*`, `checkpoint.py`, and
  `prompt_log.py` use generic vocabulary. `method_loop` owns the method;
  `rarefaction` owns estimator mathematics only.
- GASL surface (~75%): all walk-binding parts already in `gasl/commands/
  graph_nav.py` (WALK_GRAIN 70–103, `_SeedStream`/`NodeBudget` 131–191,
  `expand` 539–656, `credit_seed` 658–673, `collect` 675–685, one
  `Episode.run` 687–705), but the file also holds three unrelated handlers
  (GRAPHCONNECT/SUBGRAPH/GRAPHPATTERN) and has NO head diagram (nesting only
  as mid-file prose at 74–90).
- Provider surface (~55%): `acquisition.py` (2,283 lines, all binding) heads
  with a small labeled diagram and holds grains/fate table/crediter/sources/
  controller; the wiring half (~1,400 lines) sits in `pipeline.py` — builders
  `_build_run_episode`/`_build_strategy_episode`/`_build_search_episode`/
  `_make_page_leaf` (~1580–1742), extract slot `fetch_extract`/`_acquire_page`
  (~1747–1988), hooks `_on_page`/`_on_search`/`_on_strategy`, source callbacks
  (~2315–2507), record writers (~2581–2670, ~7285+).

The reorganization (no redesign needed; file-boundary moves only):
1. **GASL first** (small, cycle-free, independent of pipeline.py): extract the
   walk binding into one dedicated file (e.g. `gasl/walk_binding.py`); imports
   `method_loop`, the rarefaction estimator contract, `gasl.adapters.base`, and
   stdlib — pass the adapter in.
   `GraphNavHandler._execute_graphwalk` calls the binding. Head the new file
   with the labeled diagram: query ⊃ walk ⊃ seed, unbound rows marked unbound
   (as the existing 74–90 prose states).
2. **Provider consolidation — move INTO `acquisition.py`, never out of it**:
   builders, hooks, leaf-extract, source callbacks, and record writers move
   behind injected collaborators (the injected-callable pattern
   `PageSource`/`StrategyProposer`/`StrategySearches` already use) — e.g. a
   `ProviderBinding` taking crediter, frontier `next_for`/`pending_by_family`,
   `search_fn`, harvester, budget/health/termination, cost-scope, and hook
   delegates. `pipeline.py` keeps only the single `acquisition.run(...)` call
   and the post-strategy body (`_run_post_strategy_body` and everything it
   calls stays — downstream state transformation per charter, not binding);
   `_sample_strategies`/`_proposer_run_view` may stay as injected callables.
   No import cycle: `search.py` imports only `paper_fetching` and `.costs`;
   adding `from .search import SearchTask, SearchOutcome, SearchHarvester` to
   `acquisition.py` is safe; estimator mathematics stay untouched at the bottom.
   Upgrade `acquisition.py`'s head diagram to the full loop shape (verdict /
   continue-stop-switch edges and the page leaf, mirroring charter lines
   43–59).
3. Optional: a generic, surface-unlabeled diagram at `method_loop/episode.py`'s
   head — not required (the concept puts diagrams at layer bindings).
4. Verification per repo rules: a small live run per surface (a table-fill run
   for the provider surface; a GRAPHWALK-bearing GASL run for the graph
   surface) — never diff review, never a test. Direct structural verification
   gates the moves.

### Phase 3 — simple continuation checkpoint

One canonical `checkpoint.json` per run folder, updated atomically after a
completed Episode, containing only: run and lineage identity; last completed
Episode/path; active parent position if needed; explicit next Episode/action;
paths to the JSON/JSONL state files needed to reload (Episode/incidence state,
evidence state, frontier, memory, policy state, table state where applicable).
`--continue <folder>` loads `<folder>/checkpoint.json`; `--continue <file>`
loads that file. No directory scanning, no numbered-artifact inference, no
provider-buffer reconstruction, no resuming inside an Episode — reload the
preceding completed boundary and rerun the unfinished Episode; stable
evidence/finding identities prevent duplicate richness. Audit
`question_pipeline/checkpoint.py` (untracked ~280 lines): keep only the simple
mutable boundary; delete any content-addressed manifest roles, event
provenance, or high-water validation if present. Wire it into the runner and
delete the continuation flags it subsumes (list under Phase 1's parameter
consolidation). Checkpoint state-role names are generic (vocabulary rule 2).

### Phase 4 — Firecrawl and GASL are peer search methods

Peer search types, each composable as Episodes with their own rarefaction
histories. GASL is not a post-Firecrawl stage; graph enrichment is not
automatically part of acquisition; table compilation is not an Episode child.
First live experiment: Firecrawl Episodes only, no GASL, no graph required, no
automatic graph mutation — an experiment-composition restriction, never a
method restriction. Graph additions are proposed after a run as a reviewable
table; never auto-merged; eventually render a copy-paste CLI merge command as
inert text for the human.

### Phase 5 — table input-state snapshot

Table compilation is a downstream state transformation. Every compiled table
records the exact state used: evidence registry/version or snapshot identity,
accepted source state, table-spec identity/version, optional immutable graph
revision, Episode/run lineage identity. Published time supports an explicit
unknown value. Tables are never Episode children.

## Standing method semantics (preserve; the charter states them fully)

Nested Episode tree (run ⊃ strategy ⊃ search ⊃ result unit on the provider
surface), one generic method per Episode: source.next → acquire one unit →
extract → accept evidence → unique incidence by declared channel/column →
update rarefaction → numerical controller verdict → continue/stop. Each grain
has its own rarefaction history and controller; rarefaction is mandatory (no
substitute stop callback); incidence is per declared channel; repeats raise
recurrence, never unique richness; a child passes distinct accepted identities
+ typed incidence result up, parent counts each once; Chao2 is the current
internal estimator behind the generic role-based boundary (observed/rarefied/
expected/remaining + numeric uncertainty/status); the estimator is not the
controller; models do string work only (query generation, extraction, semantic
comparison, evidence-supported best guessing) and never decide from curves or
counts; provider batches are processed one-by-one with no per-query or
per-strategy quota.

Evidence acceptance (preserve the reviewed work): acceptance precedes
incidence; direct results keep source/document-version/chunk/exact-span
traceability; stable finding identity is separate from occurrence identity;
row completion credits once at the first complete accepted state; parent
evidence state is immutable, children use local overlays. Best guesses are
mandatory real columns (never a mode), each retaining stable criterion/cell
identity, derived value, derivation rule/basis, supporting assertion IDs,
source/document/version/chunk/span IDs; a best guess never masquerades as a
directly reported value.

Memory/strategy learning: each nested level holds memory for that Episode's
lifetime (last child outcome in detail, compressed earlier-children history,
per-channel incidence estimates, what yielded new unique evidence vs. repeats,
remaining opportunity, overlaps/deficits); a child's private memory ends with
it; the parent keeps what it needs to choose next. Memory steers string
generation; numbers still decide continuation. The memory template is one
generic modular interface (vocabulary rule 2).

## First foundational live experiment (last; after all structural gates)

The real earthquake table-fill on live Firecrawl + real LLM extraction.
Register predictions and obtain `experiment-steward` approval BEFORE any paid
call including a credential probe. Direct transport with `LLM_API_KEY` in
`.env` (per AGENTS.md); `FIRECRAWL_API_KEY` required; one-token completion
check before a long run; verify no `run_question_pipeline` process is live;
run exactly one process to its own numerical or typed end. No fake results, no
replay, no synthetic substitute, no automated "experimental analyzer". Let
rarefaction decide saturation; the emergency bound only catches nontermination;
a bound cut reports `bound_hit`, never convergence; buffered results left
after a verdict get no page-level LLM work. Iterate on real code failures
until the live run works; report provider/credential failures exactly. The
registered checks from the 2026-08-28 revision still apply: (1) provider batch
recorded while results process one-at-a-time; (2) every processed unit
traverses real extraction + durable evidence acceptance with no relevance
gate; (3) accepted incidence identities resolve through persisted
source-version/chunk/span/assertion/acceptance records; (4) raw candidates and
rejected assertions mint no incidence; (5) completed-row incidence only on the
first transition to all required cells accepted; (6) the verdict recomputes
from emitted estimates + controller arithmetic; (7) buffered remainder after a
verdict has no LLM work; (8) a run-wide bound cut reports `bound_hit`.

## Repository safety

Preserve unless directly required: `paper_fetching/firecrawl_client.py`,
`deliverables/`, the reviewed rarefaction estimator mathematics and generic
method/controller work,
`question_pipeline/evidence_registry.py`, mandatory best-guess behavior, and
all unrelated dirty-worktree changes. `progress_judge.py` stays deleted. Do
not commit until the current structural phase passes review; run no paid
experiment before the live-experiment phase. Orchestration protocol: a fresh
`build-orchestrator` runs the team one phase at a time; phase agents never
invoke their own stewards or edit the tracker; the orchestrator verifies
claims itself, writes tracker rows, commits per closed phase; three revision
cycles max on implementation defects; any single steward non-PASS is non-PASS.

## Final report (when every phase row is Confirmed/Diagnosed/Blocked)

Each phase's state; exact changed files per phase; every dispatched steward
verdict quoted; the live experiment's registered predictions and outcomes;
invalid runs recorded and removed; teardown completeness; the commit range.
