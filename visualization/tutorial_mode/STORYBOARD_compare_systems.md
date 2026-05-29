# Storyboard: Long-Form GASL Tutorial Through Design Space, Command Categories, and Counterexamples

This is a **long-form tutorial plan** for a 10+ minute instructional video.
It is not a replay with captions. It is a structured teaching artifact that
explains:

1. why GASL exists in the design space between classic systems, full-context LLMs,
   and RAG
2. why GASL has **different command categories**
3. why those command categories are tied to **different information-compilation modes**
4. why different examples are required to motivate different parts of the design

The tutorial should be built from modular scenes and stitched into one longer film.

## Teaching thesis

The video should teach this claim:

> GASL is not a single fixed pipeline. It is a response architecture for turning
> underspecified natural-language questions into explicit, repairable, evidence-
> preserving graph work. Different command families exist because different kinds
> of information need to be compiled in different ways, and because simpler
> alternatives fail in different ways.

## Big corrective to the previous plan

The tutorial should **not** try to make one query demonstrate all of GASL.
That is pedagogically wrong because:

- GASL is meant to handle many question shapes
- not every query exercises every command family
- not every failure mode is present in every run
- not every answer requires the same kind of information compilation

So the tutorial should use **multiple short cases** inside one long anthology film.

## Overall structure

### Act 1. The design space

This opening is conceptual and comparative, but it should begin with a
historical bridge that establishes the film's main teaching contrast:

- the popular myth of science as sudden insight and bold declaration
- the actual modern practice of scientific progress through compilation,
  collation, and legibility

The opening should therefore use a short human story first, then replay the
same structure for systems:

1. a culture-level image of Eureka-style discovery
2. Wegener making a bold claim
3. why boldness alone does not secure acceptance
4. Tharp compiling scattered traces into legible structure
5. only then: the system analogy, where LLM-only corresponds to fluent claim
   and GASL corresponds to compiled evidence

The viewer should then understand three design pressures:

1. Classic retrieval / database systems  
   precise, efficient, controllable, but brittle with uncontrolled evidence

2. Full-context LLM-only reasoning  
   flexible and articulate, but practically infeasible at graph scale

3. RAG  
   practical and selective, but often limited by retrieval precision and evidence coverage

4. GASL  
   introduced to address those limitations through explicit evidence assembly,
   local validation, repairable execution, and answer-oriented synthesis

#### Visual strategy

This should use **separate compare graphics**, not the existing graph viewer.

- Classic systems: rigid grid / SQL / deterministic table language
- LLM-only: vast context sheet / token meter / overloaded flow
- RAG: spotlight / evidence tray / partial retrieval beam
- GASL: planning bench / validator gates / evidence bins / answer boards

#### Historical analogy

Use a brief historical arc to teach the value of compilation:

- **Alfred Wegener** should appear first, in a stylized ridicule scene, as the
  scientist with a strong broad claim that is still vulnerable because the
  evidence is not yet organized into an inspectable structure.
- **Marie Tharp** should appear second, at the desk and with layered traces, as
  the scientist whose compilation work made the hidden pattern increasingly
  legible to others.

The point is not biography. The point is that:

> modern science does not usually progress by a lone bold announcement alone;
> it progresses when evidence is collated into structures others can inspect.

That analogy should bridge from science-history to GASL in sequence, not in
parallel on the screen:

- first tell the human story of insight, resistance, compilation, and
  acceptance
- then retell that same structure for AI systems, where immediate fluent
  answers resemble the claim-first mode and GASL resembles the compilation mode

## Act 2. Command families as information-compilation modes

This is the core improvement over the prior storyboard.

The tutorial should explicitly categorize GASL commands by **why they exist**.
The structure of GASL is not arbitrary; the commands correspond to distinct
information-gathering and information-compilation modes.

### Family A. Working-memory / scoping commands

Representative commands:
- `DECLARE`

Teaching point:
- These exist because natural-language questions are underspecified.
- The system needs typed working memory so later steps can accumulate evidence
  into explicit, checkable bins instead of producing free-floating intermediates.

Contrast:
- Classic systems already have schema but struggle with emergent task-specific working memory
- LLM-only can improvise working memory but not explicitly enough
- RAG retrieves evidence but does not naturally create structured intermediate tables
- GASL creates explicit symbols for the exact evidence shape the answer needs

### Family B. Access / retrieval commands

Representative commands:
- `FIND`
- `GRAPHWALK`
- `COUNT`
- `SELECT`

Teaching point:
- These exist because not all relevant evidence is co-located.
- Vector retrieval often gives plausible chunks; graph traversal gives relation-aware access.
- Different access modes are needed for different evidentiary geometries.

Contrast:
- Classic: exact access, but brittle when relation paths are not known upfront
- LLM-only: can ingest broadly but at prohibitive scale/cost
- RAG: targeted slice, but the slice may not cover the needed relation structure
- GASL: retrieval is explicit and can change mode from node search to edge/path traversal

### Family C. Assembly / reshaping commands

Representative commands:
- `PROCESS`
- `PROJECT`
- `JOIN`
- `MERGE`
- `UPDATE`

Teaching point:
- These exist because retrieved evidence is rarely already in answer-bearing shape.
- The system must combine, normalize, and reinterpret heterogeneous evidence.

Contrast:
- Classic: joins and projections are strong but depend on rigid schema assumptions
- LLM-only: can narrate across heterogeneous evidence but often without explicit structure
- RAG: returns snippets, but snippet collections are not automatically comparable evidence
- GASL: explicitly assembles evidence into new working forms

### Family D. Compilation / comparison commands

Representative commands:
- `AGGREGATE`
- `COLLAPSE`
- `COMPARE`
- `RANK`

Teaching point:
- These exist because many scientific questions are not lookup questions.
- They ask for compiled structures: distributions, frontiers, contrasts, support summaries.

This is where the Marie Tharp analogy is strongest:
- not "what is one fact?"
- but "what pattern emerges when many facts are compiled together?"

Contrast:
- Classic: can aggregate if the schema and measure are known precisely
- LLM-only: can describe patterns, but often without explicit, inspectable compilation
- RAG: often sees too small a slice to compile stable comparative structures
- GASL: has dedicated compilation operators for exactly these question types

### Family E. Validation / observability / repair support

Representative commands and mechanisms:
- `SHOW`
- `INSPECT`
- step compiler / validator
- command repair / strategy adaptation loop

Teaching point:
- These exist because first-pass plans fail.
- Failure is not exceptional noise; it is informative.
- The system needs local defect detection and bounded repair so it can continue
  without silently poisoning later evidence.

Contrast:
- Classic: invalid query often just fails hard
- LLM-only: can drift or hallucinate around failure without explicit local checks
- RAG: retrieval miss may simply remain invisible
- GASL: defects are surfaced, bounded, and used to steer the next attempt

### Family F. Evidence presentation / answer production

Representative mechanisms:
- answer views
- final synthesis

Teaching point:
- Raw graph rows are not final answers.
- Evidence should be structured before it is verbalized.
- Final language should be generated from organized evidence, not instead of it.

Contrast:
- Classic: often returns result tables rather than answers
- LLM-only: often answers fluently without preserving inspectable evidence structure
- RAG: often answers from retrieved snippets without explicit evidence compilation
- GASL: separates evidence organization from user-facing synthesis

## Act 3. Anthology case structure

The film should be long because it is made of **different miniature cases**.

Each case should carry the alternatives all the way through:

1. what a classic approach would do
2. what an LLM-only approach would do
3. what RAG would do
4. why GASL uses the relevant command family here

### Case 1. Why access modes differ

Example goal:
- show that some questions require relation traversal and not just chunk retrieval

Focus:
- `FIND`, `GRAPHWALK`, `SELECT`

### Case 2. Why assembly commands exist

Example goal:
- show that evidence often arrives in incompatible shapes

Focus:
- `PROCESS`, `PROJECT`, `JOIN`, `MERGE`

### Case 3. Why compilation commands exist

Example goal:
- show a scientific question that asks for a frontier, distribution, or comparison

Focus:
- `AGGREGATE`, `COLLAPSE`, `COMPARE`, `RANK`

### Case 4. Why validation and repair exist

Example goal:
- show a first-pass plan that is locally invalid or semantically misaligned

Focus:
- compiler / validation / repair loop

### Case 5. Why answer views and synthesis are separate

Example goal:
- show that correct evidence is still not yet a user answer

Focus:
- answer views
- final synthesis

## Visual plan

The alternatives must persist through the stories, not only the opening.

For each case:

- a left rail can show **Classic / LLM-only / RAG / GASL**
- each alternative gets a very short visual attempt
- the GASL attempt is not presented as magic; it is presented as the design
  that matches the problem shape

This keeps the compare/contrast present intellectually and visually.

## Build strategy

This is a large build, but it remains manageable if kept modular.

### Module set

1. compare-system scenes
2. command-family explainer scenes
3. case-study scenes
4. tutorial compositor

### Recommended output format

Either:
- one 10–15 minute anthology video

or:
- build the scenes separately first, then stitch them into one long film

The latter is preferable for iteration.

## Practical consequence for implementation

Do **not** force this through the current graph viewer.

Use the tutorial workspace for:
- compare graphics
- command-family explainers
- case-study overlays

Then selectively reuse real GASL trace material only where the trace is the
best way to show a specific necessity.
