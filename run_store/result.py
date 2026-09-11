"""The typed result contract shared by every ``run_store`` entry point.

One result type serves both sides of the store.  Nothing here performs I/O,
imports a driver, or knows what a search outcome or a criteria snapshot is; it
is the vocabulary in which reads and writes report what happened.

Three read statuses, not two
----------------------------

``OK`` with ``records == ()`` is a **positive fact**: the store looked, and
there are none.  :class:`ReadExtent` carries the measured counts that prove it
looked.  ``NOT_STORED`` says the key this entry point is keyed by was never
written.  ``UNREADABLE`` says the store could not answer -- the file is not
initialized, the schema is a version this build cannot migrate, a stored row
will not parse, or a run root could not be enumerated.

"No signal" and "no problem" must never be the same observable.  The specimen
this contract exists to avoid is
``question_pipeline/pipeline.py::_resolve_source_text_from_corpus_roots``,
which returns ``None`` for "no root has this source", for "the root has it and
it is empty", and for "the read raised ``OSError``" alike -- and then caches
the miss, so the conflation is permanent.

``reason_code`` is the branchable half; ``reason`` is terminal
-------------------------------------------------------------

Consumers branch on :class:`ReasonCode`.  ``reason`` is a human diagnostic: it
is never parsed, never branched on, never concatenated into a prompt, and never
passed to a model.  The tree already has one live text-coupling chain
(``pipeline.py`` emits prose, ``goals.py`` branches on its wording,
``search.py`` concatenates it into the next query).  This contract is
deliberately not its successor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

__all__ = [
    "ReadStatus",
    "WriteStatus",
    "ReasonCode",
    "Presence",
    "SightingKind",
    "ProjectionScope",
    "StoredOrigin",
    "MigrationStatus",
    "SparseValue",
    "ReadExtent",
    "SkipRecord",
    "StoreRead",
    "WriteResult",
    "EMPTY_EXTENT",
    "ABSENT_VALUE",
    "sparse_present",
    "sparse_absent",
    "sparse_from_record",
]


class ReadStatus(Enum):
    """What a read was able to say.  Three states, never two."""

    OK = "ok"
    NOT_STORED = "not_stored"
    UNREADABLE = "unreadable"


class WriteStatus(Enum):
    """What a write did.  A conflict is never an overwrite and never a drop."""

    STORED = "stored"
    ALREADY_STORED = "already_stored"
    CONFLICT = "conflict"


class ReasonCode(Enum):
    """The branchable half of every result.

    Every member is a fact about the store's own machinery.  No member names a
    domain outcome, because a domain outcome belongs in a record, not in the
    envelope that says whether records could be produced.
    """

    # --- OK -------------------------------------------------------------
    MATCHED = "matched"
    NO_MATCHES = "no_matches"

    # --- NOT_STORED -----------------------------------------------------
    KEY_NEVER_WRITTEN = "key_never_written"
    STORE_HOLDS_NO_RUNS = "store_holds_no_runs"

    # --- UNREADABLE -----------------------------------------------------
    STORE_NOT_INITIALIZED = "store_not_initialized"
    SCHEMA_UNMIGRATABLE = "schema_unmigratable"
    ROW_CORRUPT = "row_corrupt"
    STORE_ERROR = "store_error"

    # --- writes ---------------------------------------------------------
    WRITE_NEW = "write_new"
    WRITE_IDENTICAL_PAYLOAD = "write_identical_payload"
    WRITE_DIGEST_MISMATCH = "write_digest_mismatch"

    # --- enumeration / ingest skips -------------------------------------
    ROOT_MISSING = "root_missing"
    ROOT_NOT_A_DIRECTORY = "root_not_a_directory"
    ROOT_UNENUMERABLE = "root_unenumerable"
    RUN_NOT_A_DIRECTORY = "run_not_a_directory"
    RUN_UNENUMERABLE = "run_unenumerable"
    RUN_OUTCOMES_MISSING = "run_outcomes_missing"
    RUN_OUTCOMES_UNREADABLE = "run_outcomes_unreadable"
    RECORD_UNPARSEABLE = "record_unparseable"

    # --- migration ------------------------------------------------------
    MIGRATION_APPLIED = "migration_applied"
    ALREADY_CURRENT = "already_current"
    NO_MIGRATION_REGISTERED = "no_migration_registered"
    VERSION_FROM_THE_FUTURE = "version_from_the_future"


class Presence(Enum):
    """Whether a sparse source field was there at all.

    A field that is absent is recorded as ``ABSENT``, never as ``0``, ``""`` or
    ``()``.  This is the failure contract one level down: the corpus already
    models it correctly -- ``cost`` records carry
    ``provider_credits_available: false`` rather than reporting ``0.0`` as if
    it were measured.
    """

    PRESENT = "present"
    ABSENT = "absent"


class SightingKind(Enum):
    """How a URL came to be seen.  Stored data, never a caller-supplied selector."""

    SEARCH_RESULT = "search_result"
    CANDIDATE_SOURCE = "candidate_source"
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    SCRAPE_FAILED = "scrape_failed"
    JUDGED = "judged"


class ProjectionScope(Enum):
    """The closed set of row domains a projection request may cover.

    Required, and closed on purpose.  Two call sites in ``pipeline.py``
    (``L5856`` and ``L5938``) pass an identical optional-kwarg set while
    projecting completely different row domains, so a fingerprint built from
    kwargs alone would call them the same request.  That is the false-*agreement*
    direction of the join bug and it is worse than divergence, because the join
    succeeds while meaning nothing.

    Free text here would be prose steering a join, which is the text coupling
    this package exists to refuse.  New domains are added as members, by a
    change to this file, reviewed.
    """

    REWARD_BEFORE = "reward_before"
    REWARD_AFTER = "reward_after"
    REWARD_BEFORE_REBUILD = "reward_before_rebuild"
    PATH_GATE_CANDIDATES = "path_gate_candidates"
    LEDGER_REFRESH = "ledger_refresh"


class StoredOrigin(Enum):
    """Where a stored snapshot came from.

    ``COLD_START_PROJECTION`` is a **named** origin, not the absence of a
    field: the first round genuinely has no predecessor, and that fact must
    appear in the artifact rather than being inferred from a missing key.
    """

    COLD_START_PROJECTION = "cold_start_projection"
    FRESH_PROJECTION = "fresh_projection"
    CHAINED_PREDECESSOR = "chained_predecessor"
    REPLAYED_FROM_STORE = "replayed_from_store"


class MigrationStatus(Enum):
    """Whether a stored payload could be brought to the current schema."""

    CURRENT = "current"
    MIGRATED = "migrated"
    UNMIGRATABLE = "unmigratable"


@dataclass(frozen=True)
class SparseValue:
    """A source field that may legitimately be absent.

    ``value`` is meaningful only when ``presence is Presence.PRESENT``.  There
    is no "empty means missing" reading available, by construction.
    """

    presence: Presence
    value: Any = None

    def to_record(self) -> Mapping[str, Any]:
        if self.presence is Presence.PRESENT:
            return MappingProxyType({"presence": self.presence.value, "value": self.value})
        return MappingProxyType({"presence": self.presence.value})


#: The single shared "this field was not there" value.
ABSENT_VALUE = SparseValue(presence=Presence.ABSENT)


def sparse_present(value: Any) -> SparseValue:
    return SparseValue(presence=Presence.PRESENT, value=value)


def sparse_absent() -> SparseValue:
    return ABSENT_VALUE


def sparse_from_record(record: Mapping[str, Any]) -> SparseValue:
    """Recover a :class:`SparseValue` from the mapping :meth:`to_record` made."""

    if record.get("presence") == Presence.PRESENT.value:
        return SparseValue(presence=Presence.PRESENT, value=record.get("value"))
    return SparseValue(presence=Presence.ABSENT)


@dataclass(frozen=True)
class ReadExtent:
    """The measured evidence that a read actually looked.

    Without this, ``OK`` with no records is indistinguishable from a read that
    silently examined nothing.
    """

    runs_enumerated: int = 0
    runs_skipped: int = 0
    records_scanned: int = 0
    records_matched: int = 0

    def to_record(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "runs_enumerated": self.runs_enumerated,
                "runs_skipped": self.runs_skipped,
                "records_scanned": self.records_scanned,
                "records_matched": self.records_matched,
            }
        )


EMPTY_EXTENT = ReadExtent()


@dataclass(frozen=True)
class SkipRecord:
    """One directory, root, or line that was not taken in, and why.

    Carries its **own** ``reason_code``.  A run that could not be enumerated is
    not folded into the surrounding result's reason; it is named individually so
    a caller can tell one unreadable run apart from a hundred.
    """

    path: str
    reason_code: ReasonCode
    reason: str = ""

    def to_record(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "path": self.path,
                "reason_code": self.reason_code.value,
                "reason": self.reason,
            }
        )


class _NotTruthy:
    """Mixin making ``if result:`` and ``len(result)`` hard errors.

    A result must never be *silently* truthy or falsy.  ``if not result:`` would
    otherwise read "the store could not answer" and "the store looked and found
    none" as the same thing on the read side, and "this contradicts what is
    stored" and "this was already stored identically" as the same thing on the
    write side.  Those are the two conflations this whole contract exists to
    prevent, one per side.

    Python's default object truthiness is silently ``True``, so **not** defining
    ``__bool__`` delivers exactly the conflation the rule forbids.  Raising is
    the only construction that makes the mistake observable.

    ``_truth_hint`` names the accessor to branch on instead, per subclass: a
    message that pointed a ``WriteResult`` at read statuses would send the
    caller looking for a field it does not have.
    """

    __slots__ = ()

    #: Subclasses override with the accessor and vocabulary that applies to them.
    _truth_hint = "its typed status field"

    #: Subclasses override with the right way to get a count.
    _length_hint = "the collection field it carries"

    def __bool__(self) -> bool:
        raise TypeError(
            f"{type(self).__name__} has no truth value; branch on "
            f"{self._truth_hint} instead of testing the result"
        )

    def __len__(self) -> int:
        raise TypeError(
            f"{type(self).__name__} has no length; use {self._length_hint}"
        )


@dataclass(frozen=True)
class StoreRead(_NotTruthy):
    """The complete answer to one question, or a stated reason there is none.

    ``records`` is the **complete** matched set.  It is never sampled, never
    ranked, never truncated, and never windowed: a budget denominated in prompt
    units is unknowable here, so the caller windows at the prompt seam.
    """

    _truth_hint = ".status (OK / NOT_STORED / UNREADABLE)"
    _length_hint = (
        "len(result.records) for the matched set, and result.extent for the "
        "counts that prove the store looked"
    )

    status: ReadStatus
    records: tuple[Mapping[str, Any], ...]
    extent: ReadExtent
    reason_code: ReasonCode
    reason: str
    skipped: tuple[SkipRecord, ...] = ()


@dataclass(frozen=True)
class WriteResult(_NotTruthy):
    """The outcome of one write-once attempt.

    On a primary-key collision the incoming payload digest is compared with the
    stored one.  Identical means ``ALREADY_STORED`` and the write is idempotent.
    Different means ``CONFLICT``: the stored row is left exactly as it was and
    both digests travel on the result.  Nothing is overwritten and nothing is
    silently dropped, which is why ``ON CONFLICT DO NOTHING`` never appears in
    this package.
    """

    _truth_hint = ".status (STORED / ALREADY_STORED / CONFLICT)"
    _length_hint = (
        "len(result.key) for the primary key written, and compare "
        "result.incoming_digest with result.stored_digest for a conflict"
    )

    status: WriteStatus
    reason_code: ReasonCode
    reason: str
    key: tuple[Any, ...] = ()
    incoming_digest: str = ""
    stored_digest: SparseValue = ABSENT_VALUE
