# QA Generation Prompt Flow Analysis

## Current Flow (BEFORE Changes)

### Step 1: Graph Analysis via GASL Commands
**Location:** `generate_contrastive_qa.py:364-498` (analyze_graph_with_gasl)

The system uses GASL handlers to extract graph patterns:

1. **FindAlternativesHandler** (`gasl/commands/contrastive.py:13-100`)
   - Finds incoming causal edges to a target entity
   - Returns: `[{entity, entity_type, relation_type, description, weight, source_papers}, ...]`
   - **Problem:** Includes graph metadata (weight, relation_type)

2. **CompareMechanismsHandler**
   - Compares two mechanisms affecting the same target
   - Returns graph-based comparison data

3. **FindCompetingHandler**
   - Finds entities competing for the same resource
   - Returns competing entities with graph relationships

**Output Example:**
```json
{
  "target": "CARBOHYDRATE CONSUMPTION",
  "alternatives": [
    {
      "entity": "P. dorei",
      "entity_type": "BACTERIAL_SPECIES",
      "relation_type": "CAUSES",
      "description": "...",
      "weight": 0.85,
      "source_papers": [...]
    }
  ]
}
```

### Step 2: Question Generation
**Location:** `generate_contrastive_qa.py:48-95` (ContrastiveQuestionGenerator.generate)

**Current Prompt:**
```
Generate a multi-step reasoning question in the domain of {domain_name}.

CRITICAL REQUIREMENTS:
1. COMPLETELY SELF-CONTAINED - The question must provide ALL necessary scientific facts
2. NO GRAPH REFERENCES - Never mention "weights", "causal weight", etc.
3. MULTI-STEP REASONING - At least 5-7 logical reasoning steps
4. SHORT-FORM ANSWER - Brief, specific answer (1-3 sentences)
5. DOMAIN-APPROPRIATE - Only biological/scientific facts

ANALYSIS TYPE: {analysis_type}
DOMAIN: {domain_name}

SCIENTIFIC ENTITIES AND RELATIONSHIPS TO USE:
{json.dumps(analysis_data, indent=2)}  # <-- INCLUDES GRAPH METADATA!

ENTITY CONTEXT:
{entity_context}  # <-- FROM GRAPH NODE DATA

Output format:
QUESTION: [your multi-step reasoning question]
EXPECTED_REASONING_STEPS: [brief bullet points]
CORRECT_ANSWER: [the short-form answer, 2-4 sentences]
```

**Problems:**
- `analysis_data` contains weight, relation_type, graph structure
- `entity_context` pulls from graph node descriptions
- Answer format is "2-4 sentences" - too long for exact matching
- No explicit grading criteria

### Step 3: Quality Filtering
**Location:** `generate_contrastive_qa.py:180-359` (filter_question_quality)

Uses a 4-criteria scoring system:
1. **Problem Completeness** (0-2 points)
2. **Problem Complexity** (0-2 points)
3. **Technical Correctness** (0-2 points)
4. **Thinking and Reasoning** (0-2 points)

**Threshold:** Total score >= 4 to pass

**Problems:**
- Doesn't check for self-containment specifically
- Doesn't verify answer format is gradable
- Penalizes external references but doesn't catch implicit graph dependencies

---

## New Flow (AFTER Changes)

### Step 1: Graph Analysis (UNCHANGED)
Same GASL commands extract patterns from graph

### Step 2: Graph Data Sanitization (NEW)
**Location:** `generate_contrastive_qa.py` (new function: `sanitize_analysis_for_prompt`)

```python
def sanitize_analysis_for_prompt(analysis_data: dict, graph: nx.DiGraph) -> dict:
    """
    Remove graph metadata and enrich with domain facts.

    Transforms:
    {entity: "X", weight: 0.85, relation_type: "CAUSES"}

    Into:
    {entity: "X", biological_role: "...", mechanism: "..."}
    """
```

Removes: weight, relation_type, source_papers, edge data
Adds: biological_role, mechanism descriptions from node attributes

### Step 3: Question Generation (IMPROVED)
**New Prompt Template:**

```
Generate a multi-step reasoning question for the domain of {domain_name}.

CRITICAL REQUIREMENTS - SELF-CONTAINMENT:
1. The question must be a complete standalone problem statement
2. ALL necessary facts, data, mechanisms, and context must be embedded in the question text
3. A reader with domain expertise but no access to any external materials should be able to answer
4. NO references to: graphs, papers, figures, tables, "the text", "the study", weights, scores

CRITICAL REQUIREMENTS - ANSWER FORMAT:
1. The answer must be SHORT and SPECIFIC (1-15 words maximum)
2. The answer should be one of these formats:
   - A specific molecule/gene/protein name (e.g., "meropenem")
   - A specific mechanism or pathway (e.g., "homologous recombination")
   - A yes/no with brief justification (e.g., "No - NDM-1 hydrolyzes all beta-lactams")
   - A specific numerical value with units (e.g., "2.5 mM")
3. The answer must be gradable by near-exact string matching
4. Avoid answers requiring paragraphs or multi-part explanations

CRITICAL REQUIREMENTS - REASONING:
1. Answering requires 5-7 logical inference steps
2. Steps must integrate multiple pieces of information from the question
3. Correct reasoning leads to a specific, unambiguous conclusion

SCIENTIFIC CONTEXT (use these facts to build your question):
{sanitized_analysis_data}

BAD EXAMPLE (answer too long):
Q: "Which culture condition should be prioritized and what is the mechanistic rationale?"
A: "Coculture should be prioritized because it leads to more complete carbohydrate
consumption (95% inulin, 90% xylan) and significantly higher SCFA production..." (too long!)

GOOD EXAMPLE (answer is specific and short):
Q: "A patient has E. coli expressing AmpC β-lactamase (hydrolyzes cephalosporins,
not carbapenems) and NDM-1 (hydrolyzes all β-lactams). Ceftriaxone MIC is >256 μg/mL,
meropenem MIC is 0.5 μg/mL (susceptible breakpoint ≤1 μg/mL). The patient has normal
renal function but seizure history. Which antibiotic class should be used for definitive
therapy?"
A: "Carbapenems"

REASONING FOR GOOD EXAMPLE:
- NDM-1 profile makes most beta-lactams ineffective
- Meropenem MIC 0.5 is susceptible
- Despite seizure risk, carbapenem is only effective option
- Short, specific answer that's easily gradable

Output format:
QUESTION: [complete self-contained question with all necessary facts]
EXPECTED_REASONING_STEPS: [5-7 bullet points showing the logical chain]
CORRECT_ANSWER: [1-15 word specific answer]
```

### Step 4: Self-Containment Validation (NEW)
**Location:** `generate_contrastive_qa.py` (new function: `validate_self_containment`)

```python
async def validate_self_containment(
    llm: ArgoBridgeLLM,
    question: str,
    answer: str
) -> dict:
    """
    Check if question is answerable without external context.
    Returns: {is_self_contained: bool, missing_info: List[str]}
    """
```

**Validation Prompt:**
```
You are a domain expert. Read this question and determine if it contains ALL
information needed to derive the answer through reasoning alone.

QUESTION:
{question}

EXPECTED ANSWER:
{answer}

Evaluate:
1. Are all necessary scientific facts stated in the question?
2. Are all experimental values, conditions, and parameters provided?
3. Could you answer this question without access to any external materials?
4. Are there any implicit references to "the graph", "the study", or external data?

Output JSON:
{
  "is_self_contained": true/false,
  "missing_information": ["list", "of", "missing", "facts"],
  "external_references": ["list", "of", "implicit", "references"]
}
```

### Step 5: Answer Gradability Validation (NEW)
**Location:** `generate_contrastive_qa.py` (new function: `validate_answer_gradability`)

```python
async def validate_answer_gradability(
    llm: ArgoBridgeLLM,
    answer: str
) -> dict:
    """
    Check if answer is in gradable format.
    Returns: {is_gradable: bool, word_count: int, format_type: str}
    """
```

**Validation Prompt:**
```
Evaluate if this answer is in a SHORT, GRADABLE format suitable for exact matching.

ANSWER:
{answer}

Criteria:
1. Word count: 1-15 words (longer = not gradable)
2. Format: Specific entity, mechanism, yes/no, or numerical value
3. Not a paragraph or multi-sentence explanation

Output JSON:
{
  "is_gradable": true/false,
  "word_count": N,
  "format_type": "entity_name|mechanism|yes_no|numerical|paragraph",
  "reason": "why gradable or not gradable"
}
```

### Step 6: Combined Quality Filter (ENHANCED)
**Location:** `generate_contrastive_qa.py` (updated: `filter_question_quality`)

Now includes:
1. **Original 4 criteria** (completeness, complexity, correctness, reasoning)
2. **Self-containment check** (NEW)
3. **Answer gradability check** (NEW)

**New Scoring:**
- Original criteria: 0-8 points
- Self-containment penalty: -2 points if failed
- Gradability penalty: -2 points if answer too long

**New Threshold:** Total score >= 5 (slightly higher bar)

### Step 7: Question Refinement Loop (NEW)
**Location:** `generate_contrastive_qa.py` (updated: `generate_questions_from_analyses`)

```python
for attempt in range(max_attempts):
    # Generate question
    result = await generator.generate(...)

    # Validate self-containment
    containment = await validate_self_containment(...)
    if not containment['is_self_contained']:
        # Regenerate with feedback about missing info
        continue

    # Validate gradability
    gradability = await validate_answer_gradability(...)
    if not gradability['is_gradable']:
        # Regenerate with feedback to shorten answer
        continue

    # Quality filter
    quality = await filter_question_quality(...)
    if quality['passed']:
        questions.append(result)
```

---

## Key Improvements Summary

### Problem 1: Graph Dependency
**Before:** Questions relied on graph metadata (weights, edge types)
**After:** Sanitize analysis data to remove graph metadata, use only domain facts

### Problem 2: Long Answers
**Before:** Answers were "2-4 sentences" - not gradable
**After:** Answers must be 1-15 words, specific format, validated for gradability

### Problem 3: External References
**Before:** Questions could reference "the study", "the text"
**After:** Explicit self-containment validation checks for missing information

### Problem 4: No Grading Verification
**Before:** Questions generated but no verification they're gradable
**After:** Two-stage validation: self-containment + gradability

### Problem 5: Quality Criteria
**Before:** 4 generic criteria, threshold = 4
**After:** Multi-stage validation (self-containment + gradability + quality), threshold = 4

---

## Side-by-Side Flow Comparison

### BEFORE (Current System)

```
1. GASL Analysis extracts patterns from graph
   └─> Output: {entity, weight: 0.85, relation_type: "CAUSES", ...}

2. Question Generation Prompt receives:
   - Raw analysis_data (includes weight, relation_type)
   - entity_context from graph nodes
   - Prompt asks for "2-4 sentence" answers

3. LLM generates:
   Q: "Which culture condition should be prioritized and what is the
       mechanistic rationale for this choice?"
   A: "Coculture should be prioritized because it leads to more complete
       carbohydrate consumption (95% inulin, 90% xylan) and significantly
       higher SCFA production (70% increase), likely due to synergistic
       metabolic interactions between Phocaeicola dorei and Lachnoclostridium
       symbiosum..." (60+ words)

4. Quality Filtering:
   - 4 criteria scoring (completeness, complexity, correctness, reasoning)
   - Threshold >= 4
   - NO validation of self-containment
   - NO validation of answer gradability

5. Result: Question accepted with long paragraph answer
   └─> NOT gradable by exact matching
   └─> May rely on implicit graph knowledge
```

### AFTER (Improved System)

```
1. GASL Analysis extracts patterns from graph
   └─> Output: {entity, weight: 0.85, relation_type: "CAUSES", ...}

2. Sanitization removes graph metadata
   └─> sanitize_analysis_for_prompt()
   └─> Output: {entity, description: "...", mechanism: "..."}
       (weight, relation_type REMOVED)

3. Question Generation Prompt receives:
   - Sanitized analysis_data (NO graph metadata)
   - entity_context from graph nodes
   - Prompt asks for "1-20 word" answers
   - Examples show short, gradable answers

4. LLM generates:
   Q: "In monoculture, Phocaeicola dorei consumes 60% of available inulin
       over 24 hours. Lachnoclostridium symbiosum alone consumes 55% of
       inulin. When cocultured under identical conditions, total inulin
       consumption reaches 95% and SCFA levels are 70% higher than either
       monoculture. L. symbiosum lacks polysaccharide degradation genes but
       can convert acetate to butyrate. P. dorei produces acetate during
       inulin fermentation. Which culture condition maximizes both
       carbohydrate utilization and SCFA production?"
   A: "Coculture" (1 word)

5. Self-Containment Validation:
   └─> validate_self_containment()
   └─> Checks: Are all facts stated? Any external references?
   └─> If FAILS: Reject, continue to next attempt

6. Answer Gradability Validation:
   └─> validate_answer_gradability()
   └─> Checks: Word count ≤20? Format is specific entity/term?
   └─> If FAILS: Reject, continue to next attempt

7. Quality Filtering:
   - Same 4 criteria scoring
   - Threshold >= 4
   - If FAILS: Reject, continue to next attempt

8. Result: Question accepted with metadata
   └─> {
         question: "...",
         correct_answer: "Coculture",
         answer_word_count: 1,
         answer_format: "entity_name",
         is_self_contained: true,
         is_gradable: true,
         quality_score: 5.5
       }
```

---

## Code Changes Summary

### New Functions Added

1. **`sanitize_analysis_for_prompt(analysis_data, graph)`** (line 33)
   - Removes: weight, relation_type, source_papers, causal_weight
   - Keeps: entity names, descriptions, biological context

2. **`validate_self_containment(llm, question, answer)`** (line 416)
   - Returns: is_self_contained, missing_information, external_references
   - Uses LLM to check if question provides all necessary facts

3. **`validate_answer_gradability(llm, answer)`** (line 466)
   - Returns: is_gradable, word_count, format_type, reason
   - Enforces 1-20 word limit
   - Classifies format (entity_name, mechanism, yes_no, numerical, etc.)

### Modified Functions

1. **`ContrastiveQuestionGenerator.generate()`** (line 68)
   - Changed answer requirement from "2-4 sentences" to "1-20 words"
   - Added explicit examples of good/bad answers
   - Emphasized self-containment and gradability in prompt

2. **`generate_questions_from_analyses()`** (line 707)
   - Sanitizes analysis data before passing to generator (line 787)
   - Validates self-containment (line 802)
   - Validates answer gradability (line 818)
   - Adds metadata to accepted questions (line 846-847)
   - Rejects questions that fail any validation step

### Output Schema Changes

Questions now include additional metadata:
```json
{
  "question": "...",
  "reasoning_steps": [...],
  "correct_answer": "...",
  "analysis_type": "alternatives",
  "source_entities": [...],
  "quality_score": 5.5,
  "answer_word_count": 1,           // NEW
  "answer_format": "entity_name",   // NEW
  "is_self_contained": true,        // NEW
  "is_gradable": true               // NEW
}
```
