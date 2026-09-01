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
   later search strategies.
6. In table-fill mode, estimates final-table count targets, tracks incomplete
   rows, and keeps a persistent search frontier aimed at filling missing
   answer-table facts.

The public entry point is `QuestionPipeline` / `PipelineConfig` in `pipeline`.
"""

from .pipeline import PipelineConfig, QuestionPipeline
from .goals import (
    CoverageGoalState,
    FillDeficit,
    FillGoalState,
    TableCoverageGoalTracker,
    TableFillGoalTracker,
)
from .search import (
    SearchFrontier,
    SearchHarvester,
    SearchOutcome,
    SearchTask,
    load_seed_search_outcomes,
    load_seed_source_records,
    measurement_gap_search_tasks,
    reduce_text_to_relevant_windows,
    table_gap_search_tasks,
)
from .search_memory import SearchMemory
from .numeric_candidates import (
    NUMERIC_CANDIDATE_COLUMNS,
    numeric_candidates_from_tables,
)
from .reward import (
    REWARD_COMPONENT_COLUMNS,
    REWARD_VERSION,
    CreditLedger,
    CreditedDatapoint,
    RewardReport,
    aggregate_cost,
    load_seed_best_guess_rows,
    merge_best_guess_rows,
    score_criterion_yield,
)
from .best_guess import (
    BEST_GUESS_CANDIDATE_COLUMNS,
    BEST_GUESS_CONTEXT_COLUMNS,
    run_best_guess_recovery,
)
from .derived_context import (
    DERIVED_CONTEXT_COLUMNS,
    infer_best_guess_context,
)
from .table_specs import (
    ColumnRef,
    TableSpec,
    TableRef,
    load_table_spec,
    load_table_spec_with_seed_tables,
    merge_table_specs,
    observed_table_spec_paths_for_seed,
    table_spec_paths_with_seed_tables,
)
from .evidence_registry import (
    AcceptanceOccurrence,
    AcceptedCell,
    AcceptedBestGuessCell,
    AcquisitionOccurrence,
    BestGuessDerivation,
    BestGuessCellRef,
    DirectAssertionCandidate,
    EvidenceCommit,
    EvidenceRegistry,
    RowCompletionOccurrence,
    SourceChunk,
    SourceDocument,
    SourceVersion,
    TextSpan,
)

__all__ = [
    "PipelineConfig",
    "QuestionPipeline",
    "CoverageGoalState",
    "FillDeficit",
    "FillGoalState",
    "SearchFrontier",
    "SearchHarvester",
    "SearchOutcome",
    "SearchMemory",
    "NUMERIC_CANDIDATE_COLUMNS",
    "REWARD_COMPONENT_COLUMNS",
    "DERIVED_CONTEXT_COLUMNS",
    "BEST_GUESS_CANDIDATE_COLUMNS",
    "BEST_GUESS_CONTEXT_COLUMNS",
    "SearchTask",
    "TableCoverageGoalTracker",
    "TableFillGoalTracker",
    "load_seed_search_outcomes",
    "load_seed_source_records",
    "measurement_gap_search_tasks",
    "reduce_text_to_relevant_windows",
    "numeric_candidates_from_tables",
    "load_seed_best_guess_rows",
    "merge_best_guess_rows",
    "score_criterion_yield",
    "aggregate_cost",
    "CreditLedger",
    "CreditedDatapoint",
    "RewardReport",
    "REWARD_VERSION",
    "infer_best_guess_context",
    "run_best_guess_recovery",
    "table_gap_search_tasks",
    "TableSpec",
    "TableRef",
    "ColumnRef",
    "EvidenceRegistry",
    "EvidenceCommit",
    "AcquisitionOccurrence",
    "AcceptanceOccurrence",
    "RowCompletionOccurrence",
    "SourceDocument",
    "SourceVersion",
    "SourceChunk",
    "TextSpan",
    "DirectAssertionCandidate",
    "AcceptedCell",
    "AcceptedBestGuessCell",
    "BestGuessDerivation",
    "BestGuessCellRef",
    "load_table_spec",
    "load_table_spec_with_seed_tables",
    "merge_table_specs",
    "observed_table_spec_paths_for_seed",
    "table_spec_paths_with_seed_tables",
]
