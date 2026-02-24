"""
Regenerate Questions from Existing Graphs

This script iterates through existing graphs in ASM_595 and regenerates questions
using generate_contrastive_qa.py with configurable distractor and depth settings.

Key difference from run_batch_pipeline.py:
- Does NOT regenerate graphs
- Only runs question generation on existing enriched graphs
- Allows different distractor/depth settings than originally used
"""

import argparse
import asyncio
import json
import os
import sys
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.absolute()))

# Defer heavy imports until needed
networkx = None
load_domain_schema = None
ArgoBridgeLLM = None
analyze_graph_with_gasl = None
generate_questions_from_analyses = None


def _lazy_imports():
    """Import heavy dependencies only when needed."""
    global networkx, load_domain_schema, ArgoBridgeLLM
    global analyze_graph_with_gasl, generate_questions_from_analyses

    if networkx is None:
        import networkx as nx
        networkx = nx

    if load_domain_schema is None:
        from domain_schemas.schema_loader import load_domain_schema as _load_domain_schema
        load_domain_schema = _load_domain_schema

    if ArgoBridgeLLM is None:
        from gasl.llm import ArgoBridgeLLM as _ArgoBridgeLLM
        ArgoBridgeLLM = _ArgoBridgeLLM

    if analyze_graph_with_gasl is None:
        from generate_contrastive_qa import (
            analyze_graph_with_gasl as _analyze,
            generate_questions_from_analyses as _generate
        )
        analyze_graph_with_gasl = _analyze
        generate_questions_from_analyses = _generate


@dataclass
class RegenerationStats:
    """Track regeneration statistics."""
    total_papers: int = 0
    processed: int = 0
    skipped_no_graph: int = 0
    failed: int = 0
    total_questions: int = 0
    papers_with_questions: List[str] = field(default_factory=list)
    papers_failed: List[str] = field(default_factory=list)


class QuestionRegenerator:
    """
    Regenerate questions from existing graphs with new settings.

    This class finds existing enriched graphs in ASM_595 and regenerates
    questions using specified distractor and depth parameters.
    """

    def __init__(
        self,
        base_directory: Path,
        domain: str,
        enrich_info_pieces: int = 10,
        enrich_graph_depth: int = 3,
        enrich_max_candidates: int = 50,
        max_questions_per_paper: int = 20,
        sample_nodes: int = 20,
        output_suffix: str = "_v2"
    ):
        """
        Initialize the regenerator.

        Args:
            base_directory: Base directory containing papers (e.g., ASM_595/mSystems)
            domain: Domain to process (e.g., 'ecology', 'molecular_biology')
            enrich_info_pieces: Number of distracting facts per question (default: 10)
            enrich_graph_depth: Graph traversal depth for distractors (default: 3)
            enrich_max_candidates: Max candidates to score per question (default: 50)
            max_questions_per_paper: Max questions to generate per paper (default: 20)
            sample_nodes: Number of nodes to randomly sample for analysis (default: 20)
            output_suffix: Suffix for output files (default: '_v2')
        """
        self.base_directory = Path(base_directory)
        self.domain = domain
        self.enrich_info_pieces = enrich_info_pieces
        self.enrich_graph_depth = enrich_graph_depth
        self.enrich_max_candidates = enrich_max_candidates
        self.max_questions_per_paper = max_questions_per_paper
        self.sample_nodes = sample_nodes
        self.output_suffix = output_suffix
        self.interrupted = False
        self.llm = None

        # Handle Ctrl+C gracefully
        signal.signal(signal.SIGINT, self._handle_interrupt)

    def _handle_interrupt(self, signum, frame):
        """Handle interrupt signal."""
        print("\n\n⚠ Regeneration interrupted by user")
        self.interrupted = True

    def find_existing_graphs(self) -> List[Dict]:
        """
        Find all existing enriched graphs for the specified domain.

        Returns:
            List of dicts with paper_id, graph_path, output_dir
        """
        graphs = []

        # Pattern: base_dir/*/source_files/.qa_output/*/domain/enriched_graphs/*_enriched_graph.graphml
        # Also check for non-enriched graphs as fallback

        for paper_dir in self.base_directory.iterdir():
            if not paper_dir.is_dir():
                continue

            qa_output_dir = paper_dir / "source_files" / ".qa_output"
            if not qa_output_dir.exists():
                continue

            for paper_id_dir in qa_output_dir.iterdir():
                if not paper_id_dir.is_dir():
                    continue

                domain_dir = paper_id_dir / self.domain
                if not domain_dir.exists():
                    continue

                # Look for enriched graph first, then fallback to regular graph
                enriched_graph_path = domain_dir / "enriched_graphs" / f"{self.domain}_enriched_graph.graphml"
                regular_graph_path = domain_dir / "graphs" / f"{self.domain}_graph.graphml"

                graph_path = None
                graph_type = None

                if enriched_graph_path.exists():
                    graph_path = enriched_graph_path
                    graph_type = "enriched"
                elif regular_graph_path.exists():
                    graph_path = regular_graph_path
                    graph_type = "regular"

                if graph_path:
                    graphs.append({
                        "paper_id": paper_id_dir.name,
                        "graph_path": graph_path,
                        "graph_type": graph_type,
                        "output_dir": domain_dir,
                        "paper_dir": paper_dir
                    })

        return graphs

    async def regenerate_questions_for_graph(
        self,
        graph_info: Dict,
        stats: RegenerationStats
    ) -> Optional[Dict]:
        """
        Regenerate questions for a single graph.

        Args:
            graph_info: Dict with graph_path, paper_id, output_dir
            stats: Stats object to update

        Returns:
            Output data dict or None if failed
        """
        paper_id = graph_info["paper_id"]
        graph_path = graph_info["graph_path"]
        output_dir = graph_info["output_dir"]

        try:
            # Load graph
            print(f"  Loading graph: {graph_path.name} ({graph_info['graph_type']})")
            graph = networkx.read_graphml(graph_path)
            print(f"  ✓ Graph loaded: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

            if graph.number_of_nodes() < 5:
                print(f"  ⚠ Graph too small ({graph.number_of_nodes()} nodes), skipping")
                return None

            # Load domain schema
            schema = load_domain_schema(self.domain)

            # Create contrastive analyzer (samples fresh nodes per question)
            print(f"  Initializing GASL contrastive analyzer (sample_nodes={self.sample_nodes})...")
            analyzer = await analyze_graph_with_gasl(graph, self.domain, self.llm, sample_nodes=self.sample_nodes)

            # Generate questions with new enrichment settings
            print(f"  Generating questions (distractors={self.enrich_info_pieces}, depth={self.enrich_graph_depth}, max_candidates={self.enrich_max_candidates})...")
            questions = await generate_questions_from_analyses(
                analyzer=analyzer,
                graph=graph,
                domain_name=self.domain,
                llm=self.llm,
                max_questions=self.max_questions_per_paper,
                enrich_info_pieces=self.enrich_info_pieces,
                enrich_graph_depth=self.enrich_graph_depth,
                enrich_max_candidates=self.enrich_max_candidates
            )

            if not questions:
                print(f"  ⚠ No questions generated")
                return None

            print(f"  ✓ Generated {len(questions)} questions")

            # Save output with suffix
            output_filename = f"contrastive_qa{self.output_suffix}.json"
            output_path = output_dir / output_filename

            output_data = {
                "paper_id": paper_id,
                "domain": self.domain,
                "graph_file": str(graph_path),
                "graph_type": graph_info["graph_type"],
                "regenerated_at": datetime.now().isoformat(),
                "settings": {
                    "enrich_info_pieces": self.enrich_info_pieces,
                    "enrich_graph_depth": self.enrich_graph_depth,
                    "max_questions": self.max_questions_per_paper
                },
                "num_questions": len(questions),
                "questions": questions
            }

            with open(output_path, 'w') as f:
                json.dump(output_data, f, indent=2)

            print(f"  ✓ Saved to: {output_path}")

            stats.total_questions += len(questions)
            stats.papers_with_questions.append(paper_id)

            return output_data

        except Exception as e:
            print(f"  ✗ Error: {type(e).__name__}: {str(e)}")
            stats.papers_failed.append(paper_id)
            return None

    async def run(
        self,
        start_from: Optional[str] = None,
        limit: Optional[int] = None,
        paper_ids: Optional[List[str]] = None,
        force: bool = False
    ) -> RegenerationStats:
        """
        Run question regeneration on all existing graphs.

        Args:
            start_from: Paper ID to resume from
            limit: Maximum number of papers to process
            paper_ids: Specific paper IDs to process (if provided, ignores start_from)
            force: If True, regenerate even if output file exists

        Returns:
            RegenerationStats object
        """
        self.force = force
        # Load heavy dependencies
        _lazy_imports()

        # Initialize LLM
        self.llm = ArgoBridgeLLM()

        # Find existing graphs
        print(f"\n{'#'*70}")
        print(f"# QUESTION REGENERATION FROM EXISTING GRAPHS")
        print(f"{'#'*70}\n")

        print(f"Base directory: {self.base_directory}")
        print(f"Domain: {self.domain}")
        print(f"Settings:")
        print(f"  - Distracting facts per question: {self.enrich_info_pieces}")
        print(f"  - Graph traversal depth: {self.enrich_graph_depth}")
        print(f"  - Max candidates to score: {self.enrich_max_candidates}")
        print(f"  - Max questions per paper: {self.max_questions_per_paper}")
        print(f"  - Output suffix: {self.output_suffix}")
        print()

        print("Scanning for existing graphs...")
        graphs = self.find_existing_graphs()

        if not graphs:
            print("✗ No existing graphs found!")
            return RegenerationStats()

        print(f"✓ Found {len(graphs)} graphs for domain '{self.domain}'\n")

        # Filter by paper_ids if provided
        if paper_ids:
            graphs = [g for g in graphs if g["paper_id"] in paper_ids]
            print(f"Filtered to {len(graphs)} specified papers\n")

        # Handle start_from
        if start_from and not paper_ids:
            start_idx = None
            for i, g in enumerate(graphs):
                if g["paper_id"] == start_from:
                    start_idx = i
                    break

            if start_idx is None:
                print(f"✗ Paper not found: {start_from}")
                sys.exit(1)

            graphs = graphs[start_idx:]
            print(f"Resuming from paper: {start_from}\n")

        # Apply limit
        if limit:
            graphs = graphs[:limit]
            print(f"Limited to {limit} papers\n")

        stats = RegenerationStats(total_papers=len(graphs))

        print(f"{'='*70}\n")

        skipped_existing = 0
        for i, graph_info in enumerate(graphs, 1):
            if self.interrupted:
                print("\nStopping due to interrupt...")
                break

            paper_id = graph_info["paper_id"]
            output_dir = graph_info["output_dir"]

            # Skip if output file already exists (unless --force)
            output_filename = f"contrastive_qa{self.output_suffix}.json"
            output_path = output_dir / output_filename
            if output_path.exists() and not self.force:
                skipped_existing += 1
                print(f"\n[{i}/{len(graphs)}] Skipping (already exists): {paper_id}")
                continue

            print(f"\n[{i}/{len(graphs)}] Processing: {paper_id}")

            result = await self.regenerate_questions_for_graph(graph_info, stats)

            if result:
                stats.processed += 1
            else:
                stats.skipped_no_graph += 1

        # Print summary
        print(f"\n{'='*70}")
        print(f"\nRegeneration Complete!")
        print(f"  Total papers found: {stats.total_papers}")
        print(f"  Skipped (already done): {skipped_existing}")
        print(f"  Successfully processed: {stats.processed}")
        print(f"  Skipped/Failed: {stats.skipped_no_graph + len(stats.papers_failed)}")
        print(f"  Total questions generated: {stats.total_questions}")
        print(f"{'='*70}\n")

        return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Regenerate questions from existing graphs with new distractor settings"
    )

    parser.add_argument(
        "base_directory",
        type=str,
        help="Base directory containing papers (e.g., /path/to/ASM_595/mSystems)"
    )

    parser.add_argument(
        "domain",
        type=str,
        help="Domain to process (e.g., ecology, molecular_biology)"
    )

    parser.add_argument(
        "--enrich-info-pieces",
        type=int,
        default=10,
        help="Number of distracting facts per question (default: 10)"
    )

    parser.add_argument(
        "--enrich-graph-depth",
        type=int,
        default=3,
        help="Graph traversal depth for distractors (1-3, default: 3)"
    )

    parser.add_argument(
        "--enrich-max-candidates",
        type=int,
        default=50,
        help="Max candidates to score per question (default: 50). Prevents O(n) LLM calls on large graphs."
    )

    parser.add_argument(
        "--max-questions",
        type=int,
        default=20,
        help="Maximum questions per paper (default: 20)"
    )

    parser.add_argument(
        "--sample-nodes",
        type=int,
        default=20,
        help="Number of nodes to randomly sample for contrastive analysis (default: 20)"
    )

    parser.add_argument(
        "--output-suffix",
        type=str,
        default="_v2",
        help="Suffix for output files (default: '_v2')"
    )

    parser.add_argument(
        "--start-from",
        type=str,
        help="Resume from specific paper ID"
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Process maximum N papers"
    )

    parser.add_argument(
        "--papers",
        type=str,
        nargs="+",
        help="Specific paper IDs to process"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force regeneration even if output file already exists"
    )

    args = parser.parse_args()

    regenerator = QuestionRegenerator(
        base_directory=Path(args.base_directory),
        domain=args.domain,
        enrich_info_pieces=args.enrich_info_pieces,
        enrich_graph_depth=args.enrich_graph_depth,
        enrich_max_candidates=args.enrich_max_candidates,
        max_questions_per_paper=args.max_questions,
        sample_nodes=args.sample_nodes,
        output_suffix=args.output_suffix
    )

    stats = await regenerator.run(
        start_from=args.start_from,
        limit=args.limit,
        paper_ids=args.papers,
        force=args.force
    )

    # Exit with error if nothing processed
    if stats.processed == 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
