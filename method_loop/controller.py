"""A bindable numerical controller for the generic Episode method.

This module owns the decision edge and nothing below it.  It reads only the
required numeric roles on :class:`IncidenceEstimate`; the Chao2 calculation and
the rarefaction accumulator cannot select an outcome.  Tail yield is a
controller diagnostic derived from the rarefied role and the exact window
metadata, never a field added to the estimate contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Real
from typing import Mapping

from rarefaction import IncidenceEstimate, NumericBand, STATUS_NORMAL

__all__ = [
    "CONTROLLER_VERSION",
    "ControllerConfig",
    "ControllerVerdict",
    "NumericalController",
]

CONTROLLER_VERSION = "incidence_rarefaction_controller_v1"
_REQUIRED_ROLES = (
    "rarefied_results",
    "remaining_results",
)


def _thresholds(name: str, values: Mapping[str, Real], channels: tuple[str, ...]) -> dict[str, float]:
    out = {str(channel): float(value) for channel, value in values.items()}
    if set(out) != set(channels):
        raise ValueError(f"{name} must name every required channel exactly once")
    if any(not math.isfinite(value) or value < 0.0 for value in out.values()):
        raise ValueError(f"{name} thresholds must be finite and non-negative")
    return out


@dataclass(frozen=True)
class ControllerConfig:
    """One frozen epoch-scope controller declaration.

    ``required_channels`` are conjoined.  The controller deliberately has no
    callback slot: a surface can choose a source, but cannot replace stopping.
    """

    required_channels: tuple[str, ...]
    gamma: Mapping[str, Real]
    rho: Mapping[str, Real]
    streak_length: int
    version: str = CONTROLLER_VERSION
    required_roles: tuple[str, ...] = field(default=_REQUIRED_ROLES, init=False)

    def __post_init__(self) -> None:
        channels = tuple(str(channel) for channel in self.required_channels)
        if not channels or any(not channel for channel in channels):
            raise ValueError("required_channels must be a non-empty tuple of names")
        if len(set(channels)) != len(channels):
            raise ValueError("required_channels must be unique")
        if not isinstance(self.streak_length, int) or isinstance(self.streak_length, bool) or self.streak_length < 1:
            raise ValueError("streak_length K must be a positive integer")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("controller version must be a non-empty string")
        object.__setattr__(self, "required_channels", channels)
        object.__setattr__(self, "gamma", _thresholds("gamma", self.gamma, channels))
        object.__setattr__(self, "rho", _thresholds("rho", self.rho, channels))

    @classmethod
    def uniform(
        cls,
        channels: tuple[str, ...],
        *,
        gamma: Real = 0.0,
        rho: Real = 0.0,
        streak_length: int = 1,
    ) -> "ControllerConfig":
        return cls(
            required_channels=tuple(channels),
            gamma={channel: gamma for channel in channels},
            rho={channel: rho for channel in channels},
            streak_length=streak_length,
        )

    def as_record(self) -> dict:
        return {
            "version": self.version,
            "required_roles": list(self.required_roles),
            "required_channels": list(self.required_channels),
            "gamma": dict(self.gamma),
            "rho": dict(self.rho),
            "streak_length": self.streak_length,
        }

    def bind_channels(self, channels: tuple[str, ...]) -> "ControllerConfig":
        """Bind a grain's declared thresholds to its frozen run schema.

        A grain may be declared before a surface supplies real column channel
        names.  The declaration has one generic default channel; binding copies
        those registered numbers to every frozen channel and records the
        resulting per-channel config on the scope.
        """

        channels = tuple(channels)
        if channels == self.required_channels:
            return self
        if self.required_channels != ("overall",):
            raise ValueError("a multi-channel controller may not be rebound")
        return ControllerConfig.uniform(
            channels,
            gamma=self.gamma["overall"],
            rho=self.rho["overall"],
            streak_length=self.streak_length,
        )


def _tail(estimate: IncidenceEstimate) -> NumericBand:
    """Mean unseen yield per final-window unit after rarefaction to ``m``."""

    rarefied = estimate.rarefied_results
    if rarefied.status_code != STATUS_NORMAL:
        return NumericBand.coded(-1)
    denominator = estimate.window_size - estimate.subsample_size
    if denominator <= 0:
        raise ValueError("controller requires window_size > subsample_size")
    observed = float(estimate.window_observed_results)
    lower = max(0.0, (observed - rarefied.upper) / denominator)
    value = max(0.0, (observed - rarefied.value) / denominator)
    upper = max(0.0, (observed - rarefied.lower) / denominator)
    return NumericBand(
        value=value,
        lower=lower,
        upper=upper,
        status_code=STATUS_NORMAL,
        uncertainty_code=rarefied.uncertainty_code,
        alpha=rarefied.alpha,
    )


@dataclass(frozen=True)
class ControllerVerdict:
    """Recomputable arithmetic result after one eligible incidence sample."""

    stop: bool
    outcome: str
    flat_streak: int
    done_streak: int
    config: ControllerConfig
    channels: Mapping[str, Mapping[str, object]]

    def as_record(self) -> dict:
        return {
            "stop": self.stop,
            "outcome": self.outcome,
            "flat_streak": self.flat_streak,
            "done_streak": self.done_streak,
            "controller": self.config.as_record(),
            "channels": {name: dict(value) for name, value in self.channels.items()},
        }


class NumericalController:
    """Stateful streak owner for exactly one scope and epoch."""

    def __init__(self, config: ControllerConfig) -> None:
        self.config = config
        self._flat_streak = 0
        self._done_streak = 0
        self._last = self._record({}, stop=False, outcome="awaiting_eligible_observation")

    def _record(self, channels: Mapping[str, Mapping[str, object]], *, stop: bool, outcome: str) -> ControllerVerdict:
        return ControllerVerdict(stop, outcome, self._flat_streak, self._done_streak, self.config, channels)

    def verdict(self) -> ControllerVerdict:
        return self._last

    def observe(self, estimates: Mapping[str, IncidenceEstimate], *, is_root: bool) -> ControllerVerdict:
        if set(estimates) != set(self.config.required_channels):
            raise ValueError("controller estimates must contain every required channel exactly once")
        rows: dict[str, dict[str, object]] = {}
        insufficient = False
        all_flat = True
        all_done = True
        for channel in self.config.required_channels:
            estimate = estimates[channel]
            tail = _tail(estimate)
            remaining = estimate.remaining_results
            flat = tail.status_code == STATUS_NORMAL and tail.upper <= self.config.gamma[channel]
            done = flat and remaining.status_code == STATUS_NORMAL and remaining.upper <= self.config.rho[channel]
            insufficient = insufficient or tail.status_code == -1 or remaining.status_code == -1
            all_flat = all_flat and flat
            all_done = all_done and done
            rows[channel] = {
                "rarefaction_tail_yield": tail.as_record(),
                "flat": flat,
                "done": done,
                "remaining_status_code": remaining.status_code,
                "remaining_upper": remaining.upper,
                "gamma": self.config.gamma[channel],
                "rho": self.config.rho[channel],
            }
        if insufficient or not all_flat:
            self._flat_streak = 0
            self._done_streak = 0
            outcome = "insufficient" if insufficient else "continuing"
            self._last = self._record(rows, stop=False, outcome=outcome)
            return self._last
        self._flat_streak += 1
        if all_done:
            self._done_streak += 1
            if self._done_streak >= self.config.streak_length:
                self._last = self._record(rows, stop=True, outcome=("whole_convergence" if is_root else "local_convergence"))
                return self._last
            self._last = self._record(rows, stop=False, outcome="flat_progressing")
            return self._last
        self._done_streak = 0
        if self._flat_streak >= self.config.streak_length:
            self._last = self._record(rows, stop=True, outcome=("root_incomplete" if is_root else "local_saturation"))
            return self._last
        self._last = self._record(rows, stop=False, outcome="flat_progressing")
        return self._last
