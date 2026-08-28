"""``run_store`` -- durable, cross-run memory for recorded search and criteria.

Why it exists, measured
-----------------------

The pipeline runs broad web search against a *per-run* memory and tells the
planner "do not repeat a previous query" while showing it a truncated sample of
what has already been tried.  Across 77 parseable
``question_runs/*/fetched_papers/search_outcomes.jsonl`` files (23,240 records,
40.4 MB):

* **21,848 of 23,240 query instances re-issue a query already run somewhere in
  the corpus**, over 2,774 distinct queries.
* The entire recorded history contains **541 distinct URLs** across 14,498
  mentions.  **63% of those URLs appear in more than one run**, and the
  most-repeated one was re-encountered in **46 of 77 runs**.
* **2,471 of 2,783 relevance judgements (88.8%) re-judge an already-judged URL.**
* 16 URLs carry contradictory accept/reject verdicts.  **11 contradict inside a
  single question family; 5 differ only across families**, which is legitimate.
  Hence decisions are keyed by ``(url, question context)``, never by ``url``.

Shape
-----

One typed result, :class:`~run_store.result.StoreRead`, for both sides.  Three
read statuses, because "the store looked and there are none" and "the store
could not answer" are different facts.  Complete matched sets, never samples.
Write-once puts that report a conflict rather than overwriting or dropping it.

What it will never do
---------------------

Import ``question_pipeline``.  Regenerate, recompute, or fall back on a read.
Rank, score, select, sample, window, or budget.  Cache a negative.  Call a
model -- every read is a pure function over stored data.  Slice positionally.
Branch on a ``reason`` string: consumers branch on ``reason_code``, and
``reason`` is terminal.
"""

from __future__ import annotations

from .enumeration import RunEnumeration, enumerate_runs
from .identity import (
    CORPUS_ID_RULE_VERSION,
    PROJECTION_REQUEST_VERSION,
    QUESTION_CONTEXT_VERSION,
    TOKENIZER_VERSION,
    RunRef,
    canonical_json,
    default_corpus_id,
    default_query_key,
    default_query_tokens,
    payload_digest,
    projection_request_id,
    question_context_id,
    fingerprint,
)
from .ingest import (
    DENSE_FIELDS,
    RECOGNIZED_FIELDS,
    SPARSE_PRESENCE_FIELDS,
    SPARSE_VALUE_FIELDS,
    FieldScan,
    FieldScanStatus,
    IngestReport,
    UnrecognizedField,
    ingest_search_outcomes,
)
from .overlap import OverlapCounts, count_overlap, count_overlaps
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
    sparse_absent,
    sparse_from_record,
    sparse_present,
)
from .storage import (
    SearchQueryEvent,
    StoredSnapshot,
    UrlDecision,
    UrlSighting,
    clear_search_index,
    open_store,
    put_criteria_snapshot,
    put_ingest_skip,
    put_ingested_run,
    put_search_query_event,
    put_url_decision,
    put_url_sighting,
    read_prior_queries_by_key,
    read_prior_queries_by_tokens,
    read_query_yield,
    read_snapshots_for_request,
    read_stored_snapshot,
    read_url_decisions,
    read_url_decisions_in_context,
    read_url_sightings,
    stored_snapshot_from_record,
    transaction,
)
from .versioning import (
    MIGRATIONS,
    SCHEMA_VERSION,
    MigrationOutcome,
    MigrationRegistry,
    migrate_payload,
    readability,
)

__all__ = [
    # result contract
    "StoreRead",
    "WriteResult",
    "ReadStatus",
    "WriteStatus",
    "ReasonCode",
    "ReadExtent",
    "SkipRecord",
    "Presence",
    "SparseValue",
    "SightingKind",
    "ProjectionScope",
    "StoredOrigin",
    "ABSENT_VALUE",
    "EMPTY_EXTENT",
    "sparse_present",
    "sparse_absent",
    "sparse_from_record",
    # identity
    "RunRef",
    "TOKENIZER_VERSION",
    "CORPUS_ID_RULE_VERSION",
    "PROJECTION_REQUEST_VERSION",
    "QUESTION_CONTEXT_VERSION",
    "canonical_json",
    "payload_digest",
    "fingerprint",
    "default_query_key",
    "default_query_tokens",
    "default_corpus_id",
    "projection_request_id",
    "question_context_id",
    # enumeration
    "RunEnumeration",
    "enumerate_runs",
    # versioning
    "SCHEMA_VERSION",
    "MIGRATIONS",
    "MigrationRegistry",
    "MigrationOutcome",
    "migrate_payload",
    "readability",
    # overlap
    "OverlapCounts",
    "count_overlap",
    "count_overlaps",
    # storage
    "open_store",
    "transaction",
    "SearchQueryEvent",
    "UrlDecision",
    "UrlSighting",
    "StoredSnapshot",
    "clear_search_index",
    "put_search_query_event",
    "put_url_decision",
    "put_url_sighting",
    "put_criteria_snapshot",
    "put_ingested_run",
    "put_ingest_skip",
    "read_prior_queries_by_key",
    "read_prior_queries_by_tokens",
    "read_query_yield",
    "read_url_decisions",
    "read_url_decisions_in_context",
    "read_url_sightings",
    "read_stored_snapshot",
    "read_snapshots_for_request",
    "stored_snapshot_from_record",
    # ingest
    "IngestReport",
    "ingest_search_outcomes",
    "FieldScan",
    "FieldScanStatus",
    "UnrecognizedField",
    "DENSE_FIELDS",
    "SPARSE_VALUE_FIELDS",
    "SPARSE_PRESENCE_FIELDS",
    "RECOGNIZED_FIELDS",
]
