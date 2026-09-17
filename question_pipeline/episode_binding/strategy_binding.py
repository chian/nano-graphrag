from __future__ import annotations

from question_pipeline.episode_binding.provider_binding import *

class StrategySearches:
    """The ``strategy`` grain's source: one search episode per pull.

    The frontier stays the queue; the episode becomes its consumer. A strategy
    that yield-stops leaves its remaining tasks IN the frontier, which is how
    "never deleted, never domain-filtered" survives the deletion of the demotion
    machinery.
    """

    def __init__(
        self,
        *,
        strategy_key: str,
        family: str,
        next_task: Callable[[str], Any],
        make_search: Callable[[Any], Episode],
        budget: SourceBudget,
        health: ProviderHealth,
        resume_search: Optional[Episode] = None,
    ) -> None:
        self._strategy_key = strategy_key
        self._family = family
        self._next_task = next_task
        self._make_search = make_search
        self._budget = budget
        self._health = health
        self._resume_search = resume_search

    def next(self, view: EpisodeView) -> Episode | None | SourceEnd:
        if self._health.fatal:
            return SourceEnd(END_SOURCE_FAILED, FATAL_SEARCH_ERROR)
        if self._budget.exhausted:
            return SourceEnd(END_BOUND_HIT, BOUND_KIND_RUN_SOURCE_BUDGET)
        if self._resume_search is not None:
            episode = self._resume_search
            self._resume_search = None
            return episode
        task = self._next_task(self._family)
        if task is None:
            return None
        return self._make_search(task)

class StrategyBinding:
    """Methods owned by the strategy Episode."""

    def _search_episode_update(self, record: EpisodeRecord) -> EpisodeUpdate:
        return self._episode_update(record)

    def _build_strategy_episode(
        self,
        strategy_key: str,
        family: str,
        seeds: Sequence[str],
    ) -> Episode:
        resuming = bool(
            self._active_strategy_key
            and self._active_strategy_key == strategy_key
            and (self._active_search_units or self._resume_search_state)
        )
        if seeds and not resuming:
            self._strategy_seed_queries[strategy_key] = list(seeds)
            self.frontier.enqueue_queries(
                seeds,
                topic="strategy_proposal",
                expansion_op=family,
                producer_class="strategy_proposer",
            )
        if not resuming:
            self._active_search_units = []
        self._active_strategy_key = str(strategy_key)
        self._active_strategy_family = str(family)
        self._active_strategy_seeds = [str(seed) for seed in seeds]
        resume_search = None
        if self._resume_search_state:
            raw_task = self._resume_search_state.get("task") or {}
            if not isinstance(raw_task, Mapping):
                raise TypeError("active search task must be a mapping")
            allowed = set(SearchTask.__dataclass_fields__)
            task = SearchTask(
                **{key: value for key, value in raw_task.items() if key in allowed}
            )
            resume_search = self._build_search_episode(
                task,
                strategy_key,
                family,
                resume_state=self._resume_search_state,
            )
            self._resume_search_state = {}
        return Episode(
            grain=self.strategy_grain,
            key=strategy_key,
            source=StrategySearches(
                strategy_key=strategy_key,
                family=family,
                next_task=self.frontier.next_for,
                make_search=lambda task: self._build_search_episode(
                    task, strategy_key, family
                ),
                budget=self.budget,
                health=self.health,
                resume_search=resume_search,
            ),
            on_close=lambda record: self._close_strategy(
                record, strategy_key, family
            ),
            to_parent=lambda record: self._strategy_episode_update(
                record,
                strategy_key=strategy_key,
                family=family,
            ),
            resume_units=tuple(
                ResumeUnit(
                    label=str(item["label"]),
                    controller_input=_restored_observation(item),
                )
                for item in self._active_search_units
            ),
        )

    def _close_strategy(
        self,
        record: EpisodeRecord,
        strategy_key: str,
        family: str,
    ) -> None:
        """Record strategy-local trace facts before publishing its update."""

        try:
            self._strategy_ends[family] = record.ended_by
            self.append_control_decision(
                self.controller.write_decision(
                    record,
                    decision_point=DECISION_STRATEGY_YIELD,
                    family=family,
                )
            )
            self.write_episode_record(record)
        except Exception as exc:  # noqa: BLE001 - trace must not unwind the tree
            self.record_hook_failure("close_strategy", strategy_key, exc)
