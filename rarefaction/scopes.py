"""Path-addressed estimator+controller scopes for the Episode kernel.

A scope is the episode's ancestry as a tuple of ``(grain name, key)`` pairs --
never a joined string -- so uniqueness is structural and every record joins by
its path. A scope is created only by :meth:`ScopedYield.open_scope`, which
atomically creates every declared estimator and the separate controller from
the ``Grain`` in hand. An unopened scope has neither.

Each scope owns one
:class:`~rarefaction.accumulator.IncidenceEstimator` per channel in a frozen
:class:`~rarefaction.accumulator.ChannelSchema` and one separate numerical
controller over their typed estimates.

The grain discipline is the caller's and it matters: a scope's stop rule is a
statement about *its own units*. An item-grain scope observes items; a
strategy-grain scope observes completed searches. Fanning one item
observation into a strategy-grain controller would let a single chatty search
hold a dying strategy open, so this module gives the caller separate scopes
instead of guessing a hierarchy. Fan *credits* upward by observing the same
credit sequence at each scope whose unit just completed -- the identities
dedupe independently per scope, which is the point: an identity new to this
search may be a repeat for the strategy.

Zero-credit units observed with ``crediting_active=False`` are excluded from
both incidence and the controller's streak history (they are not
evidence of barrenness). ``counts_toward_verdict`` is the second, separate
exclusion: a unit that was judged but must not enter incidence (a child
episode that ended on a bound). ``None`` means "as ``crediting_active``".

**Channels** (serialized in the legacy ``facets`` slot): the frozen schema is
bound when a scope opens and every declared estimator is created immediately.
A zero-unit, all-disabled, or all-empty scope therefore emits every channel.
For a partition schema, the crediter supplies every declared base membership;
the kernel validates missing, undeclared, and disallowed overlapping membership
and derives the union channel itself. Every channel has the same eligible
incidence sample count.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

from .accumulator import (
    DEFAULT_ALPHA,
    DEFAULT_EPOCH,
    DEFAULT_SUBSAMPLE_SIZE,
    DEFAULT_WINDOW_SIZE,
    ChannelSchema,
    IncidenceEstimate,
    IncidenceEstimator,
    UnitYield,
)
from .controller import ControllerConfig, ControllerVerdict, NumericalController

__all__ = ["Path", "Scope", "ScopedYield"]

#: An episode's ancestry: ``((grain name, key), ...)`` from the root.
Path = tuple[tuple[str, str], ...]
#: A scope is its complete ancestry path.
Scope = Path


class ScopedYield:
    """A registry of per-scope incidence estimators and controllers."""

    def __init__(
        self,
        *,
        estimator_window_size: int = DEFAULT_WINDOW_SIZE,
        estimator_subsample_size: int = DEFAULT_SUBSAMPLE_SIZE,
        estimator_alpha: float = DEFAULT_ALPHA,
        estimator_epoch: str = DEFAULT_EPOCH,
    ) -> None:
        IncidenceEstimator.validate_parameters(
            estimator_window_size,
            estimator_subsample_size,
            estimator_alpha,
        )
        if not isinstance(estimator_epoch, str) or not estimator_epoch.strip():
            raise ValueError("estimator_epoch must be a non-empty stable identifier")
        self._estimator_window_size = estimator_window_size
        self._estimator_subsample_size = estimator_subsample_size
        self._estimator_alpha = float(estimator_alpha)
        self._estimator_epoch = estimator_epoch
        self._estimators: dict[Scope, IncidenceEstimator] = {}
        self._controllers: dict[Scope, NumericalController] = {}
        self._epochs: dict[Scope, str] = {}
        self._facet_estimators: dict[tuple[Scope, str], IncidenceEstimator] = {}
        self._channel_schemas: dict[Scope, ChannelSchema] = {}

    # ------------------------------------------------------------------ #
    # keys
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize_path(path: Path) -> Path:
        if not isinstance(path, tuple) or not path:
            raise ValueError("a scope path is a non-empty tuple of (grain name, key) pairs")
        out = []
        for segment in path:
            if not isinstance(segment, tuple) or len(segment) != 2:
                raise ValueError(f"path segment {segment!r} is not a (grain name, key) pair")
            out.append((str(segment[0]), str(segment[1])))
        return tuple(out)

    def _new_estimator(
        self,
        scope: Scope,
        *,
        channel: str,
    ) -> IncidenceEstimator:
        return IncidenceEstimator(
            window_size=self._estimator_window_size,
            subsample_size=self._estimator_subsample_size,
            alpha=self._estimator_alpha,
            scope_path=scope,
            epoch=self._estimator_epoch,
            channel=channel,
        )

    def _build_estimators(
        self,
        scope: Scope,
        schema: ChannelSchema,
    ) -> tuple[IncidenceEstimator, dict[str, IncidenceEstimator]]:
        if not isinstance(schema, ChannelSchema):
            raise TypeError("scope channel declaration must be a ChannelSchema")
        primary = self._new_estimator(scope, channel=schema.primary_channel)
        facets = {
            channel: self._new_estimator(scope, channel=channel)
            for channel in schema.base_channels
            if channel != schema.primary_channel
        }
        return primary, facets

    # ------------------------------------------------------------------ #
    # path scopes
    # ------------------------------------------------------------------ #
    def open_scope(
        self,
        path: Path,
        control: ControllerConfig,
        channel_schema: ChannelSchema,
    ) -> Scope:
        """Create all declared estimators and the path controller.

        ``control`` is the ``Grain``'s own -- no level-to-config lookup happens
        here or later.
        Opening a path that is already open raises: the same episode run
        twice under one parent is a defect, not a second sample.
        """

        if not isinstance(control, ControllerConfig):
            raise TypeError("open_scope needs a ControllerConfig")
        if not isinstance(channel_schema, ChannelSchema):
            raise TypeError("open_scope needs a frozen ChannelSchema")
        normalized = self._normalize_path(path)
        scope: Scope = normalized
        if scope in self._estimators or scope in self._controllers:
            raise ValueError(f"scope already open at path {normalized!r}")
        primary, facets = self._build_estimators(scope, channel_schema)
        bound_control = control.bind_channels(channel_schema.channels)
        controller = NumericalController(bound_control)
        self._estimators[scope] = primary
        self._channel_schemas[scope] = channel_schema
        for channel, estimator in facets.items():
            self._facet_estimators[(scope, channel)] = estimator
        self._controllers[scope] = controller
        self._epochs[scope] = self._estimator_epoch
        return scope

    def epoch(self, scope: Scope) -> str:
        scope = self._normalize_path(scope)
        if scope not in self._epochs:
            raise self._unopened(scope)
        return self._epochs[scope]

    def transition_scope(self, scope: Scope, epoch: str) -> Scope:
        """Start the next root statistical epoch under the same scope path."""

        scope = self._normalize_path(scope)
        if not isinstance(epoch, str) or not epoch.strip() or epoch == self.epoch(scope):
            raise ValueError("a new epoch must be a distinct non-empty stable id")
        schema = self.channel_schema(scope)
        control = self.controller(scope).config
        path = scope
        self._estimators[scope] = IncidenceEstimator(
            self._estimator_window_size, self._estimator_subsample_size,
            self._estimator_alpha, scope_path=path, epoch=epoch,
            channel=schema.primary_channel,
        )
        for channel in schema.base_channels:
            if channel != schema.primary_channel:
                self._facet_estimators[(scope, channel)] = IncidenceEstimator(
                    self._estimator_window_size, self._estimator_subsample_size,
                    self._estimator_alpha, scope_path=path, epoch=epoch,
                    channel=channel,
                )
        self._controllers[scope] = NumericalController(control)
        self._epochs[scope] = epoch
        return scope

    def _unopened(self, scope: Scope) -> LookupError:
        return LookupError(
            f"path scope {scope!r} was never opened; open_scope(path, "
            f"grain.control, explicit_channel_schema) creates its estimators and "
            f"controller atomically"
        )

    def estimator(self, scope: Scope) -> IncidenceEstimator:
        scope = self._normalize_path(scope)
        if scope not in self._estimators:
            raise self._unopened(scope)
        return self._estimators[scope]

    def channel_schema(self, scope: Scope) -> ChannelSchema:
        scope = self._normalize_path(scope)
        if scope not in self._channel_schemas:
            raise self._unopened(scope)
        return self._channel_schemas[scope]

    def controller(self, scope: Scope) -> NumericalController:
        scope = self._normalize_path(scope)
        if scope not in self._controllers:
            raise self._unopened(scope)
        return self._controllers[scope]

    # ------------------------------------------------------------------ #
    # observe
    # ------------------------------------------------------------------ #
    def observe(
        self,
        scope: Scope,
        unit_label: str,
        credits: Iterable[str],
        *,
        crediting_active: bool = True,
        counts_toward_verdict: Optional[bool] = None,
        facets: Optional[Mapping[str, Iterable[str]]] = None,
    ) -> UnitYield:
        """Record one unit at one scope and feed its controller.

        Returns the primary channel's :class:`UnitYield`. Units observed with an
        inactive crediter are kept out of incidence and the controller's
        productivity history. ``counts_toward_verdict=False`` likewise keeps
        a judged bound-cut child out of incidence. ``None`` follows
        ``crediting_active``. ``facets`` carries every declared base-channel
        membership for a partition schema; the frozen schema validates it and
        the kernel derives the primary union before any estimator is mutated.
        """

        scope = self._normalize_path(scope)
        active = bool(crediting_active)
        counted = active if counts_toward_verdict is None else bool(counts_toward_verdict)
        if counted and not active:
            raise ValueError(
                "counts_toward_verdict=True with crediting_active=False is a "
                "contradiction: a unit that could not be judged is not evidence"
            )
        credit_tuple = tuple(str(raw) for raw in credits)
        groups = {
            str(name): tuple(str(raw) for raw in members)
            for name, members in (facets or {}).items()
        }
        schema = self.channel_schema(scope)
        memberships = schema.project(credit_tuple, groups, active=active)
        unit = self.estimator(scope).observe(
            unit_label,
            memberships[schema.primary_channel],
            crediting_active=active,
            counts_toward_verdict=counted,
        )
        for channel in schema.base_channels:
            if channel == schema.primary_channel:
                continue
            self._facet_estimators[(scope, channel)].observe(
                unit_label,
                memberships[channel],
                crediting_active=active,
                counts_toward_verdict=counted,
            )
        if counted:
            self.controller(scope).observe(
                self.estimates(scope),
                is_root=len(scope) == 1,
            )
        return unit

    # ------------------------------------------------------------------ #
    # read
    # ------------------------------------------------------------------ #
    def verdict(self, scope: Scope) -> ControllerVerdict:
        return self.controller(self._normalize_path(scope)).verdict()

    def curve(self, scope: Scope) -> IncidenceEstimate:
        """Current role-based incidence estimate for one scope.

        This is the primary channel's typed incidence estimate.
        """

        return self.estimator(self._normalize_path(scope)).snapshot()

    def estimates(self, scope: Scope) -> dict[str, IncidenceEstimate]:
        scope = self._normalize_path(scope)
        schema = self.channel_schema(scope)
        estimates = {schema.primary_channel: self.estimator(scope).snapshot()}
        for channel in schema.base_channels:
            if channel != schema.primary_channel:
                estimates[channel] = self._facet_estimators[(scope, channel)].snapshot()
        return estimates

    def facet_curves(self, scope: Scope) -> dict[str, dict]:
        """Each declared facet's estimate, keyed by channel name.

        Estimates only -- a facet has no tracker and no verdict.
        """

        scope = self._normalize_path(scope)
        schema = self.channel_schema(scope)
        if schema.union_channel is None:
            return {}
        return {
            name: self._facet_estimators[(scope, name)].snapshot().as_record()
            for name in schema.base_channels
        }

    def scopes(self) -> tuple[Scope, ...]:
        return tuple(sorted(self._estimators.keys(), key=repr))

    def snapshot(self, scope: Scope) -> dict:
        """Incidence estimates plus numerical verdict for one scope."""

        scope = self._normalize_path(scope)
        record = {
            "scope_level": scope[-1][0],
            "scope_key": scope[-1][1],
            "curve": self.curve(scope).as_record(),
            "estimates": {name: estimate.as_record() for name, estimate in self.estimates(scope).items()},
            "channel_schema": self.channel_schema(scope).as_record(),
            "verdict": self.verdict(scope).as_record(),
            "path": [list(segment) for segment in scope],
            "facets": self.facet_curves(scope),
        }
        return record

    def snapshot_all(self) -> list[dict]:
        return [self.snapshot(scope) for scope in self.scopes()]
