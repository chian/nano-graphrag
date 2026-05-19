# Policy Lab Design

This folder is intentionally **design-only** for now.

The main design constraint is:

**`policy_lab` must not infer the agent’s control shape from prompt names
or prompt text. The main GASL agent must export its own shape in a
machine-readable form, and `policy_lab` must consume that export.**

The goal is to learn a **compositional prompt policy** for GASL without
mixing this work into the current GEPA prompt-optimization path. The
policy is not supposed to imitate a closed model’s full reasoning. It is
supposed to learn how to **assemble prompts on the fly from known prompt
chunks** and to do so based on the current GASL execution state.

## The genericity problem

If `policy_lab` keys on:

- prompt names like `plan_generation`
- regexes over prompt text
- one-off assumptions about slots

then any change in the main agent will silently break the policy lab or,
worse, corrupt training data.

So the correct design is:

1. the **main GASL runtime** exports a **PromptSurfaceManifest**
2. the **main GASL runtime** exports **DecisionContext** records
3. `policy_lab` uses only those exported objects

That way, if the agentic interface changes, the lab still sees the new
shape from the source of truth.

## Core exported contracts

### 1. `PromptSurfaceManifest`

This is a versioned description of the agent’s current prompt surfaces,
slots, chunk catalogs, and verifier / replay adapters.

Example shape:

```json
{
  "manifest_version": "1",
  "agent_name": "gasl",
  "surfaces": [
    {
      "surface_id": "planner",
      "prompt_name": "plan_generation",
      "skeleton_id": "planner_v3",
      "slot_schema": [
        {"slot_id": "retrieval", "cardinality": 1},
        {"slot_id": "grain", "cardinality": 1},
        {"slot_id": "variable_flow", "cardinality": 1}
      ],
      "chunk_catalog_ref": "prompts/catalogs/planner.json",
      "parser_id": "json_plan_v1",
      "verifier_id": "gasl_plan_verifier_v1",
      "replay_adapter_id": "gasl_plan_replay_v1"
    }
  ]
}
```

### 2. `DecisionContext`

This is the exact state seen at a prompt call, plus the resulting output
and verifier reward.

Example shape:

```json
{
  "decision_id": "run123:q007:iter2:planner",
  "surface_id": "planner",
  "manifest_version": "1",
  "state_schema_version": "5",
  "state": {
    "query": "...",
    "iteration": 2,
    "recent_errors": ["variable_not_found"],
    "artifacts": [...],
    "contracts": [...]
  },
  "chosen_chunks": {
    "retrieval": "retrieval_guard_v2",
    "grain": "preserve_multiplicity_v1",
    "variable_flow": "exact_names_v1"
  },
  "output": {...},
  "verifier": {
    "reward": 0.74,
    "labels": {...}
  }
}
```

## Where this maps onto the current GASL code

The current code already has most of the raw ingredients:

- prompt retrieval:
  - `nano_graphrag/prompt_system.py`
  - `gasl/llm/argo_bridge.py`
- prompt observations:
  - `gasl/prompt_observations.py`
- produced artifacts / state history:
  - `gasl/state.py`
  - `gasl/executor.py`

What is missing is not data. What is missing is the **explicit exported
shape**.

### Current-to-target mapping

Current:
- `prompt_name`
- `prompt_hash`
- `prompt_text`
- `metadata`
- `produced_artifacts`

Target:
- `PromptSurfaceManifest`
- `DecisionContext`

That means the next implementation should not add policy logic first. It
should add **shape export** first.

## Problem framing

### What is being learned

For each prompt surface exported in the manifest, the runtime prompt
should be built from:

1. a fixed **prompt skeleton**
2. several **named slots**
3. a known **chunk catalog** per slot

Examples of current prompt surfaces in GASL are:

- `plan_generation`
- `plan_repair`
- `process_repair`
- `aggregate_repair`

But `policy_lab` should not hard-code those names. It should enumerate
whatever the current manifest says exists.

Examples of slots:

### `plan_generation`
- retrieval strategy
- variable-flow guard
- grain / multiplicity guard
- path-semantics guard
- repair-constraint guard

### `plan_repair`
- patch-scope
- contract-priority
- replan-threshold

### `aggregate_repair`
- substrate rule
- grouping-field rule
- weighting rule

The policy should choose **one chunk per slot**, then the final runtime
prompt is composed as:

`prompt = skeleton + slot_1_chunk + slot_2_chunk + ...`

### What is *not* being learned

- no finetuning of the closed model
- no attempt to reproduce the full reasoning of GPT-5
- no single giant multiclass label like “pick prompt A”

## Why this is separate from GEPA

Current GEPA work optimizes prompt files directly against replay/verifier
objectives. This policy lab is a different layer:

- GEPA optimizes prompt text
- policy lab learns **how to compose prompt chunks dynamically**

That separation matters. If both are changed at once, attribution becomes
muddy and the experiments are harder to interpret.

## Interface with a closed model

The closed model stays a **black box**.

We do not need gradients or internal access. The interface is:

1. choose a prompt chunk combination
2. call the closed model through the API
3. replay / verify the resulting step or episode
4. assign reward to the chunk combination

So the learned object is the **controller outside the model**, not the
model itself.

## Data model

### Decision state

A decision state should capture enough structure that the controller can
react to **recent outputs**, not just static prompt IDs.

Required fields:

- `surface`
- `query_family`
- `graph_id`
- `iteration`
- `recent_command_types`
- `recent_statuses`
- `recent_error_signatures`
- `produced_artifacts`
- `contract_flags`
- `path_semantics_flags`
- `aggregate_substrate_flags`
- `latency_bucket`
- `last_model_output_summary`

Important points:

1. the state should be exported by the runtime as a `DecisionContext`
2. the policy should **not** train on raw prompt text alone
3. the policy should train on a **structured state representation**
   extracted from the GASL run

### Chunk catalog

Each slot has a catalog entry:

- `slot_name`
- `chunk_id`
- `chunk_text`
- `surface`
- optional metadata such as:
  - preferred contexts
  - incompatible contexts
  - version

### Replay record

Each replayed decision should produce:

- `decision_id`
- `surface`
- `state`
- `chosen_chunks_by_slot`
- `full_prompt_text`
- `model_output`
- `verifier_labels`
- `reward`

## Reward and label generation

The policy should not be trained on hand-written step labels alone.

Instead:

1. extract a decision state from a real GASL trajectory
2. sample multiple chunk combinations for that same state
3. run those combinations against the closed model
4. replay / verify the resulting run or sub-run
5. assign reward to each combination

This is how step-level supervision is created.

### Reward source

Reward should come from the verifier / replay system, not from a vague
LLM preference judgment.

Examples of reward components:

- valid plan shape
- variable-flow validity
- aggregate substrate validity
- path-semantics validity
- fewer command errors
- fewer empty-result loops
- better convergence
- lower latency blow-up

Use one scalar reward for training, but persist the underlying labels so
the scoring function can be reweighted later without replaying everything.

## Model design

### Recommended controller

Use an **embedding-based multi-head scorer**, not a flat multiclass
classifier over chunk IDs.

Reason:

- the controller must react to changing outputs
- new chunks will be added later
- we want old training to partially transfer to new chunk options

### State / chunk embedding model

Recommended design:

1. compute a **state embedding** from the structured GASL state
2. compute a **chunk embedding** for each chunk text
3. learn a scorer:

`score(state_embed, chunk_embed, slot_embed) -> utility`

At runtime:

- for each slot
- score every candidate chunk
- choose the highest-scoring chunk
- assemble the final prompt

This is better than a classifier over chunk IDs because it can generalize
to unseen chunk texts.

### Parameter scale

If embeddings are frozen and the scorer is small, a first useful model is
roughly:

- state projection: `1536 -> 256`
- chunk projection: `1536 -> 256`
- fusion MLP over `[state, chunk, state*chunk, |state-chunk|, slot]`

Order of magnitude:

- about **0.9M trainable parameters**

### Replay budget

For a first viable planner-surface model:

- roughly **10,000 scored replays**

That is enough to learn a ranking function over chunk choices without
pretending the controller is solving the full GASL problem.

## Training sequence

### Phase 1 — instrumentation

Do not write runtime policy code first.

Implement:

1. `PromptSurfaceManifest` export from the current prompt system
2. `DecisionContext` export from the current executor / prompt logger
3. chunk catalogs per manifest surface
4. prompt skeletons with named slots
5. replay harness that can branch from a saved state
6. verifier-based reward recording

### Phase 2 — offline replay dataset

For each selected decision state:

1. sample chunk combinations
2. execute closed-model API call
3. replay and verify
4. save reward record

This phase creates the actual training data.

### Phase 3 — fit specialized policies

Train **separate policies per prompt surface** first.

Do not start with one policy for all surfaces.

Reason:

- action spaces differ
- state distributions differ
- reward horizons differ
- data imbalance will be severe

So the first policies should be:

- planner policy
- plan-repair policy
- process-repair policy
- aggregate-repair policy

### Phase 4 — held-out replay evaluation

Promotion rule:

Do not wire the policy into runtime unless it beats the current direct
closed-model controller on held-out replay.

That means:

- compare policy-composed prompts vs direct baseline prompts
- same replay harness
- same verifier
- held-out states only

If the policy does not win, keep it offline.

## Runtime integration plan

Only after the offline policy is validated:

1. load the exported manifest at startup
2. build the exported decision context at each prompt surface
3. score chunks for each slot
4. compose the prompt
5. persist chosen chunks and scores into prompt observations

The runtime should also keep a **confidence threshold**:

- high-confidence policy output -> use the policy
- otherwise -> use the baseline prompt composition

That keeps the system robust during rollout.

## Implementation notes

- keep this work separate from `tools/prompt_lab/`
- keep all dataset creation append-only
- store raw replay results and derived rewards separately
- version manifests explicitly
- version chunk catalogs explicitly
- version skeletons explicitly
- snapshot the manifest into each run directory
- never discard the baseline prompt path

## Minimal first deliverable

The first implementation should not be “a full policy”.

It should be:

1. manifest export for one surface (`plan_generation`)
2. decision-context export for that surface
3. prompt skeleton with slot markers
4. chunk catalog for that surface
5. replay sampler
6. verifier reward writer
7. one embedding-based scorer trained offline
8. held-out replay comparison against baseline

Only after that should additional surfaces be added.
