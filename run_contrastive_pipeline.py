"""
Pipeline Orchestrator
Runs the complete contrastive QA generation pipeline from paper to questions
"""

import argparse
import asyncio
import sys
import os
from pathlib import Path
import subprocess
import json

sys.path.insert(0, str(Path(__file__).parent.absolute()))


def run_command(cmd: list[str], description: str, check: bool = True) -> subprocess.CompletedProcess:
    """
    Run a command and handle errors.

    Args:
        cmd: Command to run as list of strings
        description: Description for logging
        check: Whether to raise exception on error

    Returns:
        CompletedProcess result
    """
    print(f"\n{'='*60}")
    print(f"{description}")
    print(f"{'='*60}")
    print(f"Running: {' '.join(cmd)}\n")

    # Don't capture output - let it stream to console so user sees errors in real-time
    result = subprocess.run(cmd, check=False)

    if check and result.returncode != 0:
        print(f"\n{'='*60}")
        print(f"✗ ERROR: {description} failed with exit code {result.returncode}")
        print(f"{'='*60}")
        print(f"Command: {' '.join(cmd)}")
        print(f"\nSee error output above for details.")
        print(f"{'='*60}\n")
        sys.exit(result.returncode)

    return result


async def main(args):
    """Run the complete pipeline"""

    print(f"\n{'#'*60}")
    print(f"# CONTRASTIVE QA GENERATION PIPELINE")
    print(f"{'#'*60}\n")

    paper_path = Path(args.paper).resolve()
    if not paper_path.exists():
        print(f"✗ ERROR: Paper file not found: {paper_path}")
        sys.exit(1)

    # Determine output directory relative to input file
    # Structure: input_directory/.qa_output/paper_name/domain/
    use_relative_output = args.output_dir == "./pipeline_output"

    if use_relative_output:
        # Use default relative output structure if output-dir not explicitly set
        paper_stem = paper_path.stem  # filename without extension
        output_dir = paper_path.parent / ".qa_output" / paper_stem / args.domain
    else:
        # Use explicit output directory if provided
        output_dir = Path(args.output_dir).resolve()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean up old output files to avoid confusion (only in relative output dirs)
    if use_relative_output:
        print(f"\nCleaning output directory: {output_dir}")
        subdirs_to_clean = ["graphs", "queries", "fetched_papers", "enriched_graphs"]
        files_to_clean = ["contrastive_qa.json", "pipeline_metadata.json"]

        for subdir in subdirs_to_clean:
            subdir_path = output_dir / subdir
            if subdir_path.exists():
                import shutil
                shutil.rmtree(subdir_path)
                print(f"  ✓ Removed {subdir}/")

        for file in files_to_clean:
            file_path = output_dir / file
            if file_path.exists():
                file_path.unlink()
                print(f"  ✓ Removed {file}")

    print()

    # Track outputs
    outputs = {
        "paper": str(paper_path),
        "output_dir": str(output_dir)
    }

    # Domain must be specified
    domain = args.domain
    if not domain:
        print("✗ ERROR: --domain argument is required")
        print("  Available domains: molecular_biology, microbial_biology, infectious_disease,")
        print("                     ecology, epidemiology, disease_biology")
        sys.exit(1)

    outputs["domain"] = domain

    # =========================================================================
    # STAGE 1: Assess Paper Suitability for Specified Domain
    # =========================================================================
    if not args.skip_assessment:
        cmd = [
            "python", "assess_paper_suitability.py",
            str(paper_path),
            "--domain", domain
        ]
        result = run_command(cmd, f"STAGE 1: Assess Paper Suitability for {domain}", check=False)

        if result.returncode != 0:
            print(f"\n✗ Paper is not suitable for {domain}. Exiting.")
            sys.exit(1)

        print(f"\n✓ Paper is suitable for {domain}")

    # =========================================================================
    # STAGE 2: Build Initial Graph
    # =========================================================================
    graphs_dir = output_dir / "graphs"
    graph_file = graphs_dir / f"{domain}_graph.graphml"

    if not args.skip_graph_creation or not graph_file.exists():
        cmd = [
            "python", "create_domain_typed_graph.py",
            str(paper_path),
            domain,
            "--output-dir", str(graphs_dir)
        ]

        if args.chunk_size:
            cmd.extend(["--chunk-size", str(args.chunk_size)])

        run_command(cmd, "STAGE 2: Build Initial Knowledge Graph")

    outputs["initial_graph"] = str(graph_file)

    # =========================================================================
    # STAGE 3: Generate Search Queries
    # =========================================================================
    queries_dir = output_dir / "queries"
    queries_dir.mkdir(parents=True, exist_ok=True)

    query_files = []

    if not args.skip_query_generation:
        query_types = [
            ("contrastive_alternatives", "generate_queries_contrastive_alternatives.py"),
            ("pathway_expansion", "generate_queries_pathway_expansion.py"),
            ("therapeutic_alternatives", "generate_queries_therapeutic_alternatives.py"),
            ("cross_domain", "generate_queries_cross_domain.py")
        ]

        for query_type, script in query_types:
            output_file = queries_dir / f"{query_type}_queries.json"
            query_files.append(str(output_file))

            cmd = [
                "python", f"query_generation/{script}",
                str(graph_file),
                domain,
                "--output", str(output_file),
                "--max-queries", str(args.queries_per_type)
            ]

            run_command(cmd, f"STAGE 3: Generate {query_type.replace('_', ' ').title()} Queries")

    outputs["query_files"] = query_files

    # =========================================================================
    # STAGE 4: Fetch Papers with Firecrawl
    # =========================================================================
    papers_dir = output_dir / "fetched_papers"

    if not args.skip_paper_fetching and query_files:
        # Check for API key
        api_key = args.firecrawl_api_key or os.getenv('FIRECRAWL_API_KEY')

        if not api_key:
            print("\n⚠ WARNING: No Firecrawl API key provided. Skipping paper fetching.")
            print("  Set FIRECRAWL_API_KEY environment variable or use --firecrawl-api-key")
        else:
            cmd = [
                "python", "fetch_papers_firecrawl.py",
                *query_files,
                "--output-dir", str(papers_dir),
                "--max-total-papers", str(args.max_papers),
                "--api-key", api_key
            ]

            run_command(cmd, "STAGE 4: Fetch Additional Papers with Firecrawl")

    outputs["papers_dir"] = str(papers_dir)

    # =========================================================================
    # STAGE 5: Enrich Graph with Papers
    # =========================================================================
    enriched_dir = output_dir / "enriched_graphs"
    enriched_graph_file = enriched_dir / f"{domain}_enriched_graph.graphml"

    metadata_file = papers_dir / "papers_metadata.json"

    if not args.skip_graph_enrichment and metadata_file.exists():
        # Check how many papers were fetched
        with open(metadata_file, 'r') as f:
            papers_metadata = json.load(f)

        if len(papers_metadata) > 0:
            cmd = [
                "python", "enrich_graph_with_papers.py",
                str(graph_file),
                domain,
                "--papers-dir", str(papers_dir),
                "--output-dir", str(enriched_dir)
            ]

            if args.max_papers_for_enrichment:
                cmd.extend(["--max-papers", str(args.max_papers_for_enrichment)])

            run_command(cmd, "STAGE 5: Enrich Graph with Additional Papers")

            # Use enriched graph for question generation
            graph_file = enriched_graph_file
        else:
            print("\n⚠ No papers were fetched, using initial graph for question generation")
    else:
        print("\n⚠ No papers metadata found, using initial graph for question generation")

    outputs["final_graph"] = str(graph_file)

    # =========================================================================
    # STAGE 6: Generate Contrastive Questions
    # =========================================================================
    qa_output = output_dir / "contrastive_qa.json"

    cmd = [
        "python", "generate_contrastive_qa.py",
        str(graph_file),
        domain,
        "--output", str(qa_output),
        "--max-questions", str(args.num_questions)
    ]

    run_command(cmd, "STAGE 6: Generate Contrastive Questions")

    outputs["questions"] = str(qa_output)

    # =========================================================================
    # PIPELINE COMPLETE
    # =========================================================================
    print(f"\n{'#'*60}")
    print(f"# PIPELINE COMPLETE")
    print(f"{'#'*60}\n")

    print("Output files:")
    for key, value in outputs.items():
        print(f"  {key}: {value}")

    print(f"\nAll outputs saved to: {output_dir}")
    print(f"Questions saved to: {qa_output}")

    # Save pipeline metadata
    pipeline_metadata = {
        "paper": str(paper_path),
        "domain": domain,
        "outputs": outputs,
        "args": vars(args)
    }

    metadata_output = output_dir / "pipeline_metadata.json"
    with open(metadata_output, 'w') as f:
        json.dump(pipeline_metadata, f, indent=2)

    print(f"Pipeline metadata saved to: {metadata_output}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run complete contrastive QA generation pipeline"
    )
    parser.add_argument(
        "paper",
        type=str,
        help="Path to input paper (.txt file)"
    )
    parser.add_argument(
        "--domain",
        type=str,
        required=True,
        help="Domain schema to use (REQUIRED). Options: molecular_biology, microbial_biology, infectious_disease, ecology, epidemiology, disease_biology"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./pipeline_output",
        help="Output directory for all results (default: input_dir/.qa_output/paper_name/domain/ if not set)"
    )
    parser.add_argument(
        "--num-questions",
        type=int,
        default=20,
        help="Number of questions to generate (default: 20)"
    )
    parser.add_argument(
        "--firecrawl-api-key",
        type=str,
        help="Firecrawl API key (or set FIRECRAWL_API_KEY env var)"
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=30,
        help="Maximum papers to fetch from Firecrawl (default: 30)"
    )
    parser.add_argument(
        "--max-papers-for-enrichment",
        type=int,
        help="Maximum papers to use for graph enrichment (default: all fetched)"
    )
    parser.add_argument(
        "--queries-per-type",
        type=int,
        default=10,
        help="Number of queries to generate per query type (default: 10)"
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        help="Text chunk size for processing (default: 2000)"
    )
    parser.add_argument(
        "--skip-assessment",
        action="store_true",
        help="Skip paper suitability assessment"
    )
    parser.add_argument(
        "--skip-graph-creation",
        action="store_true",
        help="Skip initial graph creation (use existing)"
    )
    parser.add_argument(
        "--skip-query-generation",
        action="store_true",
        help="Skip query generation"
    )
    parser.add_argument(
        "--skip-paper-fetching",
        action="store_true",
        help="Skip paper fetching with Firecrawl"
    )
    parser.add_argument(
        "--skip-graph-enrichment",
        action="store_true",
        help="Skip graph enrichment (use initial graph only)"
    )

    args = parser.parse_args()
    asyncio.run(main(args))
