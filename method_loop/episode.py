"""The generic, nestable Episode method.

``Episode`` owns one loop: pull a unit, acquire it, send its binding-produced
value to the injected controller, publish a compact update, and then obey the
controller's structural stop decision.  It has no knowledge of columns,
incidence, rarefaction, hypervolume, or any other surface-specific result.

Nested communication and tracing are deliberately separate:

* :class:`EpisodeRequest` is the compact parent-to-child input.
* :class:`EpisodeUpdate` is the compact child-to-parent output.
* :class:`EpisodeRecord` is the complete recursive trace retained for audit.

Sources and parent-unit hooks receive the compact messages.  They never receive
a nested ``EpisodeRecord`` through the method's running view.  A child-owned
``on_close`` hook may publish that child's complete record for audit.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, runtime_checkable

from .identities import EpisodeRef, UnitRef
from .runtime import ControllerFactory, ControllerRuntime, Path, Scope

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
    "Contribution",
    "Episode",
    "EpisodeRecord",
    "EpisodeRequest",
    "EpisodeTree",
    "EpisodeUpdate",
    "EpisodeView",
    "EpochMutation",
    "Grain",
    "Leaf",
    "ResumeUnit",
    "SourceEnd",
    "UnitRecord",
    "UnitSource",
    "UnitView",
    "leaves",
]

END_EXHAUSTED = "exhausted"
END_YIELD_STOP = "yield_stop"
END_INCOMPLETE = "incomplete"
END_BOUND_HIT = "bound_hit"
END_SOURCE_FAILED = "source_failed"
ENDS = (
    END_EXHAUSTED,
    END_YIELD_STOP,
    END_INCOMPLETE,
    END_BOUND_HIT,
    END_SOURCE_FAILED,
)
COUNTING_ENDS = (END_EXHAUSTED, END_YIELD_STOP)
SOURCE_END_KINDS = (END_BOUND_HIT, END_SOURCE_FAILED)
END_REASON_UNIT_BOUND = "unit_bound"


def _record_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "as_record"):
        return value.as_record()
    if isinstance(value, Mapping):
        return {str(name): _record_value(item) for name, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_record_value(item) for item in value]
    return repr(value)


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
    """A source proposal for a new root-controller epoch."""

    epoch: str

    def __post_init__(self) -> None:
        if not isinstance(self.epoch, str) or not self.epoch.strip():
            raise ValueError("EpochMutation.epoch must be a non-empty stable id")


@dataclass(frozen=True)
class EpisodeRequest:
    """The compact information a parent supplies when it opens a child."""

    input: Any = None
    prompt_context: Any = None

    def as_record(self) -> dict[str, Any]:
        return {
            "input": _record_value(self.input),
            "prompt_context": _record_value(self.prompt_context),
        }


@dataclass(frozen=True)
class EpisodeUpdate:
    """The compact information a completed child returns to its parent."""

    record_id: str
    controller_input: Any
    prompt_context: Any = None
    output: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id:
            raise ValueError("EpisodeUpdate.record_id must be a non-empty string")

    def as_record(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "controller_input": _record_value(self.controller_input),
            "prompt_context": _record_value(self.prompt_context),
        }


@dataclass(frozen=True)
class Contribution:
    """The compact result visible to the containing Episode's hook."""

    controller_input: Any
    output: Any = None
    episode_update: Optional[EpisodeUpdate] = None


@dataclass(frozen=True)
class _AcquiredUnit:
    contribution: Contribution
    child_record: Optional["EpisodeRecord"] = None


@dataclass(frozen=True)
class UnitRecord:
    """The full trace of one acquired unit."""

    unit_label: str
    controller_input: Any
    controller_step: Any
    epoch: str
    unit_ref: UnitRef
    episode_update: Optional[EpisodeUpdate] = None
    child: Optional["EpisodeRecord"] = None

    @property
    def unit_id(self) -> str:
        return self.unit_ref.unit_id

    def as_record(self) -> dict[str, Any]:
        return {
            "unit_label": self.unit_label,
            "unit_ref": self.unit_ref.as_record(),
            "unit_id": self.unit_id,
            "epoch": self.epoch,
            "controller_input": _record_value(self.controller_input),
            "controller_step": _record_value(self.controller_step),
            "episode_update": (
                self.episode_update.as_record()
                if self.episode_update is not None
                else None
            ),
            "child": self.child.as_record() if self.child is not None else None,
        }


@dataclass(frozen=True)
class UnitView:
    """The per-unit information visible to a post-controller hook."""

    unit_label: str
    controller_input: Any
    controller_step: Any
    epoch: str
    unit_ref: UnitRef
    episode_update: Optional[EpisodeUpdate] = None


@dataclass(frozen=True)
class ResumeUnit:
    """One previously completed input restored at a durable boundary."""

    label: str
    controller_input: Any

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("ResumeUnit.label must be a non-empty string")


@dataclass(frozen=True)
class EpisodeRecord:
    """The complete recursive trace of one Episode."""

    scope_level: str
    scope_key: str
    units_consumed: int
    ended_by: str
    unit_records: tuple[UnitRecord, ...]
    controller_state: Any
    safety_bound: Optional[int] = None
    path: Path = ()
    end_reason: str = ""
    episode_ref: Optional[EpisodeRef] = None
    request: EpisodeRequest = field(default_factory=EpisodeRequest)

    @property
    def episode_id(self) -> str:
        return self.episode_ref.episode_id if self.episode_ref is not None else ""

    @property
    def run_id(self) -> str:
        return self.episode_ref.run_id if self.episode_ref is not None else ""

    def as_record(self) -> dict[str, Any]:
        return {
            "scope_level": self.scope_level,
            "scope_key": self.scope_key,
            "path": [list(item) for item in self.path],
            "episode_ref": (
                self.episode_ref.as_record() if self.episode_ref else None
            ),
            "episode_id": self.episode_id,
            "run_id": self.run_id,
            "request": self.request.as_record(),
            "units_consumed": self.units_consumed,
            "ended_by": self.ended_by,
            "end_reason": self.end_reason,
            "safety_bound": self.safety_bound,
            "controller_state": _record_value(self.controller_state),
            "units": [unit.as_record() for unit in self.unit_records],
        }


@dataclass(frozen=True)
class Grain:
    """One loop level and the controller function bound to that level."""

    name: str
    unit: str
    result: str
    controller: ControllerFactory

    def __post_init__(self) -> None:
        for field_name in ("name", "unit", "result"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Grain.{field_name} must be a non-empty sentence")
        if not callable(self.controller):
            raise TypeError("Grain.controller must be a controller function")


@dataclass(frozen=True)
class EpisodeTree:
    """The Episode types allowed beneath each parent Episode type.

    Runtime Episode instances still form an ordinary tree of paths. This
    declaration describes which *types* may occupy each child position, so a
    parent may choose among several child bindings without weakening nesting
    validation.
    """

    root: Grain
    children: Mapping[Grain, Iterable[Grain]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.root, Grain):
            raise TypeError("EpisodeTree.root must be a Grain")
        normalized: dict[Grain, tuple[Grain, ...]] = {}
        by_name: dict[str, Grain] = {self.root.name: self.root}
        parent_by_child: dict[str, str] = {}

        for parent, raw_children in self.children.items():
            if not isinstance(parent, Grain):
                raise TypeError("EpisodeTree parent keys must be Grain values")
            known_parent = by_name.get(parent.name)
            if known_parent is not None and known_parent != parent:
                raise ValueError(
                    f"grain {parent.name!r} has conflicting declarations"
                )
            by_name[parent.name] = parent
            declared_children = tuple(raw_children)
            child_names: set[str] = set()
            for child in declared_children:
                if not isinstance(child, Grain):
                    raise TypeError("EpisodeTree children must be Grain values")
                if child.name in child_names:
                    raise ValueError(
                        f"grain {child.name!r} is listed twice under {parent.name!r}"
                    )
                child_names.add(child.name)
                known_child = by_name.get(child.name)
                if known_child is not None and known_child != child:
                    raise ValueError(
                        f"grain {child.name!r} has conflicting declarations"
                    )
                by_name[child.name] = child
                prior_parent = parent_by_child.get(child.name)
                if prior_parent is not None and prior_parent != parent.name:
                    raise ValueError(
                        f"grain {child.name!r} has two parents: "
                        f"{prior_parent!r} and {parent.name!r}"
                    )
                parent_by_child[child.name] = parent.name
            normalized[parent] = declared_children

        if self.root.name in parent_by_child:
            raise ValueError("EpisodeTree.root may not also be a child")
        reachable = {self.root.name}
        frontier = [self.root]
        while frontier:
            parent = frontier.pop()
            for child in normalized.get(parent, ()):
                if child.name not in reachable:
                    reachable.add(child.name)
                    frontier.append(child)
        unreachable = set(by_name) - reachable
        if unreachable:
            raise ValueError(
                f"EpisodeTree has unreachable parent grains: {sorted(unreachable)}"
            )

        object.__setattr__(self, "children", normalized)
        object.__setattr__(self, "_by_name", by_name)
        object.__setattr__(self, "_parent_by_child", parent_by_child)

    @classmethod
    def linear(cls, grains: Iterable[Grain]) -> "EpisodeTree":
        """Build the declaration for a single linear path."""

        ordered = tuple(grains)
        if not ordered:
            raise ValueError("a linear EpisodeTree needs at least one Grain")
        return cls(
            root=ordered[0],
            children={
                parent: (child,)
                for parent, child in zip(ordered, ordered[1:])
            },
        )

    def allowed_children(self, parent_name: str) -> tuple[Grain, ...]:
        parent = self._by_name.get(str(parent_name))
        if parent is None:
            return ()
        return tuple(self.children.get(parent, ()))


@dataclass(frozen=True)
class EpisodeView:
    """The compact running state visible to one Episode's source."""

    grain: Grain
    key: str
    path: Path
    units_consumed: int
    bound: Optional[int]
    updates: tuple[EpisodeUpdate, ...]
    controller_state: Any
    episode_ref: EpisodeRef
    request: EpisodeRequest


class UnitSource(Protocol):
    """Return the next unit, ``None``, or a typed :class:`SourceEnd`."""

    def next(self, view: EpisodeView) -> Any: ...


@runtime_checkable
class Acquirable(Protocol):
    """The Composite component implemented by :class:`Leaf` and Episode."""

    label: str

    def acquire(self, ctx: "Context") -> _AcquiredUnit: ...

    async def acquire_async(self, ctx: "Context") -> _AcquiredUnit: ...


def _leaf_acquisition(
    unit: Any,
    extract: Callable[[Any], Any],
    accept: Optional[Callable[[Any, Any], Any]],
    result: Callable[[Any, Any], Any],
) -> _AcquiredUnit:
    extracted = extract(unit)
    accepted = accept(unit, extracted) if accept is not None else extracted
    controller_input = result(unit, accepted)
    return _AcquiredUnit(Contribution(controller_input, accepted))


async def _leaf_acquisition_async(
    unit: Any,
    extract: Callable[[Any], Any],
    accept: Optional[Callable[[Any, Any], Any]],
    result: Callable[[Any, Any], Any],
) -> _AcquiredUnit:
    extracted = extract(unit)
    if inspect.isawaitable(extracted):
        extracted = await extracted
    accepted = accept(unit, extracted) if accept is not None else extracted
    if inspect.isawaitable(accepted):
        accepted = await accepted
    controller_input = result(unit, accepted)
    if inspect.isawaitable(controller_input):
        controller_input = await controller_input
    return _AcquiredUnit(Contribution(controller_input, accepted))


@dataclass(frozen=True)
class Leaf:
    """A raw unit bound to extraction, acceptance, and result projection."""

    unit: Any
    extract: Callable[[Any], Any]
    result: Callable[[Any, Any], Any]
    label: str
    accept: Optional[Callable[[Any, Any], Any]] = None

    def acquire(self, ctx: "Context") -> _AcquiredUnit:
        return _leaf_acquisition(self.unit, self.extract, self.accept, self.result)

    async def acquire_async(self, ctx: "Context") -> _AcquiredUnit:
        return await _leaf_acquisition_async(
            self.unit, self.extract, self.accept, self.result
        )


@dataclass(frozen=True)
class Episode:
    """One instance of one Grain, composed from swappable parts."""

    grain: Grain
    key: str
    source: UnitSource
    on_unit: Optional[Callable[[Any, Contribution, UnitView], Any]] = None
    on_close: Optional[Callable[[EpisodeRecord], Any]] = None
    to_parent: Optional[Callable[[EpisodeRecord], EpisodeUpdate]] = None
    request: EpisodeRequest = field(default_factory=EpisodeRequest)
    bound: Optional[int] = None
    resume_units: tuple[ResumeUnit, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.grain, Grain):
            raise TypeError(
                f"Episode.grain must be a Grain, got {type(self.grain).__name__}"
            )
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("Episode.key must be a non-empty string")
        if not hasattr(self.source, "next"):
            raise TypeError(
                "Episode.source must implement UnitSource.next(view); wrap a "
                "plain iterable with leaves(...)"
            )
        if self.to_parent is not None and not callable(self.to_parent):
            raise TypeError("Episode.to_parent must be callable")
        if self.on_close is not None and not callable(self.on_close):
            raise TypeError("Episode.on_close must be callable")
        if not isinstance(self.request, EpisodeRequest):
            raise TypeError("Episode.request must be an EpisodeRequest")
        if self.bound is not None and (
            not isinstance(self.bound, int) or self.bound < 0
        ):
            raise ValueError(
                "Episode.bound must be None or a non-negative integer"
            )
        if not isinstance(self.resume_units, tuple) or any(
            not isinstance(unit, ResumeUnit) for unit in self.resume_units
        ):
            raise TypeError("Episode.resume_units must contain ResumeUnit values")

    @property
    def label(self) -> str:
        return self.key

    @classmethod
    def identity(
        cls,
        ctx: "Context",
        grain: Grain,
        key: str,
        *,
        parent_path: Path = (),
    ) -> EpisodeRef:
        path = tuple(parent_path) + ((grain.name, str(key)),)
        return EpisodeRef(run_id=ctx.require_run_id(), path=path)

    def reference(
        self,
        ctx: "Context",
        *,
        parent_path: Optional[Path] = None,
    ) -> EpisodeRef:
        parent = ctx.path if parent_path is None else tuple(parent_path)
        return self.identity(ctx, self.grain, self.key, parent_path=parent)

    def _as_parent_unit(self, record: EpisodeRecord) -> _AcquiredUnit:
        if self.to_parent is None:
            raise TypeError(
                f"nested Episode {record.path!r} has no to_parent function"
            )
        update = self.to_parent(record)
        if not isinstance(update, EpisodeUpdate):
            raise TypeError("Episode.to_parent() must return EpisodeUpdate")
        if update.record_id != record.episode_id:
            raise ValueError(
                "EpisodeUpdate.record_id must identify the completed child record"
            )
        return _AcquiredUnit(
            contribution=Contribution(
                controller_input=update.controller_input,
                output=update.output,
                episode_update=update,
            ),
            child_record=record,
        )

    def acquire(self, ctx: "Context") -> _AcquiredUnit:
        return self._as_parent_unit(self.run(ctx))

    async def acquire_async(self, ctx: "Context") -> _AcquiredUnit:
        return self._as_parent_unit(await self.run_async(ctx))

    def run(self, ctx: "Context") -> EpisodeRecord:
        if not ctx.path and not ctx.has_run_id:
            ctx.bind_run_id(self.key)
        scope = ctx.enter(self.grain, self.key)
        try:
            record = self._run_loop(ctx, scope)
            if self.on_close is not None:
                result = self.on_close(record)
                if inspect.isawaitable(result):
                    raise TypeError(
                        "an async Episode.on_close callback requires run_async()"
                    )
            return record
        finally:
            ctx.leave(scope)

    async def run_async(self, ctx: "Context") -> EpisodeRecord:
        if not ctx.path and not ctx.has_run_id:
            ctx.bind_run_id(self.key)
        scope = ctx.enter(self.grain, self.key)
        try:
            record = await self._run_loop_async(ctx, scope)
            if self.on_close is not None:
                result = self.on_close(record)
                if inspect.isawaitable(result):
                    await result
            return record
        finally:
            ctx.leave(scope)

    def _view(
        self,
        ctx: "Context",
        scope: Scope,
        records: list[UnitRecord],
    ) -> EpisodeView:
        return EpisodeView(
            grain=self.grain,
            key=self.key,
            path=scope,
            units_consumed=len(records),
            bound=self.bound,
            updates=tuple(
                record.episode_update
                for record in records
                if record.episode_update is not None
            ),
            controller_state=ctx.runtime.state(scope),
            episode_ref=EpisodeRef(run_id=ctx.require_run_id(), path=scope),
            request=self.request,
        )

    def _record(
        self,
        ctx: "Context",
        scope: Scope,
        records: list[UnitRecord],
        ended_by: str,
        end_reason: str,
    ) -> EpisodeRecord:
        path = scope
        return EpisodeRecord(
            scope_level=path[-1][0],
            scope_key=path[-1][1],
            units_consumed=len(records),
            ended_by=ended_by,
            unit_records=tuple(records),
            controller_state=ctx.runtime.state(scope),
            safety_bound=self.bound,
            path=path,
            end_reason=end_reason,
            episode_ref=EpisodeRef(run_id=ctx.require_run_id(), path=path),
            request=self.request,
        )

    def _append_record(
        self,
        ctx: "Context",
        scope: Scope,
        records: list[UnitRecord],
        label: str,
        acquired: _AcquiredUnit,
    ) -> tuple[UnitRecord, UnitView]:
        step = ctx.runtime.advance(
            scope,
            label,
            acquired.contribution.controller_input,
        )
        unit_ref = UnitRef(
            EpisodeRef(run_id=ctx.require_run_id(), path=scope).episode_id,
            len(records),
        )
        record = UnitRecord(
            unit_label=label,
            controller_input=acquired.contribution.controller_input,
            controller_step=step,
            epoch=ctx.runtime.epoch(scope),
            unit_ref=unit_ref,
            episode_update=acquired.contribution.episode_update,
            child=acquired.child_record,
        )
        view = UnitView(
            unit_label=label,
            controller_input=record.controller_input,
            controller_step=record.controller_step,
            epoch=record.epoch,
            unit_ref=record.unit_ref,
            episode_update=record.episode_update,
        )
        records.append(record)
        return record, view

    def _restore_units(
        self,
        ctx: "Context",
        scope: Scope,
    ) -> list[UnitRecord]:
        records: list[UnitRecord] = []
        for prior in self.resume_units:
            self._append_record(
                ctx,
                scope,
                records,
                prior.label,
                _AcquiredUnit(Contribution(prior.controller_input)),
            )
        return records

    @staticmethod
    def _state_stops(state: Any) -> bool:
        stop = getattr(state, "stop", None)
        if not isinstance(stop, bool):
            raise TypeError("a controller state must expose a boolean stop")
        return stop

    def _stop_end(
        self,
        ctx: "Context",
        scope: Scope,
        records: list[UnitRecord],
        step: Any,
    ) -> tuple[Scope, Optional[str]]:
        if step.requests_transition and len(scope) == 1:
            proposal = getattr(self.source, "next_epoch", None)
            mutation = proposal(self._view(ctx, scope, records)) if proposal else None
            if isinstance(mutation, EpochMutation):
                return ctx.transition(scope, mutation), None
            return scope, END_INCOMPLETE
        return scope, END_YIELD_STOP

    async def _stop_end_async(
        self,
        ctx: "Context",
        scope: Scope,
        records: list[UnitRecord],
        step: Any,
    ) -> tuple[Scope, Optional[str]]:
        if step.requests_transition and len(scope) == 1:
            proposal = getattr(self.source, "next_epoch", None)
            mutation = proposal(self._view(ctx, scope, records)) if proposal else None
            if inspect.isawaitable(mutation):
                mutation = await mutation
            if isinstance(mutation, EpochMutation):
                return ctx.transition(scope, mutation), None
            return scope, END_INCOMPLETE
        return scope, END_YIELD_STOP

    def _run_loop(self, ctx: "Context", scope: Scope) -> EpisodeRecord:
        records = self._restore_units(ctx, scope)
        ended_by, end_reason = END_EXHAUSTED, ""
        if records and self._state_stops(ctx.runtime.state(scope)):
            return self._record(ctx, scope, records, END_YIELD_STOP, "")
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
            acquired = item.acquire(ctx)
            if not isinstance(acquired, _AcquiredUnit):
                raise TypeError("Acquirable.acquire() returned an invalid result")
            _, unit_view = self._append_record(
                ctx, scope, records, item.label, acquired
            )
            if self.on_unit is not None:
                self.on_unit(item, acquired.contribution, unit_view)
            step = unit_view.controller_step
            if step.stop:
                scope, end = self._stop_end(ctx, scope, records, step)
                if end is None:
                    continue
                ended_by = end
                break
        return self._record(ctx, scope, records, ended_by, end_reason)

    async def _run_loop_async(
        self,
        ctx: "Context",
        scope: Scope,
    ) -> EpisodeRecord:
        records = self._restore_units(ctx, scope)
        ended_by, end_reason = END_EXHAUSTED, ""
        if records and self._state_stops(ctx.runtime.state(scope)):
            return self._record(ctx, scope, records, END_YIELD_STOP, "")
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
            acquired = item.acquire_async(ctx)
            if inspect.isawaitable(acquired):
                acquired = await acquired
            if not isinstance(acquired, _AcquiredUnit):
                raise TypeError("Acquirable.acquire_async() returned an invalid result")
            _, unit_view = self._append_record(
                ctx, scope, records, item.label, acquired
            )
            if self.on_unit is not None:
                result = self.on_unit(item, acquired.contribution, unit_view)
                if inspect.isawaitable(result):
                    await result
            step = unit_view.controller_step
            if step.stop:
                scope, end = await self._stop_end_async(
                    ctx, scope, records, step
                )
                if end is None:
                    continue
                ended_by = end
                break
        return self._record(ctx, scope, records, ended_by, end_reason)


class _LeafSource:
    def __init__(
        self,
        inner: Any,
        extract: Callable[[Any], Any],
        result: Callable[[Any, Any], Any],
        label: Optional[Callable[[Any], str]],
        accept: Optional[Callable[[Any, Any], Any]],
    ) -> None:
        if hasattr(inner, "next"):
            self._pull = inner.next
        else:
            iterator = iter(inner)
            self._pull = lambda _view: next(iterator, None)
        self._extract = extract
        self._result = result
        self._label = label
        self._accept = accept
        self._index = 0

    def _wrap(self, unit: Any) -> Any:
        if unit is None or isinstance(unit, SourceEnd):
            return unit
        if isinstance(unit, Acquirable):
            raise TypeError(
                "leaves(...) wraps raw units; its source returned an Acquirable"
            )
        label = (
            str(self._label(unit))
            if self._label is not None
            else f"unit-{self._index}"
        )
        self._index += 1
        return Leaf(
            unit=unit,
            extract=self._extract,
            accept=self._accept,
            result=self._result,
            label=label,
        )

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
    result: Callable[[Any, Any], Any],
    label: Optional[Callable[[Any], str]] = None,
    accept: Optional[Callable[[Any, Any], Any]] = None,
) -> UnitSource:
    """Wrap a raw-unit source with the bound leaf operations."""

    return _LeafSource(units, extract, result, label, accept)


class Context:
    """Run identity, nesting path, and controller routing only."""

    def __init__(
        self,
        *,
        order: Optional[Iterable[Grain]] = None,
        tree: Optional[EpisodeTree] = None,
        run_id: Optional[str] = None,
        runtime: Optional[ControllerRuntime] = None,
    ) -> None:
        if order is not None and tree is not None:
            raise ValueError("Context accepts either order or tree, not both")
        self.runtime = runtime if runtime is not None else ControllerRuntime()
        self.order: Optional[tuple[Grain, ...]] = None
        self.tree: Optional[EpisodeTree] = tree
        if order is not None:
            grains = tuple(order)
            names = [grain.name for grain in grains]
            if len(set(names)) != len(names):
                raise ValueError(f"Context order names a grain twice: {names}")
            self.order = grains
            self.tree = EpisodeTree.linear(grains)
        self._stack: list[Path] = []
        self._grains: dict[str, Grain] = {}
        self._run_id: Optional[str] = None
        if run_id is not None:
            self.bind_run_id(run_id)

    def bind_run_id(self, run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("Context run_id must be a non-empty string")
        if self._run_id is not None and self._run_id != run_id:
            raise ValueError("Context run_id is already bound")
        self._run_id = run_id

    @property
    def has_run_id(self) -> bool:
        return self._run_id is not None

    def require_run_id(self) -> str:
        if self._run_id is None:
            raise RuntimeError(
                "Context run_id must be bound before Episode identity is read"
            )
        return self._run_id

    @property
    def path(self) -> Path:
        return self._stack[-1] if self._stack else ()

    def _allowed_next(self, parent: Path) -> tuple[Grain, ...]:
        assert self.tree is not None
        if not parent:
            return (self.tree.root,)
        return self.tree.allowed_children(parent[-1][0])

    def enter(self, grain: Grain, key: str) -> Scope:
        if not isinstance(grain, Grain):
            raise TypeError(f"enter() needs a Grain, got {type(grain).__name__}")
        known = self._grains.get(grain.name)
        if known is not None and known is not grain and known != grain:
            raise ValueError(f"grain {grain.name!r} was declared more than once")
        parent = self.path
        if self.tree is not None:
            allowed = self._allowed_next(parent)
            declared = next(
                (item for item in allowed if item.name == grain.name),
                None,
            )
            if declared is None:
                raise ValueError(
                    f"grain {grain.name!r} may not nest under "
                    f"{parent[-1][0] if parent else 'the root'}; allowed: "
                    f"{[item.name for item in allowed]}"
                )
            if declared != grain:
                raise ValueError(
                    f"grain {grain.name!r} differs from its EpisodeTree declaration"
                )
        path: Path = tuple(parent) + ((grain.name, str(key)),)
        scope = self.runtime.open_scope(path, grain.controller)
        self._grains[grain.name] = grain
        self._stack.append(scope)
        return scope

    def leave(self, scope: Scope) -> None:
        if not self._stack or self._stack[-1] != scope:
            raise RuntimeError("episodes must close in nesting order")
        self._stack.pop()

    def transition(self, scope: Scope, mutation: EpochMutation) -> Scope:
        if scope != self.path or len(scope) != 1:
            raise ValueError("only the open root episode may transition epoch")
        return self.runtime.transition_scope(scope, mutation.epoch)
