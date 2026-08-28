"""The composable acquisition episode (phase 4E-a).

The class template of ``docs/ACQUISITION_LOOP.md`` §"The template", in the
form of the operator template note: Composite, Template Method, Strategy,
Iterator-with-feedback. Design and steward verdicts:
``experiments/log/4E-a-episode.md``.

- A :class:`Grain` is one level of the loop, declared once: its name, one
  sentence each for what a unit and a credit are, and its numerical controller
  configuration. Run-specific channel declarations are bound explicitly by
  :class:`Context`.
- An :class:`Acquirable` is a unit: a :class:`Leaf` (a page, a seed, bound to
  its grain's ``extract``/``credit``) or an :class:`Episode` (a loop over
  units). The loop calls ``item.acquire(ctx)`` and never asks which it has.
- :class:`Episode.acquire` is where fan-up and the bound-leak rule live: the
  child's distinct identities, each once, are the parent's credits; a child
  that ended on a bound or a source failure remains nested but does not enter
  the parent's incidence or stop history. The parent loop has one path and
  never handles ``bound_hit``.
- :meth:`Episode.run` is the fixed template method and owns the one loop body.
  No loop is written on a surface (charter rule 1).
- A :class:`Context` addresses scopes by ancestry path and opens each scope
  from the ``Grain`` in hand, binding the frozen run-specific channel schema
  before the first view or observation.

This module calls no model and does no I/O; it calls only the injected
``source``, ``extract``, ``credit`` and hook. A model may live inside a
``source`` or an ``extract`` (charter rule 3) -- never in a credit, a controller,
or anything that reads a curve.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, runtime_checkable

from .accumulator import ChannelSchema, IncidenceEstimate, UnitYield
from .controller import ControllerConfig, ControllerVerdict
from .scopes import Path, Scope, ScopedYield

__all__ = [
    "COUNTING_ENDS",
    "END_BOUND_HIT",
    "END_EXHAUSTED",
    "END_INCOMPLETE",
    "END_REASON_UNIT_BOUND",
    "END_SOURCE_FAILED",
    "END_YIELD_STOP",
    "ENDS",
    "SOURCE_END_KINDS",
    "Acquirable",
    "Context",
    "Episode",
    "EpisodeView",
    "Grain",
    "Leaf",
    "EpochMutation",
    "UnitSource",
    "leaves",
]

END_EXHAUSTED = "exhausted"
END_YIELD_STOP = "yield_stop"
END_INCOMPLETE = "incomplete"
END_BOUND_HIT = "bound_hit"
END_SOURCE_FAILED = "source_failed"
ENDS = (END_EXHAUSTED, END_YIELD_STOP, END_INCOMPLETE, END_BOUND_HIT, END_SOURCE_FAILED)
COUNTING_ENDS = (END_EXHAUSTED, END_YIELD_STOP)
SOURCE_END_KINDS = (END_BOUND_HIT, END_SOURCE_FAILED)
END_REASON_UNIT_BOUND = "unit_bound"


@dataclass(frozen=True)
class CreditResult:
    credits: tuple[str, ...] = ()
    active: bool = True
    note: str = ""
    facets: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "credits", tuple(str(value) for value in self.credits))
        object.__setattr__(self, "facets", {str(name): tuple(str(value) for value in values) for name, values in dict(self.facets).items()})

    @classmethod
    def disabled(cls, note: str) -> "CreditResult":
        if not str(note).strip():
            raise ValueError("a disabled CreditResult must say why")
        return cls(active=False, note=str(note))


@dataclass(frozen=True)
class SourceEnd:
    kind: str
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in SOURCE_END_KINDS:
            raise ValueError(f"unknown source end kind {self.kind!r}")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("SourceEnd.reason must be a non-empty class label")


@dataclass(frozen=True)
class EpochMutation:
    """A source proposal for a new, distribution-changing root epoch.

    The source supplies only the already-approved stable mutation identity;
    ``Episode`` owns whether the numerical root outcome permits the transition.
    """

    epoch: str

    def __post_init__(self) -> None:
        if not isinstance(self.epoch, str) or not self.epoch.strip():
            raise ValueError("EpochMutation.epoch must be a non-empty stable id")


@dataclass(frozen=True)
class UnitRecord:
    unit_label: str
    yield_record: UnitYield
    credit_note: str = ""
    credits: tuple[str, ...] = ()
    facets: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    child: Optional["EpisodeRecord"] = None
    epoch: str = ""

    def as_record(self) -> dict:
        out = self.yield_record.as_record()
        if self.credit_note:
            out["credit_note"] = self.credit_note
        out["credits"] = list(self.credits)
        out["facets"] = {name: list(values) for name, values in self.facets.items()}
        if self.child is not None:
            out["child"] = self.child.as_record()
        out["epoch"] = self.epoch
        return out


@dataclass(frozen=True)
class EpisodeRecord:
    scope_level: str
    scope_key: str
    units_consumed: int
    ended_by: str
    unit_records: tuple[UnitRecord, ...]
    final_verdict: dict
    curve: dict
    safety_bound: Optional[int] = None
    path: Path = ()
    end_reason: str = ""
    controller: dict = field(default_factory=dict)
    facets: dict = field(default_factory=dict)
    incidence_estimate: Optional[IncidenceEstimate] = None
    controller_verdict: Optional[ControllerVerdict] = None
    channel_schema: Optional[ChannelSchema] = None

    @property
    def distinct_identities(self) -> tuple[str, ...]:
        return tuple(identity for unit in self.unit_records for identity in unit.yield_record.new_identities)

    @property
    def facet_distinct(self) -> dict[str, tuple[str, ...]]:
        names = self.channel_schema.base_channels if self.channel_schema and self.channel_schema.union_channel else tuple({name for unit in self.unit_records for name in unit.facets})
        out: dict[str, tuple[str, ...]] = {}
        for name in names:
            seen: set[str] = set()
            values: list[str] = []
            for unit in self.unit_records:
                if unit.yield_record.eligible:
                    for identity in unit.facets.get(name, ()):
                        if identity not in seen:
                            seen.add(identity)
                            values.append(identity)
            out[name] = tuple(values)
        return out

    def as_record(self) -> dict:
        return {"scope_level": self.scope_level, "scope_key": self.scope_key, "path": [list(item) for item in self.path], "units_consumed": self.units_consumed, "ended_by": self.ended_by, "end_reason": self.end_reason, "safety_bound": self.safety_bound, "controller": dict(self.controller), "final_verdict": self.final_verdict, "curve": self.curve, "facets": dict(self.facets), "channel_schema": self.channel_schema.as_record() if self.channel_schema else {}, "units": [unit.as_record() for unit in self.unit_records]}


@dataclass(frozen=True)
class Contribution:
    credit: CreditResult
    counts_toward_verdict: bool
    extracted: Any = None
    child: Optional[EpisodeRecord] = None

    def __post_init__(self) -> None:
        if self.counts_toward_verdict and not self.credit.active:
            raise ValueError("an inactive credit cannot count toward a verdict")


def _leaf_contribution(unit: Any, extract: Callable[[Any], Any], credit: Callable[[Any, Any], Any]) -> Contribution:
    extracted = extract(unit)
    result = credit(unit, extracted)
    if not isinstance(result, CreditResult):
        raise TypeError("credit() must return CreditResult")
    return Contribution(result, result.active, extracted)


async def _leaf_contribution_async(unit: Any, extract: Callable[[Any], Any], credit: Callable[[Any, Any], Any]) -> Contribution:
    extracted = extract(unit)
    if inspect.isawaitable(extracted):
        extracted = await extracted
    result = credit(unit, extracted)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, CreditResult):
        raise TypeError("credit() must return CreditResult")
    return Contribution(result, result.active, extracted)


# --------------------------------------------------------------------------
# the grain -- the policy owner
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Grain:
    """One level of the loop, declared once (charter rule 4).

    ``control`` is the numerical behavior declaration. The frozen channel
    schema is run-specific and must be supplied separately to :class:`Context`;
    the grain carries no fallback schema and nothing that touches a unit or
    reads an estimate.
    """

    name: str
    unit: str
    credit: str
    control: ControllerConfig

    def __post_init__(self) -> None:
        for field_name in ("name", "unit", "credit"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Grain.{field_name} must be a non-empty sentence")
        if not isinstance(self.control, ControllerConfig):
            raise TypeError(
                f"Grain.control must be a ControllerConfig, got {type(self.control).__name__}"
            )


# --------------------------------------------------------------------------
# the view and the source protocol
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeView:
    """Read-only running state of the episode a source feeds.

    Built directly from the loop's live state. The record objects are the ones
    that will be emitted; a source that mutates one corrupts its own episode's
    export and nothing else.
    """

    grain: Grain
    key: str
    path: Path
    units_consumed: int
    bound: Optional[int]
    units: tuple[UnitRecord, ...]
    curve: IncidenceEstimate
    verdict: ControllerVerdict


class UnitSource(Protocol):
    """Answers "what is the next unit" for one episode.

    Returns an :class:`Acquirable`; ``None`` for exhaustion, the only
    spelling of exhaustion; or a :class:`SourceEnd` naming why the stream
    died. In ``run_async`` the return may be awaitable. The only place
    besides ``extract`` a model may live: a proposer reads the view, samples
    candidate strings, reports a distance number, and a written threshold
    inside it accepts one.
    """

    def next(self, view: EpisodeView) -> Any: ...


# --------------------------------------------------------------------------
# the Composite: Leaf and Episode
# --------------------------------------------------------------------------


@runtime_checkable
class Acquirable(Protocol):
    """The Composite's Component. Implemented by :class:`Leaf` and
    :class:`Episode` only; a surface implements ``UnitSource``, ``extract``,
    ``credit`` and hooks, never this."""

    label: str

    def acquire(self, ctx: "Context") -> Contribution: ...

    async def acquire_async(self, ctx: "Context") -> Contribution: ...


@dataclass(frozen=True)
class Leaf:
    """A page, a seed -- a raw unit bound to its grain's parts at construction.

    ``extract`` may do string work (fetch, judge, extract; charter rule 3);
    ``credit`` is a deterministic projection onto declared targets. A leaf
    counts toward the verdict exactly when its crediter was active.
    """

    unit: Any
    extract: Callable[[Any], Any]
    credit: Callable[[Any, Any], CreditResult]
    label: str

    def acquire(self, ctx: "Context") -> Contribution:
        return _leaf_contribution(self.unit, self.extract, self.credit)

    async def acquire_async(self, ctx: "Context") -> Contribution:
        return await _leaf_contribution_async(self.unit, self.extract, self.credit)


@dataclass(frozen=True)
class Episode:
    """The Composite: one instance of one grain. A frozen declaration with no
    run state -- "runs once" is a property of its path in the registry.

    Slots are exactly the charter's swapped parts: ``source``, the hook,
    ``bound``; ``extract``/``credit`` ride on the :class:`Leaf` a source
    yields; the controller config is the grain's. There is no ``meter`` (charter
    §"Cost has one owner": ``key`` and the leaf label are the cost
    observation ids a ledger writer joins on).
    """

    grain: Grain
    key: str
    source: UnitSource
    on_unit: Optional[Callable[[Any, Contribution, UnitRecord], Any]] = None
    bound: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.grain, Grain):
            raise TypeError(f"Episode.grain must be a Grain, got {type(self.grain).__name__}")
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("Episode.key must be a non-empty string")
        if not hasattr(self.source, "next"):
            raise TypeError(
                "Episode.source must implement UnitSource.next(view); wrap a "
                "plain iterable with leaves(...)"
            )
        if self.bound is not None and (not isinstance(self.bound, int) or self.bound < 0):
            raise ValueError(f"Episode.bound must be None or a non-negative int, got {self.bound!r}")

    @property
    def label(self) -> str:
        return self.key

    # -------------------------------------------------------------- #
    # an Episode is a unit of its parent
    # -------------------------------------------------------------- #
    def _contribution(self, record: EpisodeRecord) -> Contribution:
        """Fan-up and the bound-leak rule, defined once, beside the child.

        Credits: the child's distinct identities, each once, in first-seen
        order; per facet likewise. A child every one of whose units was
        crediting-disabled made no judgement (``active=False``). A child
        that ended on a bound or a source failure delivered fewer credits
        than it would have: its nested record retains those credits, while
        ``counts_toward_verdict=False`` excludes the whole unit from the
        parent's incidence and stop history -- otherwise a cap one level down
        would change the parent's sampling-unit definition.
        """

        estimate = record.incidence_estimate
        if estimate is None:
            # A record the loop did not build carries no typed estimate; guessing
            # "not all disabled" here would be a silent fallback.
            raise ValueError(
                f"episode record at {record.path!r} carries no typed incidence estimate; "
                f"only a record built by Episode.run or Episode.run_async can "
                f"be a unit of its parent"
            )
        all_disabled = (
            record.units_consumed > 0
            and all(unit.yield_record.crediting_disabled for unit in record.unit_records)
        )
        if all_disabled:
            credit = CreditResult.disabled(
                "child made no crediting judgement: every unit crediting-disabled"
            )
        else:
            credit = CreditResult(
                credits=record.distinct_identities,
                facets=record.facet_distinct,
            )
        return Contribution(
            credit=credit,
            counts_toward_verdict=(not all_disabled) and record.ended_by in COUNTING_ENDS,
            child=record,
        )

    def acquire(self, ctx: "Context") -> Contribution:
        return self._contribution(self.run(ctx))

    async def acquire_async(self, ctx: "Context") -> Contribution:
        return self._contribution(await self.run_async(ctx))

    # -------------------------------------------------------------- #
    # the template method -- FINAL; one call to the kernel's loop body
    # -------------------------------------------------------------- #
    def run(self, ctx: "Context") -> EpisodeRecord:
        scope = ctx.enter(self.grain, self.key)
        try:
            return self._run_loop(ctx, scope)
        finally:
            ctx.leave(scope)

    async def run_async(self, ctx: "Context") -> EpisodeRecord:
        scope = ctx.enter(self.grain, self.key)
        try:
            return await self._run_loop_async(ctx, scope)
        finally:
            ctx.leave(scope)

    def _view(self, ctx: "Context", scope: Scope, records: list[UnitRecord]) -> EpisodeView:
        return EpisodeView(
            grain=self.grain,
            key=self.key,
            path=scope,
            units_consumed=len(records),
            bound=self.bound,
            units=tuple(records),
            curve=ctx.scoped.curve(scope),
            verdict=ctx.scoped.verdict(scope),
        )

    def _record(self, ctx: "Context", scope: Scope, records: list[UnitRecord], ended_by: str, end_reason: str) -> EpisodeRecord:
        curve = ctx.scoped.curve(scope)
        verdict = ctx.scoped.verdict(scope)
        path = scope
        return EpisodeRecord(path[-1][0], path[-1][1], len(records), ended_by, tuple(records), verdict.as_record(), curve.as_record(), self.bound, path, end_reason, verdict.config.as_record(), ctx.scoped.facet_curves(scope), curve, verdict, ctx.scoped.channel_schema(scope))

    def _run_loop(self, ctx: "Context", scope: Scope) -> EpisodeRecord:
        records: list[UnitRecord] = []
        ended_by, end_reason = END_EXHAUSTED, ""
        while True:
            if self.bound is not None and len(records) >= self.bound:
                ended_by, end_reason = END_BOUND_HIT, END_REASON_UNIT_BOUND
                break
            item = self.source.next(self._view(ctx, scope, records))
            if item is None:
                break
            if isinstance(item, SourceEnd):
                ended_by, end_reason = item.kind, item.reason
                break
            contribution = item.acquire(ctx)
            if not isinstance(contribution, Contribution):
                raise TypeError("Acquirable.acquire() must return Contribution")
            unit = ctx.scoped.observe(scope, item.label, contribution.credit.credits, crediting_active=contribution.credit.active, counts_toward_verdict=contribution.counts_toward_verdict, facets=contribution.credit.facets)
            record = UnitRecord(item.label, unit, contribution.credit.note, contribution.credit.credits, contribution.credit.facets, contribution.child, ctx.scoped.epoch(scope))
            records.append(record)
            if self.on_unit is not None:
                self.on_unit(item, contribution, record)
            verdict = ctx.scoped.verdict(scope)
            if verdict.stop:
                if verdict.outcome == "root_incomplete" and len(scope) == 1:
                    proposal = getattr(self.source, "next_epoch", None)
                    mutation = proposal(self._view(ctx, scope, records)) if proposal else None
                    if isinstance(mutation, EpochMutation):
                        scope = ctx.transition(scope, mutation)
                        continue
                    ended_by = END_INCOMPLETE
                else:
                    ended_by = END_YIELD_STOP
                break
        return self._record(ctx, scope, records, ended_by, end_reason)

    async def _run_loop_async(self, ctx: "Context", scope: Scope) -> EpisodeRecord:
        records: list[UnitRecord] = []
        ended_by, end_reason = END_EXHAUSTED, ""
        while True:
            if self.bound is not None and len(records) >= self.bound:
                ended_by, end_reason = END_BOUND_HIT, END_REASON_UNIT_BOUND
                break
            item = self.source.next(self._view(ctx, scope, records))
            if inspect.isawaitable(item):
                item = await item
            if item is None:
                break
            if isinstance(item, SourceEnd):
                ended_by, end_reason = item.kind, item.reason
                break
            contribution = item.acquire_async(ctx)
            if inspect.isawaitable(contribution):
                contribution = await contribution
            if not isinstance(contribution, Contribution):
                raise TypeError("Acquirable.acquire_async() must return Contribution")
            unit = ctx.scoped.observe(scope, item.label, contribution.credit.credits, crediting_active=contribution.credit.active, counts_toward_verdict=contribution.counts_toward_verdict, facets=contribution.credit.facets)
            record = UnitRecord(item.label, unit, contribution.credit.note, contribution.credit.credits, contribution.credit.facets, contribution.child, ctx.scoped.epoch(scope))
            records.append(record)
            if self.on_unit is not None:
                result = self.on_unit(item, contribution, record)
                if inspect.isawaitable(result):
                    await result
            verdict = ctx.scoped.verdict(scope)
            if verdict.stop:
                if verdict.outcome == "root_incomplete" and len(scope) == 1:
                    proposal = getattr(self.source, "next_epoch", None)
                    mutation = proposal(self._view(ctx, scope, records)) if proposal else None
                    if inspect.isawaitable(mutation):
                        mutation = await mutation
                    if isinstance(mutation, EpochMutation):
                        scope = ctx.transition(scope, mutation)
                        continue
                    ended_by = END_INCOMPLETE
                else:
                    ended_by = END_YIELD_STOP
                break
        return self._record(ctx, scope, records, ended_by, end_reason)


# --------------------------------------------------------------------------
# sources for raw units
# --------------------------------------------------------------------------


class _LeafSource:
    """Wraps each raw unit an inner source (or iterable) yields as a Leaf."""

    def __init__(
        self,
        inner: Any,
        extract: Callable[[Any], Any],
        credit: Callable[[Any, Any], CreditResult],
        label: Optional[Callable[[Any], str]],
    ) -> None:
        self._pull: Callable[[EpisodeView], Any]
        if hasattr(inner, "next"):
            self._pull = inner.next
        else:
            iterator = iter(inner)
            self._pull = lambda _view: next(iterator, None)
        self._extract = extract
        self._credit = credit
        self._label = label
        self._index = 0

    def _wrap(self, unit: Any) -> Any:
        if unit is None or isinstance(unit, SourceEnd):
            return unit
        if isinstance(unit, Acquirable):
            raise TypeError(
                "leaves(...) wraps raw units; its inner source yielded an "
                f"Acquirable ({type(unit).__name__}). A source that yields "
                "Leaf or Episode is used directly, not through leaves(...)"
            )
        label = str(self._label(unit)) if self._label is not None else f"unit-{self._index}"
        self._index += 1
        return Leaf(unit=unit, extract=self._extract, credit=self._credit, label=label)

    def next(self, view: EpisodeView) -> Any:
        unit = self._pull(view)
        if inspect.isawaitable(unit):
            return self._wrap_awaitable(unit)
        return self._wrap(unit)

    async def _wrap_awaitable(self, awaitable: Any) -> Any:
        return self._wrap(await awaitable)


def leaves(
    units: Any,
    extract: Callable[[Any], Any],
    credit: Callable[[Any, Any], CreditResult],
    label: Optional[Callable[[Any], str]] = None,
) -> UnitSource:
    """A source of :class:`Leaf` over raw units.

    ``units`` is a plain iterable (which then ignores the view) or a
    ``UnitSource`` yielding raw units. Each unit is bound to ``extract`` and
    ``credit``; its label is ``label(unit)`` or ``unit-<index>``. The inner
    source may return ``None`` and :class:`SourceEnd` as usual. It may not
    yield an :class:`Acquirable`: that is a mis-declared composition and
    fails by name here rather than being silently double-wrapped.
    """

    return _LeafSource(units, extract, credit, label)


# --------------------------------------------------------------------------
# the context: path-addressed scopes, opened from the Grain in hand
# --------------------------------------------------------------------------


class Context:
    """The :class:`ScopedYield` plus a path stack, required frozen run-specific
    channel bindings, and optionally the composition's declared grain order.
    It keeps no records, observes nothing (the loop's step), and decides
    nothing.
    """

    def __init__(
        self,
        scoped: Optional[ScopedYield] = None,
        *,
        channel_schemas: Mapping[str, ChannelSchema],
        order: Optional[Iterable[Grain]] = None,
    ) -> None:
        self.scoped = scoped if scoped is not None else ScopedYield()
        self.order: Optional[tuple[Grain, ...]] = None
        if order is not None:
            grains = tuple(order)
            names = [grain.name for grain in grains]
            if len(set(names)) != len(names):
                raise ValueError(f"Context order names a grain twice: {names}")
            self.order = grains
        if not isinstance(channel_schemas, Mapping):
            raise TypeError("Context.channel_schemas must be a mapping")
        self._channel_schemas: dict[str, ChannelSchema] = {}
        for name, schema in channel_schemas.items():
            grain_name = str(name)
            if not grain_name:
                raise ValueError("channel schema grain names must be non-empty")
            if not isinstance(schema, ChannelSchema):
                raise TypeError(
                    f"channel schema for grain {grain_name!r} must be a ChannelSchema"
                )
            self._channel_schemas[grain_name] = schema
        if self.order is not None:
            undeclared = set(self._channel_schemas) - {grain.name for grain in self.order}
            if undeclared:
                raise ValueError(
                    f"channel schemas name grains outside the declared order: "
                    f"{sorted(undeclared)}"
                )
        self._stack: list[Path] = []
        self._grains: dict[str, Grain] = {}

    @property
    def path(self) -> Path:
        return self._stack[-1] if self._stack else ()

    def _expected_next(self, parent: Path) -> Optional[Grain]:
        assert self.order is not None
        if not parent:
            return self.order[0]
        parent_name = parent[-1][0]
        for index, grain in enumerate(self.order):
            if grain.name == parent_name:
                return self.order[index + 1] if index + 1 < len(self.order) else None
        return None

    def enter(self, grain: Grain, key: str) -> Scope:
        """Open the scope for one episode beneath the current path.

        Raises, never falls back: on a different ``Grain`` under an already
        declared name (rule 4: every grain declared once); on a grain out of
        the declared ``order``; on a path already open (the same episode run
        twice under one parent). Every estimator in the selected frozen channel
        schema is created here, before the source can receive its first view.
        The separate numerical controller is created from ``grain.control``
        directly -- there is no name-to-controller registry.
        """

        if not isinstance(grain, Grain):
            raise TypeError(f"enter() needs a Grain, got {type(grain).__name__}")
        known = self._grains.get(grain.name)
        if known is not None and known is not grain and known != grain:
            raise ValueError(
                f"grain {grain.name!r} declared twice with different parts; "
                f"every grain is declared once"
            )
        parent = self.path
        if self.order is not None:
            expected = self._expected_next(parent)
            if expected is None or expected.name != grain.name:
                raise ValueError(
                    f"grain {grain.name!r} may not nest under "
                    f"{parent[-1][0] if parent else 'the root'}: the declared "
                    f"order is {[g.name for g in self.order]}"
                )
        path: Path = tuple(parent) + ((grain.name, str(key)),)
        if grain.name not in self._channel_schemas:
            raise ValueError(
                f"no frozen channel schema declared for grain {grain.name!r}; "
                "Context.enter fails closed instead of selecting a default"
            )
        channel_schema = self._channel_schemas[grain.name]
        scope = self.scoped.open_scope(path, grain.control, channel_schema)
        self._grains[grain.name] = grain
        self._stack.append(scope)
        return scope

    def leave(self, scope: Scope) -> None:
        if not self._stack or self._stack[-1] != scope:
            raise RuntimeError(
                f"leave({scope!r}) does not match the open path "
                f"{self.path!r}; episodes nest and close in order"
            )
        self._stack.pop()

    def transition(self, scope: Scope, mutation: EpochMutation) -> Scope:
        if scope != self.path or len(scope) != 1:
            raise ValueError("only the open root episode may transition epoch")
        return self.scoped.transition_scope(scope, mutation.epoch)
