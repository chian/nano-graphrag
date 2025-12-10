"""
Stage 6: Generate Contrastive Reasoning Questions
Uses GASL contrastive commands to analyze enriched graph and generate reasoning questions
"""

import argparse
import asyncio
import json
import os
import sys
import random
from pathlib import Path
from typing import Dict, List

import networkx as nx

sys.path.insert(0, str(Path(__file__).parent.absolute()))

from domain_schemas.schema_loader import load_domain_schema
from gasl.llm import ArgoBridgeLLM
from gasl.adapters import NetworkXAdapter
from gasl.state import StateStore, ContextStore
from gasl.executor import Command
from gasl.commands.contrastive import (
    FindAlternativesHandler,
    FindOpposingHandler,
    CompareMechanismsHandler,
    FindCompetingHandler
)
from nano_graphrag._utils import convert_response_to_json
from question_enrichment import QuestionEnricher


def sanitize_analysis_for_prompt(analysis_data: dict, graph: nx.DiGraph) -> dict:
    """
    Remove graph metadata and keep only domain-relevant information.

    Removes: weight, relation_type, source_papers, edge-specific data
    Keeps: entity names, descriptions, biological context
    """
    sanitized = {}

    if isinstance(analysis_data, dict):
        for key, value in analysis_data.items():
            # Skip graph-specific metadata
            if key in ['weight', 'relation_type', 'source_papers', 'causal_weight', 'edge_type']:
                continue

            # Recursively sanitize nested structures
            if isinstance(value, dict):
                sanitized[key] = sanitize_analysis_for_prompt(value, graph)
            elif isinstance(value, list):
                sanitized[key] = [
                    sanitize_analysis_for_prompt(item, graph) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized[key] = value

    return sanitized


class ContrastiveQuestionGenerator:
    """Generate contrastive reasoning questions using LLM."""

    def __init__(self, llm: ArgoBridgeLLM):
        self.llm = llm

    async def generate(
        self,
        analysis_type: str,
        analysis_data: dict,
        domain_name: str,
        entity_context: str
    ) -> dict:
        """Generate a question from analysis data."""

        prompt = f"""Generate a multi-step reasoning question for the domain of {domain_name}.

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
{json.dumps(analysis_data, indent=2)}

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

CORRECT_ANSWER: [1-20 word specific answer]"""

        response = await self.llm.call_async(prompt)

        # Parse response to extract question, reasoning steps, and answer
        result = self._parse_open_ended_response(response)

        return result

    def _parse_open_ended_response(self, response: str) -> dict:
        """Parse LLM response to extract question, reasoning steps, and answer."""

        question_text = ""
        reasoning_steps = []
        correct_answer = ""

        lines = response.strip().split('\n')
        current_section = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Detect section headers
            if line.startswith('QUESTION:'):
                current_section = 'question'
                question_text = line.replace('QUESTION:', '').strip()
            elif line.startswith('EXPECTED_REASONING_STEPS:'):
                current_section = 'reasoning'
                remaining = line.replace('EXPECTED_REASONING_STEPS:', '').strip()
                if remaining:
                    reasoning_steps.append(remaining)
            elif line.startswith('CORRECT_ANSWER:'):
                current_section = 'answer'
                correct_answer = line.replace('CORRECT_ANSWER:', '').strip()
            elif current_section == 'question':
                question_text += " " + line
            elif current_section == 'reasoning':
                # Collect reasoning steps (typically bullet points)
                if line.startswith('-') or line.startswith('•') or line.startswith('*'):
                    reasoning_steps.append(line.lstrip('-•* '))
                else:
                    reasoning_steps.append(line)
            elif current_section == 'answer':
                correct_answer += " " + line

        return {
            'question': question_text.strip(),
            'reasoning_steps': reasoning_steps,
            'correct_answer': correct_answer.strip()
        }

    def _parse_question_response(self, response: str) -> dict:
        """Parse LLM response to extract question and options (legacy method)."""

        lines = response.strip().split('\n')
        question_text = ""
        options = {}

        current_option = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if it's an option line (A), B), etc.)
            if len(line) > 2 and line[0] in 'ABCDEFGH' and line[1] in '):':
                current_option = line[0]
                option_text = line[2:].strip()
                options[current_option] = option_text
            elif current_option and line:
                # Continuation of current option
                options[current_option] += " " + line
            elif not options:
                # Before options started, this is question text
                question_text += " " + line

        return {
            'question': question_text.strip(),
            'options': options
        }


async def filter_question_quality(llm: ArgoBridgeLLM, question_text: str, analysis_type: str) -> dict:
    """Filter questions using the same scoring scheme as generate_reasoning_qa_gasl.py"""

    # Hard disqualifiers
    lower_q = question_text.lower()
    auto_disqualifiers = [
        "the text", "the passage", "the document", "the paper", "the study",
        "according to", "as mentioned", "as described",
        "appendix", "figure", "table", "section", "chapter",
        "above", "below", "previously mentioned", "following",
        "unknown answer", "answer is unknown"
    ]
    if any(p in lower_q for p in auto_disqualifiers):
        return {"score": 0.0, "critique": "auto-disqualified (external reference/unknown)", "passed": False}

    filter_prompt = f"""Evaluate the text below according to the scoring instruction and criteria.

## Scoring Instruction
1. Evaluate the text on each criteria step by step. Provide your honest answer to each sub-question. If the answer to a sub-question is a confident Yes, add or subtract the points corresponding to the criteria.
2. Keep track of the running points from each criteria to get the total score.
3. Summarize your final evaluation results in a valid JSON object following the instruction below.

### Scoring Criteria
Criteria 1: Problem Completeness
- The content does not have clear main question, or enough clues to derive the correct answer. (0 point)
- The content includes a main question, and enough clues to derive the correct answer. (+1 point)
- The text shows evidence of engagement and discussion among multiple authors, including proposing answers, evaluating and reflecting on answers, responding to critiques, revising and editing answers. (+1 point)

Criteria 2: Problem Complexity and Technical Depth
- The difficulty of the content is college-level or below. (0 point)
- The difficulty of the content is graduate-level or above, and only domain experts can understand. (+1 point)
- The question being discussed is so challenging that even highly skilled non-experts would not be able to fully understand the question or provide a correct answer, even after spending 30 minutes searching the internet or reading up literature. (+1 point)

Criteria 3: Technical Correctness and Accuracy
- The text contains significant technical errors or inaccuracies. (-1 point)
- The text demonstrates some technical correctness, but with notable flaws or omissions. (0 point)
- The text demonstrates technical correctness, with some minor flaws or omissions. (+0.5 point)
- The text demonstrates high technical correctness, with clear and accurate explanations. (+0.5 point)
- The text exemplifies exceptional technical correctness, with rigorous and precise explanations. (+1 point)

Criteria 4: Thinking and Reasoning
- The text lacks any evidence of thinking or reasoning. (-1 point)
- The text demonstrates some basic thinking and reasoning (+0.5 point).
- The text demonstrates some thinking and reasoning (+0.5 point), considering multiple approaches or trade-offs.
- The text demonstrates significant thinking and reasoning (+1 point), such as multi-step chains or advanced patterns.
- The text exemplifies exceptional thinking and reasoning (+1 point), combining multiple techniques with novel abstraction.

## Instruction on Final Report
Follow the reporting format from the criteria prompt. Penalize any reference to external materials (e.g., 'the text', 'the paper', 'as mentioned', 'Figure', 'Table', 'Section'). Reward clarity, biological relevance, self-containment, and answer specificity.

At the end, output ONLY a JSON object with these fields:
- "scores": array of objects with "criteria" and "score" fields
- "Total Score": numeric total score

### Analysis Context
Type: {analysis_type}

### Text
{question_text}
"""

    response = await llm.call_async(filter_prompt)

    # Parse JSON block and compute raw total score
    try:
        result = convert_response_to_json(response)

        if not result:
            return {"score": 0, "critique": "Parse error", "passed": False}

        # Initialize subscores
        completeness = 0.0
        depth = 0.0
        correctness = 0.0
        reasoning = 0.0
        total_raw = 0.0

        # Case 1: scores list schema
        scores_list = result.get("scores", [])
        used_scores_list = False

        def pick_score(match_substring: str) -> float:
            for entry in scores_list:
                label = str(entry.get("criteria") or entry.get("criterion") or "").lower()
                if label and match_substring in label:
                    try:
                        return float(entry.get("score", 0))
                    except (TypeError, ValueError):
                        return 0.0
                # Case B: entry is like {"Problem Completeness": 2}
                if not label and isinstance(entry, dict) and len(entry) == 1:
                    k, v = next(iter(entry.items()))
                    if match_substring in str(k).lower():
                        try:
                            return float(v)
                        except (TypeError, ValueError):
                            return 0.0
            return 0.0

        if scores_list:
            used_scores_list = True
            completeness = pick_score("complete")
            depth = pick_score("complex") or pick_score("depth")
            correctness = pick_score("correct") or pick_score("accuracy")
            reasoning = pick_score("reason")
            for entry in scores_list:
                if isinstance(entry, dict):
                    if "score" in entry:
                        try:
                            total_raw += float(entry.get("score", 0))
                            continue
                        except (TypeError, ValueError):
                            pass
                    if len(entry) == 1:
                        _, v = next(iter(entry.items()))
                        try:
                            total_raw += float(v)
                            continue
                        except (TypeError, ValueError):
                            pass

        # Case 2: nested Evaluation object with Points
        if not used_scores_list and isinstance(result.get("Evaluation"), dict):
            ev = result["Evaluation"]
            def get_points(container: dict, key: str) -> float:
                try:
                    item = container.get(key, {})
                    if isinstance(item, dict) and "Points" in item:
                        return float(item.get("Points", 0) or 0)
                    if isinstance(item, (int, float)):
                        return float(item)
                    return 0.0
                except Exception:
                    return 0.0
            completeness = get_points(ev, "Problem Completeness")
            depth = get_points(ev, "Problem Complexity and Technical Depth")
            correctness = get_points(ev, "Technical Correctness and Accuracy")
            reasoning = get_points(ev, "Thinking and Reasoning")
            try:
                total_raw = float(ev.get("Total Score", 0) or 0)
            except Exception:
                total_raw = completeness + depth + correctness + reasoning

        # Case 3: flat top-level numeric fields
        if not used_scores_list and total_raw == 0.0:
            def get_top(name: str) -> float:
                try:
                    return float(result.get(name, 0) or 0)
                except Exception:
                    return 0.0
            c = get_top("Problem Completeness")
            d = get_top("Problem Complexity and Technical Depth")
            k = get_top("Technical Correctness and Accuracy")
            r = get_top("Thinking and Reasoning")
            if any([c, d, k, r]):
                completeness = c
                depth = d
                correctness = k
                reasoning = r
                ts = get_top("Total Score")
                total_raw = ts if ts > 0 else (completeness + depth + correctness + reasoning)

        # Use raw total score directly (no normalization)
        score_value = float(total_raw)
        difficulty = result.get("question_difficulty", "")
        parts = []
        if difficulty:
            parts.append(f"difficulty={difficulty}")
        parts.append(f"completeness={completeness}")
        parts.append(f"depth={depth}")
        parts.append(f"correctness={correctness}")
        parts.append(f"reasoning={reasoning}")
        critique = ", ".join(parts)

        # Accept if raw total score is at least 4 (same as generate_reasoning_qa_gasl.py)
        passed = total_raw >= 4
        return {"score": score_value, "critique": critique, "passed": passed}
    except Exception as e:
        print(f"Warning: Could not parse filter response: {e}")
        return {"score": 0, "critique": "Parse error", "passed": False}


async def validate_self_containment(llm: ArgoBridgeLLM, question: str, answer: str) -> dict:
    """
    Validate that the question is completely self-contained and answerable without external context.

    Returns:
        dict with is_self_contained (bool), missing_information (list), external_references (list)
    """
    validation_prompt = f"""You are a domain expert evaluating whether a question is completely self-contained.

A self-contained question provides ALL information needed to derive the answer through reasoning alone.

QUESTION:
{question}

EXPECTED ANSWER:
{answer}

Evaluate these criteria:
1. Are ALL necessary scientific facts, mechanisms, and principles stated explicitly in the question?
2. Are ALL experimental values, conditions, parameters, and data points provided?
3. Could a domain expert answer this question WITHOUT access to any papers, graphs, figures, or external materials?
4. Are there any implicit references to "the graph", "the study", "the text", or unstated context?
5. Does the question assume knowledge of specific experimental results not mentioned in the question text?

Output ONLY a JSON object:
{{
  "is_self_contained": true/false,
  "missing_information": ["list of facts or data that are required but not stated in the question"],
  "external_references": ["list of any implicit references to external materials"],
  "confidence": "high/medium/low"
}}"""

    response = await llm.call_async(validation_prompt)

    try:
        result = convert_response_to_json(response)
        if not result:
            return {"is_self_contained": False, "missing_information": ["Parse error"], "external_references": []}

        return {
            "is_self_contained": result.get("is_self_contained", False),
            "missing_information": result.get("missing_information", []),
            "external_references": result.get("external_references", []),
            "confidence": result.get("confidence", "unknown")
        }
    except Exception as e:
        print(f"Warning: Could not parse self-containment validation: {e}")
        return {"is_self_contained": False, "missing_information": ["Parse error"], "external_references": []}


async def validate_answer_gradability(llm: ArgoBridgeLLM, answer: str) -> dict:
    """
    Validate that the answer is in a short, gradable format suitable for exact/near-exact matching.

    Returns:
        dict with is_gradable (bool), word_count (int), format_type (str), reason (str)
    """
    validation_prompt = f"""Evaluate if this answer is in a SHORT, GRADABLE format suitable for automated exact matching.

ANSWER:
{answer}

Criteria for GRADABLE answers:
1. Word count: 1-20 words (strict requirement)
2. Format type must be ONE of:
   - entity_name: A specific molecule, gene, protein, species name
   - mechanism: A specific biological process or pathway
   - yes_no: Yes or No with optional brief justification (≤5 words)
   - numerical: A specific number or quantitative comparison
   - term: A specific scientific/technical term
3. NOT a paragraph, NOT multiple sentences of explanation
4. Can be graded by simple string matching or pattern matching

Examples of GRADABLE answers:
- "Coculture" (entity_name, 1 word)
- "Carbapenems" (entity_name, 1 word)
- "Cross-feeding via acetate" (mechanism, 3 words)
- "No - lacks xylan degradation genes" (yes_no, 5 words)
- "95% in coculture vs 60% monoculture" (numerical, 6 words)

Examples of NOT GRADABLE answers:
- "Coculture should be prioritized because it leads to more complete carbohydrate consumption and significantly higher SCFA production..." (paragraph, >20 words)
- "The mechanism involves multiple steps including initial breakdown by P. dorei followed by cross-feeding..." (explanation, >20 words)

Count the words and classify the format.

Output ONLY a JSON object:
{{
  "is_gradable": true/false,
  "word_count": N,
  "format_type": "entity_name|mechanism|yes_no|numerical|term|paragraph|explanation",
  "reason": "brief explanation of why gradable or not gradable"
}}"""

    response = await llm.call_async(validation_prompt)

    try:
        result = convert_response_to_json(response)
        if not result:
            return {"is_gradable": False, "word_count": 0, "format_type": "unknown", "reason": "Parse error"}

        word_count = result.get("word_count", len(answer.split()))

        # Hard limit: >20 words = not gradable
        is_gradable = result.get("is_gradable", False) and word_count <= 20

        return {
            "is_gradable": is_gradable,
            "word_count": word_count,
            "format_type": result.get("format_type", "unknown"),
            "reason": result.get("reason", "")
        }
    except Exception as e:
        print(f"Warning: Could not parse gradability validation: {e}")
        # Fallback: simple word count check
        word_count = len(answer.split())
        return {
            "is_gradable": word_count <= 20,
            "word_count": word_count,
            "format_type": "unknown",
            "reason": f"Parse error, fallback word count: {word_count}"
        }



async def analyze_graph_with_gasl(
    graph: nx.DiGraph,
    domain_name: str,
    llm: ArgoBridgeLLM
) -> Dict[str, List]:
    """Use GASL contrastive commands to analyze the graph."""

    print(f"\n{'='*60}")
    print(f"Running GASL Contrastive Analysis")
    print(f"{'='*60}\n")

    # Initialize GASL components
    state_store = StateStore()
    context_store = ContextStore()
    adapter = NetworkXAdapter(graph)

    # Initialize handlers
    alternatives_handler = FindAlternativesHandler(state_store, context_store, adapter, domain_name)
    opposing_handler = FindOpposingHandler(state_store, context_store, adapter, domain_name)
    compare_handler = CompareMechanismsHandler(state_store, context_store, adapter, domain_name)
    competing_handler = FindCompetingHandler(state_store, context_store, adapter, domain_name)

    analyses = {
        'alternatives': [],
        'opposing': [],
        'comparisons': [],
        'competing': []
    }

    # Get sample of nodes for analysis
    nodes = list(graph.nodes())[:20]  # Analyze first 20 nodes

    print(f"Analyzing {len(nodes)} nodes for contrastive patterns...\n")

    # Find alternatives
    print("1. Finding alternative mechanisms...")
    for node in nodes:
        cmd = Command(
            command_type="FIND_ALTERNATIVES",
            raw_text=f"FIND_ALTERNATIVES {node} {domain_name}",
            args={"target_entity": node, "result_var": f"alts_{node}"},
            line_number=0
        )

        result = alternatives_handler.execute(cmd)
        if result and result.data:
            analyses['alternatives'].append({
                'target': node,
                'alternatives': result.data
            })

    print(f"  Found {len(analyses['alternatives'])} nodes with alternatives\n")

    # Find opposing entities
    print("2. Finding opposing effects...")
    for node in nodes:
        cmd = Command(
            command_type="FIND_OPPOSING",
            raw_text=f"FIND_OPPOSING {node} {domain_name}",
            args={"entity": node, "result_var": f"opp_{node}"},
            line_number=0
        )

        result = opposing_handler.execute(cmd)
        if result and result.data:
            analyses['opposing'].append({
                'entity': node,
                'opposing_pairs': result.data
            })

    print(f"  Found {len(analyses['opposing'])} nodes with opposing effects\n")

    # Compare mechanisms (for nodes with alternatives)
    print("3. Comparing mechanisms...")
    for alt_analysis in analyses['alternatives'][:10]:  # Limit to 10 comparisons
        target = alt_analysis['target']
        alternatives = alt_analysis['alternatives']

        if len(alternatives) >= 2:
            mech1 = alternatives[0]['entity']
            mech2 = alternatives[1]['entity']

            cmd = Command(
                command_type="COMPARE_MECHANISMS",
                raw_text=f"COMPARE_MECHANISMS {mech1} {mech2} {target} {domain_name}",
                args={
                    "mechanism1": mech1,
                    "mechanism2": mech2,
                    "target": target,
                    "result_var": f"cmp_{mech1}_{mech2}"
                },
                line_number=0
            )

            result = compare_handler.execute(cmd)
            if result and result.data:
                analyses['comparisons'].append({
                    'mechanism1': mech1,
                    'mechanism2': mech2,
                    'target': target,
                    'comparison': result.data
                })

    print(f"  Generated {len(analyses['comparisons'])} mechanism comparisons\n")

    # Find competing entities
    print("4. Finding competing entities...")
    for node in nodes:
        cmd = Command(
            command_type="FIND_COMPETING",
            raw_text=f"FIND_COMPETING {node} {domain_name}",
            args={"entity": node, "result_var": f"comp_{node}"},
            line_number=0
        )

        result = competing_handler.execute(cmd)
        if result and result.data:
            analyses['competing'].append({
                'entity': node,
                'competing_entities': result.data
            })

    print(f"  Found {len(analyses['competing'])} nodes with competing entities\n")

    print(f"{'='*60}")
    print(f"GASL Analysis Complete")
    print(f"{'='*60}\n")
    print(f"Summary:")
    print(f"  - Alternatives: {len(analyses['alternatives'])}")
    print(f"  - Opposing: {len(analyses['opposing'])}")
    print(f"  - Comparisons: {len(analyses['comparisons'])}")
    print(f"  - Competing: {len(analyses['competing'])}")
    print()

    return analyses


def get_entity_context(graph: nx.DiGraph, entity_name: str, max_length: int = 500) -> str:
    """Get context about an entity from the graph."""

    if entity_name not in graph.nodes:
        return f"Entity: {entity_name}"

    node_data = graph.nodes[entity_name]

    context_parts = [f"Entity: {entity_name}"]

    # Add entity type
    if 'entity_type' in node_data:
        context_parts.append(f"Type: {node_data['entity_type']}")

    # Add description
    if 'description' in node_data:
        desc = str(node_data['description'])[:200]
        context_parts.append(f"Description: {desc}")

    # Add neighbors
    neighbors = list(graph.neighbors(entity_name))[:5]
    if neighbors:
        context_parts.append(f"Connected to: {', '.join(neighbors[:3])}")

    context = "\n".join(context_parts)

    return context[:max_length]


async def generate_questions_from_analyses(
    analyses: Dict[str, List],
    graph: nx.DiGraph,
    domain_name: str,
    llm: ArgoBridgeLLM,
    max_questions: int = 20,
    enrich_info_pieces: int = 0,
    enrich_graph_depth: int = 1
) -> List[Dict]:
    """
    Generate contrastive questions from GASL analysis results with quality filtering.

    Uses random selection for diversity and retries to get enough high-quality questions.
    Similar pattern to generate_reasoning_qa_gasl.py.
    """

    print(f"\n{'='*60}")
    print(f"Generating Contrastive Questions with Quality Filtering")
    print(f"{'='*60}\n")

    # Initialize enricher (can be disabled by setting enrich_info_pieces=0)
    enricher = QuestionEnricher(
        graph=graph,
        llm=llm,
        num_info_pieces=enrich_info_pieces,
        graph_depth=enrich_graph_depth
    )

    if enricher.is_enabled():
        print(f"Question Enrichment: ENABLED")
        print(f"  - Info pieces per question: {enrich_info_pieces}")
        print(f"  - Graph search depth: {enrich_graph_depth}\n")
    else:
        print(f"Question Enrichment: DISABLED\n")

    generator = ContrastiveQuestionGenerator(llm)
    questions = []
    used_entity_sets = set()  # Track which entity combinations have been used

    attempts = 0
    max_attempts = max_questions * 3  # Try up to 3x to get enough good questions

    # Combine all analyses into a pool for random selection
    analysis_pool = []

    for analysis in analyses["alternatives"]:
        analysis_pool.append(("alternatives", analysis))

    for analysis in analyses["comparisons"]:
        analysis_pool.append(("comparison", analysis))

    for analysis in analyses["competing"]:
        analysis_pool.append(("competing", analysis))

    if not analysis_pool:
        print("No contrastive patterns found to generate questions from.\n")
        return questions

    print(f"Total analysis pool size: {len(analysis_pool)}")
    print(f"Target: {max_questions} high-quality questions\n")

    while len(questions) < max_questions and attempts < max_attempts:
        attempts += 1

        # Random selection for diversity (same as generate_reasoning_qa_gasl.py)
        analysis_type, analysis = random.choice(analysis_pool)

        # Get entity context
        if analysis_type == "alternatives":
            entity_name = analysis['target']
        elif analysis_type == "comparison":
            entity_name = analysis['target']
        elif analysis_type == "competing":
            entity_name = analysis['entity']
        else:
            entity_name = ""

        # Extract source entities for deduplication
        source_entities = []
        if analysis_type == "alternatives":
            source_entities = [analysis['target']] + [alt['entity'] for alt in analysis.get('alternatives', [])]
        elif analysis_type == "comparison":
            source_entities = [analysis['mechanism1'], analysis['mechanism2'], analysis['target']]
        elif analysis_type == "competing":
            source_entities = [analysis['entity']] + [comp['entity'] for comp in analysis.get('competing_entities', [])]

        # Check if we've already used this entity combination
        entity_set = frozenset(source_entities)
        if entity_set in used_entity_sets:
            print(f"Attempt {attempts}/{max_attempts}: Already generated question with these entities, skipping...")
            continue

        entity_context = get_entity_context(graph, entity_name) if entity_name else ""

        print(f"Attempt {attempts}/{max_attempts}: Generating from {analysis_type} analysis...")

        # Sanitize analysis data to remove graph metadata
        sanitized_analysis = sanitize_analysis_for_prompt(analysis, graph)

        # Generate question
        result = await generator.generate(
            analysis_type=analysis_type,
            analysis_data=sanitized_analysis,  # Use sanitized data
            domain_name=domain_name,
            entity_context=entity_context
        )

        question_text = result['question']
        reasoning_steps = result.get('reasoning_steps', [])
        correct_answer = result.get('correct_answer', '')

        # Validate self-containment
        print(f"  Validating self-containment...")
        containment = await validate_self_containment(llm, question_text, correct_answer)

        if not containment['is_self_contained']:
            missing = containment.get('missing_information', [])
            external = containment.get('external_references', [])
            print(f"    ❌ Not self-contained")
            if missing:
                print(f"       Missing info: {', '.join(missing[:2])}")
            if external:
                print(f"       External refs: {', '.join(external[:2])}")
            continue

        print(f"    ✓ Self-contained")

        # Validate answer gradability
        print(f"  Validating answer gradability...")
        gradability = await validate_answer_gradability(llm, correct_answer)

        if not gradability['is_gradable']:
            print(f"    ❌ Not gradable: {gradability['reason']}")
            print(f"       Word count: {gradability['word_count']} (max 20)")
            continue

        print(f"    ✓ Gradable ({gradability['word_count']} words, type: {gradability['format_type']})")

        # Build full question text for filtering (includes question + answer for quality check)
        full_question = f"{question_text}\n\nExpected Answer:\n{correct_answer}"

        # Filter for quality (threshold: >= 4)
        print(f"  Checking quality score...")
        quality = await filter_question_quality(llm, full_question, analysis_type)

        print(f"  Quality score: {quality['score']}")
        print(f"  Critique: {quality['critique']}")

        if quality['passed']:
            # ENRICHMENT STEP: Add distracting information if enabled
            if enricher.is_enabled():
                print(f"  Enriching question...")
                enrichment_result = await enricher.enrich_question(
                    question=question_text,
                    correct_answer=correct_answer,
                    core_entities=source_entities,
                    domain=domain_name
                )

                final_question = enrichment_result['enriched_question']
                enrichment_pieces = enrichment_result['enrichment_pieces']
                enrichment_entities = enrichment_result['enrichment_entities']
            else:
                final_question = question_text
                enrichment_pieces = []
                enrichment_entities = []

            qa_pair = {
                'question': final_question,
                'original_question': question_text,  # Keep original for reference
                'reasoning_steps': reasoning_steps,
                'correct_answer': correct_answer,
                'analysis_type': analysis_type,
                'source_entities': source_entities,
                'quality_score': quality['score'],
                'answer_word_count': gradability['word_count'],
                'answer_format': gradability['format_type'],
                'is_self_contained': True,
                'is_gradable': True,
                'enrichment_pieces': enrichment_pieces,
                'enrichment_entities': enrichment_entities
            }

            questions.append(qa_pair)
            used_entity_sets.add(entity_set)

            print(f"    ✅ Accepted! ({len(questions)}/{max_questions} complete)\n")
        else:
            print(f"    ❌ Rejected (score {quality['score']} < 4)\n")

    print(f"{'='*60}")
    print(f"Question Generation Complete")
    print(f"{'='*60}\n")
    print(f"Generated {len(questions)} high-quality questions from {attempts} attempts\n")

    return questions


async def main(args):
    """Main function."""

    print(f"\n{'#'*60}")
    print(f"# CONTRASTIVE QA GENERATION (Stage 6)")
    print(f"{'#'*60}\n")

    # Load graph
    graph_path = Path(args.graph_path)
    if not graph_path.exists():
        print(f"✗ ERROR: Graph file not found: {graph_path}")
        sys.exit(1)

    print(f"Loading graph: {graph_path.name}...")
    graph = nx.read_graphml(graph_path)
    print(f"✓ Graph loaded: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges\n")

    # Load domain schema
    print(f"Loading domain schema: {args.domain}...")
    schema = load_domain_schema(args.domain)
    print(f"✓ Schema loaded: {schema.domain_name}\n")

    # Initialize LLM
    llm = ArgoBridgeLLM()

    # Run GASL contrastive analysis
    analyses = await analyze_graph_with_gasl(graph, args.domain, llm)

    # Generate questions (with optional enrichment)
    questions = await generate_questions_from_analyses(
        analyses=analyses,
        graph=graph,
        domain_name=args.domain,
        llm=llm,
        max_questions=args.max_questions,
        enrich_info_pieces=args.enrich_info_pieces,
        enrich_graph_depth=args.enrich_graph_depth
    )

    # Save output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        'domain': args.domain,
        'graph_file': str(graph_path),
        'num_questions': len(questions),
        'enrichment_settings': {
            'enabled': args.enrich_info_pieces > 0,
            'info_pieces': args.enrich_info_pieces,
            'graph_depth': args.enrich_graph_depth
        },
        'questions': questions
    }

    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ Saved {len(questions)} questions to: {output_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate contrastive reasoning questions from enriched knowledge graph"
    )
    parser.add_argument(
        "graph_path",
        type=str,
        help="Path to enriched graph file (.graphml)"
    )
    parser.add_argument(
        "domain",
        type=str,
        help="Domain name (e.g., molecular_biology)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./contrastive_qa.json",
        help="Output file path (default: ./contrastive_qa.json)"
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=20,
        help="Maximum number of questions to generate (default: 20)"
    )
    parser.add_argument(
        "--enrich-info-pieces",
        type=int,
        default=3,
        help="Number of distracting facts to add per question (0=disabled, default: 3)"
    )
    parser.add_argument(
        "--enrich-graph-depth",
        type=int,
        default=1,
        help="Graph traversal depth for finding enrichment candidates (1-3, default: 1)"
    )

    args = parser.parse_args()
    asyncio.run(main(args))
