from __future__ import annotations

from question_pipeline.episode_binding.table_binding import TableRegion
from question_pipeline.episode_binding.provider_binding import *

class PageChildSource:
    """Open table Episodes, then lexical probes over non-table text."""

    def __init__(
        self,
        *,
        state: PageRunState,
        table_regions: Sequence[TableRegion],
        make_table: Callable[[TableRegion], Episode],
        propose: Callable[..., Awaitable[Any]],
        rank: Callable[[Sequence[Any], str], Sequence[Any]],
        make_probe: Callable[[str, Any, Sequence[Any]], Episode],
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        open_prompt_scope: Callable[
            [str, tuple[tuple[str, str], ...]], Any
        ],
    ) -> None:
        self._state = state
        self._table_regions = tuple(table_regions)
        self._make_table = make_table
        self._next_table = 0
        self._propose = propose
        self._rank = rank
        self._make_probe = make_probe
        self._open_cost_scope = open_cost_scope
        self._open_prompt_scope = open_prompt_scope

    async def next(self, view: EpisodeView) -> Episode | None:
        if self._next_table < len(self._table_regions):
            region = self._table_regions[self._next_table]
            self._next_table += 1
            return self._make_table(region)

        remaining = self._state.remaining_chunks()
        # Physical exhaustion is authoritative. No model call and no
        # statistical extrapolation may create a unit beyond the page.
        if not remaining:
            return None

        probe_key = f"probe-{len(self._state.probe_history) + 1:04d}"
        observation_id = f"{self._state.unit.label}#{probe_key}"
        with self._open_prompt_scope(
            view.episode_ref.episode_id,
            view.path,
        ):
            with self._open_cost_scope(
                ObservationKind.PROBE_SEARCH.value,
                observation_id,
                view.episode_ref.episode_id,
                view.path,
            ):
                proposal = await self._propose(
                    outline=self._state.outline,
                    previous_probes=tuple(self._state.probe_history),
                )
        query = str(
            proposal.get("query")
            if isinstance(proposal, Mapping)
            else getattr(proposal, "query", "")
        ).strip()
        if not query:
            raise ValueError("lexical probe proposer returned an empty query")
        ranked = tuple(self._rank(remaining, query))
        if not ranked:
            return None
        proposal_record = (
            dict(proposal)
            if isinstance(proposal, Mapping)
            else proposal.to_dict()
        )
        self._state.probe_proposals[probe_key] = proposal_record
        return self._make_probe(probe_key, proposal, ranked)

class PageBinding:
    """Methods owned by the page Episode."""

    def _make_page_item(
        self,
        task: SearchTask,
        result: Mapping[str, Any],
        rank: int,
        *,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
    ) -> Any:
        """Return a page Episode that routes disjoint table and prose regions.

        Graph extraction remains a separate binding path. Table-fill pages use
        the nested bindings whenever the table extractor is available; this is
        selected by the composed capability rather than a mode flag.
        """

        if self.get_table_extractor() is None:
            return self._make_page_leaf(
                task,
                result,
                rank,
                episode_id=episode_id,
                episode_path=episode_path,
            )

        unit = PageUnit(
            task=task,
            result=result,
            rank=rank,
            episode_id=episode_id,
            episode_path=episode_path,
            label=f"{task.id}#{rank}",
        )
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            outcome = SearchOutcome.for_task(task)
            self._open_outcomes[task.id] = outcome

        with self.open_cost_scope(
            ObservationKind.SOURCE.value,
            unit.label,
            unit.episode_id,
            unit.episode_path,
        ):
            prepared = self.harvester.prepare_page(
                task, dict(result), outcome, rank=rank
            )
            if prepared.candidate is None:
                material = PageMaterial(
                    fate=page_fate(
                        mechanical=prepared.fate,
                        error_class=prepared.error_class,
                    ),
                    text_chars=prepared.text_length,
                )
                return self._material_leaf(unit, material)
            if not self.crediter.basis.columns:
                return self._material_leaf(
                    unit,
                    PageMaterial(
                        fate=page_fate(mechanical=FATE_NO_CREDIT_COLUMNS),
                        text_chars=len(prepared.candidate.text),
                    ),
                )
            source_record = self.harvester.write_source(
                task,
                prepared.candidate,
                outcome,
                rank=rank,
                episode_id=episode_id,
            )

        text = str(source_record.get("text") or "")
        table_regions = tuple(self.discover_table_regions(text))
        prose_text = self.text_without_table_regions(text, table_regions)
        spans = tuple(
            span
            for span in self.chunk_spans(
                prose_text,
                self.chunk_size,
                self.chunk_overlap,
            )
            if str(span.text).strip()
        )
        if not spans and not table_regions:
            return self._material_leaf(
                unit,
                PageMaterial(
                    fate=page_fate(extraction=EXTRACT_OK),
                    source_id=str(source_record.get("id") or ""),
                    source_record=source_record,
                    ingestion=self._open_ingestion_entry(source_record),
                    reduction=prepared.candidate.reduction,
                    text_chars=len(text),
                ),
            )

        page_path = episode_path + ((self.page_grain.name, unit.label),)
        page_ref = Episode.identity(
            self.controller.context,
            self.page_grain,
            unit.label,
            parent_path=episode_path,
        )
        state = PageRunState(
            unit=unit,
            source_record=source_record,
            ingestion=self._open_ingestion_entry(source_record),
            reduction=prepared.candidate.reduction,
            chunks=spans,
            outline=self.page_outline(
                text,
                str(source_record.get("title") or ""),
            ),
        )
        self._page_states[unit.label] = state
        source = PageChildSource(
            state=state,
            table_regions=table_regions,
            make_table=lambda region: self._make_table_episode(
                state,
                region,
                page_path=page_path,
            ),
            propose=self.propose_lexical_probe,
            rank=self.rank_chunks,
            make_probe=lambda key, proposal, ranked: self._make_probe_episode(
                state,
                key,
                proposal,
                ranked,
                page_episode_id=page_ref.episode_id,
                page_path=page_path,
            ),
            open_cost_scope=self.open_cost_scope,
            open_prompt_scope=self.open_prompt_scope,
        )
        return Episode(
            grain=self.page_grain,
            key=unit.label,
            source=source,
            on_unit=lambda child, contribution, record: self._on_page_child(
                state, child, contribution, record
            ),
            to_parent=lambda record: self._page_episode_update(state, record),
        )

    def _material_leaf(self, unit: PageUnit, material: PageMaterial) -> Leaf:
        return Leaf(
            unit=unit,
            extract=lambda _unit: material,
            accept=self.accept_evidence,
            result=self.crediter,
            label=unit.label,
        )

    def _make_page_leaf(
        self,
        task: SearchTask,
        result: Mapping[str, Any],
        rank: int,
        *,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
    ) -> Leaf:
        unit = PageUnit(
            task=task,
            result=result,
            rank=rank,
            episode_id=episode_id,
            episode_path=episode_path,
            label=f"{task.id}#{rank}",
        )
        return Leaf(
            unit=unit,
            extract=self.fetch_extract,
            accept=self.accept_evidence,
            result=self.crediter,
            label=unit.label,
        )

    def _on_page_child(
        self,
        state: PageRunState,
        episode: Episode,
        contribution: Any,
        record: Any,
    ) -> None:
        """Expose a lexical probe result; table queries update their own source."""

        if episode.grain.name == self.table_grain.name:
            return

        update = contribution.episode_update
        proposal = dict(state.probe_proposals.get(episode.key) or {})
        context = (
            dict(update.prompt_context)
            if update is not None and isinstance(update.prompt_context, Mapping)
            else {}
        )
        by_channel = dict(context.get("results_by_channel") or {})
        step = _incidence_step(record)
        proposal.update(
            {
                "probe_key": episode.key,
                "chunks_processed": int(context.get("units_processed") or 0),
                "distinct_findings": int(context.get("distinct_results") or 0),
                "findings_by_channel": {
                    self.crediter.facet_labels.get(str(name), str(name)): int(value)
                    for name, value in by_channel.items()
                },
                "ended_by": str(context.get("ended_by") or ""),
                "unprocessed_chunks": len(state.remaining_chunks()),
                "volume_credit": step.volume_credit.as_record(),
            }
        )
        state.probe_history.append(proposal)

    def _page_material(self, state: PageRunState) -> PageMaterial:
        """Project completed chunk work into the existing page artifact shape."""

        judged = [item for item in state.materials if item.fate.judged]
        fate = page_fate(
            extraction=(EXTRACT_OK if judged else EXTRACT_ALL_CHUNKS_FAILED)
        )
        chunks = tuple(
            dict(chunk)
            for material in state.materials
            for chunk in material.chunks
        )
        commits = tuple(
            material.evidence_commit
            for material in state.materials
            if material.evidence_commit is not None
        )
        return PageMaterial(
            source_id=str(state.source_record.get("id") or ""),
            fate=fate,
            records=tuple(
                record
                for material in state.materials
                for record in material.records
            ),
            guesses=tuple(
                guess
                for material in state.materials
                for guess in material.guesses
            ),
            source_record=state.source_record,
            ingestion=state.ingestion,
            reduction=state.reduction,
            chunks=chunks,
            text_chars=len(str(state.source_record.get("text") or "")),
            evidence_commits=commits,
            probe_history=tuple(dict(item) for item in state.probe_history),
            table_history=tuple(dict(item) for item in state.table_history),
        )

    def _attach_page_credit(self, state: PageRunState) -> None:
        if state.unit.credit_detail is not None:
            return
        details = [
            unit.credit_detail
            for unit in (*state.table_units, *state.chunk_units)
            if unit.credit_detail is not None
        ]
        state.unit.attach_credit(
            PageCredit(
                attributions=tuple(
                    item
                    for detail in details
                    for item in detail.attributions
                ),
                row_completions=tuple(
                    item
                    for detail in details
                    for item in detail.row_completions
                ),
                row_completion_unavailable=(
                    self.crediter.row_completion_unavailable
                ),
                declared_facets=self.crediter.declared_facets,
                chunk_encounters=tuple(
                    dict(chunk)
                    for material in state.materials
                    for chunk in material.chunks
                ),
            )
        )

    async def fetch_extract(self, unit: PageUnit) -> PageMaterial:
        task = unit.task
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            outcome = SearchOutcome.for_task(task)
            self._open_outcomes[task.id] = outcome

        with self.open_prompt_scope(unit.episode_id, unit.episode_path):
            with self.open_cost_scope(
                ObservationKind.SOURCE.value,
                unit.label,
                unit.episode_id,
                unit.episode_path,
            ):
                return await self._acquire_page(unit, outcome)

    async def _acquire_page(
        self,
        unit: PageUnit,
        outcome: SearchOutcome,
    ) -> PageMaterial:
        task = unit.task
        prepared = self.harvester.prepare_page(
            task, dict(unit.result), outcome, rank=unit.rank
        )
        if prepared.candidate is None:
            return PageMaterial(
                fate=page_fate(
                    mechanical=prepared.fate,
                    error_class=prepared.error_class,
                ),
                text_chars=prepared.text_length,
            )
        candidate = prepared.candidate

        table_extractor = self.get_table_extractor()
        graph_extractor = self.get_extractor()
        if table_extractor is None and graph_extractor is None:
            return PageMaterial(
                fate=page_fate(mechanical=FATE_NO_EXTRACTOR),
                text_chars=len(candidate.text),
            )
        if not self.crediter.basis.columns:
            return PageMaterial(
                fate=page_fate(mechanical=FATE_NO_CREDIT_COLUMNS),
                text_chars=len(candidate.text),
            )

        source_record = self.harvester.write_source(
            task, candidate, outcome, rank=unit.rank, episode_id=unit.episode_id
        )
        source_id = str(source_record.get("id") or "")
        ingestion = self._open_ingestion_entry(source_record)
        chunks: list[dict[str, Any]] = []
        try:
            observer = self._chunk_observer(
                chunks,
                source_id=source_id,
                page_text=str(source_record["text"]),
            )
            if table_extractor is not None:
                records = await self.extract_table_text(
                    table_extractor,
                    source_record["text"],
                    source_id,
                    chunk_size=self.chunk_size,
                    overlap=self.chunk_overlap,
                    concurrency=self.extraction_concurrency,
                    timeout=self.extraction_timeout_sec,
                    on_chunk=observer,
                )
                entities: Mapping[str, Mapping[str, Any]] = {}
                relationships: Sequence[Mapping[str, Any]] = ()
            else:
                entities, relationships = await self.extract_text(
                    graph_extractor,
                    source_record["text"],
                    source_id,
                    chunk_size=self.chunk_size,
                    overlap=self.chunk_overlap,
                    concurrency=self.extraction_concurrency,
                    timeout=self.extraction_timeout_sec,
                    on_chunk=observer,
                )
                records = self._extracted_records(entities, relationships)
        except Exception as exc:  # noqa: BLE001 - converted, never raised
            error_class = classify_error(exc)
            ingestion.update(
                {
                    "extraction_state": "extraction_failed",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "error_class": error_class,
                }
            )
            return PageMaterial(
                source_id=source_id,
                fate=page_fate(
                    extraction=EXTRACT_RAISED,
                    error_class=error_class,
                ),
                source_record=source_record,
                ingestion=ingestion,
                reduction=candidate.reduction,
                chunks=tuple(chunks),
                text_chars=len(candidate.text),
            )

        failed_chunks = sum(1 for chunk in chunks if chunk.get("failed"))
        if chunks and failed_chunks == len(chunks):
            ingestion.update(
                {
                    "extraction_state": "extraction_all_chunks_failed",
                    "reason": (
                        f"all {failed_chunks} chunk(s) of this page failed to "
                        f"extract, so zero entities here means 'could not "
                        f"judge', not 'this page carried nothing'"
                    ),
                    "failed_chunks": failed_chunks,
                }
            )
            return PageMaterial(
                source_id=source_id,
                fate=page_fate(extraction=EXTRACT_ALL_CHUNKS_FAILED),
                source_record=source_record,
                ingestion=ingestion,
                reduction=candidate.reduction,
                chunks=tuple(chunks),
                text_chars=len(candidate.text),
            )

        ingestion.update(
            {
                "extraction_state": (
                    "extracted_table_rows"
                    if table_extractor is not None and records
                    else "extracted_no_table_rows"
                    if table_extractor is not None
                    else "extracted_entities"
                    if entities
                    else "extracted_no_entities"
                ),
                "entity_count": len(entities or {}),
                "relationship_count": len(relationships or ()),
                "table_row_count": len(records),
                "failed_chunks": failed_chunks,
                "chunk_count": len(chunks),
            }
        )
        return PageMaterial(
            source_id=source_id,
            fate=page_fate(extraction=EXTRACT_OK),
            entities=entities or {},
            relationships=list(relationships or ()),
            records=records,
            source_record=source_record,
            ingestion=ingestion,
            reduction=candidate.reduction,
            chunks=tuple(chunks),
            text_chars=len(candidate.text),
        )

    async def accept_evidence(
        self,
        unit: PageUnit,
        material: PageMaterial,
    ) -> PageMaterial:
        """Run the bound acceptor, then persist exactly its typed decision."""

        if not material.fate.judged or material.source_record is None:
            return material
        source_record = material.source_record
        ingestion = dict(material.ingestion)
        chunks = [dict(item) for item in material.chunks]
        try:
            document, version, source_chunks = self.evidence_registry.source_records(
                source_id=material.source_id,
                canonical_locator=str(
                    source_record.get("url")
                    or source_record.get("source_url")
                    or material.source_id
                ),
                title=str(source_record.get("title") or ""),
                content=str(source_record.get("text") or ""),
                chunks=chunks,
            )
            runtime_to_registry = {
                str(chunk_record.get("chunk_id") or ""): source_chunk.id
                for chunk_record, source_chunk in zip(chunks, source_chunks)
            }
            records = [
                {
                    **dict(record),
                    "source_chunks": [
                        runtime_to_registry[chunk_id]
                        for chunk_id in (
                            str(item)
                            for item in record.get("source_chunks") or ()
                        )
                        if chunk_id in runtime_to_registry
                    ],
                }
                for record in material.records
                if isinstance(record, Mapping)
            ]
            spans, direct_candidates = self.crediter.assertion_candidates(
                records,
                document=document,
                version=version,
                chunks=source_chunks,
            )
            guesses = await self._page_best_guess(
                records=records,
                source_id=material.source_id,
                source_chunks=source_chunks,
            )
            best_guess_candidates = self.crediter.best_guess_candidates(
                records,
                guesses,
                document=document,
                version=version,
                chunks=source_chunks,
            )
            source_batch_id = self.evidence_registry.register_source_candidates(
                document=document,
                version=version,
                content=str(source_record.get("text") or ""),
                chunks=source_chunks,
                spans=spans,
                candidates=direct_candidates,
                best_guess_candidates=best_guess_candidates,
            )
            decision = self.evidence_acceptor.evaluate(
                direct_candidates=direct_candidates,
                best_guess_candidates=best_guess_candidates,
                spans=spans,
                chunks=source_chunks,
            )
            evidence_commit = self.evidence_registry.commit_acceptance(
                source_batch_id,
                decision,
            )
            accepted_by_chunk: dict[str, set[str]] = {}
            for cell in evidence_commit.accepted_cells:
                accepted_by_chunk.setdefault(cell.chunk_id, set()).add(
                    cell.criterion_id
                )
            for cell in evidence_commit.accepted_best_guess_cells:
                for chunk_id in cell.supporting_chunk_ids:
                    accepted_by_chunk.setdefault(chunk_id, set()).add(
                        cell.criterion_id
                    )
            seen_chunk_credits: set[str] = set()
            for chunk_record, source_chunk in zip(chunks, source_chunks):
                identities = accepted_by_chunk.get(source_chunk.id, set())
                new = identities - seen_chunk_credits
                chunk_record["registry_chunk_id"] = source_chunk.id
                chunk_record["credits_minted"] = len(identities)
                chunk_record["new_within_page"] = len(new)
                chunk_record["repeats_within_page"] = len(identities) - len(new)
                seen_chunk_credits.update(identities)
            return replace(
                material,
                records=tuple(records),
                guesses=tuple(guesses),
                chunks=tuple(chunks),
                evidence_commit=evidence_commit,
            )
        except (OSError, ValueError, LookupError, TypeError) as exc:
            error_class = classify_error(exc)
            ingestion.update(
                {
                    "extraction_state": "evidence_acceptance_failed",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "error_class": error_class,
                }
            )
            return replace(
                material,
                fate=page_fate(
                    extraction=EXTRACT_RAISED,
                    error_class=error_class,
                ),
                ingestion=ingestion,
                chunks=tuple(chunks),
                evidence_commit=None,
            )

    def _chunk_observer(
        self,
        sink: list[dict[str, Any]],
        *,
        source_id: str,
        page_text: str,
    ) -> Callable[..., None]:
        declared = {
            chunk.index: chunk
            for chunk in self.chunk_spans(
                page_text, self.chunk_size, self.chunk_overlap
            )
        }

        def observe(index, chunk_id, entities, relationships, failure) -> None:
            source_chunk = declared[int(index)]
            sink.append(
                {
                    "chunk_index": int(index),
                    "chunk_id": str(chunk_id),
                    "source_id": source_id,
                    "start_offset": source_chunk.start_offset,
                    "end_offset": source_chunk.end_offset,
                    "text": source_chunk.text,
                    "failed": bool(failure),
                    "failure_class": str(failure or ""),
                    "credits_minted": 0,
                    "new_within_page": 0,
                    "repeats_within_page": 0,
                    "row_credits_minted": 0,
                }
            )

        return observe

    def _extracted_records(
        self,
        entities: Mapping[str, Mapping[str, Any]],
        relationships: Sequence[Mapping[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        tables = self.crediter.basis.tables
        out: list[dict[str, Any]] = []
        index = 0
        for record in list((entities or {}).values()) + list(relationships or ()):
            if not isinstance(record, Mapping):
                continue
            attributes = record.get("attributes")
            values: dict[str, Any] = {}
            if isinstance(attributes, Mapping):
                values.update(attributes)
            for key, value in record.items():
                if key in ("attributes", "source_chunks", "source_chunk"):
                    continue
                values.setdefault(str(key), value)
            chunks = record.get("source_chunks") or (
                [record.get("source_chunk")] if record.get("source_chunk") else []
            )
            for table in tables:
                out.append(
                    {
                        "table": table,
                        "index": index,
                        "values": values,
                        "source_chunks": [str(chunk) for chunk in chunks if chunk],
                    }
                )
            index += 1
        return out

    async def _page_best_guess(
        self,
        *,
        records: Sequence[Mapping[str, Any]],
        source_id: str,
        source_chunks: Sequence[SourceChunk],
    ) -> list[dict[str, Any]]:
        columns = self.crediter.best_guess_columns_by_table()
        if not records or not any(columns.values()):
            return []
        report = await self.page_best_guess_fn(
            records=records,
            columns_by_table=columns,
            reported_alternatives_by_table=(
                self.crediter.best_guess_routes_by_table()
            ),
            subject_key_columns_by_table=(
                self.crediter.basis.subject_key_columns
            ),
            source_id=source_id,
            evidence_chunks=[
                {
                    "source_id": source_id,
                    "source_chunk": chunk.id,
                    "text": chunk.text,
                }
                for chunk in source_chunks
            ],
            extract_fn=self.infer_best_guess_candidates,
            llm_batch_size=self.best_guess_llm_batch_size,
            llm_timeout_sec=self.best_guess_llm_timeout_sec,
            evidence_chars=self.best_guess_evidence_chars,
        )
        self._page_guess_reports.append(
            {
                "source_id": source_id,
                "task_count": report.get("task_count"),
                "llm_calls": report.get("llm_calls"),
                "resolution_count": len(report.get("resolutions") or []),
                "errors": report.get("errors") or [],
            }
        )
        return list(report.get("resolutions") or [])

    def _open_ingestion_entry(
        self,
        source_record: Mapping[str, Any],
    ) -> dict[str, Any]:
        source_id = str(source_record.get("id") or "")
        entry = {
            "source_id": source_id,
            "extraction_state": "attempted",
            "reason": "",
            "entity_count": 0,
            "relationship_count": 0,
            "text_chars": len(str(source_record.get("text") or "")),
            "search_episode_id": str(source_record.get("search_episode_id") or ""),
        }
        self.source_ingestion_ledger[source_id] = entry
        return entry
