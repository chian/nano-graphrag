# Table-Fill Path Selection and Policy Learning

## Technical Gap

The table-fill continuation loop can now do the right high-level sequence:

1. carry seed tables and source memory forward
2. search for missing row families
3. ingest newly accepted sources into the graph
4. scope GASL to newly evidenced graph neighborhoods
5. seed GASL with `round_source_nodes`
6. traverse paths
7. preserve every candidate row through `PROJECT`, `PROCESS`, `COLLAPSE`, and
   final table materialization

The remaining gap is between steps 6 and 7.

`GRAPHWALK` is currently bounded by relationship names, depth, source caps, and
edge caps. It is not yet scoring whether a traversed path is a semantically
good route from the current source evidence to a missing table row. Once a path
survives the traversal, the row-preserving table machinery treats it as a row
that must be retained, repaired, collapsed, or explicitly marked as a gap.

That behavior is correct for row preservation but too weak for candidate
selection. The expensive LLM table passes should receive high-recall candidate
sets, not every weak route through broad graph context.

## Observed Outcome

| outcome | what it means | interpretation |
| --- | --- | --- |
| Source-seeded graph walks now produce rows from newly ingested sources | Continuation rounds can reach new evidence instead of only revisiting the old graph | In scope for source seeding; this part is working |
| Long row-preserving table passes complete without losing omitted rows | Candidate rows can survive LLM batching, retry, collapse, and final materialization | In scope for row identity; this part is working |
| Many final rows are context-only or carry no hard value | The traversal admits generic context nodes and source-neighborhood rows that are not direct measurements or comparisons | Out of scope for row preservation; this is a path-selection defect |
| Some rows report conflicting anchors, such as one place in the edge source and another in the neighbor label | Depth-limited walks can cross through shared source, location, method, or context hubs and land on a row from a different anchor than the one being filled | In scope for path scoring; the route should be penalized before `PROCESS` |
| The LLM correctly emits `evidence_gap` for many weak candidates | The finalizer can recognize missing fields after the fact | Out of scope for finalization; using the LLM as the first line of path filtering burns calls and creates noisy tables |

## Failure Mode

The current graph scope is source-aware, but the path expansion is not
anchor-aware.

For example, a valid source-neighborhood graph can contain all of these
structures:

- direct measurement nodes
- context nodes
- method nodes
- source/document nodes
- chunk nodes
- broad geographic or categorical nodes

A depth-3 or depth-4 walk can move from a useful newly sourced measurement into
a broad connector, then into a different estimate that only shares a paper,
method, or coarse context. Bidirectional traversal increases recall, but it
also makes these bridge routes easier to traverse.

The resulting candidate row is not malformed:

- it has a real neighbor node
- it has a real edge
- it has real `source_refs` / `source_chunks`
- it has a deterministic `src_id`, `tgt_id`, `edge_src_id`, and `edge_tgt_id`

The issue is that the row is weak evidence for the target slot being filled.
The engine currently discovers that only after an LLM has normalized the row and
written an `evidence_gap` or anchor-conflict explanation.

## What Fixing Path Selection Would Do

Fixing this local symptom should add a generic path-quality gate between graph
traversal and row-preserving extraction.

It would not delete partial rows that express real missing evidence. It would
filter or demote paths whose graph route is too weak to support the table slot
in the first place.

Expected effects:

- fewer low-value rows entering expensive `PROCESS` batches
- higher new-source to new-row yield
- fewer final rows whose only useful content is `evidence_gap`
- fewer rows where two anchors conflict because the walk crossed a hub
- better deficit search memory, because failures would distinguish:
  - no source found
  - source accepted but no graph delta
  - graph delta found but no high-quality path
  - high-quality path found but no target slot value
- better stop criteria, because remaining gaps would more often reflect missing
  literature instead of traversal noise
- more useful best-guess plots, because numeric candidates would come from
  stronger row contexts

The fix would not make a table complete by itself. It only improves one local
decision: which graph rows are worth sending to table formation. Search still
has to find the right sources, and the final table LLM still has to normalize
source-local wording into row fields without inventing values.

That means path selection should be treated as one policy surface inside a
larger learning loop, not as a hand-built endpoint.

## Generic Scoring Shape

Path scoring should stay schema-agnostic. It should derive target slots and
anchors from the current goal state, table contracts, and candidate rows rather
than from query-specific literals.

Useful generic features:

| feature | signal |
| --- | --- |
| `source_overlap` | Prefer edges and terminal nodes evidenced by the current accepted source or the same source chunk |
| `path_depth` | Penalize longer paths unless every hop preserves an anchor |
| `relation_sequence` | Prefer relation types that the goal state has found productive for the target table |
| `terminal_type` | Prefer endpoint entity types that match target-slot examples or prior productive rows |
| `anchor_consistency` | Penalize paths that start from one anchor but end on an incompatible anchor |
| `hub_degree` | Penalize high-degree nodes that connect many unrelated rows |
| `generic_context_count` | Penalize routes that spend most hops on method/source/context nodes rather than row-like evidence nodes |
| `slot_fill_potential` | Prefer rows with fields or descriptions likely to fill currently missing target slots |
| `prior_operator_yield` | Prefer path shapes produced by search operators that previously added rows |

The output should be stored with every candidate:

```json
{
  "path_score": 0.87,
  "path_score_features": {
    "source_overlap": 1.0,
    "path_depth": 1,
    "anchor_consistency": 1.0,
    "hub_penalty": 0.0
  },
  "path_selection_reason": "direct current-source edge with matching anchor"
}
```

Rows that are kept only for recall should carry the reason too:

```json
{
  "path_score": 0.32,
  "path_selection_reason": "weak route through high-degree context node"
}
```

That gives later `PROCESS`, `COLLAPSE`, and search-memory stages a state field
to learn from instead of inferring path quality from free-text gaps.

## Longer Project: Learn the Table-Fill Policy

The round-level problem is a sequential decision problem over expensive,
partially observed actions. Hand-written operators are useful as action
primitives, but the system should learn which primitive to use from prior
traces.

One episode is a table-fill continuation round. Its trace already contains most
of the state and reward signal needed for offline learning:

1. current tables and missing row families
2. universe and stop-criteria estimates
3. pending search frontier
4. generated search tasks
5. Firecrawl hits, duplicates, scrape failures, and accepted sources
6. graph node/edge deltas from ingestion
7. GASL planner actions
8. graph-walk candidate rows
9. row-preserving `PROCESS` outputs
10. final table deltas
11. derived numeric candidates
12. token, Firecrawl, and wall-clock cost

### Action Space

| policy surface | actions to learn |
| --- | --- |
| Deficit selection | which missing table family or anchor to attack next |
| Search operation | catalog search, target-deficit search, context-grain expansion, temporal-window expansion, source-family shift, terminology shift |
| Query construction | which known anchors, failed terms, productive source terms, and context tags to include |
| Source acceptance | whether a search hit is worth scraping, reducing, and ingesting |
| Graph scope | full graph, current-source graph, source hops, source seed count |
| Path selection | which path shapes are likely enough to become rows |
| Row formation | which table view to materialize and which normalization strategy to use |
| Retry and repair | retry unchanged, narrow the instruction, split the batch, or accept explicit fallback rows |
| Stop/continue | spend another round or declare the remaining gaps unsupported under the current budget |

### Reward Signals

The reward should not be "did the final prose answer look good". Table fill has
direct intermediate rewards:

| signal | sign |
| --- | --- |
| new final rows with source refs | positive |
| new hard numeric candidates | positive |
| rows that fill previously missing target slots | positive |
| novel accepted sources | positive |
| stop-criteria progress | positive |
| weak graph paths | negative |
| anchor-conflict rows | negative |
| duplicate URLs | negative |
| accepted source with no graph delta | negative |
| graph delta with no final-row delta | negative |
| LLM tokens and Firecrawl calls | negative cost |

These rewards let the system learn search and traversal policies without
waiting for a human to inspect a natural-language summary.

### Preference Optimization

The first learning layer can be offline preference optimization over traces:

1. convert each round into a compact trajectory record
2. compute deterministic metrics for novelty, table delta, gap reduction, weak
   paths, and cost
3. use a judge only for ambiguous trajectory pairs
4. train a policy or reranker to prefer the better next action from the same
   state
5. replay held-out traces to check whether the learned action would have picked
   a historically better branch

Good comparison units:

- two search tasks for the same deficit
- two source hits for the same query
- two graph scopes for the same source set
- two path candidates for the same target slot
- two table-normalization instructions for the same collapsed group
- stop vs continue for the same frontier and coverage state

### Why Path Scoring Still Matters

A deterministic path scorer is still useful, but mainly as instrumentation and
as a cheap baseline policy.

It gives the trajectory learner explicit features:

- which graph routes were weak
- why they were weak
- whether weak routes were still eventually useful
- which relation sequences produced final-row deltas
- which source families produced direct table evidence

The long-term system can then learn the weights, override a bad deterministic
cutoff, or route low-confidence paths to exploration batches.

### Project Stages

1. Instrument every decision
2. Add deterministic path and source outcome scoring
3. Build trajectory records from real continuation rounds
4. Add pairwise trace comparison and deterministic preference labels
5. Train offline rerankers for search tasks, source hits, and path candidates
6. Run off-policy evaluation against historical traces
7. Add a cautious online bandit for low-risk choices
8. Let learned policies propose search and traversal actions under a budget
9. Keep human review for stop-rule failures and metric regressions

This should be budget-aware from the start. A policy that finds ten more rows
after spending another thousand low-value searches is worse than a policy that
learns it is looking in an exhausted branch.

## Local Implementation Plan

### 1. Add path feature extraction

Build a small feature extractor over `walk_rows`.

Inputs:

- row fields from `GRAPHWALK`
- edge provenance fields
- graph degree metadata
- current source IDs
- target table contract, if present

Outputs:

- `path_score_features`
- `path_score`
- `path_selection_reason`
- optional `path_exclusion_reason`

The first version can be deterministic. The features should be explicit enough
that later LLM or learned policies can tune weights without changing the row
schema.

### 2. Add a score/filter command or PROCESS prefilter

There are two reasonable surfaces:

- a dedicated deterministic command, such as `SCORE_PATHS`
- an internal prefilter in `GRAPHWALK` when a contract says downstream rows are
  table candidates

The dedicated command is easier to inspect and benchmark:

```gasl
SCORE_PATHS seeded_measure_paths FOR target_table AS scored_measure_paths
```

Then the planner can do:

```gasl
PROJECT scored_measure_paths GRAIN path FIELDS ... PRESERVE_MULTIPLICITY AS candidates
```

### 3. Thread scores into table-fill memory

Every accepted source should produce one of these outcomes per target family:

- no graph evidence
- graph evidence but all paths were low-score
- high-score paths but no target-slot rows
- target-slot rows but no new final-table delta
- new final-table rows

That outcome is more useful than a generic "no table delta" because it tells the
next search round whether to change search terms, graph schema, traversal, or
normalization.

### 4. Route future searches from scored deficits

The deficit phase should generate different operations from the scored outcome:

| outcome | next action |
| --- | --- |
| no graph evidence | search broader source families |
| all paths low-score | search for sources with more direct terminology for the same missing slot |
| no target-slot rows | search narrower anchor examples or alternate target terms |
| no final-table delta | keep the source context and mutate the table-normalization strategy |

### 5. Validate on real add-on rounds

The acceptance test should be a full real table-fill continuation, not a
synthetic unit test.

Track:

- accepted sources
- new graph nodes/edges
- candidate rows before and after scoring
- candidates per source
- LLM batches per final table
- final rows per accepted source
- numeric candidates per accepted source
- weak-path row fraction
- rows with anchor-conflict language

## Non-Goals

- Do not special-case a scientific field or metric name.
- Do not make hard rows more "complete" by guessing values.
- Do not drop source-supported partial rows just because some fields are null.
- Do not replace deficit search. Better path scoring only improves graph-local
  selection after new sources have been ingested.
