"""The chunk Episode binding."""

from __future__ import annotations

import asyncio

from method_loop import Leaf

from ..costs import ObservationKind, classify_error
from .shared.acquisition_support import (
    EXTRACT_OK,
    EXTRACT_RAISED,
    FATE_NO_EXTRACTOR,
    ChunkUnit,
    PageMaterial,
    PageRunState,
    page_fate,
)

class ChunkBinding:
    """Methods owned by the chunk Episode."""

    def _make_chunk_leaf(
        self,
        state: PageRunState,
        span: Any,
        *,
        probe_key: str,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
    ) -> Leaf:
        unit = ChunkUnit(
            page=state.unit,
            span=span,
            source_record=state.source_record,
            episode_id=episode_id,
            episode_path=episode_path,
            probe_key=probe_key,
            label=state.chunk_id(span),
        )
        return Leaf(
            unit=unit,
            extract=self._extract_chunk,
            accept=self.accept_evidence,
            result=self.crediter,
            label=unit.label,
        )

    async def _extract_chunk(self, unit: ChunkUnit) -> PageMaterial:
        """Extract one selected chunk; no other chunk is touched by this pull."""

        source_id = str(unit.source_record.get("id") or "")
        chunk_record = {
            "chunk_index": int(unit.span.index),
            "chunk_id": unit.label,
            "source_id": source_id,
            "start_offset": int(unit.span.start_offset),
            "end_offset": int(unit.span.end_offset),
            "text": str(unit.span.text),
            "failed": False,
            "failure_class": "",
            "credits_minted": 0,
            "new_within_page": 0,
            "repeats_within_page": 0,
            "row_credits_minted": 0,
            "probe_key": unit.probe_key,
        }
        extractor = self.get_table_extractor()
        if extractor is None:
            return PageMaterial(
                source_id=source_id,
                fate=page_fate(mechanical=FATE_NO_EXTRACTOR),
                source_record=unit.source_record,
                chunks=(chunk_record,),
                text_chars=len(str(unit.span.text)),
            )

        try:
            with self.open_prompt_scope(unit.episode_id, unit.episode_path):
                with self.open_cost_scope(
                    ObservationKind.SOURCE.value,
                    unit.label,
                    unit.episode_id,
                    unit.episode_path,
                ):
                    call = extractor.forward(str(unit.span.text))
                    result = (
                        await asyncio.wait_for(
                            call, timeout=self.extraction_timeout_sec
                        )
                        if self.extraction_timeout_sec is not None
                        and self.extraction_timeout_sec > 0
                        else await call
                    )
        except Exception as exc:  # noqa: BLE001 - one chunk is one failed unit
            error_class = classify_error(exc)
            chunk_record.update(
                {
                    "failed": True,
                    "failure_class": error_class or type(exc).__name__,
                }
            )
            return PageMaterial(
                source_id=source_id,
                fate=page_fate(
                    extraction=EXTRACT_RAISED,
                    error_class=error_class,
                ),
                source_record=unit.source_record,
                chunks=(chunk_record,),
                text_chars=len(str(unit.span.text)),
            )

        records = [
            {
                "table": row["table"],
                "index": index,
                "values": dict(row["values"]),
                "source_chunks": [unit.label],
            }
            for index, row in enumerate(result.rows)
        ]
        return PageMaterial(
            source_id=source_id,
            fate=page_fate(extraction=EXTRACT_OK),
            records=tuple(records),
            source_record=unit.source_record,
            chunks=(chunk_record,),
            text_chars=len(str(unit.span.text)),
        )
