# Contrastive QA Generation Improvements

## Overview
Updated the question generation in `generate_contrastive_qa.py` (Stage 6) to create better multi-step reasoning questions that are appropriate for users without access to the underlying graph structure.

## Key Changes

### 1. **Removed Graph-Specific References**
**Problem:** Questions previously referenced graph metadata like "causal weight of 0.9" and "edge strength of 0.8", which:
- Are not meaningful to users without the graph
- Are structural metadata, not biological facts
- Make questions feel artificial and disconnected from real scientific reasoning

**Solution:** Updated prompt to explicitly forbid:
- Mentions of "weights", "causal weight", "edge strength", "graph", or any graph terminology
- Structural/metadata information that isn't domain knowledge

### 2. **Shifted to Short-Form Open-Ended Questions**
**Problem:** Multiple choice questions (A-H) with 8 options:
- Can be answered by elimination rather than reasoning
- Don't test deep understanding as well as open-ended questions
- The correct answer is visible, reducing the reasoning challenge

**Solution:** Changed to short-form answer questions where:
- Users must construct their own answer (2-4 sentences)
- Answer must be derived through multi-step reasoning
- No options are provided to guide or constrain thinking

### 3. **Emphasized Self-Contained Context**
**Problem:** Questions assumed users had context from the graph or could reference external materials

**Solution:** Questions now must:
- Embed ALL necessary scientific facts, mechanisms, and experimental data
- Provide specific quantitative data where relevant (e.g., "reduces viral load by 40%", "MIC >256 μg/mL")
- Set up realistic biological/clinical scenarios with complete context
- Be answerable using ONLY the information in the question text

### 4. **Required Multi-Step Reasoning (5-7 steps)**
**Problem:** Previous questions could sometimes be answered in 1-2 steps or by simple recall

**Solution:** Questions must now:
- Require integration of multiple facts
- Involve trade-offs, mechanism comparison, or conditional reasoning
- Take many reasoning steps to reach the answer
- Demonstrate deep understanding, not just recall

## Example Transformation

### Before (Multiple Choice with Graph References):
```
Question: "In a scenario where reducing SARS-CoV-2 viral replication in the lungs
is critical, and two inhibitory agents are available—Adintrevimab (with a weight
of 0.9) and ADG-2 (with a weight of 0.8)—which mechanism should be prioritized
for maximal reduction of lung viral load?"

Options: A-H with one correct answer
```

**Issues:**
- References graph "weights" (0.9, 0.8)
- Multiple choice format
- Limited context about mechanisms
- Can be answered by comparing numbers rather than biology

### After (Open-Ended with Embedded Facts):
```
Question: "Consider a SARS-CoV-2 infection model where two therapeutic antibodies
are available. Adintrevimab neutralizes SARS-CoV-2 and inhibits viral replication
in both upper and lower respiratory tracts, reducing lung viral load by 60% in
hamster models and showing EC50 of 0.15 nM against the Alpha variant. ADG-2
specifically inhibits viral replication in mouse lungs, reducing viral titers
by 45% at 3 days post-infection but showing limited activity in upper airways.
In a clinical scenario where the primary goal is to prevent progression to severe
pneumonia in an early-stage COVID-19 patient, which therapeutic approach should
be prioritized and what is the mechanistic rationale for this choice considering
tissue distribution, viral kinetics, and disease progression?"

Expected Reasoning Steps:
- Recognize that severe pneumonia involves lower respiratory tract pathology
- Note Adintrevimab's broader tissue distribution (upper + lower airways)
- Consider that upper airway viral replication contributes to lower tract seeding
- Evaluate the 60% vs 45% reduction in lung viral load
- Consider the EC50 potency data for Adintrevimab
- Recognize that early intervention requires blocking viral spread from upper to lower airways
- Integrate that broader anatomical coverage + higher potency = better prevention

Correct Answer: "Adintrevimab should be prioritized because it provides
neutralization across both upper and lower respiratory tracts, which is critical
for preventing viral seeding from nasopharyngeal sites to the lungs during early
infection. Its higher potency (EC50 0.15 nM) and greater lung viral load reduction
(60% vs 45%) suggest superior efficacy in preventing progression to pneumonia.
ADG-2's limited upper airway activity would allow continued viral replication
in the nasopharynx, which could lead to ongoing lower tract infection despite
local lung inhibition."
```

**Improvements:**
- No graph metadata references
- Rich biological/clinical context embedded
- Quantitative data from experiments (percentages, EC50 values)
- Requires 7+ reasoning steps
- Short-form answer tests deep understanding
- Realistic clinical decision-making scenario

## Technical Implementation

### Updated Components:

1. **`ContrastiveQuestionGenerator.generate()`** - New prompt emphasizing:
   - Self-contained context
   - No graph references
   - Multi-step reasoning requirement
   - Short-form answers

2. **`_parse_open_ended_response()`** - New parser for:
   - Question text
   - Expected reasoning steps
   - Correct answer (short-form)

3. **`generate_questions_from_analyses()`** - Updated to:
   - Handle new question format
   - Store reasoning steps and correct answers
   - Filter quality based on complete question + answer

### Preserved Components:

- Quality filtering with same threshold (score >= 4)
- Random selection for diversity
- Entity deduplication
- Same retry logic for high-quality questions

## Output Format

```json
{
  "domain": "molecular_biology",
  "graph_file": "path/to/graph.graphml",
  "num_questions": 7,
  "questions": [
    {
      "question": "Complete self-contained question text with embedded facts...",
      "reasoning_steps": [
        "Step 1: Identify key mechanisms",
        "Step 2: Compare tissue distributions",
        "...",
        "Step 7: Integrate evidence for final conclusion"
      ],
      "correct_answer": "Short-form answer (2-4 sentences) derived from reasoning...",
      "analysis_type": "alternatives",
      "source_entities": ["ENTITY1", "ENTITY2"],
      "quality_score": 4.5
    }
  ]
}
```

## Benefits

1. **Graph-Independent**: Questions can be used without access to the graph structure
2. **Tests Deeper Reasoning**: Open-ended format requires constructing answers, not selecting them
3. **More Realistic**: Mimics real scientific/clinical reasoning scenarios
4. **Better Assessment**: Evaluates ability to integrate multiple facts and mechanisms
5. **Reusable**: Questions are self-contained and can be used in various contexts

## Usage

The pipeline usage remains the same:

```bash
python run_contrastive_pipeline.py paper.txt \
  --domain molecular_biology \
  --num-questions 20
```

Questions will automatically be generated in the new format.
