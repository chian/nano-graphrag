"""Small helpers for calling an LLM and getting structured JSON back.

This is the package's provider boundary, so it is also where model tiering
lives. A call site does not name a model; it declares the `ModelTier` its work
needs, as a typed default in its own module. Which concrete model serves a tier
is configuration, resolved here.

The tier defaults are the 0M equivalence campaign's results. Each call site's
number and the sensitivity control that licenses reading it are in
`experiments/log/0M-<site>.md`; `CALL_SITE_TIERS` below is the table those logs
decided, and is the record a later phase reads to know which model served which
call.
"""

from __future__ import annotations

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

from .prompt_log import _caller_site, record_prompt
from .costs import CostErrorClass, classify_error, record_error_class, record_llm_call, record_retry


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
