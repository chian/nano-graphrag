# Question Generation Prompt: Before vs After

## BEFORE (Original Prompt)

```
Generate a multi-step reasoning question in the domain of {domain_name}.

CRITICAL REQUIREMENTS:
1. COMPLETELY SELF-CONTAINED - The question must provide ALL necessary scientific facts, mechanisms, experimental results, and context needed to derive the answer through reasoning alone
2. NO GRAPH REFERENCES - Never mention "weights", "causal weight", "edge strength", "graph", or any graph-specific terminology
3. MULTI-STEP REASONING - The answer should require at least 5-7 logical reasoning steps combining multiple pieces of information
4. SHORT-FORM ANSWER - The question should have a brief, specific answer (1-3 sentences) that can be reasoned out without multiple choice options
5. DOMAIN-APPROPRIATE - Use only biological/scientific facts and mechanisms, not metadata or structural information

FORBIDDEN:
- Any reference to graphs, networks, weights, scores, or structural data
- Phrases like: "the text", "the paper", "the study", "as mentioned", "Figure", "Table", "Section", "with a weight of", "causal weight"
- Questions that require knowing graph structure rather than domain knowledge
- Questions where the answer is stated directly in one place

REQUIRED STRUCTURE:
The question should:
1. Set up a realistic biological/clinical scenario with specific conditions
2. Provide relevant experimental or mechanistic data (e.g., "Studies show that X reduces Y by 40% in condition Z")
3. Present a problem that requires integrating multiple facts
4. Ask for a specific, short-form answer that demonstrates deep reasoning

ANALYSIS TYPE: {analysis_type}
DOMAIN: {domain_name}

SCIENTIFIC ENTITIES AND RELATIONSHIPS TO USE:
{json.dumps(analysis_data, indent=2)}  # <-- INCLUDES: weight, relation_type, source_papers

ENTITY CONTEXT:
{entity_context}

GOOD EXAMPLE (for a different topic):
"Consider a patient with bacterial sepsis caused by E. coli producing both AmpC β-lactamase (constitutively expressed, hydrolyzes cephalosporins but not carbapenems) and NDM-1 metallo-β-lactamase (hydrolyzes all β-lactams including carbapenems). Initial treatment with ceftriaxone fails, and MIC testing shows ceftriaxone MIC >256 μg/mL and meropenem MIC of 0.5 μg/mL. The patient has normal renal function (CrCl 90 mL/min) but a history of seizure disorder. Which antibiotic class should be prioritized for definitive therapy, and what is the primary biochemical rationale for this choice given the resistance mechanisms present?"

EXPECTED SHORT-FORM ANSWER: "Carbapenems should be prioritized because NDM-1 cannot hydrolyze them effectively at therapeutic concentrations (meropenem MIC 0.5 μg/mL is still susceptible), while AmpC-mediated resistance makes cephalosporins ineffective (MIC >256). Though seizure risk exists with carbapenems, the lack of alternative effective agents against NDM-1 and the low MIC suggest clinical efficacy outweighs this risk."

Now generate ONE question following this pattern:
- Provide a complex scenario with specific biological/clinical details
- Embed quantitative data where relevant (percentages, concentrations, time courses)
- Ask a question requiring 5-7 reasoning steps to answer
- The answer should be a short paragraph (2-4 sentences) that can be derived from the information given

Output format:
QUESTION: [your multi-step reasoning question]
EXPECTED_REASONING_STEPS: [brief bullet points showing the logical chain needed to reach the answer]
CORRECT_ANSWER: [the short-form answer, 2-4 sentences]
```

**Problems with this prompt:**
1. Says "brief, specific answer (1-3 sentences)" but example answer is 60+ words
2. Says "short paragraph (2-4 sentences)" - contradictory and too long
3. Receives `analysis_data` with graph metadata (weight, relation_type)
4. No explicit word limit
5. Example answer is explanatory paragraph, not gradable by exact matching

---

## AFTER (Improved Prompt)

```
Generate a multi-step reasoning question for the domain of {domain_name}.

CRITICAL REQUIREMENTS - SELF-CONTAINMENT:
1. The question must be a COMPLETE STANDALONE problem statement
2. ALL necessary facts, data, mechanisms, and context must be EMBEDDED in the question text itself
3. A reader with domain expertise but NO access to any external materials should be able to answer
4. NO references to: graphs, papers, figures, tables, "the text", "the study", weights, scores, causal edges
5. The question should read like a textbook problem or exam question with all information provided

CRITICAL REQUIREMENTS - ANSWER FORMAT:
1. The answer must be SHORT and SPECIFIC (1-20 words maximum)
2. The answer should be one of these formats:
   - A specific molecule/gene/protein/species name (e.g., "Carbapenems" or "Phocaeicola dorei")
   - A specific mechanism or process (e.g., "Cross-feeding via acetate")
   - A yes/no with brief justification (e.g., "No - lacks xylan degradation genes")
   - A specific numerical value or comparison (e.g., "Coculture (95% vs 60%)")
   - A specific biological term (e.g., "Synergistic metabolic cooperation")
3. The answer must be GRADABLE by near-exact string matching or simple pattern matching
4. DO NOT allow answers that require paragraphs, multi-part explanations, or long justifications

CRITICAL REQUIREMENTS - REASONING:
1. Answering requires 5-7 logical inference steps
2. Steps must integrate multiple pieces of information from the question
3. Correct reasoning leads to a specific, unambiguous conclusion
4. The path to the answer is not immediately obvious but can be derived

FORBIDDEN:
- Any reference to graphs, networks, weights, scores, edge types, causal weights, or structural data
- Phrases like: "the text", "the paper", "the study", "as mentioned", "Figure", "Table", "Section", "according to"
- Questions where the answer is stated directly without requiring reasoning
- Answers that are long paragraphs or require extensive explanation

ANALYSIS TYPE: {analysis_type}
DOMAIN: {domain_name}

SCIENTIFIC CONTEXT (use these to build self-contained question):
{json.dumps(analysis_data, indent=2)}  # <-- SANITIZED: NO weight, relation_type, source_papers

ENTITY CONTEXT:
{entity_context}

BAD EXAMPLE (answer too long, not gradable):
Q: "Which culture condition should be prioritized to maximize carbohydrate consumption and SCFA production, and what is the mechanistic rationale for this choice?"
A: "Coculture should be prioritized because it leads to more complete carbohydrate consumption (95% inulin, 90% xylan) and significantly higher SCFA production (70% increase), likely due to synergistic metabolic interactions between Phocaeicola dorei and Lachnoclostridium symbiosum..." (WAY TOO LONG!)

GOOD EXAMPLE (short, specific, gradable):
Q: "In monoculture, Phocaeicola dorei consumes 60% of available inulin over 24 hours. Lachnoclostridium symbiosum alone consumes 55% of inulin. When cocultured under identical conditions, total inulin consumption reaches 95% and SCFA levels are 70% higher than either monoculture. L. symbiosum lacks polysaccharide degradation genes but can convert acetate to butyrate. P. dorei produces acetate during inulin fermentation. Which culture condition maximizes both carbohydrate utilization and SCFA production?"
A: "Coculture"

REASONING FOR GOOD EXAMPLE:
- Monocultures leave 40-45% residual inulin
- Coculture achieves 95% consumption (much higher)
- L. symbiosum lacks degradation genes, depends on P. dorei breakdown products
- Cross-feeding of acetate enables L. symbiosum growth and butyrate production
- Synergy explains higher SCFA levels
- Answer is one word, easily gradable

ANOTHER GOOD EXAMPLE:
Q: "A bacterial species produces both AmpC β-lactamase (hydrolyzes cephalosporins, not carbapenems) and NDM-1 metallo-β-lactamase (hydrolyzes all β-lactams including carbapenems at high MIC). Ceftriaxone MIC >256 μg/mL (resistant), meropenem MIC 0.5 μg/mL (susceptible ≤1 μg/mL), colistin MIC 0.25 μg/mL (susceptible ≤2 μg/mL). Patient has normal renal function but seizure history (carbapenems increase seizure risk). Which antibiotic class for definitive therapy?"
A: "Carbapenems"

Now generate ONE question following this pattern:
- Provide a complete scenario with ALL specific biological/clinical details needed
- Embed quantitative data where relevant (percentages, concentrations, time courses, MIC values, etc.)
- Ask a question requiring 5-7 reasoning steps to answer
- The answer should be 1-20 words maximum, specific and gradable

Output format:
QUESTION: [complete self-contained question with all necessary facts embedded]
EXPECTED_REASONING_STEPS: [5-7 bullet points showing the logical chain needed]
CORRECT_ANSWER: [1-20 word specific answer]
```

**Improvements in this prompt:**
1. **Explicit word limit**: "1-20 words maximum" (was "2-4 sentences")
2. **Sanitized input**: `analysis_data` has NO graph metadata
3. **Clear format types**: Lists 5 specific answer formats
4. **BAD example first**: Shows what NOT to do
5. **GOOD examples**: Both show short (1 word) answers
6. **Emphasizes gradability**: "must be GRADABLE by near-exact string matching"
7. **Self-containment emphasized**: "COMPLETE STANDALONE problem statement"

---

## Validation Steps (NEW in AFTER version)

After generation, the system now validates:

### 1. Self-Containment Validation
```
You are a domain expert evaluating whether a question is completely self-contained.

QUESTION: {question}
EXPECTED ANSWER: {answer}

Evaluate these criteria:
1. Are ALL necessary scientific facts stated explicitly in the question?
2. Are ALL experimental values, conditions, parameters provided?
3. Could a domain expert answer WITHOUT access to any external materials?
4. Are there any implicit references to "the graph", "the study", etc.?
5. Does the question assume knowledge of unstated experimental results?

Output JSON:
{
  "is_self_contained": true/false,
  "missing_information": [...],
  "external_references": [...]
}
```

### 2. Answer Gradability Validation
```
Evaluate if this answer is in a SHORT, GRADABLE format suitable for automated exact matching.

ANSWER: {answer}

Criteria:
1. Word count: 1-20 words (strict requirement)
2. Format type: entity_name | mechanism | yes_no | numerical | term
3. NOT a paragraph, NOT multiple sentences of explanation
4. Can be graded by simple string matching

Examples of GRADABLE:
- "Coculture" (1 word)
- "Carbapenems" (1 word)
- "Cross-feeding via acetate" (3 words)
- "No - lacks xylan degradation genes" (5 words)

Examples of NOT GRADABLE:
- "Coculture should be prioritized because..." (paragraph, >20 words)

Output JSON:
{
  "is_gradable": true/false,
  "word_count": N,
  "format_type": "...",
  "reason": "..."
}
```

### 3. Quality Scoring (SAME as before)
4 criteria system with threshold >= 4

---

## Complete Pipeline Comparison

### BEFORE
```
Graph Analysis → Question Generation → Quality Filter → Done
                 (gets graph metadata)   (4 criteria)
```

**Result:** Long paragraph answers, implicit graph dependencies

### AFTER
```
Graph Analysis → Sanitization → Question Generation → Self-Containment → Gradability → Quality Filter → Done
                 (remove graph)  (1-20 word limit)    (all facts?)       (word count)   (4 criteria)
```

**Result:** Short specific answers (1-20 words), fully self-contained, gradable by exact matching
