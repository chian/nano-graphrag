"""Every prompt this package sends, recorded as sent.

WHY THE BOUNDARY AND NOT THE CONSTRUCTION SITES. A prompt-mutation build
attributes an outcome to a prompt, so a prompt it cannot reconstruct after the
run is an outcome it cannot explain. Recording where prompts are *built* fails
two ways: a mutated prompt is generated at runtime and exists in no source file
at all, and a construction-site recorder drifts the moment someone edits the
string without editing the recorder beside it. `llm_utils.ask_json` is the sole
provider boundary in this package, so recording there captures what was
actually sent, including prompts no construction site could have predicted.

BOTH ARGUMENTS, ALWAYS. `system_prompt` is a separate parameter that a check
over the prompt body never sees -- earlier in this campaign a retired
instruction survived a cleanup for exactly that reason, sitting in the system
prompt while the user prompt said the opposite. Recording one and not the other
would rebuild that blind spot in the artifact.

NO TRUNCATION. Prompts are large and there are many per Episode, so the volume is
real. It is answered with one file per call rather than with a slice: a clipped
prompt record is worse than no record, because it looks complete and a reader
comparing two arms would be comparing two prefixes. The manifest carries a
byte length and a digest per record so a reader can verify a file is whole.
"""

from __future__ import annotations

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
