# Pathway-Based Multi-Step Reasoning Questions - Design Document

## Overview

Design for generating multi-step reasoning questions based on causal pathway chains. This approach works across **ANY domain** that has causal directional relationships (CAUSES, ACTIVATES, INHIBITS, PRODUCES, LEADS_TO, etc.).

## Key Advantage: Domain-Agnostic

Unlike therapeutic alternatives (which requires specific entities like TREATMENT, BIOMARKER), pathway reasoning works for:
- **Molecular Biology**: GENE → PROTEIN → PATHWAY → PHENOTYPE
- **Microbial Biology**: ORGANISM → METABOLITE → ENVIRONMENTAL_CONDITION → PHENOTYPE
- **Infectious Disease**: PATHOGEN → VIRULENCE_FACTOR → HOST_RESPONSE → SYMPTOM
- **Disease Biology**: GENE → PROTEIN → PATHWAY → DISEASE
- **Ecology**: SPECIES → INTERACTION → COMMUNITY → ECOSYSTEM_FUNCTION
- **Epidemiology**: RISK_FACTOR → EXPOSURE → TRANSMISSION → OUTBREAK

**Any domain with causal chains can generate pathway questions.**

---

## Core Concept: Causal Pathway Chains

### What is a Causal Pathway?

A sequence of causal relationships forming a mechanistic chain:

```
A --[CAUSES/ACTIVATES/PRODUCES]--> B --[LEADS_TO/TRIGGERS]--> C --[RESULTS_IN]--> D
```

### Causal Relationship Types (Domain-Agnostic)

From `graph_validator.py:get_causal_edge_types()`, causal relationships are identified by keywords:
- `cause`, `activate`, `inhibit`, `produce`, `lead`, `result`
- `induce`, `suppress`, `promote`, `trigger`, `block`, `prevent`

**Standard causal types across domains:**
- `CAUSES` - A directly causes B
- `ACTIVATES` - A enhances/promotes B
- `INHIBITS` - A reduces/blocks B
- `PRODUCES` - A generates B
- `LEADS_TO` - A results in B
- `TRIGGERS` - A initiates B
- `SUPPRESSES` - A reduces B
- `PREVENTS` - A blocks B
- `PROMOTES` - A facilitates B

---

## Multi-Step Reasoning Architectures

### Architecture 1: Pathway Perturbation (7-9 steps)

**Pattern:** A → B → C → D, where blocking B affects D

**Reasoning Chain:**
1. Normal pathway: A activates B
2. B produces C
3. C leads to D (outcome)
4. Intervention blocks B
5. Blocking B prevents C production
6. Without C, D cannot occur
7. Alternative pathway may compensate
8. Evaluate net effect considering alternatives
9. **Decision**: Predict outcome when B is blocked

**Question Template:**
```
In [DOMAIN CONTEXT], the following causal pathway has been characterized:

[ENTITY_A] --[ACTIVATES]--> [ENTITY_B] --[PRODUCES]--> [ENTITY_C] --[LEADS_TO]--> [OUTCOME_D]

Experimental data shows:
- [ENTITY_A] activation increases [ENTITY_B] levels by [X%] within [timeframe]
- [ENTITY_B] directly produces [ENTITY_C] ([quantitative measurement])
- [ENTITY_C] is necessary and sufficient for [OUTCOME_D] ([evidence])

A perturbation experiment introduces [INTERVENTION] that completely blocks [ENTITY_B] activity
(confirmed by [assay] showing [quantitative result]).

Additionally, a compensatory pathway exists:
[ENTITY_E] --[ALTERNATIVE_RELATION]--> [ENTITY_C]

Under baseline conditions, [ENTITY_E] contributes [Y%] of total [ENTITY_C] production.
When [ENTITY_B] is blocked, [ENTITY_E] expression increases [Z-fold].

Given this information, what is the predicted effect on [OUTCOME_D], and what is the
mechanistic rationale considering both the primary pathway disruption and compensatory
activation?
```

**Reasoning Steps:**
- Step 1: Identify primary pathway A→B→C→D
- Step 2: Recognize B is completely blocked
- Step 3: Calculate reduction in C from primary pathway (100% loss of B's contribution)
- Step 4: Identify compensatory pathway E→C
- Step 5: Calculate baseline C contribution from E (Y%)
- Step 6: Factor in E upregulation (Z-fold increase)
- Step 7: Estimate total C levels (E pathway only, upregulated)
- Step 8: Determine if C levels sufficient for D
- Step 9: Integrate to predict D outcome

---

### Architecture 2: Competing Pathways (8-10 steps)

**Pattern:** Two parallel pathways (A→B→C and X→Y→C) both produce same outcome

**Reasoning Chain:**
1. Pathway 1: A → B → C (with quantitative contribution)
2. Pathway 2: X → Y → C (with quantitative contribution)
3. Both pathways converge at C
4. C triggers outcome D
5. Intervention affects one pathway
6. Other pathway compensates or dominates
7. Net C levels determine D
8. Kinetics matter (which pathway acts faster)
9. Context-dependent pathway preference
10. **Decision**: Predict which pathway dominates under condition Z

**Question Template:**
```
[DOMAIN_ENTITY_C] production occurs via two parallel pathways in [CONTEXT]:

**Pathway 1:**
[ENTITY_A] --[ACTIVATES]--> [ENTITY_B] --[PRODUCES]--> [ENTITY_C]
- Accounts for [X%] of total [ENTITY_C] under normal conditions
- Activation kinetics: peak [ENTITY_C] at [time T1]
- Requires [COFACTOR_1] ([availability status])

**Pathway 2:**
[ENTITY_X] --[TRIGGERS]--> [ENTITY_Y] --[GENERATES]--> [ENTITY_C]
- Accounts for [Y%] of total [ENTITY_C] under normal conditions
- Activation kinetics: peak [ENTITY_C] at [time T2]
- Requires [COFACTOR_2] ([availability status])

Both pathways contribute to [OUTCOME_D], which requires [ENTITY_C] levels above [threshold].

**Experimental Scenario:**
Condition Z is introduced, which:
- Reduces [ENTITY_A] availability by [%]
- Increases [ENTITY_X] expression [fold-change]
- [COFACTOR_1] levels remain stable
- [COFACTOR_2] levels increase by [%]

Measurements at time [T_critical]:
- [ENTITY_A]: [reduced level]
- [ENTITY_X]: [elevated level]
- Previous studies show: Pathway 2 response is delayed but sustained,
  while Pathway 1 response is rapid but transient

Will [OUTCOME_D] occur under Condition Z? Provide mechanistic rationale considering
pathway kinetics, entity availability, and cofactor requirements.
```

**Reasoning Steps:**
- Step 1: Calculate Pathway 1 output under condition Z (reduced A)
- Step 2: Calculate Pathway 2 output under condition Z (increased X)
- Step 3: Consider cofactor availability for each pathway
- Step 4: Factor in temporal kinetics (when does each peak)
- Step 5: Determine total C at critical timepoint T_critical
- Step 6: Compare to threshold for outcome D
- Step 7: Evaluate if rapid but reduced Pathway 1 + delayed but enhanced Pathway 2 meets threshold
- Step 8: Consider pathway dominance based on entity levels
- Step 9: Integrate kinetics + levels + cofactors
- Step 10: Predict outcome D occurrence (yes/no with rationale)

---

### Architecture 3: Sequential Pathway with Feedback (9-11 steps)

**Pattern:** A → B → C → D, where D inhibits A (negative feedback)

**Reasoning Chain:**
1. Forward pathway: A activates B
2. B produces C
3. C generates D
4. D inhibits A (feedback loop)
5. Initial perturbation increases A
6. Increased A → increased D (via pathway)
7. Increased D → feedback inhibition of A
8. System reaches new steady state
9. Net effect depends on feedback strength
10. Timepoint matters (transient vs steady-state)
11. **Decision**: Predict D levels at early vs late timepoints

**Question Template:**
```
A regulatory pathway in [DOMAIN] exhibits negative feedback:

**Forward Pathway:**
[ENTITY_A] --[ACTIVATES]--> [ENTITY_B] ([kinetic parameter k1])
[ENTITY_B] --[PRODUCES]--> [ENTITY_C] ([kinetic parameter k2])
[ENTITY_C] --[GENERATES]--> [ENTITY_D] ([kinetic parameter k3])

**Feedback Loop:**
[ENTITY_D] --[INHIBITS]--> [ENTITY_A] ([inhibition constant Ki])

Under steady-state conditions:
- [ENTITY_A]: baseline level [A₀]
- [ENTITY_D]: baseline level [D₀]
- Feedback inhibition reduces [ENTITY_A] activity by [%] when [ENTITY_D] doubles

**Perturbation:**
An intervention at t=0 increases [ENTITY_A] production by [fold-change],
sustained for [duration].

Kinetic parameters:
- Time to half-maximal [ENTITY_B] activation: [τ1]
- Time to half-maximal [ENTITY_C] accumulation: [τ2]
- Time to half-maximal [ENTITY_D] accumulation: [τ3]
- Feedback inhibition delay: [τ_feedback]

What are the predicted levels of [ENTITY_D] at:
1. Early timepoint (t = [τ3]), before feedback fully engages
2. Late timepoint (t = [5× τ_feedback]), after new steady-state

Provide mechanistic reasoning considering forward pathway kinetics and feedback strength.
```

**Reasoning Steps:**
- Step 1: Increased A → increased B (forward propagation)
- Step 2: Increased B → increased C (forward propagation)
- Step 3: Increased C → increased D (forward propagation)
- Step 4: At early time t=τ3, feedback not yet active
- Step 5: Calculate D at early time (no feedback, maximal forward drive)
- Step 6: D accumulates and begins inhibiting A
- Step 7: Reduced A → reduced forward flux through pathway
- Step 8: New steady-state balances: increased A production vs feedback inhibition
- Step 9: Calculate steady-state D (reduced from early peak)
- Step 10: Compare early vs late D levels
- Step 11: Predict biphasic response (early spike, late attenuation)

---

### Architecture 4: Pathway Branch Point (7-9 steps)

**Pattern:** A → B, then B → C1 (outcome 1) OR B → C2 (outcome 2), depending on conditions

**Reasoning Chain:**
1. Common pathway: A activates B
2. B can activate either C1 or C2
3. C1 leads to outcome O1
4. C2 leads to outcome O2
5. Context X favors B→C1
6. Context Y favors B→C2
7. Intervention changes context
8. Pathway switches from C1 to C2 branch
9. **Decision**: Predict which outcome (O1 vs O2) under intervention

**Question Template:**
```
[ENTITY_B] in [DOMAIN] acts as a branch point in a regulatory pathway:

**Upstream:**
[ENTITY_A] --[ACTIVATES]--> [ENTITY_B]

**Branch Point:**
Under Condition X: [ENTITY_B] --[ACTIVATES]--> [ENTITY_C1] --[LEADS_TO]--> [OUTCOME_O1]
Under Condition Y: [ENTITY_B] --[ACTIVATES]--> [ENTITY_C2] --[LEADS_TO]--> [OUTCOME_O2]

**Mechanistic Basis for Branch Selection:**
- Condition X: [COFACTOR_X] is present ([concentration]), which promotes B→C1 ([mechanism])
- Condition Y: [COFACTOR_Y] is present ([concentration]), which promotes B→C2 ([mechanism])
- [ENTITY_B] has [structural feature] that responds to [cofactor type]

**Experimental Data:**
Baseline state: Condition X (Cofactor X present at [level])
- [OUTCOME_O1]: occurs in [%] of cases
- [OUTCOME_O2]: occurs in [%] of cases

**Intervention:**
Treatment with [AGENT] causes:
- [COFACTOR_X] reduction from [baseline] to [reduced level] (below threshold for B→C1)
- [COFACTOR_Y] increase from [baseline] to [elevated level] (above threshold for B→C2)
- [ENTITY_A] levels remain unchanged
- [ENTITY_B] total levels remain unchanged

Given that:
- B→C1 requires Cofactor X > [threshold T_x]
- B→C2 requires Cofactor Y > [threshold T_y]
- B→C1 and B→C2 are mutually exclusive

What is the predicted outcome after [AGENT] treatment, and what is the mechanistic
rationale based on cofactor levels and branch selection rules?
```

**Reasoning Steps:**
- Step 1: Recognize B is branch point with two outcomes
- Step 2: Identify baseline cofactor levels favor pathway to C1/O1
- Step 3: Intervention reduces Cofactor X below T_x threshold
- Step 4: Intervention increases Cofactor Y above T_y threshold
- Step 5: B→C1 pathway no longer active (cofactor insufficient)
- Step 6: B→C2 pathway becomes active (cofactor sufficient)
- Step 7: B levels unchanged (upstream A unchanged), so flux through B constant
- Step 8: All B flux now directed to C2 instead of C1
- Step 9: Predict switch from O1 to O2

---

## Implementation Strategy

### 1. Graph Analysis: Find Causal Pathway Chains

```python
def find_causal_pathway_chains(graph, domain_name, min_length=3, max_length=5):
    """
    Find linear causal chains of specified length.

    Returns:
    - Simple chains: A → B → C → D
    - Converging pathways: (A → B → C) + (X → Y → C)
    - Feedback loops: A → B → C → D --inhibits--> A
    - Branch points: A → B, then B → (C1 | C2)
    """

    causal_types = get_causal_edge_types(domain_name)

    # Find simple chains
    simple_chains = find_simple_causal_chains(graph, causal_types, min_length, max_length)

    # Find converging pathways (two chains ending at same node)
    converging = find_converging_pathways(graph, causal_types, min_length)

    # Find feedback loops (chain where last node connects back to first)
    feedback_loops = find_feedback_loops(graph, causal_types, min_length, max_length)

    # Find branch points (node with multiple outgoing causal edges)
    branch_points = find_branch_points(graph, causal_types)

    return {
        'simple_chains': simple_chains,
        'converging_pathways': converging,
        'feedback_loops': feedback_loops,
        'branch_points': branch_points
    }
```

### 2. Entity Context Extraction

For each pathway chain, extract rich context:

```python
def extract_pathway_context(graph, pathway_chain):
    """
    For chain A → B → C → D, extract:
    - Entity types (e.g., GENE → PROTEIN → PATHWAY → PHENOTYPE)
    - Relationship types (ACTIVATES, PRODUCES, LEADS_TO)
    - Entity descriptions from graph attributes
    - Quantitative edge weights if available (but don't expose in question!)
    - Neighboring nodes that might provide compensatory pathways
    - Feedback connections
    """

    context = {
        'entities': [],
        'relationships': [],
        'compensatory_paths': [],
        'feedback_edges': []
    }

    # Extract entity info for each node in chain
    for node in pathway_chain:
        context['entities'].append({
            'id': node,
            'label': graph.nodes[node].get('label'),
            'type': graph.nodes[node].get('entity_type'),
            'description': graph.nodes[node].get('description', '')
        })

    # Extract relationship info for each edge
    for i in range(len(pathway_chain) - 1):
        src, tgt = pathway_chain[i], pathway_chain[i+1]
        edge_data = graph.get_edge_data(src, tgt)
        context['relationships'].append({
            'source': src,
            'target': tgt,
            'type': edge_data.get('relation_type'),
            'description': edge_data.get('description', '')
        })

    return context
```

### 3. Question Generation Prompt

```python
async def generate_pathway_question(pathway_data, domain_name):
    """
    Generate question from pathway chain.
    """

    prompt = f"""Generate a multi-step reasoning question based on a causal pathway
in the domain of {domain_name}.

CRITICAL REQUIREMENTS:
1. COMPLETELY SELF-CONTAINED - Provide all necessary facts, mechanisms, and data
2. NO GRAPH REFERENCES - Never mention "weights", "graph", "nodes", "edges"
3. MULTI-STEP REASONING - Require 7-10 logical reasoning steps
4. SHORT-FORM ANSWER - Brief answer (2-4 sentences) derived through reasoning
5. CAUSAL PATHWAY FOCUS - Question tests understanding of pathway propagation

PATHWAY STRUCTURE:
{json.dumps(pathway_data, indent=2)}

PATHWAY TYPE: {pathway_data['type']}  # simple_chain | converging | feedback | branch

QUESTION PATTERNS BY TYPE:

For SIMPLE_CHAIN (A → B → C → D):
- Perturbation: What happens to D when B is blocked?
- Requires reasoning through cascade: B blocked → C reduced → D reduced
- Include compensatory pathway to add complexity

For CONVERGING (A→B→C + X→Y→C):
- Competition: If pathway 1 is reduced, can pathway 2 compensate?
- Requires calculating net C from both sources

For FEEDBACK (A → B → C → D --inhibits--> A):
- Dynamics: Predict early vs late effects after perturbing A
- Requires understanding feedback creates biphasic response

For BRANCH (A → B, then B→C1 or B→C2):
- Switching: What determines which branch is taken?
- Requires identifying cofactor/condition that controls branch

REQUIREMENTS:
- Use domain-appropriate entity types ({domain_name})
- Embed quantitative data (%, fold-change, timepoints, thresholds)
- Create realistic scenario with experimental context
- Require integrating multiple facts
- Answer derivable from given information

Output format:
QUESTION: [multi-step pathway reasoning question with embedded data]

EXPECTED_REASONING_STEPS: [7-10 bullet points showing logical chain]

CORRECT_ANSWER: [2-4 sentence answer integrating pathway logic]
"""

    response = await llm.call_async(prompt)
    return _parse_open_ended_response(response)
```

### 4. Quality Criteria

**Pathway-specific quality requirements:**

1. **Pathway Clarity**: Question clearly describes causal chain
2. **Mechanistic Depth**: Requires understanding propagation through pathway
3. **Quantitative Integration**: Uses specific measurements/thresholds
4. **Perturbation Logic**: Tests ability to predict intervention effects
5. **Multi-Step**: ≥ 7 reasoning steps required
6. **Self-Contained**: No graph knowledge needed
7. **Domain-Appropriate**: Uses correct entity types for domain

**Scoring threshold: ≥ 4.0** (same as contrastive)

---

## Domain Examples

### Molecular Biology
```
GENE → ACTIVATES → PROTEIN → PHOSPHORYLATES → ENZYME → CATALYZES → METABOLITE
```
**Question**: If GENE is overexpressed 3-fold, predict METABOLITE levels considering
feedback inhibition of GENE by METABOLITE (Ki = X).

### Infectious Disease
```
PATHOGEN → PRODUCES → TOXIN → CAUSES → TISSUE_DAMAGE → TRIGGERS → SYMPTOM
```
**Question**: If TOXIN production is blocked by antibiotic, predict SYMPTOM severity
considering residual pre-formed TOXIN (half-life = Y hours).

### Microbial Biology
```
BACTERIUM → CONSUMES → SUBSTRATE → PRODUCES → METABOLITE → INHIBITS → COMPETITOR
```
**Question**: If SUBSTRATE availability drops by Z%, predict COMPETITOR growth
considering alternative metabolite production pathway.

---

## Advantages Over Other Approaches

| Feature | Contrastive Alternatives | Therapeutic Alternatives | Pathway Reasoning |
|---------|-------------------------|-------------------------|-------------------|
| Domain-agnostic | ✅ (any domain) | ❌ (needs TREATMENT, BIOMARKER) | ✅ (any domain with causal edges) |
| Mechanistic depth | ⚠️ (comparison) | ✅ (very high) | ✅ (very high) |
| Reasoning steps | 5-7 | 8-10+ | 7-10 |
| Graph independence | ✅ | ✅ | ✅ |
| Implementation complexity | Low | High (requires many entity types) | Medium |
| Applicability | All domains | Disease/clinical domains only | All domains |

**Pathway reasoning wins because it:**
1. Works for ALL domains (only needs causal relationships)
2. Achieves high reasoning complexity (7-10 steps)
3. Tests mechanistic understanding (propagation, feedback, compensation)
4. Medium implementation complexity (simpler than therapeutic)

---

## Next Steps

1. Implement `find_causal_pathway_chains()` in new file `pathway_analysis.py`
2. Create `generate_pathway_qa.py` using same structure as `generate_contrastive_qa.py`
3. Add pathway-specific prompts for each architecture type
4. Test on molecular_biology domain first (rich causal relationships)
5. Validate generates 7-10 reasoning steps consistently
6. Test on other domains (microbial_biology, infectious_disease) to confirm domain-agnostic operation
