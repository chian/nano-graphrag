"""
Quick test to verify enrichment module works correctly.
"""

import asyncio
import networkx as nx
from question_enrichment import QuestionEnricher
from gasl.llm import ArgoBridgeLLM


async def test_enrichment():
    """Test enrichment with a simple mock graph."""

    print("\n" + "="*60)
    print("Testing Question Enrichment Module")
    print("="*60 + "\n")

    # Create a simple test graph
    graph = nx.DiGraph()

    # Add core entities (used in question)
    graph.add_node("PHOCAEICOLA DOREI",
                   entity_type="BACTERIAL_SPECIES",
                   description="Gut bacterium that ferments inulin")

    graph.add_node("LACHNOCLOSTRIDIUM SYMBIOSUM",
                   entity_type="BACTERIAL_SPECIES",
                   description="Butyrate-producing bacterium")

    # Add neighboring entities (potential distractors)
    graph.add_node("BACTEROIDES FRAGILIS",
                   entity_type="BACTERIAL_SPECIES",
                   description="Related gut bacterium")

    graph.add_node("BLAUTIA PRODUCTA",
                   entity_type="BACTERIAL_SPECIES",
                   description="Another butyrate producer")

    graph.add_node("ACETATE",
                   entity_type="METABOLITE",
                   description="Short-chain fatty acid")

    # Add edges (relationships)
    graph.add_edge("PHOCAEICOLA DOREI", "ACETATE", relation_type="PRODUCES")
    graph.add_edge("LACHNOCLOSTRIDIUM SYMBIOSUM", "ACETATE", relation_type="CONSUMES")
    graph.add_edge("BACTEROIDES FRAGILIS", "ACETATE", relation_type="PRODUCES")
    graph.add_edge("BLAUTIA PRODUCTA", "ACETATE", relation_type="CONSUMES")

    print(f"Created test graph:")
    print(f"  Nodes: {graph.number_of_nodes()}")
    print(f"  Edges: {graph.number_of_edges()}\n")

    # Create test question
    test_question = """In monoculture, Phocaeicola dorei consumes 60% of available inulin over 24 hours. Lachnoclostridium symbiosum alone consumes 55% of inulin. When cocultured under identical conditions, total inulin consumption reaches 95% and SCFA levels are 70% higher than either monoculture. L. symbiosum lacks polysaccharide degradation genes but can convert acetate to butyrate. P. dorei produces acetate during inulin fermentation. Which culture condition maximizes both carbohydrate utilization and SCFA production?"""

    test_answer = "Coculture"
    core_entities = ["PHOCAEICOLA DOREI", "LACHNOCLOSTRIDIUM SYMBIOSUM"]

    print("Original Question:")
    print(f"{test_question}\n")
    print(f"Correct Answer: {test_answer}\n")
    print(f"Core Entities: {', '.join(core_entities)}\n")

    # Initialize LLM
    llm = ArgoBridgeLLM()

    # Test 1: Enrichment disabled
    print("="*60)
    print("Test 1: Enrichment DISABLED (info_pieces=0)")
    print("="*60 + "\n")

    enricher_disabled = QuestionEnricher(
        graph=graph,
        llm=llm,
        num_info_pieces=0,
        graph_depth=1
    )

    print(f"Is enabled: {enricher_disabled.is_enabled()}")

    result = await enricher_disabled.enrich_question(
        question=test_question,
        correct_answer=test_answer,
        core_entities=core_entities,
        domain="microbial ecology"
    )

    print(f"Enrichment pieces added: {len(result['enrichment_pieces'])}")
    print(f"Question unchanged: {result['enriched_question'] == test_question}\n")

    # Test 2: Light enrichment
    print("="*60)
    print("Test 2: Light Enrichment (info_pieces=2, depth=1)")
    print("="*60 + "\n")

    enricher_light = QuestionEnricher(
        graph=graph,
        llm=llm,
        num_info_pieces=2,
        graph_depth=1
    )

    print(f"Is enabled: {enricher_light.is_enabled()}")

    result = await enricher_light.enrich_question(
        question=test_question,
        correct_answer=test_answer,
        core_entities=core_entities,
        domain="microbial ecology"
    )

    print(f"\nEnrichment pieces added: {len(result['enrichment_pieces'])}")
    print(f"Enrichment entities: {', '.join(result['enrichment_entities'])}\n")

    print("Enrichment snippets:")
    for i, piece in enumerate(result['enrichment_pieces'], 1):
        print(f"  {i}. {piece}\n")

    print("Enriched Question:")
    print(f"{result['enriched_question']}\n")

    print("="*60)
    print("✓ Enrichment module tests complete!")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_enrichment())
