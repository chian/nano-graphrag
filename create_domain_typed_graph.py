"""
Stage 2: Create Domain-Typed Knowledge Graph
Builds a knowledge graph with domain-specific entity and relationship types
"""

import argparse
import asyncio
import os
import sys
import networkx as nx
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.absolute()))

from domain_schemas.schema_loader import load_domain_schema
from nano_graphrag.entity_extraction.typed_module import create_domain_extractor_from_schema
from nano_graphrag._utils import compute_mdhash_id
from gasl.llm import ArgoBridgeLLM

async def load_paper_text(paper_path: str) -> str:
    """Load paper text"""
    with open(paper_path, 'r', encoding='utf-8') as f:
        return f.read()

def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> list[str]:
    """Simple chunking with overlap"""
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap  # Overlap for continuity

    return chunks

async def extract_from_chunk(
    chunk_text: str,
    chunk_id: str,
    extractor,
    global_entities: dict,
    global_relationships: list
):
    """Extract entities and relationships from a single chunk"""

    # Run extraction
    prediction = await extractor.forward(chunk_text)

    entities = prediction.entities
    relationships = prediction.relationships

    # Add entities to global dict (merging by name)
    for entity in entities:
        entity_dict = entity.to_dict()
        entity_name = entity_dict['entity_name']

        if entity_name not in global_entities:
            global_entities[entity_name] = entity_dict
            global_entities[entity_name]['source_chunks'] = [chunk_id]
        else:
            # Merge: take higher importance score, combine descriptions
            if entity_dict['importance_score'] > global_entities[entity_name]['importance_score']:
                global_entities[entity_name]['importance_score'] = entity_dict['importance_score']

            # Append chunk if new
            if chunk_id not in global_entities[entity_name]['source_chunks']:
                global_entities[entity_name]['source_chunks'].append(chunk_id)

    # Add relationships
    for rel in relationships:
        rel_dict = rel.to_dict()
        rel_dict['source_chunk'] = chunk_id
        global_relationships.append(rel_dict)

    return len(entities), len(relationships)

async def build_graph_from_extractions(
    global_entities: dict,
    global_relationships: list
) -> nx.DiGraph:
    """Build NetworkX graph from extractions"""

    G = nx.DiGraph()

    # Add nodes
    for entity_name, entity_data in global_entities.items():
        # Convert source_chunks list to string for GraphML compatibility
        source_chunks_str = ','.join(entity_data['source_chunks']) if entity_data.get('source_chunks') else ''
        G.add_node(
            entity_name,
            entity_type=entity_data['entity_type'],
            description=entity_data['description'],
            importance_score=entity_data['importance_score'],
            source_chunks=source_chunks_str
        )

    # Add edges
    for rel in global_relationships:
        src = rel['src_id']
        tgt = rel['tgt_id']

        # Only add if both nodes exist
        if src in G.nodes and tgt in G.nodes:
            # If edge exists, merge
            if G.has_edge(src, tgt):
                # Combine descriptions
                existing_desc = G[src][tgt]['description']
                new_desc = rel['description']
                G[src][tgt]['description'] = f"{existing_desc} | {new_desc}"

                # Take max weight
                G[src][tgt]['weight'] = max(G[src][tgt]['weight'], rel['weight'])
            else:
                G.add_edge(
                    src,
                    tgt,
                    relation_type=rel.get('relation_type', 'RELATED_TO'),
                    description=rel['description'],
                    weight=rel['weight'],
                    order=rel['order'],
                    source_chunk=rel['source_chunk']
                )

    return G

async def main(args):
    """Main graph construction function"""

    print(f"\n{'='*60}")
    print(f"Stage 2: Domain-Typed Graph Construction")
    print(f"{'='*60}\n")

    # Load domain schema
    print(f"Loading domain schema: {args.domain}...")
    schema = load_domain_schema(args.domain)
    print(f"✓ Schema loaded: {schema.domain_name}")
    print(f"  Entity types: {len(schema.entity_types)}")
    print(f"  Relationship types: {len(schema.relationship_types)}\n")

    # Load paper
    print(f"Loading paper: {Path(args.paper_path).name}...")
    paper_text = await load_paper_text(args.paper_path)
    print(f"✓ Paper loaded: {len(paper_text)} characters\n")

    # Chunk text
    print(f"Chunking text (chunk_size={args.chunk_size}, overlap={args.overlap})...")
    chunks = chunk_text(paper_text, chunk_size=args.chunk_size, overlap=args.overlap)
    print(f"✓ Created {len(chunks)} chunks\n")

    # Initialize LLM
    llm = ArgoBridgeLLM()
    
    # Create domain-specific extractor
    print(f"Creating domain-specific extractor...")
    extractor = create_domain_extractor_from_schema(
        schema,
        llm_func=llm.call_async,
        num_refine_turns=args.refine_turns,
        self_refine=args.self_refine
    )
    print(f"✓ Extractor ready\n")

    # Extract from all chunks
    print(f"Extracting entities and relationships from {len(chunks)} chunks...")
    print(f"{'─'*60}")

    global_entities = {}
    global_relationships = []

    for i, chunk in enumerate(chunks):
        chunk_id = f"chunk_{i}"
        print(f"  Processing chunk {i+1}/{len(chunks)}...", end=" ")

        num_entities, num_rels = await extract_from_chunk(
            chunk,
            chunk_id,
            extractor,
            global_entities,
            global_relationships
        )

        print(f"✓ ({num_entities} entities, {num_rels} relationships)")

    print(f"{'─'*60}")
    print(f"✓ Extraction complete")
    print(f"  Total unique entities: {len(global_entities)}")
    print(f"  Total relationships: {len(global_relationships)}\n")

    # Build graph
    print(f"Building knowledge graph...")
    graph = await build_graph_from_extractions(global_entities, global_relationships)
    print(f"✓ Graph built")
    print(f"  Nodes: {graph.number_of_nodes()}")
    print(f"  Edges: {graph.number_of_edges()}\n")

    # Save graph
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    graph_file = output_dir / f"{args.domain}_graph.graphml"
    nx.write_graphml(graph, graph_file)
    print(f"✓ Graph saved to: {graph_file}")

    # Save metadata
    metadata = {
        'paper_path': args.paper_path,
        'domain': args.domain,
        'domain_name': schema.domain_name,
        'num_chunks': len(chunks),
        'num_entities': len(global_entities),
        'num_relationships': len(global_relationships),
        'num_nodes': graph.number_of_nodes(),
        'num_edges': graph.number_of_edges(),
        'entity_types': list(schema.entity_types.keys()),
        'relationship_types': list(schema.relationship_types.keys())
    }

    metadata_file = output_dir / f"{args.domain}_metadata.json"
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"✓ Metadata saved to: {metadata_file}")

    print(f"\n{'='*60}")
    print(f"Stage 2 Complete: Domain-typed graph created successfully")
    print(f"{'='*60}\n")

    return graph, metadata

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create domain-typed knowledge graph from a paper"
    )
    parser.add_argument(
        "paper_path",
        type=str,
        help="Path to the paper file"
    )
    parser.add_argument(
        "domain",
        type=str,
        help="Domain schema to use (e.g., molecular_biology, microbial_biology)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./contrastive_graphs",
        help="Directory to save output graph (default: ./contrastive_graphs)"
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=2000,
        help="Chunk size for text processing (default: 2000)"
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=200,
        help="Overlap between chunks (default: 200)"
    )
    parser.add_argument(
        "--refine-turns",
        type=int,
        default=1,
        help="Number of refinement turns (default: 1)"
    )
    parser.add_argument(
        "--no-self-refine",
        action="store_true",
        help="Disable self-refinement"
    )

    args = parser.parse_args()
    args.self_refine = not args.no_self_refine

    asyncio.run(main(args))
