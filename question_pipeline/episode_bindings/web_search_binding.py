"""The search Episode binding."""

from __future__ import annotations

from .shared.acquisition_support import *  # internal binding vocabulary

class PageSource:
    """The ``search`` grain's source: one page of one result list per pull.

    THE LIST IS CONSUMED ONE RANK PER PULL, AFTER THE VERDICT. That is the
    property the phase-batched flow structurally lacked -- it computed the
    keep-going signal after the keep-going decisions had passed -- and it is now
    a property of where the pull sits in the kernel's loop body rather than of a
    ``break`` a surface remembered to write.
    """

    def __init__(
        self,
        *,
        task: Any,
        search_fn: SearchFn,
        make_page: PageFactory,
        budget: SourceBudget,
        health: ProviderHealth,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        on_results: Optional[Callable[[Any, Sequence[Mapping[str, Any]]], None]] = None,
        on_error: Optional[Callable[[Any, BaseException, bool], None]] = None,
        is_fatal: Callable[[BaseException], bool] = lambda _exc: False,
    ) -> None:
        self._task = task
        self._search_fn = search_fn
        self._make_page = make_page
        self._budget = budget
        self._health = health
        self._episode_id = str(episode_id)
        self._episode_path = tuple(episode_path)
        self._open_cost_scope = open_cost_scope
        self._on_results = on_results
        self._on_error = on_error
        self._is_fatal = is_fatal
        self._results: list[Mapping[str, Any]] = []
        self._next_rank = 0
        self._issued = False
        #: The provider call's finished meter, for the search's own outcome.
        #: The SEARCH scope now closes when that call returns, so per-page work
        #: no longer nests inside it: a page's SOURCE record carries
        #: ``nested_in=""`` and its own ``fetched_bytes``, where those bytes
        #: used to land on the search's meter.
        self.cost: Optional[Mapping[str, Any]] = None

    @property
    def remaining(self) -> int:
        """Buffered results not processed because the episode ended."""

        return max(0, len(self._results) - self._next_rank)

    @property
    def result_buffer(self) -> dict[str, int]:
        """Provider results split into processed and still-unprocessed counts."""

        return {
            "buffered_results": len(self._results),
            "processed_results": self._next_rank,
            "unprocessed_results": self.remaining,
        }

    def next(self, view: EpisodeView) -> Any:
        if self._health.fatal:
            # The run already knows the provider refused. A search must not pay
            # another round trip to rediscover it.
            return SourceEnd(END_SOURCE_FAILED, FATAL_SEARCH_ERROR)
        if self._budget.exhausted:
            return SourceEnd(END_BOUND_HIT, BOUND_KIND_RUN_SOURCE_BUDGET)
        if not self._issued:
            self._issued = True
            end = self._issue()
            if end is not None:
                return end
        if self._next_rank >= len(self._results):
            return None
        result = self._results[self._next_rank]
        self._next_rank += 1
        return self._make_page(self._task, result, self._next_rank)

    def _issue(self) -> Optional[SourceEnd]:
        """The provider call, inside its own cost scope, on the first pull."""

        end: Optional[SourceEnd] = None
        results: list[Mapping[str, Any]] = []
        with self._open_cost_scope(
            ObservationKind.SEARCH.value,
            str(self._task.id),
            self._episode_id,
            self._episode_path,
        ) as meter:
            try:
                # ``None`` is the acquisition framework's explicit absence of
                # an item cap. The real Firecrawl adapter resolves it to that
                # provider's own default batch size; an injected adapter owns
                # its own interpretation and is never stamped as Firecrawl.
                results = list(self._search_fn(self._task.query, None))
            except Exception as exc:  # noqa: BLE001 - classified once, then named
                fatal = bool(self._is_fatal(exc))
                if meter is not None:
                    error_class = classify_error(exc)
                    if error_class == CostErrorClass.OTHER.value:
                        error_class = CostErrorClass.SEARCH_FAILED.value
                    meter.add_provider_call(error_class=error_class)
                if self._on_error is not None:
                    self._on_error(self._task, exc, fatal)
                if fatal:
                    self._health.fatal = FATAL_SEARCH_ERROR
                    end = SourceEnd(END_SOURCE_FAILED, FATAL_SEARCH_ERROR)
                else:
                    end = SourceEnd(END_SOURCE_FAILED, SEARCH_ERROR)
            else:
                if meter is not None:
                    meter.add_provider_call(returned_hits=len(results))
            if meter is not None:
                self.cost = meter.snapshot().to_dict()
        if end is not None:
            return end
        self._results = results
        if self._on_results is not None:
            self._on_results(self._task, results)
        return None

class WebSearchBinding:
    """Methods owned by the search Episode."""

    def _page_episode_update(
        self,
        state: PageRunState,
        record: EpisodeRecord,
    ) -> EpisodeUpdate:
        self._attach_page_credit(state)
        return self._episode_update(
            record,
            output=PageEpisodeOutput(
                unit=state.unit,
                material=self._page_material(state),
            ),
        )

    def _build_search_episode(
        self,
        task: SearchTask,
        strategy_key: str,
        family: str,
    ) -> Episode:
        outcome = SearchOutcome.for_task(task)
        self._open_outcomes[task.id] = outcome
        search_path = (
            (self.run_grain.name, self.run_key),
            (self.strategy_grain.name, strategy_key),
            (self.search_grain.name, task.id),
        )
        search_episode_id = Episode.identity(
            self.controller.context,
            self.search_grain,
            task.id,
            parent_path=search_path[:-1],
        ).episode_id
        source = PageSource(
            task=task,
            search_fn=self.search_fn,
            make_page=lambda task, result, rank: self._make_page_item(
                task,
                result,
                rank,
                episode_id=search_episode_id,
                episode_path=search_path,
            ),
            budget=self.budget,
            health=self.health,
            episode_id=search_episode_id,
            episode_path=search_path,
            open_cost_scope=self.open_cost_scope,
            on_results=self._note_search_results,
            on_error=self._note_search_error,
            is_fatal=is_fatal_search_error,
        )
        self._open_sources[task.id] = source
        return Episode(
            grain=self.search_grain,
            key=task.id,
            source=source,
            on_unit=lambda unit, contribution, record: self._on_page(
                unit, contribution, record, outcome, strategy_key, family
            ),
            on_close=lambda record: self._close_search(
                record, strategy_key, family
            ),
            to_parent=self._search_episode_update,
        )

    def _on_page(
        self,
        item: Any,
        contribution: Any,
        record: Any,
        outcome: SearchOutcome,
        strategy_key: str,
        family: str,
    ) -> None:
        if isinstance(item, Episode):
            output = contribution.output
            self._page_states.pop(item.key, None)
            if not isinstance(output, PageEpisodeOutput):
                self.record_hook_failure(
                    "on_page",
                    item.key,
                    TypeError(f"page update missing for {item.key!r}"),
                )
                return
            unit = output.unit
            material = output.material
        else:
            unit = item.unit
            material = contribution.output
        try:
            self.budget.charge(1)
            self.set_units_pulled(self.budget.spent)
            if isinstance(material, PageMaterial):
                skip = fate_skip_reason(material.fate)
                if skip:
                    outcome.skip(skip)
                if material.source_record is not None:
                    source = dict(material.source_record)
                    self._accepted_sources.append(source)
                    self.record_goal_discovery_sources([source])
                    if material.entities or material.relationships:
                        graph = self.enrich_graph_fn(
                            self.get_graph(),
                            dict(material.entities),
                            list(material.relationships),
                            material.source_id,
                            similarity_threshold=self.similarity_threshold,
                            auto_merge=self.auto_merge_entities,
                        )
                        self.set_graph(graph)
                self._write_page_detail(
                    unit, record, material, strategy_key, family
                )
        except Exception as exc:  # noqa: BLE001 - hook must not unwind the tree
            self.record_hook_failure("on_page", unit.label, exc)

    def _close_search(
        self,
        record: EpisodeRecord,
        strategy_key: str,
        family: str,
    ) -> None:
        """Finalize a search from its own trace before publishing its update."""

        try:
            task_id = record.scope_key
            outcome = self._open_outcomes.pop(task_id, None)
            source = self._open_sources.pop(task_id, None)
            if outcome is None:
                return
            if record.ended_by == END_YIELD_STOP:
                remaining = source.remaining if source is not None else 0
                if remaining > 0:
                    outcome.skip("yield_stop", remaining)
                self.append_control_decision(
                    self.controller.write_decision(
                        record,
                        decision_point=DECISION_SEARCH_ITEM_YIELD,
                        family=family,
                    )
                )
            if source is not None and source.cost is not None:
                outcome.cost = dict(source.cost)
            outcome.provider_batch = dict(self.search_provider_batch)
            if source is not None:
                outcome.result_buffer = source.result_buffer
            self.last_search_outcomes.append(outcome)
            self.frontier.record([outcome])
            self.search_outcomes.append(outcome.to_dict())
            self.queries_used.append(outcome.query)
            self.harvester.record_outcome(outcome)
            self.refresh_search_memory()
            self.record_prompt_attempt_counts([outcome])
            self._pending_followup_outcomes.append(outcome)
            observation = _episode_observation(record)
            self._active_search_units.append(
                {
                    "label": str(record.scope_key),
                    "credits": list(observation.identities),
                    "active": observation.status == OBSERVATION_OBSERVED,
                    "note": observation.note,
                    "facets": {
                        str(name): list(values)
                        for name, values in observation.channels.items()
                    },
                    "counts_toward_verdict": (
                        observation.status != OBSERVATION_EXCLUDED
                    ),
                }
            )
            if self.checkpoint_completed_search is not None:
                self.checkpoint_completed_search(record, strategy_key, family)
        except Exception as exc:  # noqa: BLE001 - hook must not unwind the tree
            self.record_hook_failure("close_search", record.scope_key, exc)

    def _note_search_results(
        self,
        task: SearchTask,
        results: Sequence[Mapping[str, Any]],
    ) -> None:
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            return
        outcome.firecrawl_hits = len(results)
        for rank, result in enumerate(results, start=1):
            outcome.search_result_observations.append(
                search_result_observation(dict(result), rank=rank)
            )

    def _note_search_error(
        self,
        task: SearchTask,
        exc: BaseException,
        fatal: bool,
    ) -> None:
        outcome = self._open_outcomes.get(task.id)
        if outcome is not None:
            outcome.error = str(exc)
            outcome.skip("search_failed")
        if fatal:
            self.set_search_provider_error(str(exc))
            print(f"  Search provider stopped the run: {exc}")
