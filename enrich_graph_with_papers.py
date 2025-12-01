"""
Stage 5: Enrich Graph with Additional Papers
Loads initial graph, extracts entities from fetched papers, and enriches the graph
"""

import argparse
import asyncio
import json
import sys
import networkx as nx
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.absolute()))

from domain_schemas.schema_loader import load_domain_schema
from nano_graphrag.entity_extraction.typed_module import create_domain_extractor_from_schema
from graph_enrichment.graph_merger import (
    add_entities_to_graph,
    add_relationships_to_graph,
    get_enrichment_statistics
)
from create_domain_typed_graph import chunk_text, extract_from_chunk
from gasl.llm import ArgoBridgeLLM


async def load_papers_from_metadata(
    metadata_file: Path,
    papers_dir: Path,
    limit: Optional[int] = None
) -> List[Dict]:
    """
    Load papers from metadata file.

    Args:
        metadata_file: Path to papers_metadata.json
        papers_dir: Directory containing paper text files
        limit: Maximum number of papers to load (None = all)

    Returns:
        List of paper dicts with uuid, content, and metadata
    """
    print(f"Loading papers metadata from: {metadata_file}")

    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    papers = []
    count = 0

    for paper_uuid, paper_meta in metadata.items():
        if limit and count >= limit:
            break

        # Load paper content
        content_file = papers_dir / f"{paper_uuid}.txt"

        if not content_file.exists():
            print(f"  ⚠ Warning: Content file not found: {content_file}")
            continue

        with open(content_file, 'r', encoding='utf-8') as f:
            content = f.read()

        papers.append({
            'uuid': paper_uuid,
            'content': content,
            'metadata': paper_meta
        })

        count += 1

    print(f"✓ Loaded {len(papers)} papers")

    return papers


async def extract_from_paper(
    paper: Dict,
    extractor,
    chunk_size: int = 2000,
    overlap: int = 200
) -> tuple[Dict, List]:
    """
    Extract entities and relationships from a single paper.

    Args:
        paper: Paper dict with uuid, content, metadata
        extractor: Domain-typed entity extractor
        chunk_size: Text chunk size
        overlap: Chunk overlap

    Returns:
        Tuple of (entities_dict, relationships_list)
    """
    paper_uuid = paper['uuid']
    title = paper['metadata'].get('title', 'Unknown')[:60]

    print(f"\n  Processing: {title}")
    print(f"  UUID: {paper_uuid}")

    # Chunk the paper
    chunks = chunk_text(paper['content'], chunk_size=chunk_size, overlap=overlap)
    print(f"  Chunks: {len(chunks)}")

    # Extract from all chunks
    global_entities = {}
    global_relationships = []

    for i, chunk in enumerate(chunks):
        chunk_id = f"{paper_uuid}_chunk_{i}"

        num_entities, num_rels = await extract_from_chunk(
            chunk,
            chunk_id,
            extractor,
            global_entities,
            global_relationships
        )

    print(f"  ✓ Extracted: {len(global_entities)} entities, {len(global_relationships)} relationships")

    return global_entities, global_relationships


async def enrich_graph_with_papers(
    base_graph: nx.DiGraph,
    papers: List[Dict],
    extractor,
    domain_name: str,
    chunk_size: int = 2000,
    overlap: int = 200,
    similarity_threshold: float = 0.85,
    auto_merge: bool = True
) -> nx.DiGraph:
    """
    Enrich a base graph with entities and relationships from additional papers.

    Args:
        base_graph: Initial knowledge graph
        papers: List of paper dicts to extract from
        extractor: Domain-typed entity extractor
        domain_name: Domain schema name
        chunk_size: Text chunk size
        overlap: Chunk overlap
        similarity_threshold: Threshold for entity matching
        auto_merge: Whether to automatically merge similar entities

    Returns:
        Enriched graph
    """
    enriched_graph = base_graph.copy()

    print(f"\n{'='*60}")
    print(f"Enriching graph with {len(papers)} papers")
    print(f"{'='*60}")

    for i, paper in enumerate(papers):
        print(f"\n[{i+1}/{len(papers)}]")

        # Extract entities and relationships from paper
        new_entities, new_relationships = await extract_from_paper(
            paper,
            extractor,
            chunk_size=chunk_size,
            overlap=overlap
        )

        paper_uuid = paper['uuid']

        # Add entities to graph with merging
        print(f"  Merging entities into graph...")
        enriched_graph, name_mapping = add_entities_to_graph(
            enriched_graph,
            new_entities,
            paper_uuid,
            similarity_threshold=similarity_threshold,
            auto_merge=auto_merge
        )

        print(f"    Entities: {len(new_entities)} new → {len([k for k, v in name_mapping.items() if k == v])} added, {len([k for k, v in name_mapping.items() if k != v])} merged")

        # Add relationships to graph
        print(f"  Adding relationships to graph...")
        enriched_graph = add_relationships_to_graph(
            enriched_graph,
            new_relationships,
            name_mapping,
            paper_uuid
        )

        print(f"    Relationships: {len(new_relationships)} extracted")

    return enriched_graph


async def main(args):
    """Main function"""

    print(f"\n{'='*60}")
    print(f"Stage 5: Graph Enrichment")
    print(f"{'='*60}\n")

    # Load domain schema
    print(f"Loading domain schema: {args.domain}...")
    schema = load_domain_schema(args.domain)
    print(f"✓ Schema loaded: {schema.domain_name}\n")

    # Load base graph
    print(f"Loading base graph: {args.base_graph}")
    base_graph = nx.read_graphml(args.base_graph)
    original_stats = {
        'nodes': base_graph.number_of_nodes(),
        'edges': base_graph.number_of_edges()
    }
    print(f"✓ Base graph loaded: {original_stats['nodes']} nodes, {original_stats['edges']} edges\n")

    # Load papers
    papers_dir = Path(args.papers_dir)
    metadata_file = papers_dir / "papers_metadata.json"

    if not metadata_file.exists():
        print(f"✗ ERROR: Papers metadata not found: {metadata_file}")
        sys.exit(1)

    papers = await load_papers_from_metadata(
        metadata_file,
        papers_dir,
        limit=args.max_papers
    )

    if not papers:
        print("\n✗ ERROR: No papers loaded")
        sys.exit(1)

    print("")

    # Initialize LLM
    print("Initializing LLM...")
    llm = ArgoBridgeLLM()
    print("✓ LLM ready\n")

    # Create domain-specific extractor
    print(f"Creating domain-specific extractor...")
    extractor = create_domain_extractor_from_schema(
        schema,
        llm_func=llm.call_async,
        num_refine_turns=args.refine_turns,
        self_refine=args.self_refine
    )
    print(f"✓ Extractor ready\n")

    # Enrich graph
    enriched_graph = await enrich_graph_with_papers(
        base_graph,
        papers,
        extractor,
        args.domain,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        similarity_threshold=args.similarity_threshold,
        auto_merge=args.auto_merge
    )

    # Calculate statistics
    stats = get_enrichment_statistics(base_graph, enriched_graph)

    print(f"\n{'='*60}")
    print(f"Enrichment Statistics")
    print(f"{'='*60}")
    print(f"Original graph: {stats['original_nodes']} nodes, {stats['original_edges']} edges")
    print(f"Enriched graph: {stats['enriched_nodes']} nodes, {stats['enriched_edges']} edges")
    print(f"Added: {stats['nodes_added']} nodes (+{stats['node_growth_percent']:.1f}%), {stats['edges_added']} edges (+{stats['edge_growth_percent']:.1f}%)")

    # Save enriched graph
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert list attributes to strings for GraphML compatibility
    for node in enriched_graph.nodes():
        node_data = enriched_graph.nodes[node]
        if 'source_papers' in node_data and isinstance(node_data['source_papers'], list):
            node_data['source_papers'] = ','.join(node_data['source_papers'])
        if 'source_chunks' in node_data and isinstance(node_data['source_chunks'], list):
            node_data['source_chunks'] = ','.join(node_data['source_chunks'])

    for src, tgt in enriched_graph.edges():
        edge_data = enriched_graph[src][tgt]
        if 'source_papers' in edge_data and isinstance(edge_data['source_papers'], list):
            edge_data['source_papers'] = ','.join(edge_data['source_papers'])

    graph_file = output_dir / f"{args.domain}_enriched_graph.graphml"
    nx.write_graphml(enriched_graph, graph_file)
    print(f"\n✓ Enriched graph saved to: {graph_file}")

    # Save enrichment metadata
    enrichment_metadata = {
        'domain': args.domain,
        'base_graph': str(args.base_graph),
        'papers_dir': str(args.papers_dir),
        'num_papers_used': len(papers),
        'statistics': stats,
        'papers_used': [
            {
                'uuid': p['uuid'],
                'title': p['metadata'].get('title', 'Unknown'),
                'source_query': p['metadata'].get('source_query', ''),
                'query_type': p['metadata'].get('query_type', '')
            }
            for p in papers
        ]
    }

    metadata_file = output_dir / f"{args.domain}_enrichment_metadata.json"
    with open(metadata_file, 'w') as f:
        json.dump(enrichment_metadata, f, indent=2)
    print(f"✓ Enrichment metadata saved to: {metadata_file}")

    print(f"\n{'='*60}")
    print(f"Stage 5 Complete: Graph enrichment successful")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enrich knowledge graph with additional papers"
    )
    parser.add_argument(
        "base_graph",
        type=str,
        help="Path to base GraphML file (from Stage 2)"
    )
    parser.add_argument(
        "domain",
        type=str,
        help="Domain schema name"
    )
    parser.add_argument(
        "--papers-dir",
        type=str,
        default="./fetched_papers",
        help="Directory containing fetched papers (default: ./fetched_papers)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./enriched_graphs",
        help="Directory to save enriched graph (default: ./enriched_graphs)"
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        help="Maximum number of papers to use for enrichment (default: all)"
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
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.85,
        help="Entity similarity threshold for merging (default: 0.85)"
    )
    parser.add_argument(
        "--no-auto-merge",
        action="store_true",
        help="Disable automatic entity merging"
    )

    args = parser.parse_args()
    args.self_refine = not args.no_self_refine
    args.auto_merge = not args.no_auto_merge

    asyncio.run(main(args))
