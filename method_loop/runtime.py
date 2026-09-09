"""Path-addressed routing for the generic Episode method.

This module owns scope paths and epoch lifecycle. Each opened scope is routed
to one opaque rarefaction-owned estimator-controller component; this module
does not construct, join, or interpret that component's internal estimator and
controller.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

from rarefaction import (
    ChannelSchema,
    ControlStep,
    ControllerConfig,
    ControllerVerdict,
    EstimatorController,
    IncidenceEstimate,
    ThresholdAdapter,
    UnitYield,
)
from rarefaction.method import (
    DEFAULT_ALPHA,
    DEFAULT_EPOCH,
    DEFAULT_SUBSAMPLE_SIZE,
    DEFAULT_WINDOW_SIZE,
)

__all__ = ["Path", "Scope", "ScopedYield"]

Path = tuple[tuple[str, str], ...]
Scope = Path


class ScopedYield:
    """Route each Episode scope to one paired numerical component."""

    def __init__(
        self,
        *,
        estimator_window_size: int = DEFAULT_WINDOW_SIZE,
        estimator_subsample_size: int = DEFAULT_SUBSAMPLE_SIZE,
        estimator_alpha: float = DEFAULT_ALPHA,
        estimator_epoch: str = DEFAULT_EPOCH,
        threshold_adapter: Optional[ThresholdAdapter] = None,
    ) -> None:
        EstimatorController.validate_parameters(
            estimator_window_size,
            estimator_subsample_size,
            estimator_alpha,
        )
        if not isinstance(estimator_epoch, str) or not estimator_epoch.strip():
            raise ValueError("estimator_epoch must be a non-empty stable identifier")
        self._window_size = estimator_window_size
        self._subsample_size = estimator_subsample_size
        self._alpha = float(estimator_alpha)
        self._initial_epoch = estimator_epoch
        self._threshold_adapter = threshold_adapter
        self._components: dict[Scope, EstimatorController] = {}

    @staticmethod
    def _normalize_path(path: Path) -> Path:
        if not isinstance(path, tuple) or not path:
            raise ValueError(
                "a scope path is a non-empty tuple of (grain name, key) pairs"
            )
        out: list[tuple[str, str]] = []
        for segment in path:
            if not isinstance(segment, tuple) or len(segment) != 2:
                raise ValueError(
                    f"path segment {segment!r} is not a (grain name, key) pair"
                )
            out.append((str(segment[0]), str(segment[1])))
        return tuple(out)

    def _unopened(self, scope: Scope) -> LookupError:
        return LookupError(
            f"path scope {scope!r} was never opened; open_scope(path, "
            "grain.control, explicit_channel_schema) creates its numerical "
            "component atomically"
        )

    def component(self, scope: Scope) -> EstimatorController:
        scope = self._normalize_path(scope)
        if scope not in self._components:
            raise self._unopened(scope)
        return self._components[scope]

    def open_scope(
        self,
        path: Path,
        control: ControllerConfig,
        channel_schema: ChannelSchema,
    ) -> Scope:
        """Create the path's paired numerical component."""

        if not isinstance(control, ControllerConfig):
            raise TypeError("open_scope needs a ControllerConfig")
        if not isinstance(channel_schema, ChannelSchema):
            raise TypeError("open_scope needs a frozen ChannelSchema")
        scope = self._normalize_path(path)
        if scope in self._components:
            raise ValueError(f"scope already open at path {scope!r}")
        self._components[scope] = EstimatorController(
            scope_path=scope,
            epoch=self._initial_epoch,
            channel_schema=channel_schema,
            control=control,
            window_size=self._window_size,
            subsample_size=self._subsample_size,
            alpha=self._alpha,
            threshold_adapter=self._threshold_adapter,
        )
        return scope

    def epoch(self, scope: Scope) -> str:
        return self.component(scope).epoch

    def transition_scope(self, scope: Scope, epoch: str) -> Scope:
        scope = self._normalize_path(scope)
        self._components[scope] = self.component(scope).transitioned(epoch)
        return scope

    def channel_schema(self, scope: Scope) -> ChannelSchema:
        return self.component(scope).channel_schema

    def advance(
        self,
        scope: Scope,
        unit_label: str,
        credits: Iterable[str],
        *,
        observation_status: int,
        facets: Optional[Mapping[str, Iterable[str]]] = None,
    ) -> ControlStep:
        scope = self._normalize_path(scope)
        return self.component(scope).advance(
            unit_label,
            credits,
            observation_status=observation_status,
            facets=facets,
            is_root=len(scope) == 1,
        )

    def verdict(self, scope: Scope) -> ControllerVerdict:
        return self.component(scope).verdict()

    def curve(self, scope: Scope) -> IncidenceEstimate:
        return self.component(scope).report().primary

    def estimates(self, scope: Scope) -> dict[str, IncidenceEstimate]:
        return dict(self.component(scope).report().estimates)

    def facet_curves(self, scope: Scope) -> dict[str, dict]:
        component = self.component(scope)
        schema = component.channel_schema
        if schema.union_channel is None:
            return {}
        report = component.report()
        return {
            channel: report.estimates[channel].as_record()
            for channel in schema.base_channels
        }

    def scopes(self) -> tuple[Scope, ...]:
        return tuple(sorted(self._components, key=repr))

    def snapshot(self, scope: Scope) -> dict:
        scope = self._normalize_path(scope)
        component = self.component(scope)
        report = component.report()
        verdict = component.verdict()
        return {
            "scope_level": scope[-1][0],
            "scope_key": scope[-1][1],
            "curve": report.primary.as_record(),
            "estimates": {
                name: estimate.as_record()
                for name, estimate in report.estimates.items()
            },
            "channel_schema": component.channel_schema.as_record(),
            "verdict": verdict.as_record(),
            "path": [list(segment) for segment in scope],
            "facets": self.facet_curves(scope),
        }

    def snapshot_all(self) -> list[dict]:
        return [self.snapshot(scope) for scope in self.scopes()]
