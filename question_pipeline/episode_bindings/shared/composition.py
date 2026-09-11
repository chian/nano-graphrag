"""Compose the episode-specific bindings into the provider surface."""

from __future__ import annotations

from ..chunk_binding import ChunkBinding
from ..lexical_probe_binding import LexicalProbeBinding
from ..page_binding import PageBinding
from ..run_binding import RunBinding
from ..web_search_binding import WebSearchBinding
from ..strategy_binding import StrategyBinding
from ..table_binding import TableBinding
from .acquisition_support import *  # internal binding vocabulary
from .checkpoint import CheckpointBinding
from .records import RecordBinding
from .runtime import ProviderRuntime


class ProviderBinding(
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

    def build_source_replay_episode(
        self,
        task: SearchTask,
        result: Mapping[str, Any],
        *,
        strategy_key: str = "source_replay#0",
    ) -> Episode:
        """Compose one saved source through the production Episode hierarchy.

        Replay replaces only the provider search with one explicit result.
        Page preparation, chunk ranking, extraction, evidence acceptance,
        typed table mutation, credit assignment, numerical control, hooks, and
        post-strategy exports are the same objects used by a live run. Each
        enclosing source yields its one child and then returns ``None``, so
        physical corpus exhaustion—not a synthetic numerical verdict or unit
        cap—ends the replay.
        """

        if not isinstance(task, SearchTask):
            raise TypeError("source replay requires a SearchTask")
        if not isinstance(result, Mapping):
            raise TypeError("source replay result must be a mapping")
        if not str(strategy_key):
            raise ValueError("source replay strategy_key must be non-empty")

        family = str(strategy_key).split("#", 1)[0]
        outcome = SearchOutcome.for_task(task)
        outcome.search_result_observations.append(
            search_result_observation(dict(result), rank=1)
        )
        self._open_outcomes[task.id] = outcome
        self._active_strategy_key = str(strategy_key)
        self._active_strategy_family = family
        self._active_strategy_seeds = [task.query]

        search_path = (
            (self.run_grain.name, self.run_key),
            (self.strategy_grain.name, str(strategy_key)),
            (self.search_grain.name, task.id),
        )
        search_episode_id = Episode.identity(
            self.controller.context,
            self.search_grain,
            task.id,
            parent_path=search_path[:-1],
        ).episode_id
        page_item = self._make_page_item(
            task,
            result,
            1,
            episode_id=search_episode_id,
            episode_path=search_path,
        )
        search_episode = Episode(
            grain=self.search_grain,
            key=task.id,
            source=_SingleAcquirableSource(page_item),
            on_unit=lambda item, contribution, record: self._on_page(
                item,
                contribution,
                record,
                outcome,
                str(strategy_key),
                family,
            ),
            on_close=lambda record: self._close_search(
                record, str(strategy_key), family
            ),
            to_parent=self._search_episode_update,
        )
        strategy_episode = Episode(
            grain=self.strategy_grain,
            key=str(strategy_key),
            source=_SingleAcquirableSource(search_episode),
            on_close=lambda record: self._close_strategy(
                record,
                str(strategy_key),
                family,
            ),
            to_parent=lambda record: self._strategy_episode_update(
                record,
                strategy_key=str(strategy_key),
                family=family,
            ),
        )
        return Episode(
            grain=self.run_grain,
            key=self.run_key,
            source=_SingleAcquirableSource(strategy_episode),
            on_unit=self._on_strategy,
        )
