"""Reading recorded runs into the store.

Why this module exists at all
-----------------------------

The adjudicated layout names six owners: identity, enumeration, versioning,
result, overlap, storage.  Mapping one line of a producer's JSONL onto store
rows belongs to none of them -- ``enumeration`` walks, ``storage`` writes, and
neither should know what ``relevance_decisions`` is.  So the mapping lives here,
in one file, and the boundary is: **ingest knows the producer's record shape;
nothing else in ``run_store`` does.**

Read-only, always
-----------------

``question_runs/`` is never written, never moved, never touched.  Roots arrive
as an argument, so this path is exercised in full against three fake run
directories under ``tmp_path`` with no pipeline, no LLM and no real run.

Tokenizer injection
-------------------

``run_store`` must never import ``question_pipeline``, so the key and token
functions arrive as **injected callables** and their version string is required.
That version is stamped on every row: a tokenizer change then shows up as a
detectable version skew instead of quietly producing keys that no longer mean
what the older keys meant.

The default in :mod:`run_store.identity` is purely structural -- no stopword
list, no domain vocabulary, no truncation.  In particular
``question_pipeline/search_memory.py::_query_terms`` must not be used here: it
ends in ``[:12]``, so two different long queries collapse onto one key.

Absence is UNKNOWN, never zero
------------------------------

Four fields are sparse in the recorded corpus: ``relevance_decisions`` (17,042
of 23,240 records), ``search_result_observations`` (257),
``candidate_source_outcomes`` (257) and ``cost`` (107).  A record without
``cost`` is stored with cost ``ABSENT``, never with zeros.  The producer already
models this correctly -- ``cost`` payloads carry
``provider_credits_available: false`` rather than reporting ``0.0`` as if it had
been measured -- and this follows that pattern.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .enumeration import enumerate_runs
from .identity import RunRef, question_context_id
from .result import (
    Presence,
    ReasonCode,
    SightingKind,
    SkipRecord,
    SparseValue,
    WriteResult,
    WriteStatus,
    sparse_absent,
    sparse_present,
)
from .storage import (
    SearchQueryEvent,
    UrlDecision,
    UrlSighting,
    clear_search_index,
    put_ingest_skip,
    put_ingested_run,
    put_search_query_event,
    put_url_decision,
    put_url_sighting,
    transaction,
)

__all__ = [
    "IngestReport",
    "FieldScan",
    "FieldScanStatus",
    "UnrecognizedField",
    "DENSE_FIELDS",
    "SPARSE_VALUE_FIELDS",
    "SPARSE_PRESENCE_FIELDS",
    "RECOGNIZED_FIELDS",
    "SEARCH_OUTCOMES_RELATIVE_PATH",
    "ingest_search_outcomes",
]


#: Where a run keeps its recorded search attempts, relative to the run dir.
SEARCH_OUTCOMES_RELATIVE_PATH = ("fetched_papers", "search_outcomes.jsonl")

#: The yield fields a producer writes on every record.  Verified present on all
#: 23,240 records of the recorded corpus.
_YIELD_FIELDS = (
    "accepted_source_ids",
    "accepted_urls",
    "duplicate_urls",
    "skipped_by_reason",
    "scrape_failed_urls",
    "text_reductions",
    "metadata",
)

#: Sparse fields stored **by value**: present on some runs, absent on others,
#: and their contents are not exploded into a table of their own.
#:
#: The producer's record shape is still moving, so this is a registry rather
#: than a column per field: landing a new field here is one line, and a field
#: absent from an older run stays ``ABSENT``.  Never backfill a default.  A
#: ``false`` ``yields_sources`` on a run that predates the field would be a
#: fabricated negative -- the same "no signal equals no problem" collapse the
#: whole result contract exists to prevent.
SPARSE_VALUE_FIELDS = (
    "cost",
    "yields_sources",
)

#: Sparse fields stored **by presence**: their contents already become rows in
#: ``url_decisions`` or ``url_sightings``, but *whether the producer wrote the
#: field at all* is a separate fact and is lost if only the rows are kept.
#:
#: "This run predates relevance judging" and "this run judged nothing" are
#: different, and an empty ``url_decisions`` result cannot tell them apart on
#: its own.
SPARSE_PRESENCE_FIELDS = (
    "relevance_decisions",
    "search_result_observations",
    "candidate_source_outcomes",
)

#: Fields read individually by :func:`_ingest_record` into their own columns.
DENSE_FIELDS = (
    "task_id",
    "query",
    "topic",
    "expansion_op",
    "gap",
    "round_index",
    "firecrawl_hits",
    "error",
)

#: Every top-level key this module knows how to read, derived from the four
#: registries above rather than hand-listed.  A hand-listed fifth copy would
#: reintroduce exactly the drift the field scan exists to detect.
RECOGNIZED_FIELDS = frozenset(
    DENSE_FIELDS + _YIELD_FIELDS + SPARSE_VALUE_FIELDS + SPARSE_PRESENCE_FIELDS
)


class FieldScanStatus(Enum):
    """Whether the unrecognized-field scan actually ran.

    ``SCANNED`` with no fields is the positive fact "every key in every record
    was recognized".  ``NOT_SCANNED`` means no record was read, so the empty
    result proves nothing -- the same three-status discipline as
    :class:`~run_store.result.StoreRead`, one level down.
    """

    SCANNED = "scanned"
    NOT_SCANNED = "not_scanned"


@dataclass(frozen=True)
class UnrecognizedField:
    """One top-level key the producer wrote that this module does not read."""

    name: str
    record_count: int


@dataclass(frozen=True)
class FieldScan:
    """What ingest found that it did not know how to read.

    A fixed list of field names cannot report its own blind spot.  This is the
    mechanism that makes it report one.

    The failure this prevents was observed in a neighbouring investigation: a
    citation count came out 14 against a true figure of 17, because three
    sources were cited under dynamically-named ``<field>_source_chunks`` keys
    that the harvest's fixed name list could not match.  The measurement was not
    wrong about the file it read -- it was wrong about what it had failed to
    look for, and it reported a confident number anyway.

    ``question_pipeline`` is actively landing changes to ``search_outcomes.jsonl``.
    Without this, the next field they add would be dropped while ingest reported
    success, which is "no signal" and "no problem" becoming one observable
    inside the package built to prevent that.

    An unrecognized field is **not** an error and never fails the ingest: it is
    a newer producer, not corruption.  Ingest indexes everything it recognizes
    and reports the rest.  Refusing would be as wrong as ignoring.
    """

    status: FieldScanStatus
    fields: tuple[UnrecognizedField, ...]
    records_examined: int
    recognized_names: tuple[str, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)


@dataclass(frozen=True)
class IngestReport:
    """What one ingest pass actually did.  Counts, plus every skip by name."""

    runs_enumerated: int
    runs_ingested: int
    runs_skipped: int
    records_read: int
    records_unparseable: int
    events_stored: int
    events_already_stored: int
    decisions_stored: int
    sightings_stored: int
    conflicts: tuple[WriteResult, ...]
    skipped: tuple[SkipRecord, ...]
    unrecognized_fields: FieldScan


def ingest_search_outcomes(
    conn: sqlite3.Connection,
    roots: Sequence[str | Path] | Iterable[str | Path],
    *,
    query_key_of: Callable[[str], str],
    query_tokens_of: Callable[[str], tuple[str, ...]],
    tokenizer_version: str,
    rebuild: bool,
) -> IngestReport:
    """Take every recorded search attempt under ``roots`` into ``conn``.

    ``rebuild`` is a write-side instruction, not a read-side fallback: when
    true, the search tables are emptied first and re-derived from the
    filesystem.  That is sound here and only here, because a full scan of the
    recorded corpus costs 0.24 s at 12 MB peak RSS -- cheaper than validating
    staleness -- and because every search row is re-derivable from a file that
    is never rewritten.  The snapshot side is never rebuilt and this function
    does not touch it.
    """

    if rebuild:
        clear_search_index(conn)

    enumeration = enumerate_runs(roots)
    skips: list[SkipRecord] = list(enumeration.skipped)
    conflicts: list[WriteResult] = []

    unrecognized: Counter[str] = Counter()
    runs_ingested = 0
    records_read = 0
    records_unparseable = 0
    events_stored = 0
    events_already = 0
    decisions_stored = 0
    sightings_stored = 0

    for run in enumeration.runs:
        outcomes_path = Path(run.run_dir)
        for part in SEARCH_OUTCOMES_RELATIVE_PATH:
            outcomes_path = outcomes_path / part
        if not outcomes_path.exists():
            skips.append(
                SkipRecord(
                    path=str(outcomes_path),
                    reason_code=ReasonCode.RUN_OUTCOMES_MISSING,
                    reason="run directory has no recorded search outcomes file",
                )
            )
            continue
        try:
            raw_lines = outcomes_path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            skips.append(
                SkipRecord(
                    path=str(outcomes_path),
                    reason_code=ReasonCode.RUN_OUTCOMES_UNREADABLE,
                    reason=(
                        f"recorded search outcomes could not be read: "
                        f"{error.__class__.__name__}"
                    ),
                )
            )
            continue

        run_records = 0
        with transaction(conn):
            for ordinal, line in enumerate(raw_lines):
                stripped = line.strip()
                if stripped == "":
                    continue
                try:
                    record = json.loads(stripped)
                except (ValueError, TypeError):
                    records_unparseable = records_unparseable + 1
                    skips.append(
                        SkipRecord(
                            path=f"{outcomes_path}#{ordinal}",
                            reason_code=ReasonCode.RECORD_UNPARSEABLE,
                            reason="line is not valid JSON",
                        )
                    )
                    continue
                if not isinstance(record, Mapping):
                    records_unparseable = records_unparseable + 1
                    skips.append(
                        SkipRecord(
                            path=f"{outcomes_path}#{ordinal}",
                            reason_code=ReasonCode.RECORD_UNPARSEABLE,
                            reason="line is valid JSON but is not an object",
                        )
                    )
                    continue

                run_records = run_records + 1
                records_read = records_read + 1
                # Every top-level key the producer wrote that no registry
                # mentions.  Counted, never dropped, never fatal.
                unrecognized.update(set(record) - RECOGNIZED_FIELDS)
                counts = _ingest_record(
                    conn,
                    run=run,
                    record_ordinal=ordinal,
                    record=record,
                    query_key_of=query_key_of,
                    query_tokens_of=query_tokens_of,
                    tokenizer_version=tokenizer_version,
                    conflicts=conflicts,
                )
                events_stored = events_stored + counts.events_stored
                events_already = events_already + counts.events_already
                decisions_stored = decisions_stored + counts.decisions_stored
                sightings_stored = sightings_stored + counts.sightings_stored

            run_write = put_ingested_run(conn, run, run_records)
            if run_write.status is WriteStatus.CONFLICT:
                conflicts.append(run_write)
        runs_ingested = runs_ingested + 1

    with transaction(conn):
        for skip in skips:
            put_ingest_skip(conn, skip)

    return IngestReport(
        runs_enumerated=enumeration.runs_enumerated,
        runs_ingested=runs_ingested,
        runs_skipped=len(skips),
        records_read=records_read,
        records_unparseable=records_unparseable,
        events_stored=events_stored,
        events_already_stored=events_already,
        decisions_stored=decisions_stored,
        sightings_stored=sightings_stored,
        conflicts=tuple(conflicts),
        skipped=tuple(skips),
        unrecognized_fields=FieldScan(
            status=(
                FieldScanStatus.SCANNED
                if records_read > 0
                else FieldScanStatus.NOT_SCANNED
            ),
            fields=tuple(
                UnrecognizedField(name=name, record_count=unrecognized[name])
                for name in sorted(unrecognized)
            ),
            records_examined=records_read,
            recognized_names=tuple(sorted(RECOGNIZED_FIELDS)),
        ),
    )


@dataclass(frozen=True)
class _RecordCounts:
    events_stored: int
    events_already: int
    decisions_stored: int
    sightings_stored: int


def _ingest_record(
    conn: sqlite3.Connection,
    *,
    run: RunRef,
    record_ordinal: int,
    record: Mapping[str, Any],
    query_key_of: Callable[[str], str],
    query_tokens_of: Callable[[str], tuple[str, ...]],
    tokenizer_version: str,
    conflicts: list[WriteResult],
) -> _RecordCounts:
    metadata = record.get("metadata")
    metadata_map = metadata if isinstance(metadata, Mapping) else {}
    query = _text(record.get("query"))
    query_key = query_key_of(query)
    query_tokens = tuple(query_tokens_of(query))
    task_id = _text(record.get("task_id"))
    topic = _text(record.get("topic"))
    target_table = _text(metadata_map.get("target_table"))
    target_id = _text(metadata_map.get("target_id"))
    round_index = _sparse_int(record, "round_index")
    context = question_context_id(
        corpus_id=run.corpus_id,
        task_id=task_id,
        topic=topic,
        target_table=target_table,
        target_id=target_id,
    )

    event = SearchQueryEvent(
        run_name=run.run_name,
        record_ordinal=record_ordinal,
        corpus_id=run.corpus_id,
        question_context_id=context,
        query=query,
        query_key=query_key,
        query_tokens=query_tokens,
        tokenizer_version=tokenizer_version,
        task_id=task_id,
        topic=topic,
        gap=_text(record.get("gap")),
        round_index=round_index,
        expansion_op=_text(record.get("expansion_op")),
        firecrawl_hits=_hits(record.get("firecrawl_hits")),
        error=_text(record.get("error")),
        target_table=target_table,
        target_id=target_id,
        query_yield={name: record.get(name) for name in _YIELD_FIELDS},
        sparse=_sparse_registry(record),
    )
    event_write = put_search_query_event(conn, event)
    if event_write.status is WriteStatus.CONFLICT:
        conflicts.append(event_write)

    decisions_stored = 0
    for position, decision in enumerate(_sequence(record.get("relevance_decisions"))):
        if not isinstance(decision, Mapping):
            continue
        url = _text(decision.get("url"))
        if url == "":
            continue
        write = put_url_decision(
            conn,
            UrlDecision(
                run_name=run.run_name,
                record_ordinal=record_ordinal,
                decision_ordinal=position,
                url=url,
                corpus_id=run.corpus_id,
                question_context_id=context,
                task_id=task_id,
                topic=topic,
                target_table=target_table,
                target_id=target_id,
                round_index=round_index,
                accept=_sparse_bool(decision, "accept"),
                confidence=_sparse(decision, "confidence"),
                title=_sparse(decision, "title"),
                decision_reason=_sparse(decision, "reason"),
                payload=dict(decision),
            ),
        )
        if write.status is WriteStatus.CONFLICT:
            conflicts.append(write)
        if write.status is WriteStatus.STORED:
            decisions_stored = decisions_stored + 1

    sighting_ordinal = 0
    sightings_stored = 0
    for kind, entries in _sighting_sources(record):
        for entry in entries:
            url = _sighting_url(entry)
            if url == "":
                continue
            write = put_url_sighting(
                conn,
                UrlSighting(
                    run_name=run.run_name,
                    record_ordinal=record_ordinal,
                    sighting_ordinal=sighting_ordinal,
                    url=url,
                    sighting_kind=kind,
                    corpus_id=run.corpus_id,
                    question_context_id=context,
                    round_index=round_index,
                    query_key=query_key,
                    rank=_sighting_rank(entry),
                    title=_sighting_title(entry),
                    payload=entry if isinstance(entry, Mapping) else {"url": url},
                ),
            )
            sighting_ordinal = sighting_ordinal + 1
            if write.status is WriteStatus.CONFLICT:
                conflicts.append(write)
            if write.status is WriteStatus.STORED:
                sightings_stored = sightings_stored + 1

    return _RecordCounts(
        events_stored=1 if event_write.status is WriteStatus.STORED else 0,
        events_already=1 if event_write.status is WriteStatus.ALREADY_STORED else 0,
        decisions_stored=decisions_stored,
        sightings_stored=sightings_stored,
    )


def _sighting_sources(
    record: Mapping[str, Any]
) -> tuple[tuple[SightingKind, tuple[Any, ...]], ...]:
    """Every way this record says a URL was encountered, in a fixed order.

    The order is fixed in code so ``sighting_ordinal`` is reproducible across
    ingests of the same file, which is what makes the write-once key stable.
    """

    return (
        (
            SightingKind.SEARCH_RESULT,
            _sequence(record.get("search_result_observations")),
        ),
        (
            SightingKind.CANDIDATE_SOURCE,
            _sequence(record.get("candidate_source_outcomes")),
        ),
        (SightingKind.ACCEPTED, _sequence(record.get("accepted_urls"))),
        (SightingKind.DUPLICATE, _sequence(record.get("duplicate_urls"))),
        (SightingKind.SCRAPE_FAILED, _sequence(record.get("scrape_failed_urls"))),
    )


def _sighting_url(entry: Any) -> str:
    if isinstance(entry, Mapping):
        return _text(entry.get("url"))
    return _text(entry)


def _sighting_rank(entry: Any) -> SparseValue:
    if isinstance(entry, Mapping):
        return _sparse(entry, "rank")
    return sparse_absent()


def _sighting_title(entry: Any) -> SparseValue:
    if isinstance(entry, Mapping):
        return _sparse(entry, "title")
    return sparse_absent()


def _sparse_registry(record: Mapping[str, Any]) -> Mapping[str, SparseValue]:
    """Every registered sparse field of ``record``, present or absent, by name.

    Absence is carried as ``ABSENT``.  Nothing is invented for a run that
    predates a field.
    """

    collected: dict[str, SparseValue] = {
        name: _sparse(record, name) for name in SPARSE_VALUE_FIELDS
    }
    for name in SPARSE_PRESENCE_FIELDS:
        observed = _sparse(record, name)
        if observed.presence is Presence.ABSENT:
            collected[name] = observed
        else:
            collected[name] = sparse_present({"count": len(_sequence(record[name]))})
    return collected


def _sparse_int(source: Mapping[str, Any], name: str) -> SparseValue:
    """An integer field that may legitimately be absent.

    Sized for the corpus this store will hold, not the one it holds now.
    Upstream round-index stamping is landing mid-corpus, so the historical tail
    will genuinely lack the field while newer runs carry it, and both must
    coexist without a migration.

    A record with no ``round_index`` must not read as round 0.  That is a
    fabricated fact about when the search happened, in a field downstream code
    orders and groups by.
    """

    observed = _sparse(source, name)
    if observed.presence is Presence.ABSENT:
        return observed
    try:
        return sparse_present(int(observed.value))
    except (TypeError, ValueError):
        return sparse_absent()


def _sparse(source: Mapping[str, Any], name: str) -> SparseValue:
    """``name`` as a sparse field: absent stays absent, never becomes a zero."""

    if name not in source:
        return sparse_absent()
    value = source[name]
    if value is None:
        return sparse_absent()
    return sparse_present(value)


def _sparse_bool(source: Mapping[str, Any], name: str) -> SparseValue:
    value = _sparse(source, name)
    if value.presence is Presence.ABSENT:
        return value
    return sparse_present(1 if bool(value.value) else 0)


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


def _hits(value: Any) -> int:
    """``firecrawl_hits`` is dense -- verified on all 23,240 recorded records.

    It is an integer column rather than a sparse field for that reason.  A
    non-integer here is a malformed record, not an absent field, and reads as 0
    only because the record is already broken in a way the skip machinery will
    not see.
    """

    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)
