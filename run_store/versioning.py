"""Schema version, forward migrations, and refusal to read what it cannot migrate.

A store written by a newer build than the one reading it is **unreadable**, not
"empty" and not "probably fine".  The whole point of the three-status read
contract is that a store which cannot answer says so; a version it cannot
migrate is exactly that case.

Migrations are forward-only and registered one step at a time: ``n -> n + 1``.
There is no downgrade path, because a downgrade discards information the newer
schema was added to carry, and discarding it silently is the failure mode this
package refuses everywhere else.

The registry is passed **explicitly** to every function here.  It is never a
defaulted parameter: a parameter with a fallback value is a parameter that
changes what a call returns without appearing at the call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .result import MigrationStatus, ReasonCode

__all__ = [
    "SCHEMA_VERSION",
    "MigrationRegistry",
    "MigrationOutcome",
    "MIGRATIONS",
    "migrate_payload",
    "readability",
]


#: The schema version this build writes.
SCHEMA_VERSION = 1


#: One forward step: ``n -> n + 1``, over a payload mapping.
MigrationStep = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class MigrationRegistry:
    """Forward migration steps, keyed by the version each step upgrades *from*."""

    steps: Mapping[int, MigrationStep]

    def has_path(self, from_version: int, to_version: int) -> bool:
        if from_version > to_version:
            return False
        version = from_version
        while version < to_version:
            if version not in self.steps:
                return False
            version = version + 1
        return True


#: No migration steps exist yet: version 1 is the first schema this build wrote.
#: A future schema change adds its step here, and the empty registry is what
#: makes "cannot migrate" the honest answer today rather than a guess.
MIGRATIONS = MigrationRegistry(steps={})


@dataclass(frozen=True)
class MigrationOutcome:
    """Whether a payload reached ``SCHEMA_VERSION``, and what it looks like if so.

    ``payload`` is meaningful only when ``status`` is ``CURRENT`` or
    ``MIGRATED``.  On ``UNMIGRATABLE`` the caller must surface ``UNREADABLE``,
    never fall back to the un-migrated payload.
    """

    status: MigrationStatus
    payload: Mapping[str, Any]
    reason_code: ReasonCode
    reason: str
    from_version: int
    to_version: int


def migrate_payload(
    registry: MigrationRegistry,
    payload: Mapping[str, Any],
    from_version: int,
    to_version: int,
) -> MigrationOutcome:
    """Bring ``payload`` forward from ``from_version`` to ``to_version``."""

    if from_version > to_version:
        return MigrationOutcome(
            status=MigrationStatus.UNMIGRATABLE,
            payload=payload,
            reason_code=ReasonCode.VERSION_FROM_THE_FUTURE,
            reason=(
                f"stored schema version {from_version} is newer than this build's "
                f"{to_version}; refusing to read rather than guessing at fields "
                f"this build does not know about"
            ),
            from_version=from_version,
            to_version=to_version,
        )
    if from_version == to_version:
        return MigrationOutcome(
            status=MigrationStatus.CURRENT,
            payload=payload,
            reason_code=ReasonCode.ALREADY_CURRENT,
            reason="stored schema version matches this build",
            from_version=from_version,
            to_version=to_version,
        )
    if not registry.has_path(from_version, to_version):
        return MigrationOutcome(
            status=MigrationStatus.UNMIGRATABLE,
            payload=payload,
            reason_code=ReasonCode.NO_MIGRATION_REGISTERED,
            reason=(
                f"no forward migration chain from schema version {from_version} "
                f"to {to_version} is registered"
            ),
            from_version=from_version,
            to_version=to_version,
        )

    current: Mapping[str, Any] = payload
    version = from_version
    while version < to_version:
        step = registry.steps[version]
        current = step(current)
        version = version + 1
    return MigrationOutcome(
        status=MigrationStatus.MIGRATED,
        payload=current,
        reason_code=ReasonCode.MIGRATION_APPLIED,
        reason=f"payload migrated from schema version {from_version} to {to_version}",
        from_version=from_version,
        to_version=to_version,
    )


def readability(
    registry: MigrationRegistry, stored_version: int, build_version: int
) -> MigrationOutcome:
    """Whether a store at ``stored_version`` can be read by ``build_version``.

    Payload-free: this answers the question for the store as a whole, before any
    row is fetched, so a read can return ``UNREADABLE`` without touching data it
    cannot interpret.
    """

    return migrate_payload(registry, {}, stored_version, build_version)
