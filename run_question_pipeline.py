#!/usr/bin/env python
"""
Question-driven GraphRAG pipeline.

Starts from a single question and runs one iterative loop:
  search (Firecrawl) -> build/expand a typed knowledge graph ->
  answer with GASL -> assess gaps -> search again until the answer is
  well-supported or budgets are exhausted.

If no --schema is given, a domain schema is synthesized for the question
(generate -> judge -> test on real search results -> refine) before the loop.

Examples:
  # Synthesize a schema and answer from scratch
  FIRECRAWL_API_KEY=... python run_question_pipeline.py \
      --question "How effective is upper-room UV-C at reducing TB transmission in hospitals?" \
      --output-dir question_runs/uvc_tb

  # Reuse an existing domain schema
  python run_question_pipeline.py \
      --question "..." --schema engineering_control --max-rounds 3
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from question_pipeline import PipelineConfig, QuestionPipeline


def build_config(args: argparse.Namespace) -> PipelineConfig:
    return PipelineConfig(
        question=args.question,
        output_dir=args.output_dir,
        schema_name=args.schema,
        schema_review_rounds=args.schema_review_rounds,
        schema_expectations=args.expectations or "",
        firecrawl_api_key=args.firecrawl_api_key,
        max_rounds=args.max_rounds,
        max_papers=args.max_papers,
        papers_per_round=args.papers_per_round,
        papers_per_query=args.papers_per_query,
        queries_per_round=args.queries_per_round,
        min_paper_length=args.min_paper_length,
        max_paper_length=args.max_paper_length,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        extraction_concurrency=args.extraction_concurrency,
        similarity_threshold=args.similarity_threshold,
        self_refine=args.self_refine,
        max_gasl_iterations=args.max_gasl_iterations,
        target_confidence=args.target_confidence,
        model=args.model,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Question-driven iterative search + KG + GASL pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--question", required=True, help="The question to answer.")
    parser.add_argument("--output-dir", default="./question_runs/run", help="Output directory.")
    parser.add_argument(
        "--schema",
        default=None,
        help="Existing domain schema name (see domain_schemas/). If omitted, a schema is synthesized.",
    )
    parser.add_argument("--expectations", default=None, help="Optional scope/expectation notes for schema synthesis.")
    parser.add_argument("--schema-review-rounds", type=int, default=2, help="Generate<->judge rounds for schema synthesis.")

    parser.add_argument("--max-rounds", type=int, default=4, help="Max search/build/answer rounds.")
    parser.add_argument("--max-papers", type=int, default=40, help="Total paper budget.")
    parser.add_argument("--papers-per-round", type=int, default=8, help="Papers fetched per round.")
    parser.add_argument("--papers-per-query", type=int, default=3, help="Papers fetched per search query.")
    parser.add_argument("--queries-per-round", type=int, default=6, help="Search queries generated per round.")
    parser.add_argument("--min-paper-length", type=int, default=500, help="Minimum characters for a usable paper.")
    parser.add_argument(
        "--max-paper-length",
        type=int,
        default=None,
        help="Maximum characters for a usable paper; oversized Firecrawl scrapes are skipped.",
    )

    parser.add_argument("--chunk-size", type=int, default=2000)
    parser.add_argument("--chunk-overlap", type=int, default=200)
    parser.add_argument(
        "--extraction-concurrency",
        type=int,
        default=1,
        help="Maximum concurrent typed-extraction LLM calls per paper.",
    )
    parser.add_argument("--similarity-threshold", type=float, default=0.85)
    parser.add_argument("--self-refine", action="store_true", help="Enable extractor self-refinement (slower).")

    parser.add_argument("--max-gasl-iterations", type=int, default=8, help="Max GASL traversal iterations per round.")
    parser.add_argument("--target-confidence", type=float, default=0.75, help="Stop when assessment confidence >= this and answer is sufficient.")

    parser.add_argument("--model", default=None, help="LLM model id (defaults to ArgoBridge default).")
    parser.add_argument("--firecrawl-api-key", default=None, help="Firecrawl API key (or set FIRECRAWL_API_KEY).")

    args = parser.parse_args()
    config = build_config(args)
    pipeline = QuestionPipeline(config)
    asyncio.run(pipeline.run())


if __name__ == "__main__":
    main()
