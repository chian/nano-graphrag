"""Question-pipeline bindings, organized by Episode type."""

from .provider_binding import *
from .provider_binding import (
    CheckpointBinding, ProviderComposition, ProviderRuntime, RecordBinding,
)
from .chunk_binding import ChunkBinding
from .lexical_probe_binding import LexicalProbeBinding
from .page_binding import PageBinding
from .run_binding import RunBinding, StrategyProposer
from .strategy_binding import StrategyBinding, StrategySearches
from .table_binding import TableBinding
from .web_search_binding import PageSource, WebSearchBinding


class ProviderBinding(
    ProviderComposition,
    RunBinding,
    StrategyBinding,
    WebSearchBinding,
    PageBinding,
    TableBinding,
    LexicalProbeBinding,
    ChunkBinding,
    CheckpointBinding,
    RecordBinding,
    ProviderRuntime,
):
    """One provider surface assembled from episode-owned bindings."""


__all__ = [name for name in globals() if not name.startswith("_")]
