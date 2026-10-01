"""The generic, nestable Episode method.

``Episode`` owns one loop: pull a unit, acquire it, send its binding-produced
value to the injected controller, publish a compact update, and then obey the
controller's structural stop decision.  It has no knowledge of columns,
incidence, rarefaction, hypervolume, or any other surface-specific result.

Nested communication and tracing are deliberately separate:

* :class:`EpisodeGoal` is the immutable objective at one Episode boundary.
* :class:`EpisodeRequest` carries that Goal plus compact parent-to-child input.
* :class:`EpisodeUpdate` preserves that Goal in the compact child-to-parent output.
* :class:`EpisodeRecord` is the complete recursive trace retained for audit.

Sources and parent-unit hooks receive the compact messages.  They never receive
a nested ``EpisodeRecord`` through the method's running view.  A child-owned
``on_close`` hook may publish that child's complete record for audit.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Optional, Protocol, runtime_checkable

from .identities import EpisodeRef, UnitRef
from .runtime import ControllerFactory, ControllerRuntime, Path, Scope

__all__ = [
    "END_BOUND_HIT",
    "END_EXHAUSTED",
    "END_INCOMPLETE",
    "END_REASON_UNIT_BOUND",
    "END_SOURCE_FAILED",
    "END_YIELD_STOP",
    "SOURCE_END_KINDS",
    "Acquirable",
    "Context",
    "Contribution",
    "Episode",
    "EpisodeCompletion",
    "EpisodeGoal",
    "GoalPreview",
    "GoalProposal",
    "GoalState",
    "EpisodeRecord",
    "EpisodeRequest",
    "EpisodeResult",
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


def _freeze_json(value: Any) -> Any:
    """Return an immutable JSON value or raise at the Goal boundary."""

    def thaw(item: Any) -> Any:
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        if isinstance(item, Mapping):
            return {str(name): thaw(child) for name, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [thaw(child) for child in item]
        raise TypeError(
            f"{type(item).__name__} is not a JSON-compatible Goal value"
        )

    try:
        normalized = json.loads(
            json.dumps(
                thaw(value),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            )
        )
    except (TypeError, ValueError) as exc:
        raise TypeError("EpisodeGoal values must be JSON-compatible") from exc

    def freeze(item: Any) -> Any:
        if isinstance(item, dict):
            return MappingProxyType(
                {str(name): freeze(child) for name, child in item.items()}
            )
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    return freeze(normalized)


@dataclass(frozen=True)
class EpisodeGoal:
    """The immutable objective and result contract for one Episode.

    A root Goal has no ``parent_goal_id``. A child Goal is made with
    :meth:`child`, which records the parent Goal it refines. The method loop
    validates that link before it runs a nested Episode.
    """

    objective: Any
    result_contract: Any
    task_context: Any = None
    parent_goal_id: str = ""
    goal_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.parent_goal_id, str):
            raise TypeError("EpisodeGoal.parent_goal_id must be a string")
        if self.parent_goal_id and self.task_context is None:
            raise ValueError(
                "a child EpisodeGoal must preserve its root task_context"
            )
        objective = _freeze_json(self.objective)
        result_contract = _freeze_json(self.result_contract)
        task_context = _freeze_json(
            self.task_context
            if self.task_context is not None
            else {
                "root_objective": _record_value(objective),
                "root_result_contract": _record_value(result_contract),
            }
        )
        body = {
            "objective": _record_value(objective),
            "result_contract": _record_value(result_contract),
            "task_context": _record_value(task_context),
            "parent_goal_id": self.parent_goal_id,
        }
        digest = hashlib.sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "objective", objective)
        object.__setattr__(self, "result_contract", result_contract)
        object.__setattr__(self, "task_context", task_context)
        object.__setattr__(self, "goal_id", f"goal_{digest[:24]}")

    @classmethod
    def root(
        cls,
        *,
        objective: Any,
        result_contract: Any,
        task_context: Any = None,
    ) -> "EpisodeGoal":
        return cls(
            objective=objective,
            result_contract=result_contract,
            task_context=task_context,
        )

    @classmethod
    def child(
        cls,
        parent: "EpisodeGoal",
        *,
        objective: Any,
        result_contract: Any,
    ) -> "EpisodeGoal":
        if not isinstance(parent, EpisodeGoal):
            raise TypeError("a child Goal requires an EpisodeGoal parent")
        return cls(
            objective=objective,
            result_contract=result_contract,
            task_context=parent.task_context,
            parent_goal_id=parent.goal_id,
        )

    @classmethod
    def for_grain(
        cls,
        grain: Any,
        *,
        objective: Any,
        parent: Optional["EpisodeGoal"] = None,
        result_contract: Any = None,
    ) -> "EpisodeGoal":
        """Build the standard Goal for a declared Grain.

        Bindings supply only the local objective. The Grain supplies the
        generic unit/result contract unless a binding has a more precise JSON
        contract to record.
        """

        if not isinstance(grain, Grain):
            raise TypeError("EpisodeGoal.for_grain requires a Grain")
        contract = (
            result_contract
            if result_contract is not None
            else {
                "grain": grain.name,
                "unit": grain.unit,
                "result": grain.result,
            }
        )
        if parent is None:
            return cls.root(objective=objective, result_contract=contract)
        return cls.child(
            parent,
            objective=objective,
            result_contract=contract,
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "parent_goal_id": self.parent_goal_id,
            "objective": _record_value(self.objective),
            "result_contract": _record_value(self.result_contract),
            "task_context": _record_value(self.task_context),
        }


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

    goal: EpisodeGoal
    input: Any = None
    prompt_context: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.goal, EpisodeGoal):
            raise TypeError("EpisodeRequest.goal must be an EpisodeGoal")

    def as_record(self) -> dict[str, Any]:
        return {
            "goal": self.goal.as_record(),
            "input": _record_value(self.input),
            "prompt_context": _record_value(self.prompt_context),
        }


@dataclass(frozen=True)
class EpisodeCompletion:
    """How a child Episode ended, recorded by the method rather than a binding."""

    ended_by: str
    end_reason: str
    units_consumed: int

    def __post_init__(self) -> None:
        if not isinstance(self.ended_by, str) or not self.ended_by:
            raise ValueError("EpisodeCompletion.ended_by must be a non-empty string")
        if not isinstance(self.end_reason, str):
            raise TypeError("EpisodeCompletion.end_reason must be a string")
        if (
            isinstance(self.units_consumed, bool)
            or not isinstance(self.units_consumed, int)
            or self.units_consumed < 0
        ):
            raise ValueError(
                "EpisodeCompletion.units_consumed must be a non-negative integer"
            )

    @classmethod
    def from_record(cls, record: "EpisodeRecord") -> "EpisodeCompletion":
        if not isinstance(record, EpisodeRecord):
            raise TypeError("EpisodeCompletion requires an EpisodeRecord")
        return cls(
            ended_by=record.ended_by,
            end_reason=record.end_reason,
            units_consumed=record.units_consumed,
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "ended_by": self.ended_by,
            "end_reason": self.end_reason,
            "units_consumed": self.units_consumed,
        }


@dataclass(frozen=True)
class EpisodeResult:
    """A binding's compact child result, independent of how the child ended."""

    result: Any
    prompt_context: Any = None
    output: Any = None


@dataclass(frozen=True)
class EpisodeUpdate:
    """The method-owned compact message from one child to its parent.

    ``result`` and ``completion`` remain separate. A child can therefore
    return accepted results and also report that its source later failed or a
    bound cut it short. ``controller_input`` is the binding's explicit mapping
    of those two facts into the parent's numerical component.
    """

    record_id: str
    goal: EpisodeGoal
    result: Any
    completion: EpisodeCompletion
    controller_input: Any
    prompt_context: Any = None
    output: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id:
            raise ValueError("EpisodeUpdate.record_id must be a non-empty string")
        if not isinstance(self.goal, EpisodeGoal):
            raise TypeError("EpisodeUpdate.goal must be an EpisodeGoal")
        if not isinstance(self.completion, EpisodeCompletion):
            raise TypeError(
                "EpisodeUpdate.completion must be an EpisodeCompletion"
            )

    def as_record(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "goal": self.goal.as_record(),
            "result": _record_value(self.result),
            "completion": self.completion.as_record(),
            "controller_input": _record_value(self.controller_input),
            "prompt_context": _record_value(self.prompt_context),
        }


@dataclass(frozen=True)
class GoalProposal:
    """A binding's proposed Goal result, before numerical control.

    The proposal carries no write capability. Only the Goal state installed on
    :class:`Context` can preview it and, after the controller transition,
    commit the identities selected by that transition.
    """

    payload: Any


@dataclass(frozen=True)
class GoalPreview:
    """A non-mutating Goal projection prepared for one controller step."""

    controller_input: Any
    candidate_result_ids: tuple[str, ...]
    state_id: str
    no_commit_result: Any = None
    token: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.state_id, str) or not self.state_id:
            raise ValueError("GoalPreview.state_id must be a non-empty string")
        if not isinstance(self.candidate_result_ids, tuple):
            raise TypeError("GoalPreview.candidate_result_ids must be a tuple")
        if any(
            not isinstance(result_id, str) or not result_id
            for result_id in self.candidate_result_ids
        ):
            raise ValueError("Goal result identities must be non-empty strings")
        if len(set(self.candidate_result_ids)) != len(self.candidate_result_ids):
            raise ValueError("Goal result identities must be unique")


@runtime_checkable
class GoalState(Protocol):
    """The method-owned mutable Goal boundary.

    ``preview`` must not mutate state. ``commit`` is called only after the
    numerical controller returns a non-empty subset of the previewed result
    identities.
    """

    @property
    def state_id(self) -> str: ...

    def preview(self, proposal: GoalProposal, unit_ref: UnitRef) -> GoalPreview: ...

    def commit(
        self,
        preview: GoalPreview,
        result_ids: tuple[str, ...],
    ) -> Any: ...


@dataclass(frozen=True)
class Contribution:
    """The compact result visible to the containing Episode's hook."""

    controller_input: Any
    output: Any = None
    episode_update: Optional[EpisodeUpdate] = None
    goal_result: Any = None


@dataclass(frozen=True)
class _AcquiredUnit:
    contribution: Contribution
    child_record: Optional["EpisodeRecord"] = None
    goal_proposal: Optional[GoalProposal] = None


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
    goal_result: Any = None

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
            "goal_result": _record_value(self.goal_result),
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
    goal_result: Any = None


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
    request: EpisodeRequest
    safety_bound: Optional[int] = None
    path: Path = ()
    end_reason: str = ""
    episode_ref: Optional[EpisodeRef] = None

    @property
    def goal(self) -> EpisodeGoal:
        return self.request.goal

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
            "goal": self.goal.as_record(),
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

    @property
    def goal(self) -> EpisodeGoal:
        return self.request.goal


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
    projected = result(unit, accepted)
    if isinstance(projected, GoalProposal):
        return _AcquiredUnit(
            contribution=Contribution(controller_input=None, output=accepted),
            goal_proposal=projected,
        )
    return _AcquiredUnit(Contribution(projected, accepted))


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
    projected = result(unit, accepted)
    if inspect.isawaitable(projected):
        projected = await projected
    if isinstance(projected, GoalProposal):
        return _AcquiredUnit(
            contribution=Contribution(controller_input=None, output=accepted),
            goal_proposal=projected,
        )
    return _AcquiredUnit(Contribution(projected, accepted))


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
    request: EpisodeRequest
    on_unit: Optional[Callable[[Any, Contribution, UnitView], Any]] = None
    on_close: Optional[Callable[[EpisodeRecord], Any]] = None
    to_parent: Optional[Callable[[EpisodeRecord], EpisodeResult]] = None
    parent_controller_input: Optional[
        Callable[[Any, EpisodeCompletion], Any]
    ] = None
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
        if self.parent_controller_input is not None and not callable(
            self.parent_controller_input
        ):
            raise TypeError("Episode.parent_controller_input must be callable")
        if (self.to_parent is None) != (self.parent_controller_input is None):
            raise ValueError(
                "Episode.to_parent and Episode.parent_controller_input must "
                "be supplied together"
            )
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

    @property
    def goal(self) -> EpisodeGoal:
        return self.request.goal

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

    def _as_parent_unit(self, record: EpisodeRecord) -> _AcquiredUnit:
        if self.to_parent is None:
            raise TypeError(
                f"nested Episode {record.path!r} has no to_parent function"
            )
        result = self.to_parent(record)
        if not isinstance(result, EpisodeResult):
            raise TypeError("Episode.to_parent() must return EpisodeResult")
        if self.parent_controller_input is None:
            raise TypeError(
                f"nested Episode {record.path!r} has no parent_controller_input"
            )
        completion = EpisodeCompletion.from_record(record)
        controller_input = self.parent_controller_input(
            result.result,
            completion,
        )
        update = EpisodeUpdate(
            record_id=record.episode_id,
            goal=record.goal,
            result=result.result,
            completion=completion,
            controller_input=controller_input,
            prompt_context=result.prompt_context,
            output=result.output,
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
        self._validate_position(ctx)
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
        self._validate_position(ctx)
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

    def _validate_position(self, ctx: "Context") -> None:
        if ctx.path and not self.goal.parent_goal_id:
            raise ValueError("a nested Episode must carry a child Goal")
        if not ctx.path and self.goal.parent_goal_id:
            raise ValueError("a root Episode Goal may not name a parent Goal")

    def _validate_child(self, item: Any) -> None:
        if not isinstance(item, Episode):
            return
        if item.goal.parent_goal_id != self.goal.goal_id:
            raise ValueError(
                "a child Episode Goal must name the containing Episode Goal"
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
    ) -> tuple[UnitRecord, UnitView, Contribution]:
        unit_ref = UnitRef(
            EpisodeRef(run_id=ctx.require_run_id(), path=scope).episode_id,
            len(records),
        )
        controller_input = acquired.contribution.controller_input
        goal_preview: Optional[GoalPreview] = None
        if acquired.goal_proposal is not None:
            goal_preview = ctx._preview_goal(acquired.goal_proposal, unit_ref)
            controller_input = goal_preview.controller_input
        step = ctx.runtime.advance(scope, label, controller_input)
        goal_result = acquired.contribution.goal_result
        if goal_preview is not None:
            result_ids = getattr(step, "goal_commit_ids", None)
            if result_ids is None:
                raise TypeError(
                    "a controller step handling a Goal proposal must expose "
                    "goal_commit_ids"
                )
            result_ids = tuple(str(result_id) for result_id in result_ids)
            candidates = set(goal_preview.candidate_result_ids)
            unknown = sorted(set(result_ids) - candidates)
            if unknown:
                raise ValueError(
                    "controller selected Goal identities absent from its "
                    f"preview: {unknown}"
                )
            goal_result = (
                ctx._commit_goal(goal_preview, result_ids)
                if result_ids
                else goal_preview.no_commit_result
            )
        contribution = Contribution(
            controller_input=controller_input,
            output=acquired.contribution.output,
            episode_update=acquired.contribution.episode_update,
            goal_result=goal_result,
        )
        record = UnitRecord(
            unit_label=label,
            controller_input=controller_input,
            controller_step=step,
            epoch=ctx.runtime.epoch(scope),
            unit_ref=unit_ref,
            episode_update=acquired.contribution.episode_update,
            child=acquired.child_record,
            goal_result=goal_result,
        )
        view = UnitView(
            unit_label=label,
            controller_input=record.controller_input,
            controller_step=record.controller_step,
            epoch=record.epoch,
            unit_ref=record.unit_ref,
            episode_update=record.episode_update,
            goal_result=goal_result,
        )
        records.append(record)
        return record, view, contribution

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
            self._validate_child(item)
            acquired = item.acquire(ctx)
            if not isinstance(acquired, _AcquiredUnit):
                raise TypeError("Acquirable.acquire() returned an invalid result")
            _, unit_view, contribution = self._append_record(
                ctx, scope, records, item.label, acquired
            )
            if self.on_unit is not None:
                self.on_unit(item, contribution, unit_view)
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
            self._validate_child(item)
            acquired = item.acquire_async(ctx)
            if inspect.isawaitable(acquired):
                acquired = await acquired
            if not isinstance(acquired, _AcquiredUnit):
                raise TypeError("Acquirable.acquire_async() returned an invalid result")
            _, unit_view, contribution = self._append_record(
                ctx, scope, records, item.label, acquired
            )
            if self.on_unit is not None:
                result = self.on_unit(item, contribution, unit_view)
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
    """Run identity, nesting, controller routing, and the Goal write boundary."""

    def __init__(
        self,
        *,
        tree: EpisodeTree,
        run_id: Optional[str] = None,
        runtime: Optional[ControllerRuntime] = None,
        goal_state: Optional[GoalState] = None,
    ) -> None:
        if not isinstance(tree, EpisodeTree):
            raise TypeError("Context.tree must be an EpisodeTree")
        self.runtime = runtime if runtime is not None else ControllerRuntime()
        self.tree = tree
        if goal_state is not None and not isinstance(goal_state, GoalState):
            raise TypeError("Context.goal_state must implement GoalState")
        self.__goal_state = goal_state
        self._stack: list[Path] = []
        self._grains: dict[str, Grain] = {}
        self._run_id: Optional[str] = None
        if run_id is not None:
            self.bind_run_id(run_id)

    def _preview_goal(
        self,
        proposal: GoalProposal,
        unit_ref: UnitRef,
    ) -> GoalPreview:
        state = self.__goal_state
        if state is None:
            raise RuntimeError("a Goal proposal requires a method-owned GoalState")
        before = state.state_id
        preview = state.preview(proposal, unit_ref)
        if not isinstance(preview, GoalPreview):
            raise TypeError("GoalState.preview() must return GoalPreview")
        after = state.state_id
        if before != after or preview.state_id != before:
            raise RuntimeError("GoalState.preview() mutated Goal state")
        return preview

    def _commit_goal(
        self,
        preview: GoalPreview,
        result_ids: tuple[str, ...],
    ) -> Any:
        state = self.__goal_state
        if state is None:
            raise RuntimeError("Goal commit requires a method-owned GoalState")
        if not result_ids:
            raise ValueError("GoalState.commit() requires credited result identities")
        if state.state_id != preview.state_id:
            raise RuntimeError("Goal state changed between preview and commit")
        return state.commit(preview, result_ids)

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
