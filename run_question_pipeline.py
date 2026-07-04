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
        graph_path=args.graph_path,
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
        max_extraction_chars_per_paper=args.max_extraction_chars_per_paper,
        search_frontier_mode=args.search_frontier_mode,
        scrape_search_results=args.scrape_search_results,
        table_gap_search_tasks=args.table_gap_search_tasks,
        goal_discovery_text_chars=args.goal_discovery_text_chars,
        source_relevance_mode=args.source_relevance_mode,
        task_goal_mode=args.task_goal_mode,
        task_goal_search_tasks=args.task_goal_search_tasks,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        extraction_concurrency=args.extraction_concurrency,
        extraction_timeout_sec=args.extraction_timeout_sec,
        similarity_threshold=args.similarity_threshold,
        self_refine=args.self_refine,
        max_gasl_iterations=args.max_gasl_iterations,
        answer_mode=args.answer_mode,
        seed_tables_dir=args.seed_tables_dir,
        seed_sources_dir=args.seed_sources_dir,
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
    parser.add_argument(
        "--graph-path",
        default=None,
        help="Existing GraphML file to seed the graph before running GASL.",
    )
    parser.add_argument("--expectations", default=None, help="Optional scope/expectation notes for schema synthesis.")
    parser.add_argument("--schema-review-rounds", type=int, default=2, help="Generate<->judge rounds for schema synthesis.")

    parser.add_argument("--max-rounds", type=int, default=4, help="Max search/build/answer rounds.")
    parser.add_argument("--max-papers", type=int, default=40, help="Total paper budget.")
    parser.add_argument("--papers-per-round", type=int, default=8, help="Papers fetched per round.")
    parser.add_argument("--papers-per-query", type=int, default=3, help="Papers fetched per search query.")
    parser.add_argument("--queries-per-round", type=int, default=6, help="Search queries generated per round.")
    parser.add_argument(
        "--search-frontier-mode",
        choices=("batch", "persistent"),
        default="batch",
        help="Use batch for one-wave query execution or persistent for deduplicated task-frontier search.",
    )
    parser.add_argument(
        "--scrape-search-results",
        action="store_true",
        help="Scrape each accepted search result URL before falling back to Firecrawl search-result text.",
    )
    gap_group = parser.add_mutually_exclusive_group()
    gap_group.add_argument(
        "--table-gap-search-tasks",
        dest="table_gap_search_tasks",
        type=int,
        default=12,
        help="Max deterministic table-gap search tasks to enqueue for the next round.",
    )
    gap_group.add_argument(
        "--measurement-gap-search-tasks",
        dest="table_gap_search_tasks",
        type=int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--goal-discovery-text-chars",
        type=int,
        default=6000,
        help="Characters to retain from each accepted goal-discovery source for universe estimation.",
    )
    parser.add_argument(
        "--source-relevance-mode",
        choices=("off", "focused", "all"),
        default="focused",
        help=(
            "Gate scraped sources with a task-aware LLM relevance check: "
            "off disables it, focused gates target/table gap searches, "
            "and all gates every search task."
        ),
    )
    parser.add_argument("--min-paper-length", type=int, default=500, help="Minimum characters for a usable paper.")
    parser.add_argument(
        "--max-paper-length",
        type=int,
        default=None,
        help="Maximum characters for a usable paper; oversized Firecrawl scrapes are skipped.",
    )
    parser.add_argument(
        "--max-extraction-chars-per-paper",
        type=int,
        default=None,
        help="Reduce long accepted search/scrape text to the most query-relevant characters before extraction.",
    )

    parser.add_argument("--chunk-size", type=int, default=2000)
    parser.add_argument("--chunk-overlap", type=int, default=200)
    parser.add_argument(
        "--extraction-concurrency",
        type=int,
        default=1,
        help="Maximum concurrent typed-extraction LLM calls per paper.",
    )
    parser.add_argument(
        "--extraction-timeout-sec",
        type=float,
        default=None,
        help="Skip one typed-extraction chunk after this many seconds.",
    )
    parser.add_argument("--similarity-threshold", type=float, default=0.85)
    parser.add_argument("--self-refine", action="store_true", help="Enable extractor self-refinement (slower).")

    parser.add_argument("--max-gasl-iterations", type=int, default=8, help="Max GASL traversal iterations per round.")
    parser.add_argument(
        "--seed-tables-dir",
        default=None,
        help="Directory or JSON file of previously exported answer tables to merge into new table exports.",
    )
    parser.add_argument(
        "--seed-sources-dir",
        default=None,
        help=(
            "Directory or JSON/JSONL file of previous source metadata used to "
            "seed URL deduplication; pass multiple paths separated by the OS "
            "path separator."
        ),
    )
    parser.add_argument(
        "--answer-mode",
        choices=("natural", "table"),
        default="natural",
        help="Use 'table' to ask GASL to materialize CSV/JSON table variables.",
    )
    parser.add_argument("--target-confidence", type=float, default=0.75, help="Stop when assessment confidence >= this and answer is sufficient.")
    parser.add_argument(
        "--task-goal-mode",
        choices=("off", "table_coverage"),
        default="off",
        help="Use a task-level stop rule instead of natural-answer sufficiency.",
    )
    parser.add_argument(
        "--task-goal-search-tasks",
        type=int,
        default=0,
        help="Broad stop-criterion search tasks to enqueue after each table round.",
    )
    parser.add_argument("--model", default=None, help="LLM model id (defaults to ArgoBridge default).")
    parser.add_argument("--firecrawl-api-key", default=None, help="Firecrawl API key (or set FIRECRAWL_API_KEY).")

    args = parser.parse_args()
    config = build_config(args)
    pipeline = QuestionPipeline(config)
    asyncio.run(pipeline.run())


if __name__ == "__main__":
    main()
