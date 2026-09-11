"""Checkpoint state shared across the composed episode tree."""

from __future__ import annotations

from .acquisition_support import *  # internal binding vocabulary

class CheckpointBinding:

    def checkpoint_state(self) -> dict[str, Any]:
        """Return provider-owned state at a completed strategy boundary."""

        return {
            "completed_run_units": list(self._completed_run_units),
            "completed_strategies": self._completed_strategies,
            "strategy_ends": dict(self._strategy_ends),
            "strategy_seed_queries": {
                key: list(values)
                for key, values in self._strategy_seed_queries.items()
            },
            "episode_records": list(self._episode_records),
            "strategy_proposals": list(self._strategy_proposals),
            "strategy_learning_history": list(
                self._strategy_learning_history
            ),
            "credit_assignments": list(self.crediter.checkpoint_assignments()),
            "proposer": (
                self.proposer.checkpoint_state() if self.proposer else {}
            ),
            "active_strategy": {
                "key": self._active_strategy_key,
                "family": self._active_strategy_family,
                "seeds": list(self._active_strategy_seeds),
                "completed_search_units": list(self._active_search_units),
            },
        }

    def restore_checkpoint_state(self, state: Mapping[str, Any]) -> None:
        """Restore provider-owned state before the run Episode is built."""

        self._completed_run_units = [
            dict(item) for item in (state.get("completed_run_units") or ())
        ]
        self._completed_strategies = int(
            state.get("completed_strategies") or len(self._completed_run_units)
        )
        self._strategy_ends = {
            str(name): str(value)
            for name, value in dict(state.get("strategy_ends") or {}).items()
        }
        self._strategy_seed_queries = {
            str(key): [str(value) for value in values]
            for key, values in dict(
                state.get("strategy_seed_queries") or {}
            ).items()
        }
        self._episode_records = [
            dict(item) for item in (state.get("episode_records") or ())
        ]
        self._strategy_proposals = [
            dict(item) for item in (state.get("strategy_proposals") or ())
        ]
        self._strategy_learning_history = [
            dict(item)
            for item in (state.get("strategy_learning_history") or ())
        ]
        self.crediter.restore_assignments(state.get("credit_assignments") or ())
        self._resume_proposer_state = dict(state.get("proposer") or {})
        active = dict(state.get("active_strategy") or {})
        self._active_strategy_key = str(active.get("key") or "")
        self._active_strategy_family = str(active.get("family") or "")
        self._active_strategy_seeds = [
            str(value) for value in (active.get("seeds") or ())
        ]
        self._active_search_units = [
            dict(item) for item in (active.get("completed_search_units") or ())
        ]
