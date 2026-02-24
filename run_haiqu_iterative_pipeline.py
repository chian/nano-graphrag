"""
HAIQU Iterative GraphRAG Pipeline

Uses the HAIQU PDF as seed for iterative graph-guided paper discovery.
Creates NEW code files - does not modify existing pipeline code.

Usage:
    python run_haiqu_iterative_pipeline.py --seed-pdf haiqu/20260126\ Cognitive\ Tests\ for\ HAIQU.pdf
    python run_haiqu_iterative_pipeline.py --config haiqu_config.yaml
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Set
import networkx as nx

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from iterative_search import (
    IterativeSearchState,
    EntityPriorityQueue,
    IterativeQueryGenerator,
    ConvergenceChecker,
    HAIQUPipelineConfig,
    StopReason
)
from domain_schemas.schema_loader import load_domain_schema
from nano_graphrag.entity_extraction.typed_module import create_domain_extractor_from_schema
from paper_fetching.firecrawl_client import (
    search_papers,
    save_paper_with_uuid,
    load_papers_metadata,
    save_papers_metadata,
    extract_text_from_result
)
from graph_enrichment.graph_merger import (
    add_entities_to_graph,
    add_relationships_to_graph,
    get_enrichment_statistics
)
from gasl.llm import ArgoBridgeLLM


def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> List[str]:
    """Simple chunking with overlap."""
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap

    return chunks


async def extract_from_chunk(
    chunk_text: str,
    chunk_id: str,
    extractor,
    global_entities: dict,
    global_relationships: list
) -> Tuple[int, int]:
    """Extract entities and relationships from a single chunk."""
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
            # Merge: take higher importance score
            if entity_dict['importance_score'] > global_entities[entity_name]['importance_score']:
                global_entities[entity_name]['importance_score'] = entity_dict['importance_score']

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
    """Build NetworkX graph from extractions."""
    G = nx.DiGraph()

    # Add nodes
    for entity_name, entity_data in global_entities.items():
        source_chunks_str = ','.join(entity_data.get('source_chunks', []))
        G.add_node(
            entity_name,
            entity_type=entity_data.get('entity_type', 'UNKNOWN'),
            description=entity_data.get('description', ''),
            importance_score=entity_data.get('importance_score', 0.5),
            source_chunks=source_chunks_str
        )

    # Add edges
    for rel in global_relationships:
        src = rel['src_id']
        tgt = rel['tgt_id']

        if src in G.nodes and tgt in G.nodes:
            if G.has_edge(src, tgt):
                existing_desc = G[src][tgt]['description']
                new_desc = rel['description']
                G[src][tgt]['description'] = f"{existing_desc} | {new_desc}"
                G[src][tgt]['weight'] = max(G[src][tgt]['weight'], rel['weight'])
            else:
                G.add_edge(
                    src,
                    tgt,
                    relation_type=rel.get('relation_type', 'RELATED_TO'),
                    description=rel['description'],
                    weight=rel.get('weight', 0.5),
                    order=rel.get('order', 1),
                    source_chunk=rel.get('source_chunk', '')
                )

    return G


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from PDF file using pymupdf (fitz)."""
    import fitz  # pymupdf

    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            page_text = page.get_text()
            if page_text:
                text += page_text + "\n\n"

    return text


class HAIQUIterativePipeline:
    """
    Iterative GraphRAG pipeline for HAIQU respiratory disease cognition research.

    Process:
    1. Extract entities from seed PDF
    2. Build initial graph
    3. Iteratively: select entities -> generate queries -> fetch papers -> enrich graph
    4. Stop when 50 papers OR convergence
    5. Generate domain-specific QA
    """

    def __init__(self, config: HAIQUPipelineConfig):
        self.config = config
        self.state = IterativeSearchState()
        self.graph = nx.DiGraph()
        self.schema = None
        self.extractor = None
        self.llm = None
        self.papers_metadata = {}

        # Setup output directories
        self.output_dir = Path(config.output_dir)
        self.graphs_dir = self.output_dir / "graphs"
        self.papers_dir = self.output_dir / "fetched_papers"
        self.queries_dir = self.output_dir / "queries"
        self.state_dir = self.output_dir / "state"

        for d in [self.graphs_dir, self.papers_dir, self.queries_dir, self.state_dir]:
            d.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Initialize LLM, schema, and extractor."""
        print(f"\n{'='*60}")
        print("Initializing HAIQU Iterative Pipeline")
        print(f"{'='*60}\n")

        # Load domain schema
        print(f"Loading domain schema: {self.config.domain_schema}...")
        self.schema = load_domain_schema(self.config.domain_schema)
        print(f"  Domain: {self.schema.domain_name}")
        print(f"  Entity types: {len(self.schema.entity_types)}")
        print(f"  Relationship types: {len(self.schema.relationship_types)}\n")

        # Initialize LLM
        print("Initializing LLM...")
        self.llm = ArgoBridgeLLM()
        print("  LLM ready\n")

        # Create extractor
        print("Creating domain-specific extractor...")
        self.extractor = create_domain_extractor_from_schema(
            self.schema,
            llm_func=self.llm.call_async,
            num_refine_turns=1,
            self_refine=True
        )
        print("  Extractor ready\n")

        # Check for existing state (resumability)
        state_file = self.state_dir / "search_state.json"
        if state_file.exists():
            print("Found existing state - attempting to resume...")
            self.state = IterativeSearchState.load_state(state_file)
            print(f"  Resumed from round {self.state.current_round}")
            print(f"  Papers already fetched: {self.state.total_papers}\n")

            # Load existing graph
            graph_file = self.graphs_dir / "current_graph.graphml"
            if graph_file.exists():
                self.graph = nx.read_graphml(graph_file)
                print(f"  Loaded existing graph: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges\n")
        else:
            # New session
            self.state.start_session(str(self.config.seed_document))

    async def run(self) -> None:
        """Execute the full iterative pipeline."""
        await self.initialize()

        # Round 0: Process seed document
        if self.state.current_round == 0:
            await self.process_seed_document()
            self.state.current_round = 1
            self._save_state()

        # Iterative rounds
        convergence_checker = ConvergenceChecker(
            self.config,
            self.state,
            self.graph
        )

        while True:
            should_stop, reason_code, message = convergence_checker.should_stop()
            if should_stop:
                print(f"\n{'='*60}")
                print(f"STOPPING: {message}")
                print(f"{'='*60}\n")
                break

            await self.execute_round()
            self._save_state()

            # Update graph reference in convergence checker
            convergence_checker.set_graph(self.graph)

        # Final QA generation
        await self.generate_qa()

        # Save final summary
        self._save_summary()

    async def process_seed_document(self) -> None:
        """Process the HAIQU PDF seed document."""
        print(f"\n{'#'*60}")
        print("ROUND 0: Processing Seed Document")
        print(f"{'#'*60}\n")

        seed_path = Path(self.config.seed_document)
        print(f"Seed document: {seed_path.name}")

        # Extract text from PDF
        print("Extracting text from PDF...")
        paper_text = extract_pdf_text(seed_path)
        print(f"  Extracted {len(paper_text)} characters\n")

        # Chunk and extract entities
        chunks = chunk_text(
            paper_text,
            chunk_size=self.config.chunk_size,
            overlap=self.config.chunk_overlap
        )
        print(f"  Created {len(chunks)} chunks")

        global_entities = {}
        global_relationships = []

        print("  Extracting entities and relationships...")
        for i, chunk in enumerate(chunks):
            chunk_id = f"seed_chunk_{i}"
            print(f"    Processing chunk {i+1}/{len(chunks)}...", end="\r")

            num_entities, num_rels = await extract_from_chunk(
                chunk,
                chunk_id,
                self.extractor,
                global_entities,
                global_relationships
            )

        print(f"\n  Extracted: {len(global_entities)} entities, {len(global_relationships)} relationships")

        # Build initial graph
        self.graph = await build_graph_from_extractions(global_entities, global_relationships)
        print(f"  Built graph: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")

        # Record initial entities
        self.state.add_entities_for_round(0, set(global_entities.keys()))

        # Save initial graph
        self._save_graph("round_0_seed")

        print(f"\n  Round 0 complete.\n")

    async def execute_round(self) -> None:
        """Execute one round of query -> fetch -> enrich."""
        round_num = self.state.current_round

        print(f"\n{'#'*60}")
        print(f"ROUND {round_num}: Iterative Discovery")
        print(f"{'#'*60}\n")

        print(f"Current state:")
        print(f"  Total papers: {self.state.total_papers}/{self.config.max_total_papers}")
        print(f"  Graph nodes: {self.graph.number_of_nodes()}")
        print(f"  Graph edges: {self.graph.number_of_edges()}\n")

        # Step 1: Prioritize entities for search
        print("Step 1: Prioritizing entities for search...")
        prioritizer = EntityPriorityQueue(self.graph, self.state, self.config)
        top_entities = prioritizer.get_top_entities(n=self.config.entities_per_round)

        if not top_entities:
            print("  No unsearched entities available")
            self.state.advance_round()
            return

        print(f"  Selected {len(top_entities)} entities:")
        for entity in top_entities:
            entity_type = self.graph.nodes[entity].get('entity_type', 'UNKNOWN')
            print(f"    - {entity} ({entity_type})")
        print()

        # Step 2: Generate queries
        print("Step 2: Generating search queries...")
        query_generator = IterativeQueryGenerator(self.graph, self.state, self.config)

        all_queries = []
        for entity in top_entities:
            queries = query_generator.generate_queries_for_entity(
                entity,
                max_queries=self.config.queries_per_entity
            )
            all_queries.extend(queries)

        print(f"  Generated {len(all_queries)} queries")
        self._save_queries(all_queries, round_num)
        print()

        # Step 3: Fetch papers
        print("Step 3: Fetching papers...")
        papers_this_round = await self._fetch_papers(all_queries, top_entities)
        print(f"  Fetched {len(papers_this_round)} papers\n")

        # Update entity search records
        for entity in top_entities:
            entity_queries = [q['query'] for q in all_queries if q['entity'] == entity]
            papers_for_entity = sum(1 for p in papers_this_round.values()
                                    if p.get('source_entity') == entity)
            self.state.mark_entity_searched(
                entity,
                self.graph.nodes[entity].get('entity_type', 'UNKNOWN'),
                entity_queries,
                papers_for_entity
            )

        if not papers_this_round:
            print("  No new papers found")
            self.state.advance_round()
            return

        # Step 4: Extract and enrich
        print("Step 4: Extracting entities and enriching graph...")
        initial_nodes = self.graph.number_of_nodes()
        initial_edges = self.graph.number_of_edges()

        new_entities_this_round: Set[str] = set()

        for paper_uuid, paper_meta in papers_this_round.items():
            paper_content = paper_meta.get('content', '')
            if len(paper_content) < self.config.min_paper_length:
                continue

            entities, relationships = await self._extract_from_paper(paper_content, paper_uuid)

            # Add to graph with merging
            self.graph, name_mapping = add_entities_to_graph(
                self.graph,
                entities,
                paper_uuid,
                similarity_threshold=self.config.similarity_threshold,
                auto_merge=self.config.auto_merge_entities
            )

            self.graph = add_relationships_to_graph(
                self.graph,
                relationships,
                name_mapping,
                paper_uuid
            )

            # Track new entities
            for entity_name in entities.keys():
                canonical = name_mapping.get(entity_name, entity_name)
                if canonical not in self.state.searched_entities:
                    new_entities_this_round.add(canonical)

        # Record entities for this round
        all_current_entities = set(self.graph.nodes())
        self.state.add_entities_for_round(round_num, all_current_entities)

        nodes_added = self.graph.number_of_nodes() - initial_nodes
        edges_added = self.graph.number_of_edges() - initial_edges

        print(f"  New nodes: +{nodes_added}, New edges: +{edges_added}")
        print(f"  New unique entities: {len(new_entities_this_round)}")
        print(f"  Updated graph: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")

        # Save graph for this round
        self._save_graph(f"round_{round_num}")

        self.state.advance_round()
        print(f"\n  Round {round_num} complete.\n")

    async def _fetch_papers(
        self,
        queries: List[Dict],
        source_entities: List[str]
    ) -> Dict[str, Dict]:
        """Fetch papers for queries."""
        api_key = self.config.firecrawl_api_key or os.getenv('FIRECRAWL_API_KEY')
        if not api_key:
            print("  WARNING: No Firecrawl API key - skipping paper fetching")
            return {}

        papers_limit = min(
            self.config.papers_per_round,
            self.config.papers_remaining(self.state.total_papers)
        )

        if papers_limit <= 0:
            return {}

        papers_fetched = {}

        for query_dict in queries:
            if len(papers_fetched) >= papers_limit:
                break

            query = query_dict['query']
            source_entity = query_dict.get('entity', '')

            results = search_papers(
                query=query,
                api_key=api_key,
                max_results=self.config.papers_per_query
            )

            for result in results:
                if len(papers_fetched) >= papers_limit:
                    break

                url = result.get('url', '')
                if self.state.is_paper_fetched(url):
                    continue

                content = extract_text_from_result(result)
                if len(content) < self.config.min_paper_length:
                    continue

                # Save paper
                paper_uuid, metadata = save_paper_with_uuid(
                    content=content,
                    metadata={
                        'title': result.get('title', 'Unknown'),
                        'url': url,
                        'source_query': query,
                        'source_entity': source_entity,
                        'round': self.state.current_round
                    },
                    output_dir=self.papers_dir
                )

                # Store metadata with content for extraction
                metadata['content'] = content
                papers_fetched[paper_uuid] = metadata

                # Update state
                self.state.add_fetched_paper(
                    uuid=paper_uuid,
                    url=url,
                    title=result.get('title', 'Unknown'),
                    source_query=query,
                    source_entity=source_entity
                )

                self.papers_metadata[paper_uuid] = metadata

        # Save updated metadata
        metadata_file = self.papers_dir / "papers_metadata.json"
        metadata_to_save = {k: {kk: vv for kk, vv in v.items() if kk != 'content'}
                           for k, v in self.papers_metadata.items()}
        save_papers_metadata(metadata_to_save, metadata_file)

        return papers_fetched

    async def _extract_from_paper(
        self,
        content: str,
        paper_uuid: str
    ) -> Tuple[Dict, List]:
        """Extract entities and relationships from paper content."""
        chunks = chunk_text(
            content,
            chunk_size=self.config.chunk_size,
            overlap=self.config.chunk_overlap
        )

        global_entities = {}
        global_relationships = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{paper_uuid}_chunk_{i}"
            try:
                await extract_from_chunk(
                    chunk,
                    chunk_id,
                    self.extractor,
                    global_entities,
                    global_relationships
                )
            except Exception as e:
                print(f"    Warning: Failed to extract from chunk {i}: {e}")
                continue

        return global_entities, global_relationships

    async def generate_qa(self) -> None:
        """Generate QA pairs from the final enriched graph."""
        print(f"\n{'#'*60}")
        print("FINAL STAGE: Generating QA Pairs")
        print(f"{'#'*60}\n")

        try:
            from generate_contrastive_qa import (
                analyze_graph_with_gasl,
                generate_questions_from_analyses
            )

            print("Running GASL analysis...")
            analyses = await analyze_graph_with_gasl(
                self.graph,
                self.config.domain_schema,
                self.llm
            )

            print(f"  Found {sum(len(v) for v in analyses.values())} analysis results\n")

            print("Generating questions from analyses...")
            questions = await generate_questions_from_analyses(
                analyses=analyses,
                graph=self.graph,
                domain_name=self.config.domain_schema,
                llm=self.llm,
                max_questions=self.config.num_questions,
                enrich_info_pieces=self.config.enrich_info_pieces,
                enrich_graph_depth=self.config.enrich_graph_depth
            )

            # Save QA output
            qa_output = self.output_dir / "haiqu_contrastive_qa.json"
            output_data = {
                'domain': self.config.domain_schema,
                'seed_document': str(self.config.seed_document),
                'total_papers': self.state.total_papers,
                'total_rounds': self.state.current_round,
                'final_graph_nodes': self.graph.number_of_nodes(),
                'final_graph_edges': self.graph.number_of_edges(),
                'num_questions': len(questions),
                'generated_at': datetime.now().isoformat(),
                'questions': questions
            }

            with open(qa_output, 'w') as f:
                json.dump(output_data, f, indent=2)

            print(f"\n  Saved {len(questions)} questions to: {qa_output}")

        except ImportError as e:
            print(f"  Warning: Could not import QA generation module: {e}")
            print("  Skipping QA generation - graph is saved and can be used later.")

        except Exception as e:
            print(f"  Error during QA generation: {e}")
            print("  Graph has been saved. You can regenerate QA later.")

    def _save_state(self) -> None:
        """Save current state to disk."""
        state_file = self.state_dir / "search_state.json"
        self.state.save_state(state_file)

    def _save_graph(self, name: str) -> None:
        """Save graph to disk."""
        # Create a copy with serialized attributes (GraphML doesn't support lists)
        graph_copy = self.graph.copy()

        # Serialize node attributes
        for node in graph_copy.nodes():
            for key, value in list(graph_copy.nodes[node].items()):
                if isinstance(value, list):
                    graph_copy.nodes[node][key] = ','.join(str(v) for v in value)
                elif not isinstance(value, (str, int, float, bool, type(None))):
                    graph_copy.nodes[node][key] = str(value)

        # Serialize edge attributes
        for src, tgt in graph_copy.edges():
            for key, value in list(graph_copy.edges[src, tgt].items()):
                if isinstance(value, list):
                    graph_copy.edges[src, tgt][key] = ','.join(str(v) for v in value)
                elif not isinstance(value, (str, int, float, bool, type(None))):
                    graph_copy.edges[src, tgt][key] = str(value)

        # Save timestamped version
        nx.write_graphml(graph_copy, self.graphs_dir / f"{name}.graphml")
        # Save current version (for resumability)
        nx.write_graphml(graph_copy, self.graphs_dir / "current_graph.graphml")

    def _save_queries(self, queries: List[Dict], round_num: int) -> None:
        """Save queries to disk."""
        # Remove any non-serializable fields
        serializable_queries = []
        for q in queries:
            sq = {k: v for k, v in q.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
            serializable_queries.append(sq)

        query_file = self.queries_dir / f"round_{round_num}_queries.json"
        with open(query_file, 'w') as f:
            json.dump({
                'round': round_num,
                'num_queries': len(serializable_queries),
                'queries': serializable_queries
            }, f, indent=2)

    def _save_summary(self) -> None:
        """Save pipeline execution summary."""
        summary = {
            'completed_at': datetime.now().isoformat(),
            'seed_document': str(self.config.seed_document),
            'domain_schema': self.config.domain_schema,
            'total_rounds': self.state.current_round,
            'total_papers': self.state.total_papers,
            'final_graph_nodes': self.graph.number_of_nodes(),
            'final_graph_edges': self.graph.number_of_edges(),
            'entities_searched': len(self.state.searched_entities),
            'papers_by_round': {
                str(r): len(p) for r, p in self.state.papers_by_round.items()
            },
            'config': self.config.to_dict()
        }

        summary_file = self.output_dir / "pipeline_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        print(f"\n{'='*60}")
        print("Pipeline Summary")
        print(f"{'='*60}")
        print(f"  Total rounds: {summary['total_rounds']}")
        print(f"  Total papers: {summary['total_papers']}")
        print(f"  Final graph: {summary['final_graph_nodes']} nodes, {summary['final_graph_edges']} edges")
        print(f"  Entities searched: {summary['entities_searched']}")
        print(f"\n  Summary saved to: {summary_file}")
        print(f"{'='*60}\n")


async def main(args):
    """Main entry point."""
    # Build config
    if args.config:
        if args.config.endswith('.yaml') or args.config.endswith('.yml'):
            config = HAIQUPipelineConfig.from_yaml(args.config)
        else:
            config = HAIQUPipelineConfig.from_json(args.config)
    else:
        config = HAIQUPipelineConfig(
            seed_document=args.seed_pdf,
            output_dir=args.output_dir,
            max_total_papers=args.max_papers,
            papers_per_round=args.papers_per_round,
            num_questions=args.num_questions,
            firecrawl_api_key=args.firecrawl_api_key or os.getenv('FIRECRAWL_API_KEY')
        )

    print("\nConfiguration:")
    print(config)
    print()

    # Run pipeline
    pipeline = HAIQUIterativePipeline(config)
    await pipeline.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HAIQU Iterative GraphRAG Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default settings
  python run_haiqu_iterative_pipeline.py --seed-pdf haiqu/20260126\\ Cognitive\\ Tests\\ for\\ HAIQU.pdf

  # Run with custom limits
  python run_haiqu_iterative_pipeline.py --seed-pdf haiqu/doc.pdf --max-papers 100 --num-questions 50

  # Run with config file
  python run_haiqu_iterative_pipeline.py --config haiqu_config.yaml
"""
    )

    parser.add_argument(
        "--seed-pdf",
        type=str,
        help="Path to seed PDF document"
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to YAML or JSON config file (overrides other arguments)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./haiqu_output",
        help="Output directory (default: ./haiqu_output)"
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=50,
        help="Maximum total papers to fetch (default: 50)"
    )
    parser.add_argument(
        "--papers-per-round",
        type=int,
        default=10,
        help="Papers to fetch per round (default: 10)"
    )
    parser.add_argument(
        "--num-questions",
        type=int,
        default=30,
        help="Number of QA pairs to generate (default: 30)"
    )
    parser.add_argument(
        "--firecrawl-api-key",
        type=str,
        help="Firecrawl API key (or set FIRECRAWL_API_KEY env var)"
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.config and not args.seed_pdf:
        parser.error("Either --seed-pdf or --config is required")

    asyncio.run(main(args))
