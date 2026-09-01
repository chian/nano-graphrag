#!/usr/bin/env python
"""
Question-driven GraphRAG pipeline.

The default `answer` pipeline mode starts from a single question and runs the
acquisition Episode composition:
  search (Firecrawl) -> build/expand a typed knowledge graph ->
  answer with GASL -> assess gaps -> search again until the numerical
  Episode verdicts, the typed stop conditions, or a declared bound end it.

The `table-fill` pipeline mode is for aggregation tasks. It materializes GASL
answer tables, estimates the answer universe, keeps a persistent search
frontier, and searches to resolve unsupported criteria and aggregate criterion
shortfalls until its own stop criteria and Episode verdicts end the run.

If no --schema is given, a domain schema is synthesized for the question
(generate -> judge -> test on real search results -> refine) before the loop.

Examples:
  # Synthesize a schema and answer from scratch
  FIRECRAWL_API_KEY=... python run_question_pipeline.py \\
      --question "How effective is upper-room UV-C at reducing TB transmission in hospitals?" \\
      --output-dir question_runs/uvc_tb

  # Reuse an existing domain schema
  python run_question_pipeline.py \\
      --question "..." --schema engineering_control

  # Fill table answers from a saved graph and prior tables/sources
  python run_question_pipeline.py \\
      --pipeline-mode table-fill \\
      --question "..." \\
      --graph-path question_runs/previous/graphs/current_graph.graphml \\
      --seed-tables-dir question_runs/previous/answers/tables \\
      --seed-sources-dir question_runs/previous/fetched_papers
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
    pipeline_mode = args.pipeline_mode.replace("-", "_")
    table_fill = pipeline_mode == "table_fill"
    # Answer mode is DERIVED from the pipeline mode -- table-fill forces
    # table output and answer mode stays natural. There is no flag for it.
    answer_mode = "table" if table_fill else "natural"
    task_goal_search_tasks = (
        args.task_goal_search_tasks
        if args.task_goal_search_tasks is not None
        else (4 if table_fill else 0)
    )

    return PipelineConfig(
        pipeline_mode=pipeline_mode,
        question=args.question,
        output_dir=args.output_dir,
        schema_name=args.schema,
        graph_path=args.graph_path,
        schema_review_passes=args.schema_review_passes,
        schema_expectations=args.expectations or "",
        firecrawl_api_key=args.firecrawl_api_key,
        max_source_units=args.max_source_units,
        min_source_length=args.min_source_length,
        max_source_length=args.max_source_length,
        max_extraction_chars_per_source=args.max_extraction_chars_per_source,
        scrape_search_results=args.scrape_search_results,
        goal_discovery_text_chars=args.goal_discovery_text_chars,
        task_goal_search_tasks=task_goal_search_tasks,
        target_deficit_max_evolutions=args.target_deficit_max_evolutions,
        target_prompt_arms_per_evolution=args.target_prompt_arms_per_evolution,
        target_queries_per_prompt_arm=args.target_queries_per_prompt_arm,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        extraction_concurrency=args.extraction_concurrency,
        extraction_timeout_sec=args.extraction_timeout_sec,
        similarity_threshold=args.similarity_threshold,
        self_refine=args.self_refine,
        max_gasl_iterations=args.max_gasl_iterations,
        answer_mode=answer_mode,
        table_spec_path=args.table_spec_path,
        seed_tables_dir=args.seed_tables_dir,
        seed_sources_dir=args.seed_sources_dir,
        evidence_corpus_roots=tuple(args.evidence_corpus_root or ()),
        seed_frontier_path=args.seed_frontier_path,
        best_guess_evidence_chars=args.best_guess_evidence_chars,
        best_guess_llm_batch_size=args.best_guess_llm_batch_size,
        best_guess_llm_timeout_sec=args.best_guess_llm_timeout_sec,
        model=args.model,
        fast_model=args.fast_model,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Question-driven iterative search + KG + GASL pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--question", required=True, help="The question to answer.")
    parser.add_argument(
        "--pipeline-mode",
        choices=("answer", "table-fill"),
        default="answer",
        help=(
            "Use answer for the normal question-answer loop, or table-fill for "
            "a persistent aggregation loop that materializes tables, estimates "
            "the answer universe, and searches to resolve unsupported criteria."
        ),
    )
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
    parser.add_argument("--schema-review-passes", type=int, default=2, help="Generate<->judge passes for schema synthesis.")

    parser.add_argument(
        "--max-source-units",
        type=int,
        default=0,
        help=(
            "The ONE operator-declared run-wide bound: source units (pages or "
            "documents) PULLED from result lists, accepted or not -- "
            "mechanical and extraction failures still consume acquisition "
            "work. 0 (the default) means UNBOUNDED: the numerical Episode "
            "verdicts decide continuation, and a declared bound that cuts a "
            "run is reported as bound_hit, never convergence."
        ),
    )
    parser.add_argument(
        "--scrape-search-results",
        action="store_true",
        help="Scrape each accepted search result URL before falling back to Firecrawl search-result text.",
    )
    parser.add_argument(
        "--goal-discovery-text-chars",
        type=int,
        default=6000,
        help="Characters to retain from each accepted goal-discovery source for universe estimation.",
    )
    parser.add_argument(
        "--min-source-length",
        type=int,
        default=500,
        help="Minimum characters for a usable source unit.",
    )
    parser.add_argument(
        "--max-source-length",
        type=int,
        default=None,
        help="Maximum characters for a usable source unit; oversized Firecrawl scrapes are skipped.",
    )
    parser.add_argument(
        "--max-extraction-chars-per-source",
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
        help="Maximum concurrent typed-extraction LLM calls per source unit.",
    )
    parser.add_argument(
        "--extraction-timeout-sec",
        type=float,
        default=None,
        help="Skip one typed-extraction chunk after this many seconds.",
    )
    parser.add_argument("--similarity-threshold", type=float, default=0.85)
    parser.add_argument("--self-refine", action="store_true", help="Enable extractor self-refinement (slower).")

    parser.add_argument(
        "--max-gasl-iterations",
        type=int,
        default=8,
        help="Emergency GASL traversal safety cap per invocation.",
    )
    parser.add_argument(
        "--seed-tables-dir",
        default=None,
        help="Directory or JSON file of previously exported answer tables to carry into new table exports.",
    )
    parser.add_argument(
        "--table-spec-path",
        action="append",
        default=None,
        help=(
            "Editable YAML/JSON table-fill spec. Pass more than once to carry "
            "forward multiple named table contracts; later files add new "
            "tables or update same-name tables, columns, and migrations. "
            "With --seed-tables-dir, the latest adjacent observed spec is "
            "loaded first so prior seeded tables keep exporting."
        ),
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
        "--seed-frontier-path",
        default=None,
        help=(
            "Previous frontier JSON, stop-criteria JSON, or run directory whose "
            "queued search tasks should be requeued before generating new "
            "table-fill deficit searches."
        ),
    )
    parser.add_argument(
        "--evidence-corpus-root",
        action="append",
        default=[],
        help=(
            "Root containing saved source texts from the established run lineage. "
            "May be repeated. Only source IDs already referenced by the seed graph "
            "are discovered; the corpus is not searched or rebuilt."
        ),
    )
    parser.add_argument(
        "--best-guess-evidence-chars",
        type=int,
        default=5000,
        help="Maximum existing source text characters to send per best-guess task.",
    )
    parser.add_argument(
        "--best-guess-llm-batch-size",
        type=int,
        default=8,
        help="Maximum best-guess extraction tasks per local evidence LLM call.",
    )
    parser.add_argument(
        "--best-guess-llm-timeout-sec",
        type=float,
        default=None,
        help=(
            "Optional per-batch timeout for LLM best-guess sidecar extraction; "
            "timed-out batches are recorded and skipped."
        ),
    )
    parser.add_argument(
        "--task-goal-search-tasks",
        type=int,
        default=None,
        help=(
            "Deficit-search tasks one planner call may emit per table-fill "
            "planning pass -- planner string breadth, never a stop rule. "
            "Defaults to 4 in table-fill mode and 0 in answer mode."
        ),
    )
    parser.add_argument(
        "--target-deficit-max-evolutions",
        type=int,
        default=1,
        help=(
            "Maximum prompt-mutation evolutions to try for target-deficit "
            "search within one prompt-mutation attempt. Values above 1 let a "
            "zero-accepted-source prompt-arm experiment mutate and search "
            "again before graph ingestion."
        ),
    )
    parser.add_argument(
        "--target-prompt-arms-per-evolution",
        type=int,
        default=1,
        help=(
            "Prompt arms the target-deficit planner may compare inside one "
            "evolution."
        ),
    )
    parser.add_argument(
        "--target-queries-per-prompt-arm",
        type=int,
        default=1,
        help="Concrete search queries the planner may emit per prompt arm.",
    )
    parser.add_argument("--model", default=None, help="LLM model id (defaults to gpt-5.5).")
    parser.add_argument(
        "--fast-model",
        default=None,
        help=(
            "Model serving the call sites 0M found equivalent on a cheaper model "
            "(defaults to gpt-5.4-mini). Which call sites those are is fixed by "
            "experiment, not by this flag."
        ),
    )
    parser.add_argument("--firecrawl-api-key", default=None, help="Firecrawl API key (or set FIRECRAWL_API_KEY).")

    args = parser.parse_args()
    config = build_config(args)
    pipeline = QuestionPipeline(config)
    asyncio.run(pipeline.run())


if __name__ == "__main__":
    main()
