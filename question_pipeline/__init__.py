"""
Question-driven GraphRAG pipeline.

Given a single question, this package runs one iterative loop that:

1. Synthesizes a domain graph schema for the question (generate -> judge ->
   test-on-real-text -> refine), unless an existing schema is supplied.
2. Searches the web (Firecrawl) for relevant scientific text.
3. Extracts typed entities/relationships and merges them into an evolving
   knowledge graph.
4. Runs a GASL hypothesis-driven traversal to answer the question against the
   current graph.
5. In answer mode, assesses the answer for gaps and feeds the gaps back into
   the next round of search.
6. In table-fill mode, estimates final-table count targets, tracks incomplete
   rows, and keeps a persistent search frontier aimed at filling missing
   answer-table facts.

The public entry point is `QuestionPipeline` / `PipelineConfig` in `pipeline`.
"""

from .pipeline import PipelineConfig, QuestionPipeline
from .goals import (
    CoverageGoalState,
    FillGoalState,
    TableCoverageGoalTracker,
    TableFillGoalTracker,
)
from .search import (
    SearchFrontier,
    SearchHarvester,
    SearchOutcome,
    SourceRelevanceDecision,
    SearchTask,
    load_seed_search_outcomes,
    load_seed_source_records,
    measurement_gap_search_tasks,
    reduce_text_to_relevant_windows,
    table_gap_search_tasks,
)

__all__ = [
    "PipelineConfig",
    "QuestionPipeline",
    "CoverageGoalState",
    "FillGoalState",
    "SearchFrontier",
    "SearchHarvester",
    "SearchOutcome",
    "SourceRelevanceDecision",
    "SearchTask",
    "TableCoverageGoalTracker",
    "TableFillGoalTracker",
    "load_seed_search_outcomes",
    "load_seed_source_records",
    "measurement_gap_search_tasks",
    "reduce_text_to_relevant_windows",
    "table_gap_search_tasks",
]
