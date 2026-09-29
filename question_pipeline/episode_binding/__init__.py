"""Question-pipeline bindings, organized by Episode type."""

from .provider_binding import *
from .provider_binding import (
    CheckpointBinding, ProviderComposition, ProviderRuntime, RecordBinding,
)
from .chunk_binding import ChunkBinding
from .lexical_probe_binding import LexicalProbeBinding
from .page_binding import PageBinding, propose_page_child
from .report_binding import ReportBinding, extract_report_window
from .run_binding import RunBinding, StrategyProposer
from .strategy_binding import StrategyBinding, StrategySearches
from .source_table_binding import SourceTableBinding
from .web_search_binding import (
    PageCandidateAssessment,
    SearchPageProposal,
    SearchPageProposer,
    WebSearchBinding,
    assess_page_candidate,
    propose_search_page,
)


class ProviderBinding(
    ProviderComposition,
    RunBinding,
    StrategyBinding,
    WebSearchBinding,
    PageBinding,
    ReportBinding,
    SourceTableBinding,
    LexicalProbeBinding,
    ChunkBinding,
    CheckpointBinding,
    RecordBinding,
    ProviderRuntime,
):
    """One provider surface assembled from episode-owned bindings."""


__all__ = [name for name in globals() if not name.startswith("_")]
