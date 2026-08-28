"""Walking run roots, deterministically, with one named skip per omission.

Roots arrive as an **argument**.  Nothing in this package knows where
``question_runs/`` is, which is what lets a test build three fake run
directories under ``tmp_path`` and exercise the whole ingest path with no
pipeline, no LLM, and no real run.

Order is total and deterministic: absolute path, sorted.  A caller re-running
enumeration over an unchanged tree gets the identical sequence, so a rebuild is
reproducible rather than merely repeatable.

Every directory that is *not* enumerated produces exactly one
:class:`~run_store.result.SkipRecord` carrying its **own** ``reason_code``.
Silently dropping an unreadable run would make "this corpus has no such run"
and "this run could not be opened" the same observable, which is the defect the
whole result contract exists to prevent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .identity import RunRef, default_corpus_id
from .result import ReasonCode, SkipRecord

__all__ = ["RunEnumeration", "enumerate_runs"]


@dataclass(frozen=True)
class RunEnumeration:
    """Runs that could be enumerated, and one skip per run that could not."""

    runs: tuple[RunRef, ...]
    skipped: tuple[SkipRecord, ...]

    @property
    def runs_enumerated(self) -> int:
        return len(self.runs)

    @property
    def runs_skipped(self) -> int:
        return len(self.skipped)


def enumerate_runs(roots: Sequence[str | Path] | Iterable[str | Path]) -> RunEnumeration:
    """Enumerate every immediate child directory of every root in ``roots``.

    A root that does not exist, is not a directory, or cannot be listed yields a
    skip and does not abort the walk: one broken root must not make the other
    roots unreadable.
    """

    runs: list[RunRef] = []
    skipped: list[SkipRecord] = []
    seen_dirs: set[str] = set()

    for raw_root in roots:
        root = Path(raw_root).resolve()
        if not root.exists():
            skipped.append(
                SkipRecord(
                    path=str(root),
                    reason_code=ReasonCode.ROOT_MISSING,
                    reason="run root does not exist",
                )
            )
            continue
        if not root.is_dir():
            skipped.append(
                SkipRecord(
                    path=str(root),
                    reason_code=ReasonCode.ROOT_NOT_A_DIRECTORY,
                    reason="run root exists but is not a directory",
                )
            )
            continue
        try:
            entries = sorted(os.listdir(root))
        except OSError as error:
            skipped.append(
                SkipRecord(
                    path=str(root),
                    reason_code=ReasonCode.ROOT_UNENUMERABLE,
                    reason=f"run root could not be listed: {error.__class__.__name__}",
                )
            )
            continue

        for entry in entries:
            candidate = root / entry
            try:
                is_dir = candidate.is_dir()
            except OSError as error:
                skipped.append(
                    SkipRecord(
                        path=str(candidate),
                        reason_code=ReasonCode.RUN_UNENUMERABLE,
                        reason=f"run directory could not be stat'd: {error.__class__.__name__}",
                    )
                )
                continue
            if not is_dir:
                skipped.append(
                    SkipRecord(
                        path=str(candidate),
                        reason_code=ReasonCode.RUN_NOT_A_DIRECTORY,
                        reason="entry under a run root is not a directory",
                    )
                )
                continue
            absolute = str(candidate)
            if absolute in seen_dirs:
                continue
            seen_dirs.add(absolute)
            runs.append(
                RunRef(
                    run_dir=absolute,
                    run_name=entry,
                    corpus_id=default_corpus_id(entry),
                )
            )

    runs.sort(key=_run_sort_key)
    skipped.sort(key=_skip_sort_key)
    return RunEnumeration(runs=tuple(runs), skipped=tuple(skipped))


def _run_sort_key(run: RunRef) -> tuple[str, str]:
    return (run.run_dir, run.run_name)


def _skip_sort_key(skip: SkipRecord) -> tuple[str, str]:
    return (skip.path, skip.reason_code.value)
