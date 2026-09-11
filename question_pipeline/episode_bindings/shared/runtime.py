"""Injected collaborators and state shared by the composed bindings."""

from __future__ import annotations

from .acquisition_support import *  # internal binding vocabulary

class ProviderRuntime:

    def __init__(
        self,
        *,
        controller: AcquisitionController,
        run_key: str,
        episode_unit_safety_cap: int,
        strategy_catalog: AbstractSet[str],
        frontier: SearchFrontier,
        search_fn: SearchFn,
        harvester: SearchHarvester,
        search_provider_batch: Mapping[str, Any],
        answers_dir: Path,
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        open_prompt_scope: Callable[
            [str, tuple[tuple[str, str], ...]], Any
        ],
        sample_strategies: Callable[
            [Sequence[Mapping[str, Any]]],
            Awaitable[Sequence[Mapping[str, Any]]],
        ],
        post_strategy: Callable[..., Awaitable[None]],
        discover_table_regions: Callable[[str], Sequence[Any]],
        text_without_table_regions: Callable[[str, Sequence[Any]], str],
        plan_table_parser: Callable[..., Awaitable[Any]],
        propose_table_query: Callable[..., Awaitable[Any]],
        get_table_extractor: Callable[[], Any],
        extract_table_text: Callable[..., Awaitable[list[dict[str, Any]]]],
        page_outline: Callable[[str, str], Mapping[str, Any]],
        propose_lexical_probe: Callable[..., Awaitable[Any]],
        rank_chunks: Callable[[Sequence[Any], str], Sequence[Any]],
        get_extractor: Callable[[], Any],
        extract_text: Callable[..., Awaitable[tuple[Any, Any]]],
        chunk_spans: Callable[..., Iterable[Any]],
        page_best_guess_fn: Callable[..., Awaitable[Mapping[str, Any]]],
        infer_best_guess_candidates: Callable[..., Awaitable[Sequence[Mapping[str, Any]]]],
        evidence_acceptor: EvidenceAcceptor,
        evidence_registry: Any,
        get_graph: Callable[[], Any],
        set_graph: Callable[[Any], None],
        enrich_graph_fn: Callable[..., Any],
        similarity_threshold: float,
        auto_merge_entities: bool,
        chunk_size: int,
        chunk_overlap: int,
        extraction_concurrency: int,
        extraction_timeout_sec: Optional[float],
        best_guess_evidence_chars: int,
        best_guess_llm_batch_size: int,
        best_guess_llm_timeout_sec: Optional[float],
        record_goal_discovery_sources: Callable[[list[dict[str, Any]]], None],
        refresh_search_memory: Callable[[], None],
        record_prompt_attempt_counts: Callable[[Sequence[SearchOutcome]], None],
        append_control_decision: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        record_hook_failure: Callable[[str, str, BaseException], None],
        set_active_strategy: Callable[
            [str, tuple[tuple[str, str], ...]], None
        ],
        set_units_pulled: Callable[[int], None],
        set_search_provider_error: Callable[[str], None],
        goal_states: Callable[[], Sequence[Mapping[str, Any]]],
        exported_rows: Callable[[], Mapping[str, Sequence[Mapping[str, Any]]]],
        source_ingestion_ledger: dict[str, dict[str, Any]],
        last_search_outcomes: list[SearchOutcome],
        search_outcomes: list[dict[str, Any]],
        queries_used: list[str],
        orphan_snapshot: Callable[[], Mapping[str, Any]],
        hook_failures: Callable[[], Sequence[Mapping[str, Any]]],
        criteria_projection_version: str,
        missing_tokens: Callable[[], AbstractSet[str]],
        checkpoint_completed_strategy: Optional[
            Callable[[EpisodeUpdate, Any], Any]
        ] = None,
        checkpoint_completed_search: Optional[
            Callable[[Optional[EpisodeRecord], str, str], Any]
        ] = None,
    ) -> None:
        self.controller = controller
        self.run_grain = controller.grain_by_name[RUN_GRAIN_NAME]
        self.strategy_grain = controller.grain_by_name[STRATEGY_GRAIN_NAME]
        self.search_grain = controller.grain_by_name[SEARCH_GRAIN_NAME]
        self.page_grain = controller.grain_by_name[PAGE_GRAIN_NAME]
        self.table_grain = controller.grain_by_name[TABLE_GRAIN_NAME]
        self.lexical_probe_grain = controller.grain_by_name[
            LEXICAL_PROBE_GRAIN_NAME
        ]
        self.crediter = controller.crediter
        self.budget = controller.budget
        self.health = controller.health
        self.termination = controller.termination
        self.run_key = str(run_key)
        self.run_path = ((self.run_grain.name, self.run_key),)
        self.controller.context.bind_run_id(self.run_key)
        self.run_episode_id = Episode.identity(
            self.controller.context,
            self.run_grain,
            self.run_key,
        ).episode_id
        self.episode_unit_safety_cap = int(episode_unit_safety_cap)
        self.strategy_catalog = frozenset(strategy_catalog)
        self.frontier = frontier
        self.search_fn = search_fn
        self.harvester = harvester
        self.search_provider_batch = dict(search_provider_batch)
        self.answers_dir = Path(answers_dir)
        self.open_cost_scope = open_cost_scope
        self.open_prompt_scope = open_prompt_scope
        self.sample_strategies = sample_strategies
        self.post_strategy = post_strategy
        self.discover_table_regions = discover_table_regions
        self.text_without_table_regions = text_without_table_regions
        self.plan_table_parser = plan_table_parser
        self.propose_table_query = propose_table_query
        self.get_table_extractor = get_table_extractor
        self.extract_table_text = extract_table_text
        self.page_outline = page_outline
        self.propose_lexical_probe = propose_lexical_probe
        self.rank_chunks = rank_chunks
        self.get_extractor = get_extractor
        self.extract_text = extract_text
        self.chunk_spans = chunk_spans
        self.page_best_guess_fn = page_best_guess_fn
        self.infer_best_guess_candidates = infer_best_guess_candidates
        if not isinstance(evidence_acceptor, EvidenceAcceptor):
            raise TypeError("evidence_acceptor must implement EvidenceAcceptor")
        self.evidence_acceptor = evidence_acceptor
        self.evidence_registry = evidence_registry
        self.get_graph = get_graph
        self.set_graph = set_graph
        self.enrich_graph_fn = enrich_graph_fn
        self.similarity_threshold = float(similarity_threshold)
        self.auto_merge_entities = bool(auto_merge_entities)
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)
        self.extraction_concurrency = int(extraction_concurrency)
        self.extraction_timeout_sec = extraction_timeout_sec
        self.best_guess_evidence_chars = int(best_guess_evidence_chars)
        self.best_guess_llm_batch_size = int(best_guess_llm_batch_size)
        self.best_guess_llm_timeout_sec = best_guess_llm_timeout_sec
        self.record_goal_discovery_sources = record_goal_discovery_sources
        self.refresh_search_memory = refresh_search_memory
        self.record_prompt_attempt_counts = record_prompt_attempt_counts
        self.append_control_decision = append_control_decision
        self.record_hook_failure = record_hook_failure
        self.set_active_strategy = set_active_strategy
        self.set_units_pulled = set_units_pulled
        self.set_search_provider_error = set_search_provider_error
        self.goal_states = goal_states
        self.exported_rows = exported_rows
        self.source_ingestion_ledger = source_ingestion_ledger
        self.last_search_outcomes = last_search_outcomes
        self.search_outcomes = search_outcomes
        self.queries_used = queries_used
        self.orphan_snapshot = orphan_snapshot
        self.hook_failures = hook_failures
        self.criteria_projection_version = str(criteria_projection_version)
        self.missing_tokens = missing_tokens
        self.checkpoint_completed_strategy = checkpoint_completed_strategy
        self.checkpoint_completed_search = checkpoint_completed_search

        self._strategy_ends: dict[str, str] = {}
        self._strategy_seed_queries: dict[str, list[str]] = {}
        self._open_outcomes: dict[str, SearchOutcome] = {}
        self._open_sources: dict[str, PageSource] = {}
        self._accepted_sources: list[dict[str, Any]] = []
        self._trace_records: dict[str, EpisodeRecord] = {}
        self._episode_records: list[dict[str, Any]] = []
        self._strategy_proposals: list[dict[str, Any]] = []
        # One compact post-verdict observation per completed strategy. This is
        # the run-level memory used by the next string proposal; it is not read
        # by credit, incidence, or any stop predicate.
        self._strategy_learning_history: list[dict[str, Any]] = []
        self._page_guess_reports: list[dict[str, Any]] = []
        self._page_states: dict[str, PageRunState] = {}
        self._pending_followup_outcomes: list[SearchOutcome] = []
        self.acquisition_page_details: list[dict[str, Any]] = []
        self._completed_strategies = 0
        self._completed_run_units: list[dict[str, Any]] = []
        self._resume_proposer_state: dict[str, Any] = {}
        self._active_strategy_key = ""
        self._active_strategy_family = ""
        self._active_strategy_seeds: list[str] = []
        self._active_search_units: list[dict[str, Any]] = []
        self.proposer: Optional[StrategyProposer] = None
        self._page_detail_path = self.answers_dir / "acquisition_page_detail.jsonl"
        self._episodes_path = self.answers_dir / "acquisition_episodes.json"

    def _episode_update(
        self,
        record: EpisodeRecord,
        *,
        prompt_context: Optional[Mapping[str, Any]] = None,
        output: Any = None,
        retain_trace: bool = False,
    ) -> EpisodeUpdate:
        """Return the compact parent message, retaining audit state if needed."""

        if retain_trace:
            self._trace_records[record.episode_id] = record
        return EpisodeUpdate(
            record_id=record.episode_id,
            controller_input=_episode_observation(record),
            prompt_context=(
                dict(prompt_context)
                if prompt_context is not None
                else _base_prompt_context(record)
            ),
            output=output,
        )

    def take_episode_record(self, record_id: str) -> EpisodeRecord:
        """Give the checkpoint writer a retained trace; never used for steering."""

        try:
            return self._trace_records.pop(str(record_id))
        except KeyError as exc:
            raise LookupError(
                f"no retained EpisodeRecord for {record_id!r}"
            ) from exc
