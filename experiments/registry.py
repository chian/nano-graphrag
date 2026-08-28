"""Prediction registration: make "no tuning to green" checkable.

An experiment is only evidence if its prediction was fixed before its result
was seen. Nothing about a written prediction proves that ordering, so this
module makes the ordering mechanical:

1. :func:`spec_fingerprint` hashes every parameter that can move a result.
2. :func:`register` stamps that fingerprint and a timestamp into the
   experiment's log file, and refuses to re-stamp a log whose fingerprint has
   changed -- editing a spec after registering is a hard error, not a warning.
3. :func:`assert_registered` is called by a runner *before* it does anything
   costly. A run against an unregistered or drifted spec does not start.

The failure this prevents is specific and was live in this build: adjust a
threshold, re-run, report the direction that came out. With the fingerprint in
the log, that shows up as a mismatch instead of as a result.

This module deliberately has no dependency on the pipeline, no provider call,
and no filesystem layout assumptions beyond the log path it is handed.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


__all__ = [
    "spec_fingerprint",
    "register",
    "assert_registered",
    "assert_registered_all",
    "package_hashes",
    "read_registration",
    "RegistrationError",
]

_MARKER_RE = re.compile(
    r"<!--\s*registered:\s*(?P<epoch>[0-9.]+)\s*-->.*?"
    r"<!--\s*spec-fingerprint:\s*(?P<fingerprint>[0-9a-f]{32})\s*-->",
    re.S,
)


class RegistrationError(RuntimeError):
    """Raised when a run is attempted against an unregistered or drifted spec."""


def spec_fingerprint(spec: Mapping[str, Any]) -> str:
    """Stable hash over a spec's parameters.

    Sorted keys and a canonical separator, so the fingerprint depends on the
    *values* rather than on dict ordering or formatting. Anything that can move
    a result belongs in ``spec``; anything left out is, by construction, not
    covered by the guarantee.
    """

    payload = json.dumps(
        dict(spec),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def read_registration(log_path: str | Path) -> dict[str, Any] | None:
    """Return the registration stamped in ``log_path``, or None if unstamped."""

    path = Path(log_path)
    if not path.exists():
        return None
    match = _MARKER_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        return None
    return {
        "registered_epoch": float(match.group("epoch")),
        "spec_fingerprint": match.group("fingerprint"),
    }


def register(
    log_path: str | Path,
    spec: Mapping[str, Any],
    *,
    experiment_id: str = "",
) -> dict[str, Any]:
    """Stamp ``spec``'s fingerprint into ``log_path``. Idempotent, never silent.

    Re-registering an unchanged spec is a no-op and returns the existing
    registration. Re-registering a *changed* spec raises: the honest move after
    changing a spec is a new experiment id with the old result retained, not a
    re-stamp of the old log.
    """

    path = Path(log_path)
    fingerprint = spec_fingerprint(spec)
    existing = read_registration(path)

    if existing is not None:
        if existing["spec_fingerprint"] != fingerprint:
            raise RegistrationError(
                f"{path} is registered at fingerprint "
                f"{existing['spec_fingerprint']} but the spec now hashes to "
                f"{fingerprint}. A spec that changed after registration is a "
                f"new experiment: give it a new id and retain the old result."
            )
        return existing

    # Round before stamping *and* returning, so what a caller receives is
    # exactly what `read_registration` will later parse back out. A returned
    # value that differs from the stamped one in the last decimal makes an
    # honest equality check fail.
    now = round(time.time(), 3)
    header = (
        f"<!-- registered: {now:.3f} -->\n"
        f"<!-- registered-iso: {datetime.fromtimestamp(now, timezone.utc).isoformat()} -->\n"
        f"<!-- spec-fingerprint: {fingerprint} -->\n"
    )
    if experiment_id:
        header = f"# {experiment_id}\n\n" + header

    path.parent.mkdir(parents=True, exist_ok=True)
    prior = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(header + ("\n" + prior if prior else ""), encoding="utf-8")
    return {"registered_epoch": now, "spec_fingerprint": fingerprint}


def assert_registered(log_path: str | Path, spec: Mapping[str, Any]) -> None:
    """Refuse to run unless ``spec`` matches what ``log_path`` registered.

    Call this before the first provider call, not after. A runner that checks
    afterwards is checking whether it *was* honest, which is not the same as
    being prevented from being dishonest.
    """

    existing = read_registration(log_path)
    if existing is None:
        raise RegistrationError(
            f"{log_path} carries no registration marker. Register the "
            f"prediction before running: the run is not evidence otherwise."
        )
    fingerprint = spec_fingerprint(spec)
    if existing["spec_fingerprint"] != fingerprint:
        raise RegistrationError(
            f"spec fingerprint {fingerprint} does not match the registered "
            f"{existing['spec_fingerprint']} in {log_path}. The spec changed "
            f"after registration; this run would not be evidence for the "
            f"prediction that was registered."
        )


def sha256_file(path: str | Path) -> str:
    """The hash of one file's bytes."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def package_hashes(prefix: str, root: str | Path) -> dict[str, str]:
    """Every ``.py`` under ``root``, keyed by path. A GLOB, NOT A LIST.

    The rule a spec's implementation map must satisfy is *the producers of every
    measured artifact* -- every file whose behaviour can change which rows exist
    in a measured artifact, or what identity is computed over them -- and not
    merely the files a phase touched. A hand-kept list re-acquires that defect
    on every refactor: a file added tomorrow is unguarded tomorrow, and the
    failure is silent because the spec still verifies.

    A glob over the packages that produce the artifacts is strictly a superset
    of that rule and cannot omit a producer by oversight. Per-file keys mean a
    mismatch names the drifted file rather than a directory. Its cost is that
    any edit anywhere in the package re-registers the spec, which for a phase
    that rewrites its own host module is the right trade: a pre-run
    re-registration is cheap, an unguarded producer is not -- and registering
    again *before* a run is not "changing a spec after registering", which is
    what :func:`register` refuses.
    """

    directory = Path(root)
    return {
        f"{prefix}:{path.relative_to(directory).as_posix()}": sha256_file(path)
        for path in sorted(directory.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def assert_registered_all(
    entries: Sequence[tuple[str | Path, Mapping[str, Any]]],
    *,
    observed: Mapping[str, Mapping[str, str]] | None = None,
) -> None:
    """Refuse to run unless EVERY spec riding this execution is registered.

    ``entries`` pairs each spec's log path with its spec. ``observed`` maps a
    log path to the implementation hashes recomputed *now*; when supplied, each
    spec's own ``implementation`` map must equal it, and the first mismatch
    raises naming the spec, the key, the registered value and the observed one.

    EVERY SPEC, NOT THE FIRST. 4C v2 and 4D v2 rode a launcher that guarded a
    third spec only: four of 4C's seven implementation hashes had drifted, and
    nothing would have checked either experiment. A launch would have produced a
    result its own registration did not describe, which is a number joined to
    the wrong code.

    :func:`assert_registered` is unchanged and keeps its callers; this adds the
    multi-spec loop and the per-key diagnosis each launcher was open-coding.
    """

    for log_path, spec in entries:
        assert_registered(log_path, spec)
        if observed is None:
            continue
        expected = dict((spec.get("implementation") or {}))
        actual = dict(observed.get(str(log_path)) or {})
        if not expected:
            raise RegistrationError(
                f"{log_path} registered no implementation map, so nothing "
                f"about the code that will run is guaranteed. A spec that "
                f"hashes no producer covers no producer."
            )
        for key in sorted(set(expected) | set(actual)):
            if expected.get(key) != actual.get(key):
                raise RegistrationError(
                    f"{log_path}: implementation key {key!r} is registered as "
                    f"{expected.get(key)!r} but observes {actual.get(key)!r}. "
                    f"The code changed after registration; this run would not "
                    f"be evidence for the prediction that was registered."
                )
