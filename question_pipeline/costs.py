"""Per-action cost accounting (Phase 1B).

What this module is for: a reward with no cost term cannot prefer two
criterion-yielding LLM calls over twenty broad searches returning duplicates.
Both look like progress. So every observation the pipeline writes — search,
source, GASL, best guess — carries what it cost to produce.

Three properties this file exists to hold:

* **Typed zero, never absent.** :class:`CostRecord` has a value for every field
  on every record. A missing field and a zero-cost action must be
  distinguishable downstream, and absence forces every consumer to guess.
* **Per action, never aggregated.** A record covers one action. Summing across
  actions is the consumer's business, and 3A's attribution rules say which sums
  are legitimate.
* **Observation only.** Nothing here branches. Recording is inert in behaviour
  by construction: a meter accumulates numbers and a scope writes one record.

The spend basis is the **per-call event**, not a client's lifetime accumulator.
``ArgoBridgeLLM.usage`` is per instance and ``llm_utils.for_tier`` memoizes a
separate client per model, so a tier clone's spend accumulates on the clone;
anything reading one client's accumulator as "the run's spend" silently misses
every call a clone served. :func:`record_llm_call` is fed by the instrumented
client at the moment of the call, from whichever client actually served it.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Iterator, Optional

#: Folded into every record. A change to what a field means is a version bump,
#: so a later phase joining across runs sees incomparability as a mismatch
#: rather than as a comparable number.
COST_ACCOUNTING_VERSION = "cost_accounting_v2"


class CostErrorClass(str, Enum):
    """Class labels from the raising subsystem, not prose for a human."""

    NONE = ""
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"
    PROVIDER_REFUSED = "provider_refused"
    PROVIDER_ERROR = "provider_error"
    SEARCH_FAILED = "search_failed"
    OTHER = "other"


class ObservationKind(str, Enum):
    """The action a cost record is about."""

    SEARCH = "search"
    PROBE_SEARCH = "probe_search"
    SOURCE = "source"
    GASL = "gasl"
    BEST_GUESS = "best_guess"
    #: One pull of the acquisition composition's run-grain source -- the switch
    #: edge (phase 4E-c). It wraps the whole pull rather than only the model
    #: sample, because a pull that returns a declared family still reaches the
    #: billed arm planner; a narrower scope would orphan that spend.
    STRATEGY_PROPOSAL = "strategy_proposal"
    RUN_RESIDUAL = "run_residual"
    ORPHAN = "orphan"


_TIMEOUT_MARKERS = ("timeout", "timed out")
_REFUSAL_MARKERS = (
    "out of budget",
    "insufficient credit",
    "payment required",
    "quota",
    "402",
)


def classify_error(exc: BaseException) -> str:
    """Map an exception onto a cost error class.

    Deliberately coarse. The record carries a class, and the full message stays
    where the raising subsystem already put it.
    """
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "jsonerror" in name or ("json" in name and "decode" in name):
        return CostErrorClass.PARSE_ERROR.value
    if any(marker in message for marker in _REFUSAL_MARKERS):
        return CostErrorClass.PROVIDER_REFUSED.value
    if "timeout" in name or any(marker in message for marker in _TIMEOUT_MARKERS):
        return CostErrorClass.TIMEOUT.value
    if "llmerror" in name or "apierror" in name or "statuserror" in name:
        return CostErrorClass.PROVIDER_ERROR.value
    return CostErrorClass.OTHER.value


@dataclass(frozen=True)
class CostRecord:
    """What one action cost. Every field defaults to a typed zero.

    ``provider_calls`` and ``llm_calls`` are counted separately and never summed
    here: a search provider round trip and a model call are different money and
    a consumer that wants one number should say which.
    """

    observation_kind: str = ""
    observation_id: str = ""
    episode_id: str = ""
    episode_path: tuple[tuple[str, str], ...] = ()
    nested_in: str = ""

    # search / fetch provider
    provider_calls: int = 0
    provider_credits: float = 0.0
    provider_credits_available: bool = False
    returned_hits: int = 0
    fetched_bytes: int = 0

    # model provider
    llm_calls: int = 0
    llm_model: str = ""
    llm_models: tuple[str, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0

    # time and failure
    wall_ms: float = 0.0
    error_class: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0

    version: str = COST_ACCOUNTING_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["llm_models"] = list(self.llm_models)
        payload["episode_path"] = [list(segment) for segment in self.episode_path]
        return payload


#: The typed-zero record, serialized. Used as the default for a cost field on an
#: observation that never opened a meter, so the field is present and zero
#: rather than absent.
def zero_cost(**overrides: Any) -> dict[str, Any]:
    return CostRecord(**overrides).to_dict()


COST_FIELD_NAMES: tuple[str, ...] = tuple(CostRecord().to_dict())


class CostMeter:
    """Accumulates the cost of one action.

    Mutable by design and shared across the coroutines and threads that make up
    a single action: extraction fans out over chunks, GASL runs off the event
    loop, and all of it is one action's spend.
    """

    def __init__(
        self,
        kind: str,
        *,
        observation_id: str = "",
        episode_id: str = "",
        episode_path: tuple[tuple[str, str], ...] = (),
        nested_in: str = "",
    ):
        self.kind = str(kind)
        self.observation_id = str(observation_id)
        self.episode_id = str(episode_id)
        self.episode_path = tuple(
            (str(grain), str(key)) for grain, key in episode_path
        )
        self.nested_in = str(nested_in)
        self._lock = threading.Lock()
        self.provider_calls = 0
        self.provider_credits = 0.0
        self.provider_credits_available = False
        self.returned_hits = 0
        self.fetched_bytes = 0
        self.llm_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.retries = 0
        self.error_class = ""
        self._models: list[str] = []
        self._model_completion: dict[str, int] = {}
        self.started_at = 0.0
        self.ended_at = 0.0
        self._started_perf = 0.0
        self.wall_ms = 0.0

    # -- accumulation --------------------------------------------------- #

    def add_llm_call(
        self,
        *,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        calls: int = 1,
        retries: int = 0,
        error_class: str = "",
    ) -> None:
        with self._lock:
            self.llm_calls += int(calls)
            self.prompt_tokens += int(prompt_tokens or 0)
            self.completion_tokens += int(completion_tokens or 0)
            self.retries += int(retries or 0)
            served = str(model or "")
            if served and served not in self._models:
                self._models.append(served)
            if served:
                self._model_completion[served] = (
                    self._model_completion.get(served, 0) + int(completion_tokens or 0)
                )
            if error_class and not self.error_class:
                self.error_class = str(error_class)

    def add_provider_call(
        self,
        *,
        returned_hits: int = 0,
        fetched_bytes: int = 0,
        credits: Optional[float] = None,
        calls: int = 1,
        error_class: str = "",
    ) -> None:
        with self._lock:
            self.provider_calls += int(calls)
            self.returned_hits += int(returned_hits or 0)
            self.fetched_bytes += int(fetched_bytes or 0)
            if credits is not None:
                self.provider_credits += float(credits)
                self.provider_credits_available = True
            if error_class and not self.error_class:
                self.error_class = str(error_class)

    def add_fetched_bytes(self, count: int) -> None:
        with self._lock:
            self.fetched_bytes += max(0, int(count or 0))

    def add_retry(self, count: int = 1) -> None:
        with self._lock:
            self.retries += int(count)

    def set_error_class(self, error_class: str) -> None:
        with self._lock:
            if error_class and not self.error_class:
                self.error_class = str(error_class)

    # -- lifecycle ------------------------------------------------------ #

    def start(self) -> "CostMeter":
        self.started_at = time.time()
        self._started_perf = time.perf_counter()
        return self

    def stop(self) -> "CostMeter":
        self.ended_at = time.time()
        if self._started_perf:
            self.wall_ms = (time.perf_counter() - self._started_perf) * 1000.0
        return self

    def snapshot(self) -> CostRecord:
        """The record as it stands. Safe to call before :meth:`stop`.

        ``llm_model`` is the model that served this action. When more than one
        did, it is the one that produced the most completion tokens, and
        ``llm_models`` lists every one of them in call order — so a mixed action
        is visible as mixed rather than collapsed onto whichever call was last.
        """
        dominant = ""
        if self._model_completion:
            dominant = max(
                sorted(self._model_completion),
                key=lambda name: self._model_completion[name],
            )
        elif len(self._models) == 1:
            dominant = self._models[0]
        return CostRecord(
            observation_kind=self.kind,
            observation_id=self.observation_id,
            episode_id=self.episode_id,
            episode_path=self.episode_path,
            nested_in=self.nested_in,
            provider_calls=self.provider_calls,
            provider_credits=self.provider_credits,
            provider_credits_available=self.provider_credits_available,
            returned_hits=self.returned_hits,
            fetched_bytes=self.fetched_bytes,
            llm_calls=self.llm_calls,
            llm_model=dominant,
            llm_models=tuple(self._models),
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            retries=self.retries,
            wall_ms=round(self.wall_ms, 3),
            error_class=self.error_class,
            started_at=self.started_at,
            ended_at=self.ended_at,
        )


_ACTIVE: ContextVar[Optional[CostMeter]] = ContextVar(
    "question_pipeline_cost_meter",
    default=None,
)

#: Calls made with no scope open at all — a direct call into a pipeline
#: internal from a driver, or a call site reached before ``run()``. Recorded so
#: that "not attributed" is visible as a number rather than as silence.
_ORPHAN = CostMeter(ObservationKind.ORPHAN.value)


def active_meter() -> Optional[CostMeter]:
    return _ACTIVE.get()


def orphan_meter() -> CostMeter:
    return _ORPHAN


def _target() -> CostMeter:
    meter = _ACTIVE.get()
    return meter if meter is not None else _ORPHAN


def record_llm_call(
    *,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    calls: int = 1,
    retries: int = 0,
    error_class: str = "",
) -> None:
    """Attribute one model call to whichever action is open."""
    _target().add_llm_call(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        calls=calls,
        retries=retries,
        error_class=error_class,
    )


def record_retry(count: int = 1) -> None:
    _target().add_retry(count)


def record_error_class(error_class: str) -> None:
    _target().set_error_class(error_class)


def record_fetched_bytes(count: int) -> None:
    _target().add_fetched_bytes(count)


CostSink = Callable[[CostRecord], None]


@contextmanager
def cost_scope(
    kind: str,
    *,
    observation_id: str = "",
    episode_id: str = "",
    episode_path: tuple[tuple[str, str], ...] = (),
    sink: Optional[CostSink] = None,
) -> Iterator[CostMeter]:
    """Open one action's meter, and hand the finished record to `sink`.

    Scopes do not nest their spend. When one opens inside another, the inner
    meter takes the calls and records ``nested_in``; the outer does not also
    count them. Every provider call is therefore in exactly one record, which
    is what makes a sum over records meaningful to a consumer that wants one.

    The record reaches `sink` whether the action succeeded or raised, and the
    exception propagates unchanged: this context manager never swallows and
    never substitutes a return value.
    """
    parent = _ACTIVE.get()
    meter = CostMeter(
        kind,
        observation_id=observation_id,
        episode_id=episode_id,
        episode_path=episode_path,
        nested_in=parent.kind if parent is not None else "",
    )
    token = _ACTIVE.set(meter)
    meter.start()
    try:
        yield meter
    except BaseException as exc:  # noqa: BLE001 - classified, re-raised untouched
        meter.set_error_class(classify_error(exc))
        raise
    finally:
        meter.stop()
        _ACTIVE.reset(token)
        if sink is not None:
            try:
                sink(meter.snapshot())
            except Exception:  # noqa: BLE001 - recording never breaks the run
                pass
