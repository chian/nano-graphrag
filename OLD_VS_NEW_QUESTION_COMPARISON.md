# Old vs New Contrastive Question Format Comparison

## Summary

The new format successfully eliminates graph-specific references and creates self-contained, multi-step reasoning questions with short-form answers. All 5 generated questions passed quality filtering (score ≥ 4.0).

## Key Improvements Achieved

### ✅ No Graph References
- **OLD**: Questions mentioned "weight of 0.9", "causal weight of 0.8", graph metadata
- **NEW**: All questions use only biological facts and experimental data (e.g., "70% reduction", "within 24 hours", "2% baseline to 18% at day 3")

### ✅ Self-Contained Context
- **OLD**: Assumed user had access to graph or external materials
- **NEW**: Every question embeds all necessary facts, mechanisms, and quantitative data

### ✅ Short-Form Answers
- **OLD**: Multiple choice (A-H) with 8 options
- **NEW**: Short paragraph answers (2-4 sentences) requiring constructed responses

### ✅ Multi-Step Reasoning
- **OLD**: Could sometimes be answered by elimination or simple recall
- **NEW**: All questions require 5-7 reasoning steps explicitly outlined

---

## Example Comparison

### OLD FORMAT (from your example):

```json
{
  "question": "In a scenario where reducing SARS-CoV-2 viral replication in the lungs is critical, and two inhibitory agents are available—Adintrevimab (with a weight of 0.9) and ADG-2 (with a weight of 0.8)—which mechanism should be prioritized for maximal reduction of lung viral load?",
  "answers": {
    "A": "Prioritize Adintrevimab because its broader inhibition in both upper and lower respiratory tracts ensures maximal reduction of lung viral load.",
    "B": "Prioritize ADG-2 because its inhibition in mouse lungs is more targeted...",
    "C": "Prioritize Adintrevimab because its higher weight (0.9) indicates greater efficacy...",
    "..." : "7 more options"
  },
  "correct_answer": "A"
}
```

**Problems:**
- ❌ References graph "weights" (0.9, 0.8)
- ❌ Multiple choice format
- ❌ Limited embedded context about mechanisms
- ❌ Answer can be selected rather than reasoned out

---

### NEW FORMAT (Generated):

```json
{
  "question": "A group of mice is infected with C. rodentium engineered to express Shiga toxin, resulting in severe kidney and liver damage within 72 hours. In parallel experiments, two groups receive either kanamycin or tetracycline at doses shown to clear bacterial infection within 24 hours. Histological analysis at 96 hours reveals that both antibiotic-treated groups show no signs of organ damage, while untreated infected mice display extensive tissue pathology. Given that Shiga toxin is known to directly cause organ damage during infection, and both antibiotics clear infection without causing organ injury, which factor is most critical for preventing organ damage in this scenario: direct inhibition of Shiga toxin activity, rapid bacterial clearance, or the specific choice of antibiotic? Justify your answer using the mechanistic and experimental data provided.",

  "reasoning_steps": [
    "Shiga toxin is the direct cause of organ damage during infection.",
    "Both kanamycin and tetracycline clear the infection rapidly (within 24 hours).",
    "Histology shows no organ damage in antibiotic-treated groups, but extensive damage in untreated infected mice.",
    "Both antibiotics prevent organ damage, regardless of their specific class.",
    "The key difference between treated and untreated groups is bacterial clearance, not direct toxin inhibition or antibiotic type.",
    "Since organ damage is absent when infection is cleared, rapid bacterial clearance prevents toxin-mediated pathology.",
    "Therefore, the critical factor is the elimination of bacteria before significant toxin-induced damage occurs."
  ],

  "correct_answer": "Rapid bacterial clearance is the most critical factor for preventing organ damage in this scenario. Both kanamycin and tetracycline, despite being different antibiotics, prevent tissue injury by eliminating the bacteria before Shiga toxin can cause pathology, indicating that the timing of infection clearance, rather than direct toxin inhibition or antibiotic choice, is decisive for protecting organs.",

  "quality_score": 5.0
}
```

**Improvements:**
- ✅ No graph metadata - uses biological facts only
- ✅ Rich experimental context (timepoints, histology, specific outcomes)
- ✅ Quantitative data ("within 72 hours", "within 24 hours", "at 96 hours")
- ✅ Requires 7-step reasoning process
- ✅ Short-form answer that must be constructed
- ✅ Tests understanding of causal mechanisms
- ✅ Realistic scientific scenario

---

## All 5 Generated Questions Summary

### Question 1: Organ Damage Prevention
- **Scenario**: Mouse infection + antibiotics
- **Reasoning Steps**: 7
- **Key Concept**: Timing of bacterial clearance vs toxin inhibition
- **Quality Score**: 5.0

### Question 2: Enterobacteriaceae Expansion
- **Scenario**: Multiple interventions affecting bacterial abundance
- **Reasoning Steps**: 7
- **Key Concept**: Synergistic effects of infection + antibiotics
- **Quality Score**: 5.0

### Question 3: Colonization Resistance Loss
- **Scenario**: Patient with ulcerative colitis + antibiotics
- **Reasoning Steps**: 7
- **Key Concept**: Comparing antibiotic impacts on dysbiosis
- **Quality Score**: 5.0

### Question 4: SCFA and Barrier Function
- **Scenario**: Post-antibiotic recovery
- **Reasoning Steps**: 7
- **Key Concept**: Metabolite production in colonization resistance
- **Quality Score**: 5.0

### Question 5: VRE Bloodstream Infection
- **Scenario**: Hospital patient + secondary infection
- **Reasoning Steps**: 7
- **Key Concept**: Dysbiosis → reduced colonization resistance → bacteremia
- **Quality Score**: 5.0

---

## Validation Against Requirements

| Requirement | OLD Format | NEW Format |
|-------------|-----------|------------|
| Self-contained | ❌ | ✅ |
| No graph references | ❌ | ✅ |
| Multi-step reasoning (5-7 steps) | ⚠️ Partial | ✅ |
| Short-form answer | ❌ (Multiple choice) | ✅ |
| Domain-appropriate facts | ✅ | ✅ |
| Quantitative data | ⚠️ Limited | ✅ |
| Realistic scenarios | ⚠️ Partial | ✅ |
| Quality filtered (≥4.0) | Unknown | ✅ All 5.0 |

---

## Technical Changes Made

### 1. Updated Prompt (generate_contrastive_qa.py:48-95)
- Added FORBIDDEN list: graphs, weights, scores, external references
- Required realistic biological scenarios with quantitative data
- Specified 5-7 reasoning step requirement
- Changed from multiple choice to short-form answers

### 2. New Parser (_parse_open_ended_response)
- Extracts: question, reasoning_steps, correct_answer
- Replaces old A-H option parser

### 3. Updated Output Schema
```json
{
  "question": "Full question text",
  "reasoning_steps": ["Step 1", "Step 2", ...],
  "correct_answer": "Short paragraph answer",
  "analysis_type": "alternatives",
  "source_entities": ["ENTITY1", "ENTITY2"],
  "quality_score": 5.0
}
```

---

## Conclusion

The new format successfully addresses all the issues you identified:

1. ✅ **Graph independence**: No weights, scores, or structural metadata
2. ✅ **Self-contained**: All necessary facts embedded in question
3. ✅ **Deep reasoning**: Requires multi-step integration of information
4. ✅ **Short-form**: Tests ability to construct answers, not select them
5. ✅ **High quality**: All questions scored 5.0 (maximum)

The questions are now appropriate for assessment without access to the graph and test genuine scientific reasoning ability.
