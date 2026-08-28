"""Connection, DDL, transactions, write-once puts, and the named read entry points.

Engine is SQLite, held as a **gitignored build artifact**.  ``question_runs/``
is already 13,160 tracked files across 36 GB; a committed derived index over it
would be pure churn.  A full scan of the recorded corpus takes 0.24 s at 12 MB
peak RSS, so on the search side rebuilding is cheaper than validating staleness
-- which is why that side is a rebuildable derived index rather than an
incrementally-maintained one.

Shape
-----

Concrete tables with concrete schemas.  There is **no** ``kind`` discriminator
over a shared payload and **no** generic ``get(table, key)``: a single code path
whose behaviour depends on a caller-supplied selector is the options trap
wearing a schema.  Each question gets a named entry point whose signature says
which question it answers.

What the read path will not do
------------------------------

No ranking, no scoring, no selection, no sampling, no windowing, no negative
caching, no regeneration, and no LLM call -- ever.  Every read is a pure
function over stored data.  A read returns the **complete** matched set or a
stated reason, and the caller windows at the prompt seam, where a budget
denominated in prompt units is actually knowable.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

from .identity import (
    TOKENIZER_VERSION,
    RunRef,
    payload_digest,
)
from .overlap import count_overlap
from .result import (
    ABSENT_VALUE,
    EMPTY_EXTENT,
    Presence,
    ProjectionScope,
    ReadExtent,
    ReadStatus,
    ReasonCode,
    SightingKind,
    SkipRecord,
    SparseValue,
    StoreRead,
    StoredOrigin,
    WriteResult,
    WriteStatus,
    sparse_present,
)
from .versioning import MIGRATIONS, SCHEMA_VERSION, MigrationStatus, readability

__all__ = [
    "SearchQueryEvent",
    "UrlDecision",
    "UrlSighting",
    "StoredSnapshot",
    "open_store",
    "transaction",
    "put_search_query_event",
    "put_url_decision",
    "put_url_sighting",
    "put_criteria_snapshot",
    "put_ingested_run",
    "put_ingest_skip",
    "clear_search_index",
    "read_prior_queries_by_key",
    "read_prior_queries_by_tokens",
    "read_query_yield",
    "read_url_decisions",
    "read_url_decisions_in_context",
    "read_url_sightings",
    "read_stored_snapshot",
    "read_snapshots_for_request",
    "stored_snapshot_from_record",
]


_META_SCHEMA_VERSION = "schema_version"
_META_TOKENIZER_VERSION = "tokenizer_version"

#: Tables the search side owns.  They are dropped and rebuilt wholesale by
#: :func:`clear_search_index`; the snapshot side is never touched by a rebuild,
#: because a snapshot is a point-in-time fact that cannot be re-derived from the
#: filesystem later.
_SEARCH_TABLES = (
    "search_query_events",
    "query_tokens",
    "url_decisions",
    "url_sightings",
    "ingested_runs",
    "ingest_skips",
)


_DDL = (
    """
    CREATE TABLE IF NOT EXISTS store_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ingested_runs (
        run_name       TEXT PRIMARY KEY,
        run_dir        TEXT NOT NULL,
        corpus_id      TEXT NOT NULL,
        records_read   INTEGER NOT NULL,
        payload_digest TEXT NOT NULL,
        schema_version INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ingest_skips (
        path        TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        reason      TEXT NOT NULL,
        PRIMARY KEY (path, reason_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS search_query_events (
        run_name            TEXT    NOT NULL,
        record_ordinal      INTEGER NOT NULL,
        corpus_id           TEXT    NOT NULL,
        question_context_id TEXT    NOT NULL,
        query               TEXT    NOT NULL,
        query_key           TEXT    NOT NULL,
        query_tokens_json   TEXT    NOT NULL,
        tokenizer_version   TEXT    NOT NULL,
        task_id             TEXT    NOT NULL,
        topic               TEXT    NOT NULL,
        gap                 TEXT    NOT NULL,
        round_index         INTEGER,
        expansion_op        TEXT    NOT NULL,
        firecrawl_hits      INTEGER NOT NULL,
        error               TEXT    NOT NULL,
        target_table        TEXT    NOT NULL,
        target_id           TEXT    NOT NULL,
        yield_json          TEXT    NOT NULL,
        sparse_json         TEXT    NOT NULL,
        payload_digest      TEXT    NOT NULL,
        schema_version      INTEGER NOT NULL,
        PRIMARY KEY (run_name, record_ordinal)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_sqe_query_key ON search_query_events (query_key)",
    """
    CREATE TABLE IF NOT EXISTS query_tokens (
        query_key TEXT NOT NULL,
        token     TEXT NOT NULL,
        PRIMARY KEY (query_key, token)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_qt_token ON query_tokens (token)",
    """
    CREATE TABLE IF NOT EXISTS url_decisions (
        run_name            TEXT    NOT NULL,
        record_ordinal      INTEGER NOT NULL,
        decision_ordinal    INTEGER NOT NULL,
        url                 TEXT    NOT NULL,
        corpus_id           TEXT    NOT NULL,
        question_context_id TEXT    NOT NULL,
        task_id             TEXT    NOT NULL,
        topic               TEXT    NOT NULL,
        target_table        TEXT    NOT NULL,
        target_id           TEXT    NOT NULL,
        round_index         INTEGER,
        accept              INTEGER,
        confidence          REAL,
        title               TEXT,
        decision_reason     TEXT,
        payload_json        TEXT    NOT NULL,
        payload_digest      TEXT    NOT NULL,
        schema_version      INTEGER NOT NULL,
        PRIMARY KEY (run_name, record_ordinal, decision_ordinal)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_ud_url ON url_decisions (url)",
    """
    CREATE TABLE IF NOT EXISTS url_sightings (
        run_name            TEXT    NOT NULL,
        record_ordinal      INTEGER NOT NULL,
        sighting_ordinal    INTEGER NOT NULL,
        url                 TEXT    NOT NULL,
        sighting_kind       TEXT    NOT NULL,
        corpus_id           TEXT    NOT NULL,
        question_context_id TEXT    NOT NULL,
        round_index         INTEGER,
        query_key           TEXT    NOT NULL,
        rank                INTEGER,
        title               TEXT,
        payload_json        TEXT    NOT NULL,
        payload_digest      TEXT    NOT NULL,
        schema_version      INTEGER NOT NULL,
        PRIMARY KEY (run_name, record_ordinal, sighting_ordinal)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_us_url ON url_sightings (url)",
    """
    CREATE TABLE IF NOT EXISTS criteria_snapshots (
        projection_request_id   TEXT    NOT NULL,
        snapshot_id             TEXT    NOT NULL,
        projection_version      TEXT    NOT NULL,
        scope                   TEXT    NOT NULL,
        supplied_json           TEXT    NOT NULL,
        deliverable_tables_json TEXT    NOT NULL,
        run_name                TEXT    NOT NULL,
        round_index             INTEGER NOT NULL,
        origin                  TEXT    NOT NULL,
        payload_json            TEXT    NOT NULL,
        payload_digest          TEXT    NOT NULL,
        schema_version          INTEGER NOT NULL,
        PRIMARY KEY (projection_request_id, snapshot_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_cs_request ON criteria_snapshots (projection_request_id)",
)


# ---------------------------------------------------------------------------
# Write-side record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchQueryEvent:
    """One recorded search attempt, exactly as the producer wrote it.

    ``query_key`` and ``query_tokens`` are **opaque index fields**.  This
    package stores them, indexes them, and counts overlap between them; it never
    interprets them, never normalizes them, and holds no near-duplicate
    threshold.  ``tokenizer_version`` travels on every row so a tokenizer change
    is detectable as version skew rather than silently producing keys that no
    longer mean what the older keys meant.

    ``sparse`` carries every field the producer's record shape has grown over
    time, each as a :class:`SparseValue`.  It is one mapping rather than a
    column per field because that shape is still moving: registering a
    newly-landed field is one line in :mod:`run_store.ingest`, and a field
    absent from an older run stays ``ABSENT`` rather than being backfilled with
    a value nobody measured.  A ``false`` on a run that predates the field would
    be a fabricated negative.

    ``round_index`` is sparse, and the load-bearing reason is **forward
    compatibility, not present cost**.  Every record in the corpus recorded so
    far carries one, so today the column is never null -- that observation is
    the weakest possible argument for the design, and if it were the only one
    the column should simply be an integer.

    The real reason: upstream round-index stamping is landing mid-corpus.  When
    it does, the historical tail genuinely predates it, and a nullable column
    absorbs that split with **no migration and no fabricated round 0**.  An
    integer column would force a choice between rewriting history and asserting
    that every unstamped search happened in the first round -- a claim about
    when the search ran that nobody measured, in a column downstream code
    orders and groups by.
    """

    run_name: str
    record_ordinal: int
    corpus_id: str
    question_context_id: str
    query: str
    query_key: str
    query_tokens: tuple[str, ...]
    tokenizer_version: str
    task_id: str
    topic: str
    gap: str
    round_index: SparseValue
    expansion_op: str
    firecrawl_hits: int
    error: str
    target_table: str
    target_id: str
    query_yield: Mapping[str, Any]
    sparse: Mapping[str, SparseValue]


@dataclass(frozen=True)
class UrlDecision:
    """One relevance verdict on one URL, in the question context that reached it.

    ``question_context_id`` is not decoration.  Of the 16 URLs in the recorded
    corpus carrying contradictory accept/reject verdicts, 11 contradict inside a
    single question family and 5 differ only across families -- and the second
    group is legitimate.  A verdict keyed by URL alone cannot tell those apart.

    ``accept`` and ``confidence`` are :class:`SparseValue`, because a decision
    that recorded neither must not read as ``reject`` at confidence ``0.0``.
    """

    run_name: str
    record_ordinal: int
    decision_ordinal: int
    url: str
    corpus_id: str
    question_context_id: str
    task_id: str
    topic: str
    target_table: str
    target_id: str
    round_index: SparseValue
    accept: SparseValue
    confidence: SparseValue
    title: SparseValue
    decision_reason: SparseValue
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class UrlSighting:
    """One occasion on which a URL was seen at all, and in what capacity.

    ``sighting_kind`` is *stored data* describing how the producer encountered
    the URL.  It is never a caller-supplied selector: no read entry point takes
    a kind and switches on it.  Reads return every sighting, each carrying its
    own kind.
    """

    run_name: str
    record_ordinal: int
    sighting_ordinal: int
    url: str
    sighting_kind: SightingKind
    corpus_id: str
    question_context_id: str
    round_index: SparseValue
    query_key: str
    rank: SparseValue
    title: SparseValue
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class StoredSnapshot:
    """A criteria snapshot as it was written, plus the metadata that joins it.

    The key is the **pair** ``(projection_request_id, snapshot_id)``.  A
    snapshot id alone is unjoinable: five call sites in ``pipeline.py`` pass
    five different optional-kwarg sets and each set changes the resulting id.

    ``payload`` is an **opaque mapping**.  ``run_store`` must never import
    ``question_pipeline``, so it cannot hold a ``CriteriaSnapshot`` and does not
    try; rebuilding one from this payload is an adapter's job on the other side
    of the boundary.

    That opacity is also what makes read-back-never-regenerate enforceable by
    **type incompatibility** rather than by convention: a historical consumer
    that is annotated to take ``StoredSnapshot`` cannot be handed a freshly
    projected ``CriteriaSnapshot``, because the two types share no members.
    """

    projection_request_id: str
    snapshot_id: str
    projection_version: str
    scope: ProjectionScope
    supplied: tuple[str, ...]
    deliverable_tables: tuple[str, ...]
    run_name: str
    round_index: int
    origin: StoredOrigin
    payload: Mapping[str, Any]


# ---------------------------------------------------------------------------
# Connection, DDL, transactions
# ---------------------------------------------------------------------------


def open_store(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the store at ``path``.

    A store whose recorded schema version this build cannot migrate is still
    *opened*: refusing here would raise where the contract promises a typed
    ``UNREADABLE`` read.  The refusal happens at every read entry point instead.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    initialized = _has_table(conn, "store_meta")
    if not initialized:
        with transaction(conn):
            for statement in _DDL:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO store_meta (key, value) VALUES (?, ?)",
                (_META_SCHEMA_VERSION, str(SCHEMA_VERSION)),
            )
            conn.execute(
                "INSERT INTO store_meta (key, value) VALUES (?, ?)",
                (_META_TOKENIZER_VERSION, TOKENIZER_VERSION),
            )
    else:
        with transaction(conn):
            for statement in _DDL:
                conn.execute(statement)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One all-or-nothing unit of work.  A raise rolls the whole thing back."""

    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def clear_search_index(conn: sqlite3.Connection) -> None:
    """Drop every search-side row so ingest can rebuild it from the filesystem.

    This is a **write-side** entry point with its own name, not a
    ``regenerate=`` flag on a read.  A read never rebuilds anything; a caller
    that wants a rebuild says so, out loud, at a call site that does nothing
    else.

    The snapshot side is untouched.  Search rows are re-derivable from
    ``search_outcomes.jsonl`` in 0.24 s; a criteria snapshot is a point-in-time
    fact about a round that has already ended and can never be re-derived.
    """

    with transaction(conn):
        for table in _SEARCH_TABLES:
            conn.execute(f"DELETE FROM {table}")


# ---------------------------------------------------------------------------
# Read guard
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Guard:
    """Whether the store can answer at all, and the typed refusal if not."""

    readable: bool
    status: ReadStatus
    reason_code: ReasonCode
    reason: str


_READABLE = _Guard(
    readable=True,
    status=ReadStatus.OK,
    reason_code=ReasonCode.MATCHED,
    reason="",
)


def _guard(conn: sqlite3.Connection) -> _Guard:
    if not _has_table(conn, "store_meta"):
        return _Guard(
            readable=False,
            status=ReadStatus.UNREADABLE,
            reason_code=ReasonCode.STORE_NOT_INITIALIZED,
            reason="store file has no store_meta table; it was never initialized",
        )
    row = conn.execute(
        "SELECT value FROM store_meta WHERE key = ?", (_META_SCHEMA_VERSION,)
    ).fetchone()
    if row is None:
        return _Guard(
            readable=False,
            status=ReadStatus.UNREADABLE,
            reason_code=ReasonCode.STORE_NOT_INITIALIZED,
            reason="store_meta carries no schema version",
        )
    try:
        stored_version = int(row["value"])
    except (TypeError, ValueError):
        return _Guard(
            readable=False,
            status=ReadStatus.UNREADABLE,
            reason_code=ReasonCode.ROW_CORRUPT,
            reason="store_meta schema version is not an integer",
        )
    outcome = readability(MIGRATIONS, stored_version, SCHEMA_VERSION)
    if outcome.status is MigrationStatus.UNMIGRATABLE:
        return _Guard(
            readable=False,
            status=ReadStatus.UNREADABLE,
            reason_code=outcome.reason_code,
            reason=outcome.reason,
        )
    return _READABLE


def _refused(guard: _Guard) -> StoreRead:
    return StoreRead(
        status=guard.status,
        records=(),
        extent=EMPTY_EXTENT,
        reason_code=guard.reason_code,
        reason=guard.reason,
        skipped=(),
    )


def _corpus_extent(conn: sqlite3.Connection) -> tuple[int, int, tuple[SkipRecord, ...]]:
    runs = int(conn.execute("SELECT COUNT(*) AS n FROM ingested_runs").fetchone()["n"])
    skips = tuple(
        SkipRecord(
            path=str(row["path"]),
            reason_code=ReasonCode(str(row["reason_code"])),
            reason=str(row["reason"]),
        )
        for row in conn.execute(
            "SELECT path, reason_code, reason FROM ingest_skips ORDER BY path, reason_code"
        )
    )
    return runs, len(skips), skips


def _unreadable_row(reason: str, extent: ReadExtent) -> StoreRead:
    return StoreRead(
        status=ReadStatus.UNREADABLE,
        records=(),
        extent=extent,
        reason_code=ReasonCode.ROW_CORRUPT,
        reason=reason,
        skipped=(),
    )


def _decode(raw: Any) -> Any:
    return json.loads(raw)


def _sparse_column(row: sqlite3.Row, column: str) -> SparseValue:
    value = row[column]
    if value is None:
        return ABSENT_VALUE
    return sparse_present(value)


# ---------------------------------------------------------------------------
# Write-once primitive
# ---------------------------------------------------------------------------


def _put_once(
    conn: sqlite3.Connection,
    table: str,
    key_columns: Sequence[str],
    row: Mapping[str, Any],
) -> WriteResult:
    """Insert ``row`` if its key is free; otherwise compare digests and report.

    ``ON CONFLICT DO NOTHING`` appears nowhere in this package, deliberately.
    It collapses "already written identically" and "written differently" into
    one silent outcome, and the second of those is a fact somebody needs.
    """

    columns = tuple(row)
    placeholders = ", ".join("?" for _ in columns)
    column_list = ", ".join(columns)
    values = tuple(row[column] for column in columns)
    key = tuple(row[column] for column in key_columns)
    incoming = str(row["payload_digest"])

    try:
        conn.execute(
            f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})", values
        )
    except sqlite3.IntegrityError:
        predicate = " AND ".join(f"{column} = ?" for column in key_columns)
        existing = conn.execute(
            f"SELECT payload_digest FROM {table} WHERE {predicate}", key
        ).fetchone()
        if existing is None:
            return WriteResult(
                status=WriteStatus.CONFLICT,
                reason_code=ReasonCode.STORE_ERROR,
                reason=(
                    f"insert into {table} was rejected but no row holds that key; "
                    f"a constraint other than the primary key refused the write"
                ),
                key=key,
                incoming_digest=incoming,
                stored_digest=ABSENT_VALUE,
            )
        stored = str(existing["payload_digest"])
        if stored == incoming:
            return WriteResult(
                status=WriteStatus.ALREADY_STORED,
                reason_code=ReasonCode.WRITE_IDENTICAL_PAYLOAD,
                reason=f"{table} already holds this key with a byte-identical payload",
                key=key,
                incoming_digest=incoming,
                stored_digest=sparse_present(stored),
            )
        return WriteResult(
            status=WriteStatus.CONFLICT,
            reason_code=ReasonCode.WRITE_DIGEST_MISMATCH,
            reason=(
                f"{table} already holds this key with a different payload; the "
                f"stored row was left exactly as it was and the incoming payload "
                f"was not written"
            ),
            key=key,
            incoming_digest=incoming,
            stored_digest=sparse_present(stored),
        )
    return WriteResult(
        status=WriteStatus.STORED,
        reason_code=ReasonCode.WRITE_NEW,
        reason=f"row written to {table}",
        key=key,
        incoming_digest=incoming,
        stored_digest=ABSENT_VALUE,
    )


# ---------------------------------------------------------------------------
# Named write entry points
# ---------------------------------------------------------------------------


def put_search_query_event(
    conn: sqlite3.Connection, event: SearchQueryEvent
) -> WriteResult:
    """Store one search attempt write-once, and index its tokens."""

    sparse_record = {
        name: dict(value.to_record()) for name, value in event.sparse.items()
    }
    row = {
        "run_name": event.run_name,
        "record_ordinal": int(event.record_ordinal),
        "corpus_id": event.corpus_id,
        "question_context_id": event.question_context_id,
        "query": event.query,
        "query_key": event.query_key,
        "query_tokens_json": json.dumps(list(event.query_tokens)),
        "tokenizer_version": event.tokenizer_version,
        "task_id": event.task_id,
        "topic": event.topic,
        "gap": event.gap,
        "round_index": _int_or_none(event.round_index),
        "expansion_op": event.expansion_op,
        "firecrawl_hits": int(event.firecrawl_hits),
        "error": event.error,
        "target_table": event.target_table,
        "target_id": event.target_id,
        "yield_json": json.dumps(dict(event.query_yield), sort_keys=True),
        "sparse_json": json.dumps(sparse_record, sort_keys=True),
        "payload_digest": payload_digest(
            {
                "run_name": event.run_name,
                "record_ordinal": event.record_ordinal,
                "query": event.query,
                "query_key": event.query_key,
                "query_tokens": list(event.query_tokens),
                "tokenizer_version": event.tokenizer_version,
                "task_id": event.task_id,
                "topic": event.topic,
                "gap": event.gap,
                "round_index": dict(event.round_index.to_record()),
                "expansion_op": event.expansion_op,
                "firecrawl_hits": event.firecrawl_hits,
                "error": event.error,
                "target_table": event.target_table,
                "target_id": event.target_id,
                "yield": dict(event.query_yield),
                "sparse": sparse_record,
            }
        ),
        "schema_version": SCHEMA_VERSION,
    }
    result = _put_once(conn, "search_query_events", ("run_name", "record_ordinal"), row)
    if result.status is WriteStatus.STORED:
        for token in event.query_tokens:
            try:
                conn.execute(
                    "INSERT INTO query_tokens (query_key, token) VALUES (?, ?)",
                    (event.query_key, token),
                )
            except sqlite3.IntegrityError:
                # The token index is a set: the same (query_key, token) pair
                # arriving from a second event is the same fact, not a new one.
                continue
    return result


def put_url_decision(conn: sqlite3.Connection, decision: UrlDecision) -> WriteResult:
    """Store one URL verdict write-once, keyed by run, record, and position."""

    row = {
        "run_name": decision.run_name,
        "record_ordinal": int(decision.record_ordinal),
        "decision_ordinal": int(decision.decision_ordinal),
        "url": decision.url,
        "corpus_id": decision.corpus_id,
        "question_context_id": decision.question_context_id,
        "task_id": decision.task_id,
        "topic": decision.topic,
        "target_table": decision.target_table,
        "target_id": decision.target_id,
        "round_index": _int_or_none(decision.round_index),
        "accept": _int_or_none(decision.accept),
        "confidence": _float_or_none(decision.confidence),
        "title": _text_or_none(decision.title),
        "decision_reason": _text_or_none(decision.decision_reason),
        "payload_json": json.dumps(dict(decision.payload), sort_keys=True),
        "payload_digest": payload_digest(
            {
                "run_name": decision.run_name,
                "record_ordinal": decision.record_ordinal,
                "decision_ordinal": decision.decision_ordinal,
                "url": decision.url,
                "question_context_id": decision.question_context_id,
                "accept": dict(decision.accept.to_record()),
                "confidence": dict(decision.confidence.to_record()),
                "payload": dict(decision.payload),
            }
        ),
        "schema_version": SCHEMA_VERSION,
    }
    return _put_once(
        conn,
        "url_decisions",
        ("run_name", "record_ordinal", "decision_ordinal"),
        row,
    )


def put_url_sighting(conn: sqlite3.Connection, sighting: UrlSighting) -> WriteResult:
    """Store one occasion on which a URL was seen, write-once."""

    row = {
        "run_name": sighting.run_name,
        "record_ordinal": int(sighting.record_ordinal),
        "sighting_ordinal": int(sighting.sighting_ordinal),
        "url": sighting.url,
        "sighting_kind": sighting.sighting_kind.value,
        "corpus_id": sighting.corpus_id,
        "question_context_id": sighting.question_context_id,
        "round_index": _int_or_none(sighting.round_index),
        "query_key": sighting.query_key,
        "rank": _int_or_none(sighting.rank),
        "title": _text_or_none(sighting.title),
        "payload_json": json.dumps(dict(sighting.payload), sort_keys=True),
        "payload_digest": payload_digest(
            {
                "run_name": sighting.run_name,
                "record_ordinal": sighting.record_ordinal,
                "sighting_ordinal": sighting.sighting_ordinal,
                "url": sighting.url,
                "sighting_kind": sighting.sighting_kind.value,
                "payload": dict(sighting.payload),
            }
        ),
        "schema_version": SCHEMA_VERSION,
    }
    return _put_once(
        conn,
        "url_sightings",
        ("run_name", "record_ordinal", "sighting_ordinal"),
        row,
    )


def put_criteria_snapshot(
    conn: sqlite3.Connection, snapshot: StoredSnapshot
) -> WriteResult:
    """Store one criteria snapshot write-once under its **pair** key."""

    if not isinstance(snapshot.scope, ProjectionScope):
        raise TypeError("StoredSnapshot.scope must be a ProjectionScope member")
    if not isinstance(snapshot.origin, StoredOrigin):
        raise TypeError(
            "StoredSnapshot.origin must be a StoredOrigin member; a first-round "
            "projection is COLD_START_PROJECTION, never a missing field"
        )
    row = {
        "projection_request_id": snapshot.projection_request_id,
        "snapshot_id": snapshot.snapshot_id,
        "projection_version": snapshot.projection_version,
        "scope": snapshot.scope.value,
        "supplied_json": json.dumps(sorted(snapshot.supplied)),
        "deliverable_tables_json": json.dumps(list(snapshot.deliverable_tables)),
        "run_name": snapshot.run_name,
        "round_index": int(snapshot.round_index),
        "origin": snapshot.origin.value,
        "payload_json": json.dumps(dict(snapshot.payload), sort_keys=True),
        "payload_digest": payload_digest(
            {
                "projection_request_id": snapshot.projection_request_id,
                "snapshot_id": snapshot.snapshot_id,
                "payload": dict(snapshot.payload),
            }
        ),
        "schema_version": SCHEMA_VERSION,
    }
    return _put_once(
        conn,
        "criteria_snapshots",
        ("projection_request_id", "snapshot_id"),
        row,
    )


def put_ingested_run(
    conn: sqlite3.Connection, run: RunRef, records_read: int
) -> WriteResult:
    """Record that ``run`` was taken in, and how many records it offered."""

    row = {
        "run_name": run.run_name,
        "run_dir": run.run_dir,
        "corpus_id": run.corpus_id,
        "records_read": int(records_read),
        "payload_digest": payload_digest(
            {"run": dict(run.to_record()), "records_read": int(records_read)}
        ),
        "schema_version": SCHEMA_VERSION,
    }
    return _put_once(conn, "ingested_runs", ("run_name",), row)


def put_ingest_skip(conn: sqlite3.Connection, skip: SkipRecord) -> WriteResult:
    """Record one directory, root, or line that ingest could not take in.

    Skips are stored, not merely returned, because a later read must be able to
    say "this answer was computed over a corpus with three unreadable runs in
    it" without re-walking the filesystem.
    """

    row = {
        "path": skip.path,
        "reason_code": skip.reason_code.value,
        "reason": skip.reason,
        "payload_digest": payload_digest(
            {"path": skip.path, "reason_code": skip.reason_code.value}
        ),
    }
    columns = ("path", "reason_code", "reason")
    values = tuple(row[column] for column in columns)
    key = (skip.path, skip.reason_code.value)
    try:
        conn.execute(
            "INSERT INTO ingest_skips (path, reason_code, reason) VALUES (?, ?, ?)",
            values,
        )
    except sqlite3.IntegrityError:
        return WriteResult(
            status=WriteStatus.ALREADY_STORED,
            reason_code=ReasonCode.WRITE_IDENTICAL_PAYLOAD,
            reason="this path was already recorded as skipped for this reason code",
            key=key,
            incoming_digest=str(row["payload_digest"]),
            stored_digest=sparse_present(str(row["payload_digest"])),
        )
    return WriteResult(
        status=WriteStatus.STORED,
        reason_code=ReasonCode.WRITE_NEW,
        reason="skip recorded",
        key=key,
        incoming_digest=str(row["payload_digest"]),
        stored_digest=ABSENT_VALUE,
    )


def _int_or_none(value: SparseValue) -> Any:
    if value.presence is Presence.ABSENT:
        return None
    return int(value.value)


def _float_or_none(value: SparseValue) -> Any:
    if value.presence is Presence.ABSENT:
        return None
    return float(value.value)


def _text_or_none(value: SparseValue) -> Any:
    if value.presence is Presence.ABSENT:
        return None
    return str(value.value)


# ---------------------------------------------------------------------------
# Named read entry points -- search side
# ---------------------------------------------------------------------------


def read_prior_queries_by_key(
    conn: sqlite3.Connection, *, query_key: str
) -> StoreRead:
    """Every prior instance of the **exact** query identified by ``query_key``.

    Answers "has this query been run before, anywhere in the corpus".  ``OK``
    with no records is the positive fact "it has not"; ``extent`` carries the
    counts proving the store looked.
    """

    guard = _guard(conn)
    if not guard.readable:
        return _refused(guard)
    runs, skipped_count, skips = _corpus_extent(conn)
    scanned = int(
        conn.execute("SELECT COUNT(*) AS n FROM search_query_events").fetchone()["n"]
    )
    if runs == 0:
        return StoreRead(
            status=ReadStatus.NOT_STORED,
            records=(),
            extent=ReadExtent(
                runs_enumerated=0,
                runs_skipped=skipped_count,
                records_scanned=scanned,
                records_matched=0,
            ),
            reason_code=ReasonCode.STORE_HOLDS_NO_RUNS,
            reason="no run has been ingested, so the corpus this question is keyed by was never written",
            skipped=skips,
        )
    rows = conn.execute(
        "SELECT * FROM search_query_events WHERE query_key = ? "
        "ORDER BY run_name, record_ordinal",
        (query_key,),
    ).fetchall()
    try:
        records = tuple(_query_event_record(row) for row in rows)
    except (ValueError, TypeError) as error:
        return _unreadable_row(
            f"a stored search event will not decode: {error.__class__.__name__}",
            ReadExtent(runs, skipped_count, scanned, 0),
        )
    return _ok(records, ReadExtent(runs, skipped_count, scanned, len(records)), skips)


def read_prior_queries_by_tokens(
    conn: sqlite3.Connection, *, query_tokens: tuple[str, ...]
) -> StoreRead:
    """Every prior distinct query sharing at least one token with ``query_tokens``.

    One record per distinct ``query_key``, each carrying **measured** overlap
    counts and the runs it appeared in.  There is no threshold here, no
    similarity score, no ranking, and no verdict: the near-duplicate ruling
    belongs to ``question_pipeline``, which owns query normalization and knows
    what its own planner should treat as a repeat.

    "Shares at least one token" is the *definition of the question asked*, fixed
    in code and reported on every record as ``match_rule``.  It is not a tunable:
    it cannot be passed, defaulted, or omitted.
    """

    guard = _guard(conn)
    if not guard.readable:
        return _refused(guard)
    runs, skipped_count, skips = _corpus_extent(conn)
    scanned = int(
        conn.execute(
            "SELECT COUNT(DISTINCT query_key) AS n FROM query_tokens"
        ).fetchone()["n"]
    )
    if runs == 0:
        return StoreRead(
            status=ReadStatus.NOT_STORED,
            records=(),
            extent=ReadExtent(0, skipped_count, scanned, 0),
            reason_code=ReasonCode.STORE_HOLDS_NO_RUNS,
            reason="no run has been ingested, so the corpus this question is keyed by was never written",
            skipped=skips,
        )

    tokens = tuple(sorted(set(query_tokens)))
    if len(tokens) == 0:
        return _ok((), ReadExtent(runs, skipped_count, scanned, 0), skips)

    placeholders = ", ".join("?" for _ in tokens)
    matched_keys = tuple(
        str(row["query_key"])
        for row in conn.execute(
            f"SELECT DISTINCT query_key FROM query_tokens WHERE token IN ({placeholders}) "
            f"ORDER BY query_key",
            tokens,
        )
    )
    if len(matched_keys) == 0:
        return _ok((), ReadExtent(runs, skipped_count, scanned, 0), skips)

    records: list[Mapping[str, Any]] = []
    for key in matched_keys:
        stored_tokens = tuple(
            str(row["token"])
            for row in conn.execute(
                "SELECT token FROM query_tokens WHERE query_key = ? ORDER BY token",
                (key,),
            )
        )
        summary = conn.execute(
            "SELECT COUNT(*) AS instances, COUNT(DISTINCT run_name) AS runs, "
            "MIN(query) AS query, MIN(tokenizer_version) AS tokenizer_version "
            "FROM search_query_events WHERE query_key = ?",
            (key,),
        ).fetchone()
        run_names = tuple(
            str(row["run_name"])
            for row in conn.execute(
                "SELECT DISTINCT run_name FROM search_query_events "
                "WHERE query_key = ? ORDER BY run_name",
                (key,),
            )
        )
        corpus_ids = tuple(
            str(row["corpus_id"])
            for row in conn.execute(
                "SELECT DISTINCT corpus_id FROM search_query_events "
                "WHERE query_key = ? ORDER BY corpus_id",
                (key,),
            )
        )
        overlap = count_overlap(tokens, stored_tokens)
        records.append(
            MappingProxyType(
                {
                    "query_key": key,
                    "query": summary["query"],
                    "tokenizer_version": summary["tokenizer_version"],
                    "query_tokens": list(stored_tokens),
                    "instances": int(summary["instances"]),
                    "runs": list(run_names),
                    "run_count": len(run_names),
                    "corpus_ids": list(corpus_ids),
                    "overlap": dict(overlap.to_record()),
                    "match_rule": "shares_at_least_one_token",
                }
            )
        )
    return _ok(
        tuple(records), ReadExtent(runs, skipped_count, scanned, len(records)), skips
    )


def read_query_yield(conn: sqlite3.Connection, *, query_key: str) -> StoreRead:
    """What the query identified by ``query_key`` actually produced, every time.

    One record per recorded instance, carrying the producer's own yield fields
    verbatim -- accepted source ids and URLs, duplicates, scrape failures,
    skip reasons, text reductions, the error string -- plus ``cost`` as a sparse
    field, because ``cost`` is present on only 107 of 23,240 recorded instances
    and an absent cost must never read as zero cost.
    """

    return read_prior_queries_by_key(conn, query_key=query_key)


def read_url_decisions(conn: sqlite3.Connection, *, url: str) -> StoreRead:
    """Every relevance verdict ever recorded for ``url``, with its context.

    Complete: 2,471 of 2,783 relevance judgements in the recorded corpus
    re-judge an already-judged URL, so the useful answer is the whole history,
    not a sample of it.  Each record carries ``question_context_id`` and the
    context fields it was built from, because 11 of the 16 contradictory URLs
    contradict *within* a question family and 5 differ only *across* families.
    Grouping and ruling on that is the caller's.
    """

    guard = _guard(conn)
    if not guard.readable:
        return _refused(guard)
    runs, skipped_count, skips = _corpus_extent(conn)
    scanned = int(
        conn.execute("SELECT COUNT(*) AS n FROM url_decisions").fetchone()["n"]
    )
    if runs == 0:
        return StoreRead(
            status=ReadStatus.NOT_STORED,
            records=(),
            extent=ReadExtent(0, skipped_count, scanned, 0),
            reason_code=ReasonCode.STORE_HOLDS_NO_RUNS,
            reason="no run has been ingested, so the corpus this question is keyed by was never written",
            skipped=skips,
        )
    rows = conn.execute(
        "SELECT * FROM url_decisions WHERE url = ? "
        "ORDER BY run_name, record_ordinal, decision_ordinal",
        (url,),
    ).fetchall()
    try:
        records = tuple(_decision_record(row) for row in rows)
    except (ValueError, TypeError) as error:
        return _unreadable_row(
            f"a stored URL decision will not decode: {error.__class__.__name__}",
            ReadExtent(runs, skipped_count, scanned, 0),
        )
    return _ok(records, ReadExtent(runs, skipped_count, scanned, len(records)), skips)


def read_url_decisions_in_context(
    conn: sqlite3.Connection, *, url: str, question_context_id: str
) -> StoreRead:
    """Every verdict on ``url`` reached in one specific question context.

    Both arguments define *which question is asked* and neither can be omitted.
    This is the entry point that exists because a verdict keyed by URL alone
    cannot separate a real inconsistency from two different questions.
    """

    guard = _guard(conn)
    if not guard.readable:
        return _refused(guard)
    runs, skipped_count, skips = _corpus_extent(conn)
    scanned = int(
        conn.execute("SELECT COUNT(*) AS n FROM url_decisions").fetchone()["n"]
    )
    if runs == 0:
        return StoreRead(
            status=ReadStatus.NOT_STORED,
            records=(),
            extent=ReadExtent(0, skipped_count, scanned, 0),
            reason_code=ReasonCode.STORE_HOLDS_NO_RUNS,
            reason="no run has been ingested, so the corpus this question is keyed by was never written",
            skipped=skips,
        )
    rows = conn.execute(
        "SELECT * FROM url_decisions WHERE url = ? AND question_context_id = ? "
        "ORDER BY run_name, record_ordinal, decision_ordinal",
        (url, question_context_id),
    ).fetchall()
    try:
        records = tuple(_decision_record(row) for row in rows)
    except (ValueError, TypeError) as error:
        return _unreadable_row(
            f"a stored URL decision will not decode: {error.__class__.__name__}",
            ReadExtent(runs, skipped_count, scanned, 0),
        )
    return _ok(records, ReadExtent(runs, skipped_count, scanned, len(records)), skips)


def read_url_sightings(conn: sqlite3.Connection, *, url: str) -> StoreRead:
    """Every occasion on which ``url`` was seen at all, judged or not.

    63% of the 541 distinct URLs in the entire recorded history appear in more
    than one run, and the most-repeated URL was re-encountered in 46 of 77 runs.
    "Seen" is therefore a much larger fact than "judged", and it has its own
    entry point rather than a ``kind=`` selector on a shared one.
    """

    guard = _guard(conn)
    if not guard.readable:
        return _refused(guard)
    runs, skipped_count, skips = _corpus_extent(conn)
    scanned = int(
        conn.execute("SELECT COUNT(*) AS n FROM url_sightings").fetchone()["n"]
    )
    if runs == 0:
        return StoreRead(
            status=ReadStatus.NOT_STORED,
            records=(),
            extent=ReadExtent(0, skipped_count, scanned, 0),
            reason_code=ReasonCode.STORE_HOLDS_NO_RUNS,
            reason="no run has been ingested, so the corpus this question is keyed by was never written",
            skipped=skips,
        )
    rows = conn.execute(
        "SELECT * FROM url_sightings WHERE url = ? "
        "ORDER BY run_name, record_ordinal, sighting_ordinal",
        (url,),
    ).fetchall()
    try:
        records = tuple(_sighting_record(row) for row in rows)
    except (ValueError, TypeError) as error:
        return _unreadable_row(
            f"a stored URL sighting will not decode: {error.__class__.__name__}",
            ReadExtent(runs, skipped_count, scanned, 0),
        )
    return _ok(records, ReadExtent(runs, skipped_count, scanned, len(records)), skips)


# ---------------------------------------------------------------------------
# Named read entry points -- snapshot side
# ---------------------------------------------------------------------------


def read_stored_snapshot(
    conn: sqlite3.Connection, *, projection_request_id: str, snapshot_id: str
) -> StoreRead:
    """The snapshot stored under the **pair** ``(request, snapshot)``.

    ``NOT_STORED`` here means exactly what it says: that pair was never written.
    It never means "so project it fresh" -- there is no parameter on this
    function that could, and a caller wanting a projection calls the projector,
    which lives on the other side of the boundary.
    """

    guard = _guard(conn)
    if not guard.readable:
        return _refused(guard)
    scanned = int(
        conn.execute("SELECT COUNT(*) AS n FROM criteria_snapshots").fetchone()["n"]
    )
    rows = conn.execute(
        "SELECT * FROM criteria_snapshots WHERE projection_request_id = ? AND snapshot_id = ?",
        (projection_request_id, snapshot_id),
    ).fetchall()
    if len(rows) == 0:
        return StoreRead(
            status=ReadStatus.NOT_STORED,
            records=(),
            extent=ReadExtent(0, 0, scanned, 0),
            reason_code=ReasonCode.KEY_NEVER_WRITTEN,
            reason=(
                "no snapshot was written under this (projection_request_id, "
                "snapshot_id) pair"
            ),
            skipped=(),
        )
    try:
        records = tuple(_snapshot_record(row) for row in rows)
    except (ValueError, TypeError) as error:
        return _unreadable_row(
            f"a stored snapshot will not decode: {error.__class__.__name__}",
            ReadExtent(0, 0, scanned, 0),
        )
    return _ok(records, ReadExtent(0, 0, scanned, len(records)), ())


def read_snapshots_for_request(
    conn: sqlite3.Connection, *, projection_request_id: str
) -> StoreRead:
    """Every snapshot ever written under one projection request.

    ``OK`` with no records is the positive fact that this request has produced
    nothing yet -- distinct from ``NOT_STORED`` on the pair read, which is about
    one specific snapshot id.
    """

    guard = _guard(conn)
    if not guard.readable:
        return _refused(guard)
    scanned = int(
        conn.execute("SELECT COUNT(*) AS n FROM criteria_snapshots").fetchone()["n"]
    )
    rows = conn.execute(
        "SELECT * FROM criteria_snapshots WHERE projection_request_id = ? "
        "ORDER BY round_index, snapshot_id",
        (projection_request_id,),
    ).fetchall()
    try:
        records = tuple(_snapshot_record(row) for row in rows)
    except (ValueError, TypeError) as error:
        return _unreadable_row(
            f"a stored snapshot will not decode: {error.__class__.__name__}",
            ReadExtent(0, 0, scanned, 0),
        )
    return _ok(records, ReadExtent(0, 0, scanned, len(records)), ())


def stored_snapshot_from_record(record: Mapping[str, Any]) -> StoredSnapshot:
    """Rebuild a :class:`StoredSnapshot` from a record this module returned.

    The payload stays an opaque mapping.  Turning it back into a
    ``CriteriaSnapshot`` is an adapter's job in ``criteria.py``, on the other
    side of the import boundary.
    """

    return StoredSnapshot(
        projection_request_id=str(record["projection_request_id"]),
        snapshot_id=str(record["snapshot_id"]),
        projection_version=str(record["projection_version"]),
        scope=ProjectionScope(str(record["scope"])),
        supplied=tuple(record["supplied"]),
        deliverable_tables=tuple(record["deliverable_tables"]),
        run_name=str(record["run_name"]),
        round_index=int(record["round_index"]),
        origin=StoredOrigin(str(record["origin"])),
        payload=record["payload"],
    )


# ---------------------------------------------------------------------------
# Row -> record
# ---------------------------------------------------------------------------


def _ok(
    records: tuple[Mapping[str, Any], ...],
    extent: ReadExtent,
    skips: tuple[SkipRecord, ...],
) -> StoreRead:
    matched = len(records) > 0
    return StoreRead(
        status=ReadStatus.OK,
        records=records,
        extent=extent,
        reason_code=ReasonCode.MATCHED if matched else ReasonCode.NO_MATCHES,
        reason=(
            "the store matched records for this question"
            if matched
            else "the store looked and there are none; see extent for what it examined"
        ),
        skipped=skips,
    )


def _query_event_record(row: sqlite3.Row) -> Mapping[str, Any]:
    sparse = _decode(row["sparse_json"])
    return MappingProxyType(
        {
            "run_name": str(row["run_name"]),
            "record_ordinal": int(row["record_ordinal"]),
            "corpus_id": str(row["corpus_id"]),
            "question_context_id": str(row["question_context_id"]),
            "query": str(row["query"]),
            "query_key": str(row["query_key"]),
            "query_tokens": _decode(row["query_tokens_json"]),
            "tokenizer_version": str(row["tokenizer_version"]),
            "task_id": str(row["task_id"]),
            "topic": str(row["topic"]),
            "gap": str(row["gap"]),
            "round_index": dict(_sparse_column(row, "round_index").to_record()),
            "expansion_op": str(row["expansion_op"]),
            "firecrawl_hits": int(row["firecrawl_hits"]),
            "error": str(row["error"]),
            "target_table": str(row["target_table"]),
            "target_id": str(row["target_id"]),
            "yield": _decode(row["yield_json"]),
            "sparse": sparse,
        }
    )


def _decision_record(row: sqlite3.Row) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "run_name": str(row["run_name"]),
            "record_ordinal": int(row["record_ordinal"]),
            "decision_ordinal": int(row["decision_ordinal"]),
            "url": str(row["url"]),
            "corpus_id": str(row["corpus_id"]),
            "question_context_id": str(row["question_context_id"]),
            "task_id": str(row["task_id"]),
            "topic": str(row["topic"]),
            "target_table": str(row["target_table"]),
            "target_id": str(row["target_id"]),
            "round_index": dict(_sparse_column(row, "round_index").to_record()),
            "accept": dict(_sparse_column(row, "accept").to_record()),
            "confidence": dict(_sparse_column(row, "confidence").to_record()),
            "title": dict(_sparse_column(row, "title").to_record()),
            "decision_reason": dict(_sparse_column(row, "decision_reason").to_record()),
            "payload": _decode(row["payload_json"]),
        }
    )


def _sighting_record(row: sqlite3.Row) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "run_name": str(row["run_name"]),
            "record_ordinal": int(row["record_ordinal"]),
            "sighting_ordinal": int(row["sighting_ordinal"]),
            "url": str(row["url"]),
            "sighting_kind": SightingKind(str(row["sighting_kind"])).value,
            "corpus_id": str(row["corpus_id"]),
            "question_context_id": str(row["question_context_id"]),
            "round_index": dict(_sparse_column(row, "round_index").to_record()),
            "query_key": str(row["query_key"]),
            "rank": dict(_sparse_column(row, "rank").to_record()),
            "title": dict(_sparse_column(row, "title").to_record()),
            "payload": _decode(row["payload_json"]),
        }
    )


def _snapshot_record(row: sqlite3.Row) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "projection_request_id": str(row["projection_request_id"]),
            "snapshot_id": str(row["snapshot_id"]),
            "projection_version": str(row["projection_version"]),
            "scope": ProjectionScope(str(row["scope"])).value,
            "supplied": _decode(row["supplied_json"]),
            "deliverable_tables": _decode(row["deliverable_tables_json"]),
            "run_name": str(row["run_name"]),
            "round_index": int(row["round_index"]),
            "origin": StoredOrigin(str(row["origin"])).value,
            "payload": _decode(row["payload_json"]),
        }
    )
