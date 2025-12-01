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

        prompt = f"""Generate a multi-step reasoning question in the domain of {domain_name}.

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
{json.dumps(analysis_data, indent=2)}

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

CORRECT_ANSWER: [the short-form answer, 2-4 sentences]"""

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
    max_questions: int = 20
) -> List[Dict]:
    """
    Generate contrastive questions from GASL analysis results with quality filtering.

    Uses random selection for diversity and retries to get enough high-quality questions.
    Similar pattern to generate_reasoning_qa_gasl.py.
    """

    print(f"\n{'='*60}")
    print(f"Generating Contrastive Questions with Quality Filtering")
    print(f"{'='*60}\n")

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

        # Generate question
        result = await generator.generate(
            analysis_type=analysis_type,
            analysis_data=analysis,
            domain_name=domain_name,
            entity_context=entity_context
        )

        question_text = result['question']
        reasoning_steps = result.get('reasoning_steps', [])
        correct_answer = result.get('correct_answer', '')

        # Build full question text for filtering (includes question + answer for quality check)
        full_question = f"{question_text}\n\nExpected Answer:\n{correct_answer}"

        # Filter for quality (same threshold as generate_reasoning_qa_gasl.py: >= 4)
        quality = await filter_question_quality(llm, full_question, analysis_type)

        print(f"  Quality score: {quality['score']}")
        print(f"  Critique: {quality['critique']}")

        if quality['passed']:
            qa_pair = {
                'question': question_text,
                'reasoning_steps': reasoning_steps,
                'correct_answer': correct_answer,
                'analysis_type': analysis_type,
                'source_entities': source_entities,
                'quality_score': quality['score']
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

    # Generate questions
    questions = await generate_questions_from_analyses(
        analyses=analyses,
        graph=graph,
        domain_name=args.domain,
        llm=llm,
        max_questions=args.max_questions
    )

    # Save output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        'domain': args.domain,
        'graph_file': str(graph_path),
        'num_questions': len(questions),
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

    args = parser.parse_args()
    asyncio.run(main(args))
