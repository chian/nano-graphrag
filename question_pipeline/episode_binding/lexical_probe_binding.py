from __future__ import annotations

from question_pipeline.episode_binding.provider_binding import *

class RankedChunkSource:
    """One lexical ranking over chunks that were unprocessed when it opened."""

    def __init__(
        self,
        *,
        state: PageRunState,
        ranked_chunks: Sequence[Any],
        make_leaf: Callable[[Any], Leaf],
    ) -> None:
        self._state = state
        self._ranked_chunks = tuple(ranked_chunks)
        self._make_leaf = make_leaf
        self._next_index = 0

    def next(self, view: EpisodeView) -> Leaf | None:
        while self._next_index < len(self._ranked_chunks):
            span = self._ranked_chunks[self._next_index]
            self._next_index += 1
            if self._state.chunk_id(span) in self._state.processed_chunk_ids:
                continue
            return self._make_leaf(span)
        return None

class LexicalProbeBinding:
    """Methods owned by the lexical-probe Episode."""

    def _make_probe_episode(
        self,
        state: PageRunState,
        probe_key: str,
        proposal: Any,
        ranked_chunks: Sequence[Any],
        *,
        page_episode_id: str,
        page_path: tuple[tuple[str, str], ...],
    ) -> Episode:
        probe_path = page_path + ((self.lexical_probe_grain.name, probe_key),)
        probe_ref = Episode.identity(
            self.controller.context,
            self.lexical_probe_grain,
            probe_key,
            parent_path=page_path,
        )
        source = RankedChunkSource(
            state=state,
            ranked_chunks=ranked_chunks,
            make_leaf=lambda span: self._make_chunk_leaf(
                state,
                span,
                probe_key=probe_key,
                episode_id=probe_ref.episode_id,
                episode_path=probe_path,
            ),
        )
        return Episode(
            grain=self.lexical_probe_grain,
            key=probe_key,
            source=source,
            on_unit=lambda leaf, contribution, record: self._on_chunk(
                state, leaf, contribution, record
            ),
            to_parent=self._episode_update,
        )

    def _on_chunk(
        self,
        state: PageRunState,
        leaf: Leaf,
        contribution: Any,
        record: Any,
    ) -> None:
        """Close one chunk pull and make it ineligible for every later probe."""

        unit = leaf.unit
        state.processed_chunk_ids.add(unit.label)
        state.chunk_units.append(unit)
        material = contribution.output
        if isinstance(material, PageMaterial):
            observation = _incidence_input(contribution.controller_input)
            findings = set(observation.identities)
            new_findings = findings - state.seen_finding_ids
            repeated_findings = findings & state.seen_finding_ids
            for chunk in material.chunks:
                if isinstance(chunk, dict):
                    chunk["credits_minted"] = len(findings)
                    chunk["new_within_page"] = len(new_findings)
                    chunk["repeats_within_page"] = len(repeated_findings)
            state.seen_finding_ids.update(findings)
            state.materials.append(material)
        successful = sum(1 for item in state.materials if item.fate.judged)
        failed = sum(1 for item in state.materials if not item.fate.judged)
        state.ingestion.update(
            {
                "extraction_state": (
                    "extracting_chunks"
                    if state.remaining_chunks()
                    else "extracted_table_rows"
                    if any(item.records for item in state.materials)
                    else "extracted_no_table_rows"
                ),
                "table_row_count": sum(
                    len(item.records) for item in state.materials
                ),
                "failed_chunks": failed,
                "successful_chunks": successful,
                "chunk_count": len(state.materials),
                "unprocessed_chunk_count": len(state.remaining_chunks()),
            }
        )
