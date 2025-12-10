"""
Question Enrichment Module

Adds realistic "noise" to self-contained questions by injecting non-essential
but plausible information from neighboring graph entities.

This module is designed to be modular:
1. Graph can be extended/enriched before enrichment (future: firecrawl, external sources)
2. Enrichment strategies can be customized
3. Can be toggled on/off via parameters
"""

import json
import random
from typing import List, Dict, Tuple, Optional, Set
import networkx as nx
from gasl.llm import ArgoBridgeLLM
from nano_graphrag._utils import convert_response_to_json


class QuestionEnricher:
    """
    Enriches questions with non-essential but plausible information from the graph.

    Design allows for future graph extension step before enrichment.
    """

    def __init__(
        self,
        graph: nx.DiGraph,
        llm: ArgoBridgeLLM,
        num_info_pieces: int = 0,
        graph_depth: int = 1
    ):
        """
        Args:
            graph: NetworkX graph (can be pre-extended with additional data)
            llm: Language model for validation
            num_info_pieces: Number of distracting facts to add (0 = disabled)
            graph_depth: How many hops to search for candidates (1-3)
        """
        self.graph = graph
        self.llm = llm
        self.num_info_pieces = num_info_pieces
        self.graph_depth = graph_depth

    def is_enabled(self) -> bool:
        """Check if enrichment is enabled."""
        return self.num_info_pieces > 0

    async def enrich_question(
        self,
        question: str,
        correct_answer: str,
        core_entities: List[str],
        domain: str
    ) -> Dict:
        """
        Enrich a question with distracting information.

        Args:
            question: Original self-contained question text
            correct_answer: The expected answer
            core_entities: Entity names used in the reasoning chain
            domain: Domain name (e.g., "microbial ecology")

        Returns:
            Dict with enriched_question, enrichment_pieces, enrichment_entities
        """
        if not self.is_enabled():
            return {
                "enriched_question": question,
                "enrichment_pieces": [],
                "enrichment_entities": []
            }

        # Step 1: Find candidate entities from graph traversal
        candidates = self._find_candidate_entities(core_entities)

        if not candidates:
            print(f"    ⚠ No enrichment candidates found within depth {self.graph_depth}")
            return {
                "enriched_question": question,
                "enrichment_pieces": [],
                "enrichment_entities": []
            }

        print(f"    Found {len(candidates)} enrichment candidates")

        # Step 2: Score candidates using LLM (always validate for quality)
        scored_candidates = await self._score_candidates(
            candidates, question, correct_answer, domain
        )

        # Step 3: Select top N candidates
        selected = self._select_top_candidates(scored_candidates, self.num_info_pieces)

        if not selected:
            print(f"    ⚠ No suitable enrichment pieces passed validation")
            return {
                "enriched_question": question,
                "enrichment_pieces": [],
                "enrichment_entities": []
            }

        # Step 4: Generate enrichment snippets
        enrichment_pieces = await self._generate_enrichment_snippets(
            selected, question, domain
        )

        # Step 5: Inject into question
        enriched_question = self._inject_enrichments(question, enrichment_pieces)

        enrichment_entities = [e['entity'] for e in selected]

        print(f"    ✓ Added {len(enrichment_pieces)} enrichment pieces")

        return {
            "enriched_question": enriched_question,
            "enrichment_pieces": enrichment_pieces,
            "enrichment_entities": enrichment_entities
        }

    def _find_candidate_entities(self, core_entities: List[str]) -> List[Dict]:
        """
        Traverse graph to find candidate entities for enrichment.

        Args:
            core_entities: Entities in the reasoning chain (exclude these)

        Returns:
            List of candidate entity dicts with name, type, description
        """
        candidates = []
        visited = set()
        core_set = set(e.upper() for e in core_entities)

        # BFS traversal from core entities up to graph_depth hops
        current_level = core_set.copy()

        for depth in range(self.graph_depth):
            next_level = set()

            for entity in current_level:
                if entity not in self.graph.nodes:
                    continue

                # Get neighbors (both directions)
                neighbors = set(self.graph.successors(entity)) | set(self.graph.predecessors(entity))

                for neighbor in neighbors:
                    if neighbor in visited or neighbor in core_set:
                        continue

                    visited.add(neighbor)
                    next_level.add(neighbor)

                    # Extract entity info
                    node_data = self.graph.nodes[neighbor]
                    entity_type = node_data.get('entity_type', 'UNKNOWN')
                    description = node_data.get('description', '')

                    candidates.append({
                        'entity': neighbor,
                        'entity_type': entity_type,
                        'description': description,
                        'depth': depth + 1
                    })

            current_level = next_level

        return candidates

    async def _score_candidates(
        self,
        candidates: List[Dict],
        question: str,
        answer: str,
        domain: str
    ) -> List[Dict]:
        """
        Score candidates for suitability as enrichment.
        Always uses LLM validation for quality.

        Args:
            candidates: List of candidate entity dicts
            question: Original question
            answer: Correct answer
            domain: Domain name

        Returns:
            Candidates with added 'score' and 'reasoning' fields
        """
        scored = []

        for candidate in candidates:
            # Use LLM to score relevance and distraction quality
            score_prompt = f"""You are evaluating whether an entity would be good as a "distractor" for a reasoning question.

DOMAIN: {domain}

ORIGINAL QUESTION:
{question}

CORRECT ANSWER:
{answer}

CANDIDATE ENTITY TO ADD AS DISTRACTION:
Name: {candidate['entity']}
Type: {candidate['entity_type']}
Description: {candidate['description']}

Evaluate this candidate as a distractor:
1. PLAUSIBILITY: Is it plausible that this entity would be mentioned in the scenario? (domain-related, similar context)
2. NON-INTERFERENCE: Will mentioning this entity NOT change the reasoning path or answer?
3. DISTRACTION QUALITY: Could it make the problem slightly harder by requiring the reader to determine what's relevant?

Score from 1-10 where:
- 1-3: Not plausible or would break the question
- 4-6: Somewhat related but not very distracting
- 7-8: Good distractor - plausible and makes problem harder
- 9-10: Excellent distractor - very realistic and challenging

Output ONLY a JSON object:
{{
  "score": 1-10,
  "plausibility": "high|medium|low",
  "interference_risk": "high|medium|low",
  "reasoning": "brief explanation of score"
}}"""

            try:
                response = await self.llm.call_async(score_prompt)
                result = convert_response_to_json(response)

                if result:
                    candidate['score'] = result.get('score', 0)
                    candidate['plausibility'] = result.get('plausibility', 'unknown')
                    candidate['interference_risk'] = result.get('interference_risk', 'unknown')
                    candidate['scoring_reasoning'] = result.get('reasoning', '')

                    # Only keep if score >= 7 and low interference risk
                    if candidate['score'] >= 7 and candidate['interference_risk'] in ['low', 'medium']:
                        scored.append(candidate)
                else:
                    continue

            except Exception as e:
                print(f"      Warning: Could not score candidate {candidate['entity']}: {e}")
                continue

        return scored

    def _select_top_candidates(self, scored_candidates: List[Dict], n: int) -> List[Dict]:
        """
        Select top N candidates by score.

        Args:
            scored_candidates: Candidates with scores
            n: Number to select

        Returns:
            Top N candidates
        """
        # Sort by score descending
        sorted_candidates = sorted(scored_candidates, key=lambda x: x['score'], reverse=True)

        # Take top N
        return sorted_candidates[:n]

    async def _generate_enrichment_snippets(
        self,
        selected_entities: List[Dict],
        question: str,
        domain: str
    ) -> List[str]:
        """
        Generate text snippets for each enrichment entity.

        Uses LLM to generate realistic, contextually appropriate snippets.

        Args:
            selected_entities: Entities to enrich with
            question: Original question
            domain: Domain name

        Returns:
            List of snippet strings
        """
        snippets = []

        for entity_info in selected_entities:
            snippet_prompt = f"""Generate a SHORT factual snippet to add to a reasoning question as a distractor.

DOMAIN: {domain}

ORIGINAL QUESTION (for context):
{question}

ENTITY TO MENTION:
Name: {entity_info['entity']}
Type: {entity_info['entity_type']}
Description: {entity_info['description']}

Generate a 1-2 sentence factual snippet that:
1. Mentions this entity naturally in the question's context
2. Provides plausible quantitative or mechanistic information
3. Does NOT help answer the question directly
4. Reads like it belongs in the scenario

SNIPPET STYLE EXAMPLES:
- "Bacteroides fragilis, a related species, ferments inulin at 50% efficiency but produces primarily acetate and propionate."
- "Under low-pH conditions (pH 5.5), species X exhibits 30% reduced growth compared to neutral pH."
- "Gene Y is upregulated 3-fold in the presence of substrate Z, though this does not affect the primary pathway."

Output ONLY the snippet text (1-2 sentences, no extra formatting):"""

            try:
                response = await self.llm.call_async(snippet_prompt)
                snippet = response.strip()

                # Clean up any markdown or extra formatting
                snippet = snippet.replace('**', '').replace('*', '')
                snippet = snippet.strip('"\'')

                snippets.append(snippet)

            except Exception as e:
                print(f"      Warning: Could not generate snippet for {entity_info['entity']}: {e}")
                continue

        return snippets

    def _inject_enrichments(self, question: str, enrichment_pieces: List[str]) -> str:
        """
        Inject enrichment snippets into the question text.

        Strategy: Insert snippets naturally into the scenario, interspersed
        with the core information.

        Args:
            question: Original question
            enrichment_pieces: Snippet strings to inject

        Returns:
            Enriched question text
        """
        if not enrichment_pieces:
            return question

        # Split question into sentences
        sentences = []
        current = ""
        for char in question:
            current += char
            if char in '.?!' and current.strip():
                sentences.append(current.strip())
                current = ""
        if current.strip():
            sentences.append(current.strip())

        # Find the question sentence (usually last, contains '?')
        question_sentence_idx = len(sentences) - 1
        for i in range(len(sentences) - 1, -1, -1):
            if '?' in sentences[i]:
                question_sentence_idx = i
                break

        # Split into setup sentences and question sentence
        setup_sentences = sentences[:question_sentence_idx]
        question_sentence = sentences[question_sentence_idx:]

        # Distribute enrichment pieces throughout setup
        if setup_sentences:
            # Insert enrichments at roughly evenly spaced positions
            positions = []
            if len(setup_sentences) > len(enrichment_pieces):
                # More setup sentences than enrichments - spread them out
                step = len(setup_sentences) // (len(enrichment_pieces) + 1)
                for i in range(len(enrichment_pieces)):
                    positions.append((i + 1) * step)
            else:
                # More enrichments than setup sentences - insert after each
                positions = list(range(len(setup_sentences)))

            # Insert enrichments at positions
            enriched_setup = []
            enrichment_idx = 0
            for i, sentence in enumerate(setup_sentences):
                enriched_setup.append(sentence)
                if i in positions and enrichment_idx < len(enrichment_pieces):
                    enriched_setup.append(enrichment_pieces[enrichment_idx])
                    enrichment_idx += 1

            # Add any remaining enrichments
            while enrichment_idx < len(enrichment_pieces):
                enriched_setup.append(enrichment_pieces[enrichment_idx])
                enrichment_idx += 1

            # Reconstruct question
            enriched_question = ' '.join(enriched_setup + question_sentence)
        else:
            # No setup sentences, just prepend enrichments before question
            enriched_question = ' '.join(enrichment_pieces + question_sentence)

        return enriched_question


# Future extension point: Graph enrichment functions can be added here
# These would be called BEFORE QuestionEnricher to expand the graph itself

async def extend_graph_with_external_data(
    graph: nx.DiGraph,
    domain: str,
    llm: ArgoBridgeLLM,
    **kwargs
) -> nx.DiGraph:
    """
    FUTURE: Extend graph with additional entities/relationships from external sources.

    This function is a placeholder for future graph extension capabilities like:
    - Firecrawl to scrape related entities from web
    - External knowledge bases
    - Additional literature mining

    Args:
        graph: Existing graph
        domain: Domain name
        llm: Language model
        **kwargs: Extension-specific parameters

    Returns:
        Extended graph
    """
    # TODO: Implement graph extension via firecrawl, external APIs, etc.
    # For now, just return original graph
    return graph
