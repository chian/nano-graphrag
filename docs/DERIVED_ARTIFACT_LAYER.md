# Derived Artifact Layer and Promotion Policy

## Purpose

This note proposes a third data layer for nano-graphrag:

1. base graph
2. query-time GASL state/context
3. persistent derived artifacts

The goal is to let GASL reorganize graph evidence for future reuse without
polluting the base graph with query-shaped or model-shaped artifacts.

The design is intentionally narrower than "save a new graph." Many useful
reusable products are not graph-shaped:

- node or edge annotations
- overlay edges
- materialized aggregate tables
- memoized subgraphs
- reusable transform outputs

The derived layer is where those products live.

## Why This Layer Exists

GASL is useful precisely because:

- domain experts will not hand-author a perfect schema for every future query
- LLM planning will not reliably choose the best restructuring on the first try
- some queries need temporary reorganization to become answerable

But the system also needs a controlled way to decide when a restructuring should
stay query-local and when it should become reusable system memory.

## Design Principle

Default to an overlay registry, not base-graph mutation.

The codebase already supports adding properties to nodes and relationships, but
that should be a late-stage publication step, not the default persistence
target. Writing directly into the base graph too early creates rollback and
invalidation problems and turns model errors into apparent facts.

## Artifact States

Every nontrivial transformation candidate moves through a state machine instead
of a single yes/no persistence decision.

### 1. Scratch

- lifetime: single query
- storage: current GASL state/context
- visibility: current run only

Examples:

- one-off filters
- query-specific joins
- prompt-shaped summaries

### 2. Memoized

- lifetime: reusable for exact-match replay
- storage: persistent registry
- visibility: planner may reuse only for exact signature matches

This is the first automatic persistence state.

### 3. Overlay Artifact

- lifetime: reusable across related future queries
- storage: persistent registry
- visibility: planner can actively consult it as a reusable resource

Examples:

- stable derived fields
- repeated aggregate tables
- cached subgraphs used by a query family

### 4. Published Feature

- lifetime: long-term
- storage: may be published back to graph properties or graph-adjacent indexes
- visibility: part of the ordinary data model

This state should be rare and gated.

## Artifact Types

The system should type artifacts by transformation semantics, not by which GASL
command happened to produce them.

Suggested first taxonomy:

- `semantic_filter`
- `field_derivation`
- `classification`
- `cross_node_synthesis`
- `aggregate_table`
- `overlay_edge`
- `subgraph_cache`
- `plan_template`

This is important because different artifact types deserve different persistence
rules and invalidation logic.

## PROCESS Strategy

The current GASL surface syntax can keep a single `PROCESS` command while the
executor internally subtypes it after planning and before execution.

Suggested runtime subtypes:

- `semantic_filter`
- `field_derivation`
- `classification`
- `cross_node_synthesis`

This keeps the language stable while letting the executor pick better models,
sampling strategies, and persistence rules per subtype.

## Candidate Selection and Probe-Then-Widen

`PROCESS` should not be the first place where coarse search happens. Instead,
the executor should build a bounded candidate pool before the expensive LLM
step.

Suggested selector stack:

1. schema/entity exact matching
2. field-weighted lexical search over:
   - `id`
   - `entity_type`
   - `entity_name`
   - `alternative_names`
   - `description`
3. graph-neighborhood or graphwalk constraints
4. optional vector similarity candidates

For large candidate sets, use a probe-then-widen loop:

1. build a probe set of about 20 items
2. run `PROCESS` on the probe set
3. use the outputs to refine either:
   - the selector weights
   - the instruction
   - both
4. widen the candidate pool only when the probe indicates the process is
   informative

### Random sampler for probe bias

A naive top-20 probe will be biased toward one retrieval mode. The probe set
should therefore be stratified:

- top lexical matches
- top vector matches (if available)
- graph-central or representative items
- a small random tail sample

The random tail should be deterministic per query signature so benchmark runs
are reproducible while still resisting single-mode bias.

## Promotion Inputs

Each candidate artifact should be scored on:

- `grounding`: how directly it is tied to explicit graph evidence
- `stability`: how consistent it is across reruns
- `reuse`: how often similar future queries trigger the same transform
- `utility`: whether it improves answer quality, not only latency
- `cost`: how expensive it is to recompute
- `invalidation_risk`: how likely upstream changes make it stale

## Proposed Promotion Policy

### Automatic promotion to Memoized

Promote from `scratch` to `memoized` when all are true:

- the artifact is source-grounded
- the transform is deterministic enough or bounded enough
- recompute cost is nontrivial
- the signature is stable enough to identify exact reuse safely

### Automatic promotion to Overlay Artifact

Promote from `memoized` to `overlay_artifact` when all are true:

- multiple distinct queries or query clusters reuse it
- reruns are stable across time and model versions
- quality improvement is measurable
- invalidation dependencies are explicit

### Human review before Published Feature

Require review before publishing to node/edge properties or durable graph
indexes when any are true:

- the artifact changes global interpretation of entities or edges
- the planner begins to depend on it broadly
- the artifact is not strongly source-grounded
- rollback is expensive

This is the stage where an admin inbox or PR-like flow makes sense.

## Persistence Target by Default

Default persistence target:

- overlay registry

Do not default to:

- writing new node properties
- writing new edge properties
- mutating graph topology

Base graph mutation should be opt-in and occur only for `published_feature`
artifacts.

## Signature Model

Every persistent artifact should have a stable signature. Suggested fields:

- `artifact_type`
- `graph_id`
- `graph_version`
- `transform_signature`
- `source_fields`
- `source_entity_types`
- `source_relation_types`
- `model_family`
- `prompt_family`
- `code_version`

The point is not exact reproducibility of every token. The point is safe reuse
and safe invalidation.

## Invalidation

Persistent artifacts must carry dependency metadata. At minimum:

- graph version / build id
- model family
- prompt family
- code version for the producing transform

The system should never silently reuse an artifact whose dependencies do not
match the current environment.

## Planner Behavior

The planner should not decide publication. It may propose or consume artifacts,
but publication is a policy decision.

Planner behaviors to allow:

- exact reuse of memoized artifacts
- use of overlay artifacts as additional available fields/resources
- fallback to scratch execution when a reusable artifact is stale or missing

Planner behaviors to avoid:

- silently treating prior LLM outputs as facts
- assuming a cached artifact outranks direct graph evidence

## How This Fits the Current Repo

### Existing places that already align

- query-time state/context:
  - [gasl/executor.py](/home/chia/repos/nano-graphrag/gasl/executor.py:370)
  - [gasl/commands/process.py](/home/chia/repos/nano-graphrag/gasl/commands/process.py:159)
- graph-version-aware processing:
  - `gasl/graph_versioning.py`
- graph mutation capability:
  - add/update/create commands in `gasl/commands/`

### Suggested implementation hooks

1. Instrument transformations
- log every nontrivial `PROCESS`, `AGGREGATE`, `GRAPHWALK`, `JOIN`, and
  `SELECT` result as an artifact candidate

2. Add an artifact registry
- a sidecar store keyed by artifact signature

3. Add a consolidation job
- cluster similar candidates
- compute promotion metrics
- move `scratch -> memoized -> overlay_artifact`

4. Add planner read path
- expose valid overlay artifacts as additional reusable resources

5. Add `PROCESS` routing
- subtype `PROCESS` internally
- route `semantic_filter` and `field_derivation` to a smaller model first
- escalate `classification` and `cross_node_synthesis` only when needed

6. Add admin review path
- only for publication of high-impact features

## Recommended MVP

Implement in this order:

1. candidate logging
2. exact-signature memoization
3. offline consolidation and scoring
4. planner reuse of memoized artifacts
5. overlay artifact registry
6. optional admin review inbox

This sequence keeps the first version narrow and measurable.

## What Not To Do

- do not persist every query-time view
- do not write model-shaped fields back to the base graph by default
- do not let warm caches contaminate benchmark comparisons
- do not treat persistent artifacts as ground truth without provenance

## Evaluation

Benchmarks should separate:

- cold performance with no artifact reuse
- warm performance with memoized/overlay artifacts enabled

Both quality and latency should be tracked. Otherwise the derived layer will
look better than it is.

## Open Questions

- what minimal artifact metadata is enough for safe reuse?
- which artifact types should be planner-visible first?
- when should the system prefer an overlay artifact over a fresh GASL run?
- what level of human review is worth the cost for publishing features?
