"""Extract source-local table rows directly from page text.

Table-fill and graph acquisition are parallel provider bindings.  This module
owns the table side: a frozen :class:`TableSpec` is the extraction schema, and
each model call maps one exact source chunk into partial rows of that schema.
It emits no graph nodes or edges and performs no persistence or acceptance.

The model is necessary here because mapping source language into declared
column names is string interpretation.  Exact-span enforcement, evidence
acceptance, persistence, credit, and every numerical decision remain outside
this module.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from ...extraction import chunk_spans
from ...llm_utils import ModelTier, ask_json, register_call_site_tier
from ...table_specs import ColumnEvidenceRole, TableSpec


# The V15 run is the reasoning-tier baseline for this high-volume call site.
# The fresh continuation experiment moves this one call site to the configured
# fast model while holding the table contract and all acquisition rules fixed.
_TABLE_PAGE_EXTRACTION_TIER = register_call_site_tier(
    "table-page-extraction",
    ModelTier.FAST,
)

_SYSTEM_PROMPT = """You extract source-reported values into a declared table
contract. Return one valid JSON object and no prose. Never infer, estimate,
normalize, reconcile, or fill a value that the supplied source chunk does not
state. Preserve the source wording of text, dates, ranges, bounds, and
comparisons. Numeric JSON values may differ only in harmless numeric formatting
such as commas. Omit missing fields."""


@dataclass(frozen=True)
class TableChunkExtraction:
    """Validated source-local rows returned for one exact chunk."""

    rows: tuple[dict[str, Any], ...]


class TableSpecExtractor:
    """Model-backed mapper from one source chunk to a frozen ``TableSpec``."""

    def __init__(self, llm: Any, table_spec: TableSpec) -> None:
        diagnostic = table_spec.column_yield_diagnostic()
        if not diagnostic["usable_schema"]:
            raise ValueError(
                "table extraction requires a usable table contract: "
                f"{diagnostic}"
            )
        self._llm = llm
        self._table_spec = table_spec
        self._tables = {
            name: table
            for name, table in table_spec.tables.items()
            if table.deliverable
        }

    async def forward(self, text: str) -> TableChunkExtraction:
        contract = self._extraction_contract()
        prompt = f"""TABLE CONTRACT:
{json.dumps(contract, ensure_ascii=False, sort_keys=True)}

SOURCE CHUNK:
{text}

Extract every distinct source-local subject described in this chunk that
belongs in a declared table.

Rules:
- Return only declared table and column names.
- Return only columns whose role is reported. Best-guess columns are handled
  by a separate evidence-anchored reasoning step.
- One row represents one subject at the table's declared grain.
- Partial rows are allowed, but include every subject-key column that the
  chunk explicitly states. Do not invent a missing identity field.
- Every string value must be an exact substring of SOURCE CHUNK.
- Do not combine facts from different subjects.
- If the chunk contains no qualifying row, return an empty rows list.

Return exactly:
{{
  "rows": [
    {{
      "table": "declared_table_name",
      "values": {{"declared_reported_column": "exact source value"}}
    }}
  ]
}}"""
        payload = await ask_json(
            self._llm,
            prompt,
            system_prompt=_SYSTEM_PROMPT,
            tier=_TABLE_PAGE_EXTRACTION_TIER,
            call_site="table-page-extraction",
        )
        if not isinstance(payload, Mapping):
            raise ValueError("table extraction must return a JSON object")
        return TableChunkExtraction(rows=self._validated_rows(payload.get("rows")))

    def _extraction_contract(self) -> dict[str, Any]:
        tables: dict[str, Any] = {}
        for name, table in self._tables.items():
            reported = {
                column.name: column.to_dict()
                for column in table.all_columns()
                if column.role is ColumnEvidenceRole.REPORTED
            }
            tables[name] = {
                "description": table.description,
                "grain": table.grain,
                "subject_key_columns": list(table.subject_key_columns),
                "reported_columns": reported,
            }
        return {"tables": tables}

    def _validated_rows(self, raw_rows: Any) -> tuple[dict[str, Any], ...]:
        if raw_rows is None:
            return ()
        if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
            raise ValueError("table extraction rows must be a list")
        rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                continue
            table_name = str(raw.get("table") or "")
            table = self._tables.get(table_name)
            values = raw.get("values")
            if table is None or not isinstance(values, Mapping):
                continue
            reported_names = {
                column.name
                for column in table.all_columns()
                if column.role is ColumnEvidenceRole.REPORTED
            }
            admitted = {
                str(name): value
                for name, value in values.items()
                if str(name) in reported_names
                and value is not None
                and not isinstance(value, (Mapping, list, tuple, set, bool))
                and str(value).strip()
            }
            if admitted:
                rows.append({"table": table_name, "values": admitted})
        return tuple(rows)


async def extract_table_rows_from_text(
    extractor: TableSpecExtractor,
    text: str,
    source_id: str,
    *,
    chunk_size: int = 2000,
    overlap: int = 200,
    concurrency: int = 1,
    timeout: Optional[float] = None,
    on_chunk: Optional[Callable[[int, str, list, list, str], None]] = None,
) -> list[dict[str, Any]]:
    """Apply the table extractor chunkwise while preserving source anchors."""

    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    spans = chunk_spans(text, chunk_size, overlap)
    semaphore = asyncio.Semaphore(concurrency)

    async def extract_chunk(index: int, chunk_text: str):
        chunk_id = f"{source_id}_chunk_{index}"
        try:
            async with semaphore:
                call = extractor.forward(chunk_text)
                result = (
                    await asyncio.wait_for(call, timeout=timeout)
                    if timeout is not None and timeout > 0
                    else await call
                )
        except asyncio.TimeoutError:
            return index, chunk_id, (), "timeout"
        except Exception as exc:  # noqa: BLE001 - one chunk cannot abort a page
            return index, chunk_id, (), type(exc).__name__
        return index, chunk_id, result.rows, ""

    results = await asyncio.gather(
        *(extract_chunk(chunk.index, chunk.text) for chunk in spans)
    )
    records: list[dict[str, Any]] = []
    for index, chunk_id, rows, failure in sorted(results, key=lambda item: item[0]):
        if on_chunk is not None:
            on_chunk(index, chunk_id, list(rows), [], failure)
        for row in rows:
            records.append(
                {
                    "table": row["table"],
                    "index": len(records),
                    "values": dict(row["values"]),
                    "source_chunks": [chunk_id],
                }
            )
    return records
