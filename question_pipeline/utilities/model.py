"""The pipeline's single LLM boundary, tiering, and prompt records."""

from __future__ import annotations


# ============================================================================
# prompt_log.py
# ============================================================================

import hashlib
import json
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

PROMPT_LOG_VERSION = "prompt_log_v2"


@dataclass
class PromptScope:
    """Where prompt records go, and which Episode owns them."""

    directory: Path
    episode_id: str
    episode_path: tuple[tuple[str, str], ...] = ()
    prompt_arm: Mapping[str, Any] | None = None
    sequence: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)


_ACTIVE: ContextVar[Optional[PromptScope]] = ContextVar(
    "question_pipeline_prompt_scope", default=None
)


def _caller_site(depth: int = 3) -> str:
    """`module.function` of the code that called `ask_json`.

    Derived from the stack rather than passed in, so a call site cannot forget
    to identify itself and a new one is attributed the day it is added. An
    explicit `call_site` argument overrides this when a caller wants a stable
    name that survives refactoring.
    """

    try:
        frame = sys._getframe(depth)
    except (ValueError, AttributeError):
        return "unknown"
    module = frame.f_globals.get("__name__", "unknown")
    return f"{module}.{frame.f_code.co_name}"


@contextmanager
def prompt_scope(
    directory: Path | str,
    *,
    episode_id: str,
    episode_path: tuple[tuple[str, str], ...] = (),
    prompt_arm: Mapping[str, Any] | None = None,
) -> Iterator[PromptScope]:
    """Record every prompt sent inside this block into ``directory``."""

    scope = PromptScope(
        directory=Path(directory),
        episode_id=str(episode_id),
        episode_path=tuple((str(grain), str(key)) for grain, key in episode_path),
        prompt_arm=dict(prompt_arm) if prompt_arm else None,
    )
    token = _ACTIVE.set(scope)
    try:
        yield scope
    finally:
        _ACTIVE.reset(token)
        _write_manifest(scope)


def open_scope(
    directory: Path | str,
    *,
    episode_id: str,
    episode_path: tuple[tuple[str, str], ...] = (),
    prompt_arm: Mapping[str, Any] | None = None,
) -> Any:
    """Open a scope without a `with` block, returning a token to close it.

    This lower-level form exists for callers whose Episode lifecycle already
    owns the surrounding control flow. `close_scope` writes the manifest.
    """

    scope = PromptScope(
        directory=Path(directory),
        episode_id=str(episode_id),
        episode_path=tuple((str(grain), str(key)) for grain, key in episode_path),
        prompt_arm=dict(prompt_arm) if prompt_arm else None,
    )
    return _ACTIVE.set(scope)


def close_scope(token: Any) -> None:
    """Write the manifest for the open scope and restore the previous one."""

    scope = _ACTIVE.get()
    if scope is not None:
        _write_manifest(scope)
    if token is not None:
        _ACTIVE.reset(token)


def active_scope() -> Optional[PromptScope]:
    return _ACTIVE.get()


def record_prompt(
    prompt: str,
    system_prompt: str | None,
    *,
    call_site: str = "",
    attempt: int = 0,
    tier: str = "",
) -> Optional[dict[str, Any]]:
    """Write one prompt exactly as sent. Returns the manifest entry, or None.

    ``attempt`` distinguishes a retry from the first call, because the retry
    prompt is DIFFERENT TEXT -- `ask_json` appends a re-ask nudge -- and
    recording only the first would misattribute what the model actually
    answered.

    Returns None when no scope is open. That is the honest outcome for a call
    made outside a recorded block, and the manifest's `recorded_calls` lets a
    reader see how many there were rather than assuming the log is complete.
    """

    scope = _ACTIVE.get()
    if scope is None:
        return None

    scope.sequence += 1
    site = call_site or _caller_site()
    safe_site = "".join(c if c.isalnum() or c in "._-" else "_" for c in site)
    stem = f"{scope.sequence:04d}_{safe_site}"
    if attempt:
        stem = f"{stem}_retry{attempt}"

    payload = {
        "prompt_log_version": PROMPT_LOG_VERSION,
        "sequence": scope.sequence,
        "episode_id": scope.episode_id,
        "episode_path": [list(segment) for segment in scope.episode_path],
        "call_site": site,
        "attempt": attempt,
        "tier": tier,
        "prompt_arm": scope.prompt_arm,
        # As sent. Never sliced.
        "prompt": prompt,
        "system_prompt": system_prompt,
    }
    directory = scope.directory
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    entry = {
        "sequence": scope.sequence,
        "episode_id": scope.episode_id,
        "episode_path": [list(segment) for segment in scope.episode_path],
        "call_site": site,
        "attempt": attempt,
        "tier": tier,
        "prompt_arm": scope.prompt_arm,
        "path": str(path),
        # Length and digest of the text as sent, so a reader can confirm the
        # file holds the whole prompt rather than trusting that it does.
        "prompt_chars": len(prompt or ""),
        "system_prompt_chars": len(system_prompt or ""),
        "prompt_sha256": hashlib.sha256((prompt or "").encode("utf-8")).hexdigest(),
        "system_prompt_sha256": hashlib.sha256(
            (system_prompt or "").encode("utf-8")
        ).hexdigest(),
    }
    scope.records.append(entry)
    return entry


def _write_manifest(scope: PromptScope) -> None:
    if not scope.records:
        return
    scope.directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "prompt_log_version": PROMPT_LOG_VERSION,
        "episode_id": scope.episode_id,
        "episode_path": [list(segment) for segment in scope.episode_path],
        "recorded_calls": len(scope.records),
        "total_prompt_chars": sum(r["prompt_chars"] for r in scope.records),
        "storage": "one file per provider call; prompts recorded in full",
        "records": scope.records,
    }
    (scope.directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )


# ============================================================================
# llm_utils.py
# ============================================================================

import functools
import sys
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nano_graphrag._utils import extract_first_complete_json

from question_pipeline.utilities.acquisition import CostErrorClass, classify_error, record_error_class, record_llm_call, record_retry


class LLMJSONError(RuntimeError):
    """Raised when the model never returns parseable JSON."""


class ModelTier(str, Enum):
    """The class of model a call site's work needs.

    Chosen per call site by experiment, not per call by a heuristic. `FAST` is
    only ever a call site whose 0M equivalence result cleared its registered
    threshold with its sensitivity control discriminating.
    """

    REASONING = "reasoning"
    FAST = "fast"


#: Default model for `ModelTier.FAST`. Overridable through
#: `PipelineConfig.fast_model` / `--fast-model`.
DEFAULT_FAST_MODEL = "gpt-5.4-mini"


@dataclass(frozen=True)
class TierPolicy:
    """Which concrete model serves each tier, for one pipeline run."""

    reasoning_model: str
    fast_model: str = DEFAULT_FAST_MODEL

    def model_for(self, tier: ModelTier) -> str:
        if tier is ModelTier.FAST and self.fast_model:
            return self.fast_model
        return self.reasoning_model

    def to_dict(self) -> dict[str, str]:
        return {
            ModelTier.REASONING.value: self.reasoning_model,
            ModelTier.FAST.value: self.fast_model or self.reasoning_model,
        }


def attach_tier_policy(llm: Any, policy: TierPolicy) -> Any:
    """Declare the tier→model mapping this client should serve."""
    llm.tier_policy = policy
    return llm


def for_tier(llm: Any, tier: ModelTier) -> Any:
    """Return the client that serves `tier`.

    Clones the caller's client rather than building a new one, so credentials,
    transport and any wrapper around it — the experiment harness's recorder, for
    one — are carried across instead of bypassed. Clones are memoized on the
    client, because a fresh HTTP client per call would churn connections.
    """
    policy = getattr(llm, "tier_policy", None)
    if policy is None or tier is ModelTier.REASONING:
        return llm
    target = policy.model_for(tier)
    if not target or target == getattr(llm, "model", ""):
        return llm
    clone = getattr(llm, "clone", None)
    if clone is None:
        return llm
    cache = getattr(llm, "_tier_clients", None)
    if cache is None:
        cache = {}
        try:
            llm._tier_clients = cache
        except Exception:  # noqa: BLE001 - a client that refuses attributes still works
            return clone(model=target)
    if target not in cache:
        served = attach_tier_policy(clone(model=target), policy)
        # A tier clone keeps its own `usage` accumulator, so a clone that is not
        # instrumented is spend that no per-call event ever reports. Instrument
        # it iff the client it was cloned from was.
        if is_instrumented(llm):
            instrument_client(served)
        cache[target] = served
    return cache[target]


# --------------------------------------------------------------------------- #
# Cost recording at the provider boundary (Phase 1B)
# --------------------------------------------------------------------------- #

#: `id(usage_dict) -> (strong ref to the dict, last claimed totals)`.
#:
#: The claim pointer belongs to the object that owns the `usage` accumulator,
#: not to whichever wrapper is holding it, so that two wrappers around one
#: client cannot each claim the same tokens. The strong reference keeps the
#: dict alive, which keeps its `id` from being reused by a later object.
_USAGE_CLAIMS: dict[int, tuple[Any, tuple[int, int, int]]] = {}
_USAGE_CLAIM_LOCK = threading.Lock()


def _usage_totals(usage: Any) -> tuple[int, int, int]:
    if not isinstance(usage, dict):
        return (0, 0, 0)
    return (
        int(usage.get("prompt_tokens", 0) or 0),
        int(usage.get("completion_tokens", 0) or 0),
        int(usage.get("calls", 0) or 0),
    )


def _claim_usage(llm: Any) -> tuple[int, int, int]:
    """Take the provider-reported usage that has appeared since the last claim.

    Deltas rather than absolutes, and one pointer per accumulator, so the sum of
    every claim equals the client's own total: nothing is counted twice and
    nothing is dropped. Under concurrency the split between two in-flight calls
    on one client is approximate — whichever finishes first claims what has
    landed — but the total for the action they both belong to is exact, and the
    action is the unit this phase records.
    """
    usage = getattr(llm, "usage", None)
    if not isinstance(usage, dict):
        return (0, 0, 0)
    current = _usage_totals(usage)
    with _USAGE_CLAIM_LOCK:
        _, previous = _USAGE_CLAIMS.get(id(usage), (usage, (0, 0, 0)))
        _USAGE_CLAIMS[id(usage)] = (usage, current)
    return (
        current[0] - previous[0],
        current[1] - previous[1],
        current[2] - previous[2],
    )


def _innermost_client(llm: Any) -> Any:
    """The deepest object that actually talks to the provider.

    Recording must sit at that boundary rather than on an outer wrapper: a
    client's synchronous `call()` re-enters *its own* `call_async`, so a wrapper
    installed one level out never sees it. GASL's `PROCESS` and
    `search_refinement_agent` both take that path.
    """
    seen: set[int] = set()
    current = llm
    while True:
        inner = getattr(current, "_inner", None) or getattr(current, "inner", None)
        if inner is None or id(inner) in seen or not hasattr(inner, "call_async"):
            return current
        seen.add(id(inner))
        current = inner


def instrument_client(llm: Any) -> Any:
    """Record every model call this client serves, as it serves it.

    Purely additive: the wrapper forwards arguments untouched, returns the
    provider's answer unchanged, and re-raises without substitution. It records
    the model the call was **served** by, read off the client at call time —
    `for_tier` returns the caller's own client when it has no `clone`, so what
    was configured and what served can differ, and only the second is a cost.
    """
    if llm is None:
        return llm
    target = _innermost_client(llm)
    if getattr(target, "_cost_instrumented", False):
        return llm
    inner_async = getattr(target, "call_async", None)
    if inner_async is None or not callable(inner_async):
        return llm

    @functools.wraps(inner_async)
    async def call_async(*args: Any, **kwargs: Any) -> Any:
        served = str(getattr(target, "model", "") or "")
        try:
            result = await inner_async(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - classified and re-raised
            prompt_tokens, completion_tokens, calls = _claim_usage(target)
            record_llm_call(
                model=served,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                calls=max(calls, 1),
                error_class=classify_error(exc),
            )
            raise
        prompt_tokens, completion_tokens, calls = _claim_usage(target)
        record_llm_call(
            model=served,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            calls=max(calls, 1),
        )
        return result

    try:
        target.call_async = call_async
        target._cost_instrumented = True
    except Exception:  # noqa: BLE001 - a client that refuses attributes still works
        return llm
    return llm


def is_instrumented(llm: Any) -> bool:
    return bool(getattr(_innermost_client(llm), "_cost_instrumented", False))


def describe_tiers(llm: Any) -> dict[str, Any]:
    """The per-call-site model configuration a run actually executed on.

    Written into the run's `final_answer.json`, because a run's costs are
    uninterpretable without it.
    """
    policy = getattr(llm, "tier_policy", None)
    resolved = policy.to_dict() if policy is not None else {}
    return {
        "tier_models": resolved,
        "base_model": getattr(llm, "model", ""),
        "call_sites": {
            site: tier.value for site, tier in sorted(CALL_SITE_TIERS.items())
        },
        "evidence": "experiments/log/0M-<site>.md",
    }


async def _call_llm(llm, prompt: str, *, system_prompt: str | None = None) -> str:
    try:
        return await llm.call_async(prompt, system_prompt=system_prompt)
    except TypeError as exc:
        if system_prompt is None or "system_prompt" not in str(exc):
            raise
        record_retry()
        return await llm.call_async(
            f"SYSTEM:\n{system_prompt}\n\nUSER:\n{prompt}"
        )


async def ask_text(
    llm,
    prompt: str,
    *,
    system_prompt: str | None = None,
    tier: ModelTier = ModelTier.REASONING,
) -> str:
    """Call the LLM asynchronously and return the raw string response."""
    return await _call_llm(for_tier(llm, tier), prompt, system_prompt=system_prompt)


async def ask_json(
    llm,
    prompt: str,
    *,
    system_prompt: str | None = None,
    retries: int = 2,
    tier: ModelTier = ModelTier.REASONING,
    call_site: str = "",
) -> Any:
    """Call the LLM and parse a JSON object/array from its response.

    Reuses nano_graphrag's tolerant extractor (handles ```json fences and
    surrounding prose). On a parse failure it re-asks with an explicit
    "valid JSON only" nudge before giving up.

    `tier` is the call site's declared model class. It defaults to
    `REASONING`, so a call site that says nothing keeps the model the pipeline
    has always used.

    THIS IS THE PACKAGE'S ONLY PROVIDER BOUNDARY, so it is where prompts are
    recorded. Both arguments are captured, and each retry is recorded
    separately because the re-ask prompt is different text from the first --
    recording only the first would attribute the model's answer to a prompt it
    did not receive. `call_site` overrides the stack-derived name when a caller
    wants one that survives refactoring.
    """
    client = for_tier(llm, tier)
    last_raw = ""
    current_prompt = prompt
    for attempt in range(retries + 1):
        if attempt:
            # A re-ask after an unparseable reply is a retry that was paid for.
            record_retry()
        record_prompt(
            current_prompt,
            system_prompt,
            call_site=call_site or _caller_site(2),
            attempt=attempt,
            tier=getattr(tier, "value", str(tier)),
        )
        last_raw = await _call_llm(client, current_prompt, system_prompt=system_prompt)
        parsed = extract_first_complete_json(last_raw)
        if isinstance(parsed, (dict, list)):
            return parsed
        current_prompt = (
            prompt
            + "\n\nIMPORTANT: Your previous reply could not be parsed as JSON. "
            "Reply with a single valid JSON value and nothing else."
        )
    record_error_class(CostErrorClass.PARSE_ERROR.value)
    raise LLMJSONError(
        f"Model did not return parseable JSON after {retries + 1} attempts. "
        f"Last response started: {last_raw[:200]!r}"
    )


#: The per-call-site tier table, one entry per call site 0M tested. Each
#: consumer module registers its own on import, so the table cannot drift from
#: the constants the call sites actually pass. A call site absent from this
#: table is untested and therefore `REASONING`.
CALL_SITE_TIERS: dict[str, ModelTier] = {}


def register_call_site_tier(site_id: str, tier: ModelTier) -> ModelTier:
    """Declare a call site's decided tier and return it, for use as a default.

    Written as `_TIER = register_call_site_tier("progress-judge", ModelTier.X)`
    so the declaration and the value the call site passes are the same object.
    """
    CALL_SITE_TIERS[site_id] = tier
    return tier


# ============================================================================
# windowing.py
# ============================================================================

import json
from typing import Any, Iterable, Sequence


def measured_size(item: Any) -> int:
    """Serialized size of one item, in the units budgets are denominated in."""

    return len(json.dumps(item, default=str))


def window_items(
    items: Sequence[Any] | Iterable[Any],
    *,
    budget: int,
) -> list[list[Any]]:
    """Group ``items`` into windows that each fit ``budget`` where possible.

    Grouping is by measured serialized size rather than by a count, so a list
    of unusually large items produces more windows instead of producing
    oversized calls. A count-based grouping composed with a size-based budget
    is how a losslessly-windowed payload ends up clipped one layer up: the
    group is chosen without reference to the quantity the budget constrains.

    Returns ``[]`` for no items -- never ``[[]]`` -- so ``window_count`` is
    zero when there is nothing to send rather than one empty call.
    """

    budget = max(1, int(budget or 1))
    windows: list[list[Any]] = []
    current: list[Any] = []
    size = 0

    for item in items or []:
        length = measured_size(item)
        if current and size + length > budget:
            windows.append(current)
            current, size = [], 0
        current.append(item)
        size += length

    if current:
        windows.append(current)
    return windows


def window_text(text: str, *, budget: int) -> list[str]:
    """Split ``text`` into contiguous windows whose concatenation is ``text``.

    The list counterpart is ``window_items``; this is the same invariant for a
    payload that is one long string rather than a sequence of records, and it
    lives here so there is one implementation of that invariant rather than one
    per caller.

    The split prefers a line boundary inside the budget and falls back to the
    budget itself, so text with no newlines still windows rather than being
    cut. Returns ``[]`` for empty text -- never ``[""]`` -- so a window count of
    zero means there was nothing to send.
    """

    budget = max(1, int(budget or 1))
    if not text:
        return []

    windows: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + budget)
        if end < length:
            boundary = text.rfind("\n", start + 1, end)
            if boundary > start:
                end = boundary + 1
        windows.append(text[start:end])
        start = end
    return windows


def window_stamps(index: int, count: int) -> dict[str, int]:
    """The disclosure a windowed call carries.

    Honest by construction rather than by assertion: it states which slice this
    is and how many there are, both of which are facts about the split. It
    makes no claim about what was removed, because nothing was.
    """

    return {"window_index": index, "window_count": count}
