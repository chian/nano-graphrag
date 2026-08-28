"""Durable exact-span evidence acceptance for acquisition and criteria.

The registry is the authority boundary between extracted candidates and
incidence.  One page is committed in two ordered durable records:

1. its exact source blob, source/version/chunk/span anchors, and assertion
   candidates are persisted and fsynced;
2. deterministic direct-assertion acceptances are appended and fsynced.

Only an :class:`AcceptedCell` returned from the second commit may become an
incidence credit.  A crash between the commits leaves auditable candidates and
no creditable acceptance.  The module performs no model call and contains no
semantic fallback over graph edges, source references, or populated cells.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .control import stable_id

EVIDENCE_REGISTRY_VERSION = "evidence_registry_v1"
DIRECT_ACCEPTANCE_RULE_VERSION = "direct_exact_span_acceptance_v1"
BEST_GUESS_CELL_VERSION = "best_guess_cell_v1"
SOURCE_BATCH_VERSION = "source_assertion_batch_v1"
ACCEPTANCE_BATCH_VERSION = "acceptance_batch_v1"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _required(name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


@dataclass(frozen=True)
class BestGuessCellRef:
    """Stable address reserved for a future accepted derived cell.

    This phase creates the address only.  It deliberately defines no
    derivation, acceptance, or incidence route.
    """

    id: str
    criterion_id: str

    @classmethod
    def create(cls, criterion_id: str) -> "BestGuessCellRef":
        criterion = _required("criterion_id", criterion_id)
        return cls(
            id=stable_id(
                {"version": BEST_GUESS_CELL_VERSION, "criterion_id": criterion}
            ),
            criterion_id=criterion,
        )


@dataclass(frozen=True)
class SourceDocument:
    id: str
    source_id: str
    canonical_locator: str
    title: str = ""

    @classmethod
    def create(
        cls, source_id: str, canonical_locator: str, title: str = ""
    ) -> "SourceDocument":
        source = _required("source_id", source_id)
        locator = _required("canonical_locator", canonical_locator or source)
        return cls(
            id=stable_id(
                {
                    "version": EVIDENCE_REGISTRY_VERSION,
                    "source_id": source,
                    "canonical_locator": locator,
                }
            ),
            source_id=source,
            canonical_locator=locator,
            title=str(title or ""),
        )


@dataclass(frozen=True)
class SourceVersion:
    id: str
    source_document_id: str
    content_sha256: str
    text_chars: int

    @classmethod
    def create(cls, source_document_id: str, content: str) -> "SourceVersion":
        document = _required("source_document_id", source_document_id)
        digest = _sha256(content)
        return cls(
            id=stable_id(
                {
                    "version": EVIDENCE_REGISTRY_VERSION,
                    "source_document_id": document,
                    "content_sha256": digest,
                }
            ),
            source_document_id=document,
            content_sha256=digest,
            text_chars=len(content),
        )


@dataclass(frozen=True)
class SourceChunk:
    id: str
    source_version_id: str
    index: int
    start_offset: int
    end_offset: int
    text_sha256: str
    text: str

    @classmethod
    def create(
        cls,
        source_version_id: str,
        index: int,
        start_offset: int,
        end_offset: int,
        text: str,
    ) -> "SourceChunk":
        if start_offset < 0 or end_offset < start_offset:
            raise ValueError("chunk offsets must satisfy 0 <= start <= end")
        if end_offset - start_offset != len(text):
            raise ValueError("chunk offsets must describe the exact chunk text")
        version = _required("source_version_id", source_version_id)
        digest = _sha256(text)
        return cls(
            id=stable_id(
                {
                    "version": EVIDENCE_REGISTRY_VERSION,
                    "source_version_id": version,
                    "index": int(index),
                    "start_offset": int(start_offset),
                    "end_offset": int(end_offset),
                    "text_sha256": digest,
                }
            ),
            source_version_id=version,
            index=int(index),
            start_offset=int(start_offset),
            end_offset=int(end_offset),
            text_sha256=digest,
            text=text,
        )


@dataclass(frozen=True)
class TextSpan:
    id: str
    source_version_id: str
    chunk_id: str
    start_offset: int
    end_offset: int
    chunk_start_offset: int
    chunk_end_offset: int
    text_sha256: str
    text: str

    @classmethod
    def create(
        cls, chunk: SourceChunk, chunk_start_offset: int, chunk_end_offset: int
    ) -> "TextSpan":
        if not 0 <= chunk_start_offset < chunk_end_offset <= len(chunk.text):
            raise ValueError("span offsets must identify non-empty text in the chunk")
        text = chunk.text[chunk_start_offset:chunk_end_offset]
        start = chunk.start_offset + chunk_start_offset
        end = chunk.start_offset + chunk_end_offset
        digest = _sha256(text)
        return cls(
            id=stable_id(
                {
                    "version": EVIDENCE_REGISTRY_VERSION,
                    "source_version_id": chunk.source_version_id,
                    "chunk_id": chunk.id,
                    "start_offset": start,
                    "end_offset": end,
                    "text_sha256": digest,
                }
            ),
            source_version_id=chunk.source_version_id,
            chunk_id=chunk.id,
            start_offset=start,
            end_offset=end,
            chunk_start_offset=chunk_start_offset,
            chunk_end_offset=chunk_end_offset,
            text_sha256=digest,
            text=text,
        )


@dataclass(frozen=True)
class DirectAssertionCandidate:
    id: str
    table_id: str
    table: str
    column_id: str
    column: str
    subject_id: str
    subject_bound: bool
    criterion_id: str
    source_id: str
    source_document_id: str
    source_version_id: str
    chunk_id: str
    span_id: str
    verbatim_text: str
    value_json: str
    normalized_value: str
    value_type: str
    unit: str
    field_name: str
    match_rule: str

    @classmethod
    def create(cls, **values: Any) -> "DirectAssertionCandidate":
        payload = {
            key: values[key]
            for key in (
                "table_id",
                "column_id",
                "subject_id",
                "criterion_id",
                "source_version_id",
                "span_id",
                "verbatim_text",
                "value_json",
                "normalized_value",
                "value_type",
                "unit",
                "field_name",
                "match_rule",
            )
        }
        return cls(
            id=stable_id(
                {"version": EVIDENCE_REGISTRY_VERSION, "assertion": payload}
            ),
            **values,
        )


@dataclass(frozen=True)
class AcceptanceRecord:
    id: str
    assertion_id: str
    criterion_id: str
    source_document_id: str
    source_version_id: str
    chunk_id: str
    span_id: str
    supporting_text_sha256: str
    rule_version: str = DIRECT_ACCEPTANCE_RULE_VERSION


@dataclass(frozen=True)
class AcceptedCell:
    """A direct cell whose complete persisted assertion chain was accepted."""

    id: str
    table_id: str
    table: str
    column_id: str
    column: str
    subject_id: str
    criterion_id: str
    value_json: str
    normalized_value: str
    value_type: str
    unit: str
    assertion_id: str
    acceptance_id: str
    source_id: str
    source_document_id: str
    source_version_id: str
    chunk_id: str
    span_id: str
    supporting_text_sha256: str
    acceptance_rule_version: str = DIRECT_ACCEPTANCE_RULE_VERSION


@dataclass(frozen=True)
class RowCompletionAcceptance:
    id: str
    table_id: str
    table: str
    subject_id: str
    required_column_ids: tuple[str, ...]
    accepted_cell_ids: tuple[str, ...]
    acceptance_rule_version: str = DIRECT_ACCEPTANCE_RULE_VERSION


@dataclass(frozen=True)
class EvidenceCommit:
    source_batch_id: str
    accepted_cells: tuple[AcceptedCell, ...] = ()
    completed_rows: tuple[RowCompletionAcceptance, ...] = ()
    rejected_assertion_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_batch_id": self.source_batch_id,
            "accepted_cells": [asdict(item) for item in self.accepted_cells],
            "completed_rows": [asdict(item) for item in self.completed_rows],
            "rejected_assertion_ids": list(self.rejected_assertion_ids),
        }


class EvidenceRegistry:
    """Append-only source/assertion and acceptance ledgers under one directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.blobs_dir = self.root / "blobs"
        self.source_ledger = self.root / "source_assertions.jsonl"
        self.acceptance_ledger = self.root / "acceptances.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def source_records(
        *,
        source_id: str,
        canonical_locator: str,
        title: str,
        content: str,
        chunks: Iterable[Mapping[str, Any]],
    ) -> tuple[SourceDocument, SourceVersion, tuple[SourceChunk, ...]]:
        document = SourceDocument.create(source_id, canonical_locator, title)
        version = SourceVersion.create(document.id, content)
        records: list[SourceChunk] = []
        for item in chunks:
            start = int(item.get("start_offset") or 0)
            end = int(item.get("end_offset") or 0)
            text = str(item.get("text") or "")
            if content[start:end] != text:
                raise ValueError("chunk text does not match the source-version blob")
            records.append(
                SourceChunk.create(
                    version.id,
                    int(item.get("chunk_index") or 0),
                    start,
                    end,
                    text,
                )
            )
        return document, version, tuple(records)

    def register_source_candidates(
        self,
        *,
        document: SourceDocument,
        version: SourceVersion,
        content: str,
        chunks: Iterable[SourceChunk],
        spans: Iterable[TextSpan],
        candidates: Iterable[DirectAssertionCandidate],
    ) -> str:
        """Durably commit the source blob and all candidate anchors first."""

        if _sha256(content) != version.content_sha256:
            raise ValueError("source content does not match SourceVersion")
        chunk_tuple = tuple(chunks)
        span_tuple = tuple(spans)
        candidate_tuple = tuple(candidates)
        chunks_by_id = {item.id: item for item in chunk_tuple}
        spans_by_id = {item.id: item for item in span_tuple}
        for span in span_tuple:
            chunk = chunks_by_id.get(span.chunk_id)
            if chunk is None or chunk.source_version_id != version.id:
                raise ValueError("span does not resolve to this source version")
            if chunk.text[span.chunk_start_offset:span.chunk_end_offset] != span.text:
                raise ValueError("span text does not match its exact chunk slice")
        for candidate in candidate_tuple:
            span = spans_by_id.get(candidate.span_id)
            if (
                span is None
                or candidate.source_id != document.source_id
                or candidate.source_document_id != document.id
                or candidate.source_version_id != version.id
                or candidate.chunk_id != span.chunk_id
            ):
                raise ValueError("assertion candidate does not resolve its source chain")

        blob_path = self.blobs_dir / f"{version.content_sha256}.txt"
        self._write_blob(blob_path, content)
        payload = {
            "registry_version": EVIDENCE_REGISTRY_VERSION,
            "batch_version": SOURCE_BATCH_VERSION,
            "document": asdict(document),
            "source_version": asdict(version),
            "blob_path": str(blob_path.relative_to(self.root)),
            "chunks": [asdict(item) for item in chunk_tuple],
            "spans": [asdict(item) for item in span_tuple],
            "assertion_candidates": [asdict(item) for item in candidate_tuple],
        }
        batch_id = stable_id({"version": SOURCE_BATCH_VERSION, "payload": payload})
        existing = self._source_batches().get(batch_id)
        if existing is not None:
            if existing != {"source_batch_id": batch_id, **payload}:
                raise ValueError("stable source batch id conflicts with durable payload")
            return batch_id
        self._append_fsync(self.source_ledger, {"source_batch_id": batch_id, **payload})
        return batch_id

    def accept_direct(
        self,
        source_batch_id: str,
        *,
        required_columns_by_table: Mapping[str, Iterable[str]],
    ) -> EvidenceCommit:
        """Validate, append, and fsync direct acceptances as the second commit."""

        required_contract = {
            str(table_id): list(dict.fromkeys(str(item) for item in columns))
            for table_id, columns in sorted(required_columns_by_table.items())
        }
        batch = self._source_batches().get(source_batch_id)
        if batch is None:
            raise LookupError(f"unknown source assertion batch {source_batch_id!r}")
        existing = self._acceptance_batches_by_source().get(source_batch_id)
        if existing is not None:
            if existing.get("required_columns_by_table") != required_contract:
                raise ValueError(
                    "accepted source batch cannot be retried under a different "
                    "required-column contract"
                )
            for durable_batch, durable_commit in self._validated_commits():
                if str(durable_batch.get("source_batch_id") or "") == source_batch_id:
                    return durable_commit
            raise ValueError("durable acceptance batch did not resolve its full chain")
        spans = {
            str(item["id"]): item for item in batch.get("spans") or ()
            if isinstance(item, Mapping)
        }
        candidates = [
            DirectAssertionCandidate(**item)
            for item in batch.get("assertion_candidates") or ()
            if isinstance(item, Mapping)
        ]
        accepted_cells: list[AcceptedCell] = []
        rejected: list[str] = []
        acceptance_rows: list[dict[str, Any]] = []
        for candidate in candidates:
            span = spans.get(candidate.span_id)
            exact = bool(
                span
                and str(span.get("text") or "")
                == candidate.verbatim_text
                and _sha256(str(span.get("text") or ""))
                == str(span.get("text_sha256") or "")
                and candidate.subject_bound
            )
            if not exact:
                rejected.append(candidate.id)
                continue
            acceptance = AcceptanceRecord(
                id=stable_id(
                    {
                        "version": DIRECT_ACCEPTANCE_RULE_VERSION,
                        "assertion_id": candidate.id,
                    }
                ),
                assertion_id=candidate.id,
                criterion_id=candidate.criterion_id,
                source_document_id=candidate.source_document_id,
                source_version_id=candidate.source_version_id,
                chunk_id=candidate.chunk_id,
                span_id=candidate.span_id,
                supporting_text_sha256=str(span["text_sha256"]),
            )
            cell = AcceptedCell(
                id=stable_id(
                    {
                        "version": EVIDENCE_REGISTRY_VERSION,
                        "criterion_id": candidate.criterion_id,
                        "kind": "direct_cell",
                    }
                ),
                table_id=candidate.table_id,
                table=candidate.table,
                column_id=candidate.column_id,
                column=candidate.column,
                subject_id=candidate.subject_id,
                criterion_id=candidate.criterion_id,
                value_json=candidate.value_json,
                normalized_value=candidate.normalized_value,
                value_type=candidate.value_type,
                unit=candidate.unit,
                assertion_id=candidate.id,
                acceptance_id=acceptance.id,
                source_id=candidate.source_id,
                source_document_id=candidate.source_document_id,
                source_version_id=candidate.source_version_id,
                chunk_id=candidate.chunk_id,
                span_id=candidate.span_id,
                supporting_text_sha256=str(span["text_sha256"]),
            )
            accepted_cells.append(cell)
            acceptance_rows.append(
                {"acceptance": asdict(acceptance), "accepted_cell": asdict(cell)}
            )

        prior_cells = self.accepted_cells()
        all_cells = [*prior_cells, *accepted_cells]
        completed_subjects = {
            (item.table_id, item.subject_id) for item in self.completed_rows()
        }
        completed_rows: list[RowCompletionAcceptance] = []
        subjects = {
            (cell.table_id, cell.table, cell.subject_id)
            for cell in accepted_cells
            if (cell.table_id, cell.subject_id) not in completed_subjects
        }
        for table_id, table, subject_id in sorted(subjects):
            required = tuple(required_contract.get(table_id) or ())
            if not required:
                continue
            cells = [
                cell
                for cell in all_cells
                if cell.table_id == table_id and cell.subject_id == subject_id
            ]
            if not set(required) <= {cell.column_id for cell in cells}:
                continue
            selected = tuple(
                sorted(
                    {
                        cell.id
                        for cell in cells
                        if cell.column_id in set(required)
                    }
                )
            )
            completed_rows.append(
                RowCompletionAcceptance(
                    id=stable_id(
                        {
                            "version": DIRECT_ACCEPTANCE_RULE_VERSION,
                            "table_id": table_id,
                            "subject_id": subject_id,
                            "required_column_ids": list(required),
                        }
                    ),
                    table_id=table_id,
                    table=table,
                    subject_id=subject_id,
                    required_column_ids=required,
                    accepted_cell_ids=selected,
                )
            )

        payload = {
            "registry_version": EVIDENCE_REGISTRY_VERSION,
            "batch_version": ACCEPTANCE_BATCH_VERSION,
            "source_batch_id": source_batch_id,
            "required_columns_by_table": required_contract,
            "accepted": acceptance_rows,
            "completed_rows": [asdict(item) for item in completed_rows],
            "rejected_assertion_ids": rejected,
        }
        acceptance_batch_id = stable_id(
            {"version": ACCEPTANCE_BATCH_VERSION, "payload": payload}
        )
        self._append_fsync(
            self.acceptance_ledger,
            {"acceptance_batch_id": acceptance_batch_id, **payload},
        )
        return EvidenceCommit(
            source_batch_id=source_batch_id,
            accepted_cells=tuple(accepted_cells),
            completed_rows=tuple(completed_rows),
            rejected_assertion_ids=tuple(rejected),
        )

    def _acceptance_batches_by_source(self) -> dict[str, dict[str, Any]]:
        return {
            str(item.get("source_batch_id") or ""): item
            for item in self._read_jsonl(self.acceptance_ledger)
            if str(item.get("source_batch_id") or "")
        }

    @staticmethod
    def _commit_from_acceptance_batch(batch: Mapping[str, Any]) -> EvidenceCommit:
        cells = tuple(
            AcceptedCell(**row["accepted_cell"])
            for row in batch.get("accepted") or ()
            if isinstance(row, Mapping)
            and isinstance(row.get("accepted_cell"), Mapping)
        )
        rows: list[RowCompletionAcceptance] = []
        for row in batch.get("completed_rows") or ():
            if not isinstance(row, Mapping):
                continue
            payload = dict(row)
            payload["required_column_ids"] = tuple(
                payload.get("required_column_ids") or ()
            )
            payload["accepted_cell_ids"] = tuple(
                payload.get("accepted_cell_ids") or ()
            )
            rows.append(RowCompletionAcceptance(**payload))
        return EvidenceCommit(
            source_batch_id=str(batch.get("source_batch_id") or ""),
            accepted_cells=cells,
            completed_rows=tuple(rows),
            rejected_assertion_ids=tuple(
                str(item) for item in batch.get("rejected_assertion_ids") or ()
            ),
        )

    def accepted_cells(self) -> tuple[AcceptedCell, ...]:
        return tuple(
            cell
            for _batch, commit in self._validated_commits()
            for cell in commit.accepted_cells
        )

    def completed_rows(self) -> tuple[RowCompletionAcceptance, ...]:
        return tuple(
            row
            for _batch, commit in self._validated_commits()
            for row in commit.completed_rows
        )

    def _validated_commits(
        self,
    ) -> tuple[tuple[dict[str, Any], EvidenceCommit], ...]:
        """Resolve every acceptance through its durable source chain."""

        source_batches = self._source_batches()
        known_cells: dict[str, AcceptedCell] = {}
        completed_subjects: set[tuple[str, str]] = set()
        out: list[tuple[dict[str, Any], EvidenceCommit]] = []
        for batch in self._read_jsonl(self.acceptance_ledger):
            source_batch_id = str(batch.get("source_batch_id") or "")
            source_batch = source_batches.get(source_batch_id)
            if source_batch is None:
                raise ValueError(
                    f"acceptance batch references missing source batch {source_batch_id!r}"
                )
            commit = self._validate_acceptance_batch(
                batch,
                source_batch,
                known_cells=known_cells,
                completed_subjects=completed_subjects,
            )
            for cell in commit.accepted_cells:
                known_cells[cell.id] = cell
            completed_subjects.update(
                (row.table_id, row.subject_id) for row in commit.completed_rows
            )
            out.append((batch, commit))
        return tuple(out)

    def _validate_acceptance_batch(
        self,
        batch: Mapping[str, Any],
        source_batch: Mapping[str, Any],
        *,
        known_cells: Mapping[str, AcceptedCell],
        completed_subjects: set[tuple[str, str]],
    ) -> EvidenceCommit:
        source_payload = dict(source_batch)
        source_batch_id = str(source_payload.pop("source_batch_id", "") or "")
        if stable_id({"version": SOURCE_BATCH_VERSION, "payload": source_payload}) != source_batch_id:
            raise ValueError("source batch content does not match its stable id")

        document = SourceDocument(**dict(source_batch.get("document") or {}))
        version = SourceVersion(**dict(source_batch.get("source_version") or {}))
        if SourceDocument.create(
            document.source_id, document.canonical_locator, document.title
        ) != document:
            raise ValueError("source document does not match its stable identity")
        blob_relative = Path(str(source_batch.get("blob_path") or ""))
        blob_path = (self.root / blob_relative).resolve()
        root = self.root.resolve()
        if root != blob_path and root not in blob_path.parents:
            raise ValueError("source batch blob path escapes the evidence registry")
        try:
            content = blob_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError("accepted source blob is missing or unreadable") from exc
        if SourceVersion.create(document.id, content) != version:
            raise ValueError("source version does not resolve to the durable blob")

        chunks: dict[str, SourceChunk] = {}
        for raw in source_batch.get("chunks") or ():
            chunk = SourceChunk(**dict(raw))
            expected = SourceChunk.create(
                version.id,
                chunk.index,
                chunk.start_offset,
                chunk.end_offset,
                chunk.text,
            )
            if expected != chunk or content[chunk.start_offset:chunk.end_offset] != chunk.text:
                raise ValueError("source chunk does not resolve to its source version")
            chunks[chunk.id] = chunk

        spans: dict[str, TextSpan] = {}
        for raw in source_batch.get("spans") or ():
            span = TextSpan(**dict(raw))
            chunk = chunks.get(span.chunk_id)
            if chunk is None:
                raise ValueError("text span references a missing source chunk")
            expected = TextSpan.create(
                chunk, span.chunk_start_offset, span.chunk_end_offset
            )
            if expected != span:
                raise ValueError("text span does not resolve to its exact chunk slice")
            spans[span.id] = span

        candidates: dict[str, DirectAssertionCandidate] = {}
        for raw in source_batch.get("assertion_candidates") or ():
            values = dict(raw)
            candidate_id = str(values.pop("id", "") or "")
            candidate = DirectAssertionCandidate.create(**values)
            span = spans.get(candidate.span_id)
            if candidate.id != candidate_id or span is None:
                raise ValueError("assertion candidate does not match its stable source chain")
            if (
                not candidate.subject_bound
                or
                candidate.source_id != document.source_id
                or candidate.source_document_id != document.id
                or candidate.source_version_id != version.id
                or candidate.chunk_id != span.chunk_id
                or candidate.verbatim_text != span.text
            ):
                raise ValueError("assertion candidate source chain is inconsistent")
            candidates[candidate.id] = candidate

        acceptance_payload = dict(batch)
        acceptance_batch_id = str(
            acceptance_payload.pop("acceptance_batch_id", "") or ""
        )
        if stable_id(
            {"version": ACCEPTANCE_BATCH_VERSION, "payload": acceptance_payload}
        ) != acceptance_batch_id:
            raise ValueError("acceptance batch content does not match its stable id")

        commit = self._commit_from_acceptance_batch(batch)
        accepted_rows = list(batch.get("accepted") or ())
        if len(accepted_rows) != len(commit.accepted_cells):
            raise ValueError("acceptance rows do not match accepted cells")
        current_cells: dict[str, AcceptedCell] = {}
        accepted_assertion_ids: set[str] = set()
        for raw, cell in zip(accepted_rows, commit.accepted_cells):
            if not isinstance(raw, Mapping):
                raise ValueError("acceptance row is not a mapping")
            acceptance = AcceptanceRecord(**dict(raw.get("acceptance") or {}))
            candidate = candidates.get(cell.assertion_id)
            span = spans.get(cell.span_id)
            if candidate is None or span is None:
                raise ValueError("accepted cell does not resolve its assertion and span")
            expected_acceptance = AcceptanceRecord(
                id=stable_id(
                    {
                        "version": DIRECT_ACCEPTANCE_RULE_VERSION,
                        "assertion_id": candidate.id,
                    }
                ),
                assertion_id=candidate.id,
                criterion_id=candidate.criterion_id,
                source_document_id=candidate.source_document_id,
                source_version_id=candidate.source_version_id,
                chunk_id=candidate.chunk_id,
                span_id=candidate.span_id,
                supporting_text_sha256=span.text_sha256,
            )
            expected_cell = AcceptedCell(
                id=stable_id(
                    {
                        "version": EVIDENCE_REGISTRY_VERSION,
                        "criterion_id": candidate.criterion_id,
                        "kind": "direct_cell",
                    }
                ),
                table_id=candidate.table_id,
                table=candidate.table,
                column_id=candidate.column_id,
                column=candidate.column,
                subject_id=candidate.subject_id,
                criterion_id=candidate.criterion_id,
                value_json=candidate.value_json,
                normalized_value=candidate.normalized_value,
                value_type=candidate.value_type,
                unit=candidate.unit,
                assertion_id=candidate.id,
                acceptance_id=expected_acceptance.id,
                source_id=candidate.source_id,
                source_document_id=candidate.source_document_id,
                source_version_id=candidate.source_version_id,
                chunk_id=candidate.chunk_id,
                span_id=candidate.span_id,
                supporting_text_sha256=span.text_sha256,
            )
            if acceptance != expected_acceptance or cell != expected_cell:
                raise ValueError("accepted cell does not match deterministic acceptance")
            current_cells[cell.id] = cell
            accepted_assertion_ids.add(cell.assertion_id)

        rejected_ids = set(commit.rejected_assertion_ids)
        if accepted_assertion_ids & rejected_ids:
            raise ValueError("an assertion cannot be both accepted and rejected")
        if accepted_assertion_ids | rejected_ids != set(candidates):
            raise ValueError("acceptance batch does not resolve every assertion candidate")

        all_cells = {**known_cells, **current_cells}
        required_contract = {
            str(table_id): tuple(str(item) for item in columns)
            for table_id, columns in dict(
                batch.get("required_columns_by_table") or {}
            ).items()
        }
        batch_completed: set[tuple[str, str]] = set()
        for row in commit.completed_rows:
            row_key = (row.table_id, row.subject_id)
            if row_key in completed_subjects or row_key in batch_completed:
                raise ValueError("row completion is not the first accepted transition")
            batch_completed.add(row_key)
            if row.required_column_ids != required_contract.get(row.table_id, ()):
                raise ValueError("row completion does not match the frozen required columns")
            selected = [all_cells.get(cell_id) for cell_id in row.accepted_cell_ids]
            if any(cell is None for cell in selected):
                raise ValueError("row completion references an unresolved accepted cell")
            resolved = [cell for cell in selected if cell is not None]
            if any(
                cell.table_id != row.table_id or cell.subject_id != row.subject_id
                for cell in resolved
            ):
                raise ValueError("row completion cells do not share its table and subject")
            if not set(row.required_column_ids) <= {
                cell.column_id for cell in resolved
            }:
                raise ValueError("row completion lacks a required accepted column")
            expected_id = stable_id(
                {
                    "version": DIRECT_ACCEPTANCE_RULE_VERSION,
                    "table_id": row.table_id,
                    "subject_id": row.subject_id,
                    "required_column_ids": list(row.required_column_ids),
                }
            )
            if row.id != expected_id:
                raise ValueError("row completion does not match its stable identity")
        return commit

    def accepted_bindings(
        self, criterion_id: str, normalized_value: str
    ) -> tuple[AcceptedCell, ...]:
        return tuple(
            cell
            for cell in self.accepted_cells()
            if cell.criterion_id == criterion_id
            and cell.normalized_value == normalized_value
        )

    def summary(self) -> dict[str, Any]:
        cells = self.accepted_cells()
        rows = self.completed_rows()
        return {
            "version": EVIDENCE_REGISTRY_VERSION,
            "source_batches": len(self._source_batches()),
            "accepted_assertion_occurrences": len(cells),
            "accepted_criteria": len({cell.criterion_id for cell in cells}),
            "completed_rows": len(rows),
            "direct_acceptance_rule_version": DIRECT_ACCEPTANCE_RULE_VERSION,
        }

    def _source_batches(self) -> dict[str, dict[str, Any]]:
        return {
            str(item.get("source_batch_id") or ""): item
            for item in self._read_jsonl(self.source_ledger)
            if str(item.get("source_batch_id") or "")
        }

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"invalid durable evidence ledger {path}:{line_number}"
                    ) from exc
                if not isinstance(item, dict):
                    raise ValueError(f"evidence ledger row is not a mapping: {path}:{line_number}")
                out.append(item)
        return out

    @staticmethod
    def _write_blob(path: Path, content: str) -> None:
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise ValueError(f"content-addressed evidence blob conflicts at {path}")
            return
        temporary = path.with_suffix(f".tmp.{os.getpid()}")
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        EvidenceRegistry._fsync_directory(path.parent)

    @staticmethod
    def _append_fsync(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical(dict(payload)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        EvidenceRegistry._fsync_directory(path.parent)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
