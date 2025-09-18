## Graph Analysis & State Language (GASL) - Design Document

### Goals

- Provide a compact, declarative language for LLM-driven graph analysis and stateful accumulation.
- Use a NetworkX adapter as the computation engine; GASL expresses intent, not low-level code.
- Modular components; minimal coupling to `analytical_retriever.py`.
- Support iterative planning: propose, execute, evaluate, update state.

### High-Level Architecture

- GASL Parser: converts command strings into typed AST nodes.
- GASL Executor: dispatches AST nodes to graph adapters and state operations, maintains context/state, and records history.
- Graph Adapter: interface to the graph backend.
- Processing Engine: LLM-assisted transformations over intermediate data.
- State Store: persistent, queryable accumulation store (file-backed JSON by default).
- Prompting: small, focused prompts to guide LLM for PROCESS/ANALYZE steps.

### Proposed Package Layout

```
gasl/
  __init__.py
  types.py                 # Typed dicts, enums, dataclasses for AST and results
  errors.py                # Exception types
  parser.py                # GASLParser
  ast.py                   # AST node classes
  executor.py              # GASLExecutor (orchestrator)
  dispatcher.py            # CommandDispatcher (routes AST → op)
  context.py               # ContextStore for ephemeral variables
  state.py                 # StateStore + JSONFileStateBackend
  conditions.py            # Condition parsing/evaluation (WHERE, IF)
  commands/
    __init__.py
    find.py                # FIND implementation
    process.py             # PROCESS implementation (LLM-assisted)
    update.py              # UPDATE implementation
    analyze.py             # ANALYZE implementation (LLM-assisted)
    branch.py              # BRANCH implementation
  adapters/
    __init__.py
    base.py                # GraphAdapter protocol
    networkx_adapter.py    # NetworkX implementation
    neo4j_adapter.py       # (future) Neo4j implementation
  llm/
    __init__.py
    client.py              # LLMClient interface
    argo_bridge.py         # ArgoBridge client wrapper (uses existing argo_bridge_llm)
    prompting.py           # Prompt builders for PROCESS/ANALYZE
  serialization.py         # Safe dumps of large results for logs/prompts
  utils.py                 # Shared utilities
docs/
  GASL_DESIGN.md          # This document
```

### Core Data Structures

- CommandString: str (single GASL command line)
- VariableName: str (e.g., `authors`, `coauthor_paths`)
- ResultValue: list|dict|scalar
- ContextStore: ephemeral variable namespace for command outputs
- StateStore: persistent accumulation with merge/replace semantics
- ExecutionRecord: {command, summary, errors, metrics}

### State Model and Data Format

The StateStore persists accumulated results and metadata in a file-backed JSON structure.

**Note**: The state object begins as a minimal container. The LLM dynamically defines the nested structure of the `variables` section at the start of its analysis using `DECLARE` commands.

#### State Evolution Example

**1. The LLM's Initial `PLAN` to Define State:**

The LLM wants to analyze co-authorship patterns. It emits the following plan to set up its state structure:
```json
{
  "plan_id": "plan-init-state-001",
  "why": "Initialize the state structure for co-authorship analysis.",
  "commands": [
    "DECLARE co_authorship_analysis AS DICT",
    "DECLARE co_authorship_analysis.authors AS LIST WITH_DESCRIPTION 'List of all unique authors found.'",
    "DECLARE co_authorship_analysis.institutions AS DICT WITH_DESCRIPTION 'Institutions and their associated authors.'",
    "DECLARE co_authorship_analysis.collaboration_graph AS LIST WITH_DESCRIPTION 'Edge list of (author1, author2, shared_entity).'",
    "DECLARE co_authorship_analysis.summary AS DICT"
  ],
  "config": { "stop_on_error": true, "continue_on_empty": false }
}
```

**2. The Resulting State Object (after execution):**

After the executor runs this plan, the persistent state file will contain the initialized, empty structure, ready to be populated by subsequent `UPDATE` commands.

```
{
  "version": "0.1",
  "created_at": "2025-09-16T12:34:56Z",
  "updated_at": "2025-09-16T13:45:00Z",
  "query": "<original user query>",
  "config": {
    "adapter": { "type": "networkx", "path": "...", "params": {"max_path_len": 3} },
    "llm": { "provider": "argo_bridge", "model": "gpt41" }
  },
  "variables": {
    "co_authorship_analysis": {
      "_meta": { "type": "DICT", "description": null },
      "authors": {
        "_meta": { "type": "LIST", "description": "List of all unique authors found." },
        "items": []
      },
      "institutions": {
        "_meta": { "type": "DICT", "description": "Institutions and their associated authors." }
      },
      "collaboration_graph": {
        "_meta": { "type": "LIST", "description": "Edge list of (author1, author2, shared_entity)." },
        "items": []
      },
      "summary": {
        "_meta": { "type": "DICT", "description": null }
      }
    }
  },
  "history": [
    {
      "step": 1,
      "command": "FIND nodes WHERE entity_type = \"PERSON\" AS authors",
      "why": "Seed the author set",
      "summary": { "count": 1475 },
      "provenance_summary": { "items": 1475, "sources": 84 },
      "started_at": "2025-09-16T12:34:59Z",
      "finished_at": "2025-09-16T12:35:01Z"
    }
  ],
  "replay": {
    "seed": 0,
    "commands": [
      "FIND nodes WHERE entity_type = \"PERSON\" AS authors",
      "PROCESS authors USING \"...\" AS coauthor_triplets",
      "UPDATE coauthorship_network WITH coauthor_triplets MERGE"
    ]
  }
}
```

Key inclusions:
- `variables`: user-defined named datasets persisted across steps.
- `provenance`: per-item evidence with source linkage, snippets, extraction meta.
- `history`: ordered execution log with an explicit `why` (one-line rationale) per step.
- `replay`: minimal artifact to reproduce a run (seed, commands, relevant config).

### LLM Output: The Plan Object

The LLM's primary output is a structured JSON object representing a strategic plan. This object contains all the metadata and the sequence of GASL commands to be executed. This approach ensures robust parsing and clear separation of planning from execution.

#### Plan JSON Schema

```json
{
  "plan_id": "string (UUID for tracking)",
  "why": "string (A brief, one-line rationale for this plan)",
  "commands": [
    "string (A single GASL command)",
    "..."
  ],
  "config": {
    "stop_on_error": "boolean (default: true)",
    "continue_on_empty": "boolean (default: false)"
  }
}
```

The executor will validate incoming JSON against this schema before proceeding. For single-step, exploratory actions, the LLM can emit a plan with a single command in the `commands` list.

### GASL Grammar (v1)

- **State Definition**:
  - `DECLARE <state_key> AS <LIST|DICT|COUNTER> [WITH_DESCRIPTION "<description>"]`: Initializes a key in the persistent state. This should be the first step in a plan.

- **Core Commands**:
  - `FIND <nodes|edges|paths> WHERE <conditions> [LIMIT <n>] AS <var>`
  - `PROCESS <input_var> USING "<instruction>" AS <output_var>`
  - `UPDATE <state_key> WITH <var> [MERGE|REPLACE]`
  - `ANALYZE <state_key> USING "<instruction>" AS <output_var>`

- **Control Flow & Guards**: These allow plans to be robust and self-correcting.
  - `REQUIRE EXISTS <var>`: Fails the plan if a variable from a previous step doesn't exist.
  - `ASSERT <condition>`: Fails the plan if a condition on a variable is false (e.g., `ASSERT LEN ${authors} > 0`).
  - `ON <EMPTY|ERROR|PARTIAL|SCHEMA_MISMATCH> <variable> THEN <command>`: Conditional one-shot command for local pivots.
  - `TRY ... CATCH ANY ... FINALLY ... END`: Block-level error handling for complex steps.

- **Dynamic Configuration**: Allows the LLM to tune its own strategy.
  - `SET adapter.caps.<key>=<value>` (e.g., `SET adapter.caps.max_path_length=2`).
  - `CANCEL PLAN "<plan_id>"`: Aborts a running plan if evaluation shows it's unproductive.

- **Data Manipulation (Deterministic)**: For preparing inputs for subsequent steps without needing an LLM.
  - `SELECT <variable> FIELDS <field1>, <field2> AS <new_variable>` (Projection)
  - `SELECT <variable> WHERE <condition> AS <new_variable>` (Filtering)

Conditions support:
- Comparisons: `=, !=, >, >=, <, <=`
- Membership: `IN`, `NOT IN`
- Text: `CONTAINS`, `STARTS_WITH`, `ENDS_WITH`
- Boolean combination: `AND`, `OR`, parentheses

### Class Design

#### gasl/types.py
- Enums: `TargetKind {NODES, EDGES, PATHS}`, `UpdateMode {MERGE, REPLACE}`
- TypedDicts/Dataclasses: `FindSpec`, `ProcessSpec`, `UpdateSpec`, `AnalyzeSpec`, `BranchSpec`
- `ExecutionResult`: holds value, count, metadata

#### gasl/errors.py
- `ParseError`, `ConditionError`, `ExecutionError`, `AdapterError`

#### gasl/ast.py
- Base: `GASLNode`
- Nodes: `FindNode`, `ProcessNode`, `UpdateNode`, `AnalyzeNode`, `BranchNode`

#### gasl/parser.py (GASLParser)
- `parse(command: str) -> GASLNode`
- Tokenization (lightweight), condition parsing to internal predicate tree
- Helpful diagnostics (unknown token, missing AS, etc.)

#### gasl/conditions.py
- `parse_conditions(expr: str) -> Predicate`
- `evaluate(node_attrs|edge_attrs, predicate) -> bool`

#### gasl/context.py (ContextStore)
- `set(var: str, value: Any)`
- `get(var: str) -> Any`
- `exists(var: str) -> bool`
- `summary(max_items: int) -> dict`

#### gasl/state.py (StateStore)
- `get(key: str) -> Any`
- `merge(key: str, value: Any)`
- `replace(key: str, value: Any)`
- `summary(keys: list[str] | None) -> dict`
- `persist()` and `load()` via JSONFileStateBackend
- `append_history(record: dict)` where record includes: `{ step, command, why, summary, started_at, finished_at, errors? }`
- `attach_provenance(key: str, indices: list[int], provenance_items: list[dict])`
- `replay_info() -> dict` returns `{ seed, commands, config }`

#### gasl/adapters/base.py (GraphAdapter)
- `find_nodes(conditions: Predicate, limit: int|None) -> list[dict]`
- `find_edges(conditions: Predicate, limit: int|None) -> list[dict]`
- `find_paths(starts: list[str], ends: list[str], max_length: int) -> list[list[str]]`
- `get_node(name_or_id: str) -> dict | None`

#### gasl/adapters/networkx_adapter.py (NetworkXAdapter)
- Implements `GraphAdapter` over a `networkx.Graph`
- Performs attribute normalization (e.g., entity_type stripping quotes)
- Enforces safe defaults (e.g., path `cutoff`)

#### gasl/llm/client.py (LLMClient)
- `generate(prompt: str, system: str|None = None) -> str`
- `structured(prompt: str, schema: dict) -> dict`

#### gasl/llm/argo_bridge.py (ArgoBridgeLLMClient)
- Wraps existing `argo_bridge_llm`
- Adds small helpers for retries/logging if desired (no extra retries if user forbids)

#### gasl/llm/prompting.py
- Builders for PROCESS/ANALYZE:
  - `build_process_prompt(data_excerpt: str, instruction: str) -> str`
  - `build_analyze_prompt(state_excerpt: str, instruction: str) -> str`
  - Prompts must request JSON with schema and require provenance fields when applicable.

#### gasl/commands/find.py
- `run(adapter: GraphAdapter, spec: FindSpec, ctx: ContextStore) -> ExecutionResult`
  - Routes to `find_nodes`, `find_edges`, `find_paths`
  - Adds extraction provenance entries for matched items when possible (source_id, doc_id)

#### gasl/commands/process.py
- `run(llm: LLMClient, spec: ProcessSpec, ctx: ContextStore) -> ExecutionResult`
  - Extracts safe excerpt of input data (via `serialization.py`)
  - Calls LLM with `USING` instruction; expects structured JSON output
  - Validates schema, enriches outputs with `extraction` metadata (model, temperature, timestamp)

#### gasl/commands/update.py
- `run(state: StateStore, spec: UpdateSpec, ctx: ContextStore) -> ExecutionResult`
  - Merges or replaces target key; if inputs contain provenance, carry forward

#### gasl/commands/declare.py
- `run(state: StateStore, spec: DeclareSpec) -> ExecutionResult`: Initializes a state key with a given type and description.

#### gasl/commands/analyze.py
- `run(llm: LLMClient, state: StateStore, spec: AnalyzeSpec, ctx: ContextStore) -> ExecutionResult`
  - ANALYZE prompts must only consume state summaries or bounded samples; outputs include rationale and (optional) evidence references

#### gasl/commands/branch.py
- `run(executor: GASLExecutor, spec: BranchSpec) -> ExecutionResult`
  - Evaluates condition; executes nested THEN/ELSE command

#### gasl/dispatcher.py (CommandDispatcher)
- `dispatch(node: GASLNode, ...) -> ExecutionResult`
- Maps AST node type → respective command runner

#### gasl/executor.py (GASLExecutor)
- ctor: `(adapter: GraphAdapter, llm: LLMClient, state: StateStore, context: ContextStore)`
- `execute_one(command_str: str) -> ExecutionResult`
- `run_until_complete(step_fn)`: loop powered by LLM that emits next GASL command or `COMPLETE: ...`
- Maintains `command_history: list[ExecutionRecord]`
- On each step:
  - capture `started_at/finished_at`
  - require a one-line `why` rationale provided by the LLM; record in history
  - record summary metrics (counts, sizes)
  - update `replay` with the exact command string

### Integration with `analytical_retriever.py`

- Add a new mode that leverages GASL:
  - Build `NetworkXAdapter` from `rag.chunk_entity_relation_graph._graph`
  - Build `ArgoBridgeLLMClient` from `examples/using_custom_argo_bridge_api.py`
  - Construct `GASLExecutor` with a `JSONFileStateBackend` under the working dir
  - Loop: prompt LLM for next GASL command; execute; persist state after each successful step
  - Stop when LLM responds `COMPLETE: <final_answer>`; return/output final answer and state summary

### Hypothesis-Driven Traversal (HDT) Execution Flow

The system operates on an iterative, agentic loop where the LLM acts as a researcher. It forms a hypothesis, tests it using a GASL plan, evaluates the outcome, and refines its strategy.

#### The HDT Loop

1.  **Phase 1: Hypothesize & Plan**
    *   **Input**: The user query, current state summary, and recent execution history.
    *   **LLM Task**:
        1.  Formulate a hypothesis (e.g., "Authors are connected via shared EVENT nodes representing papers").
        2.  Define the state variables needed to test it.
        3.  Emit a **JSON Plan Object** containing a sequence of GASL commands to test the hypothesis. The plan can include guards (`ASSERT`) and branches (`ON EMPTY`).
    *   **Example Output**: A JSON object conforming to the Plan Object schema.

2.  **Phase 2: Execute Plan**
    *   The `GASLExecutor` receives the **JSON Plan Object**. After validating its schema, it executes the commands from the `commands` list sequentially, respecting the plan's `config` flags.
    *   **For each command in the plan:**
        1.  **Bind Inputs**: Resolve all `${variable}` references from the context. If a binding fails, the step fails with a `binding_failure` status.
        2.  **Execute Step**: The command is dispatched to the appropriate runner (e.g., `FIND` goes to the Graph Adapter). The execution is deterministic (no LLM for traversal). `PROCESS` and `ANALYZE` are the primary commands that invoke the LLM for reasoning over data.
        3.  **Validate Output**: The executor checks the result. For `PROCESS`/`ANALYZE`, it validates the output against an expected schema.
        4.  **Record Step**: A detailed `ExecutionRecord` is created, including:
            *   The exact command and "why" rationale.
            *   Start/end timestamps and duration.
            *   **Status**: `success`, `empty`, `partial`, `binding_failure`, `schema_mismatch`, or `error`.
            *   **Metrics**: Result counts, shapes, whether adapter caps were hit.
            *   **Provenance**: Source IDs and snippets are attached to the output data.
        5.  **Update Memory**:
            *   **Context**: The command's output is stored in the temporary `ContextStore` under its `AS <variable>` name. This variable is available for subsequent steps within the same plan.
            *   **State**: The persistent `StateStore` is only modified by the `UPDATE` and `DECLARE` commands. This enforces a clean separation between intermediate results and long-term findings. State updates are copy-on-write to create a new, immutable state snapshot.

3.  **Phase 3: Evaluate & Update Strategy**
    *   **Input**: The `ExecutionRecord` from the last step/plan and the new state summary.
    *   **LLM Task**:
        1.  Analyze the outcome. Was the hypothesis supported, invalidated, or partially answered?
        2.  Decide the next strategic move based on the status and metrics.
    *   **Possible Decisions**:
        *   **Continue**: The hypothesis holds; generate the next logical `PLAN` to continue the investigation.
        *   **Refine**: The results are promising but noisy or incomplete (e.g., `partial` status). Generate a new `PLAN` with tighter constraints (e.g., `SET adapter.caps.max_path_length=2` then `FIND` again).
        *   **Pivot**: The hypothesis failed (e.g., `empty` status on a key `ASSERT`). Formulate a new hypothesis and generate a new `PLAN` to test it.
        *   **Terminate**: Sufficient information has been gathered. Emit `COMPLETE: <final answer>`.

This loop repeats, allowing the LLM to navigate the graph, process information, and adapt its strategy based on concrete evidence from the execution engine.

### Future-Proofing for Search Algorithms (e.g., MCTS)

This architecture is designed to support more advanced search algorithms in the future with minimal changes.

1.  **State Snapshots**: Because state updates are copy-on-write, each step's resulting state is a forkable, hashable node in a potential search tree.
2.  **Explicit Decision Points**: The `EVALUATE` phase is a natural point for tree expansion. The LLM can be prompted to generate a *ranked list* of several possible next plans.
    *   **Example LLM Output**:
        ```json
        {
          "next_actions": [
            { "plan": ["..."], "confidence": 0.8, "rationale": "Most likely fix for empty result." },
            { "plan": ["..."], "confidence": 0.6, "rationale": "Alternative exploratory path." }
          ]
        }
        ```
3.  **MCTS Implementation**: A future MCTS runner would:
    *   Use the current state as the root of the search.
    *   Call the LLM to get the list of `next_actions` to expand the tree.
    *   Use a cheaper "rollout policy" (e.g., a simpler LLM or rule-based agent) to simulate paths down the tree to estimate their value.
    *   The current executor will simply pick the action with the highest confidence, but the hooks for expansion are built-in.

### Error Handling & Diagnostics

- Parser errors → return actionable messages to the LLM to self-correct
- Adapter errors → include normalized hints (e.g., unknown node, empty result)
- PROCESS/ANALYZE → enforce small, bounded data excerpts to keep context size manageable
- History keeps truncated inputs/outputs for traceability without blowing up logs
- Provenance recorded for FIND/PROCESS outputs; state can emit an evidence report
- Replay artifact (`state.replay`) allows deterministic re-execution of a session (subject to external LLM variability)

### Non-Goals (v0)

- Full Cypher compatibility
- Arbitrary Python execution from LLM
- Full-text search indexing

---

This document acts as the reference for implementation. Keep modules small and composable; prefer narrow interfaces; isolate backend-specific logic under `adapters/`; ensure all GASL-facing behavior is deterministic and easy for the LLM to learn.


