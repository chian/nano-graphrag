# Enzyme GASL Demo Storyboard · Process Variant

## Scope

This variant explains how GASL behaved on the two enzyme questions, with emphasis on:

1. what the planner tried to do
2. where graph normalization weakened direct enzyme anchoring
3. how the final story should blend raw trace evidence with hand-shaped replay

## Slide 1

Title: `How GASL approached the enzyme question`

Story:
- Introduce the query as a graph problem: find enzyme anchors, traverse to substrate/evidence neighborhoods, summarize validation mode
- Show the four-step planner logic:
  - declare query symbols
  - find enzyme anchor nodes
  - graphwalk to evidence/support neighborhoods
  - project answer rows

Visual:
- Left-to-right process strip
- Query text at top
- Four labeled GASL phases underneath

Key trace artifacts:
- `planner_symbols_prompt`
- `planner_symbols_response`
- `planner_plan`
- first `command_result`

## Slide 2

Title: `Where the raw trace struggled`

Story:
- The graph stores normalized names like `VANA RIESKE MONOOXYGENASE ASSIGNMENT`
- The user query used compact enzyme tokens: `verA`, `vanA`, `gdmA`
- GASL repeatedly attempted exact and semantic anchor finds, but the raw anchor search stayed empty
- This is not a planner failure alone; it reflects a graph naming mismatch

Visual:
- Left: compact token input
- Right: normalized graph node names
- Middle: failed anchor attempts highlighted in amber

Key trace artifacts:
- repeated `FIND ... AS enzyme_nodes`
- `command_repair_response`
- `iteration_failure_summary`

## Slide 3

Title: `What GASL still recovered correctly`

Story:
- Even with weak direct anchors, the retrieval context surfaced the relevant Rieske neighborhoods:
  - `VANA RIESKE MONOOXYGENASE ASSIGNMENT`
  - `SWGDMAB IN VITRO-IN VIVO MISMATCH EVIDENCE`
  - `GUAIACOL_O_DEMETHYLATION`
  - `VANB PARTNER REDUCTASE SEQUENCE (UNIPROTKB O05617)`
- The step-by-step narrative should therefore show:
  - raw trace mechanics
  - then the evidence neighborhoods that the replay will use

Visual:
- Split screen:
  - left = trace/event flow
  - right = evidence neighborhood map

## Slide 4

Title: `Why the final demo should be hand-shaped`

Story:
- A raw replay would over-emphasize the empty anchor loops
- A good demo should instead:
  - keep the genuine GASL phases
  - preserve the trace-derived evidence neighborhoods
  - replace the weak anchor section with a hand-shaped explanatory transition

Visual:
- Three-part sequence:
  - raw GASL mechanics
  - graph normalization gap
  - hand-shaped evidence replay

Message:
- The value of GASL here is not “perfect direct retrieval”
- It is the combination of trace transparency and evidence-guided story shaping

## Slide 5

Title: `What GASL did on the confound question`

Story:
- The second query is stronger for a process-style demo because it naturally aligns with the graph’s partner/evidence nodes
- GASL can be shown doing:
  - reductase partner identification
  - evidence comparison
  - confound hypothesis construction
- This slide should explain that the confound story is a better fit for a literal step-by-step replay than the substrate-scope question

Visual:
- Pipeline:
  - native reductase
  - homolog pair
  - substrate panel
  - confound outcome
