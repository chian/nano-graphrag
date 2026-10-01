from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Sequence

from method_loop import EpisodeGoal
from source_table_language import TableRegion
from question_pipeline.episode_binding.provider_binding import *
from question_pipeline.utilities.model import (
    JEV_REQUEST_TOKEN_BUDGET,
    JEV_TOKEN_ENCODING,
    ModelTier,
    ask_json,
    register_call_site_tier,
    token_count,
    token_window_text,
)
from question_pipeline.utilities.tables import TableSpec


PAGE_CHILD_SOURCE_TABLE = "source_table"
PAGE_CHILD_REPORT = "report"
PAGE_CHILD_LEXICAL_PROBE = "lexical_probe"
PAGE_CHILD_PROPOSAL_FAILED = "page_child_proposal_failed"
PAGE_CONTENT_ASSESSMENT_FAILED = "page_content_assessment_failed"
PAGE_CONTENT_ASSESSMENT_VERSION = "jev_goal_need_vector_v1"
JEV_PAGE_CONTENT_REQUEST_TARGET = JEV_REQUEST_TOKEN_BUDGET - 9_000
PAGE_CHILD_TABLE_PREVIEW_CHARS = 512

_PAGE_CHILD_PROPOSER_TIER = register_call_site_tier(
    "page-child-proposer",
    ModelTier.FAST,
)


@dataclass(frozen=True)
class PageInformationNeed:
    """One Goal-derived kind of information Jev measures in page content."""

    need_id: str
    table: str
    kind: str
    label: str
    columns: tuple[str, ...]
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "need_id": self.need_id,
            "table": self.table,
            "kind": self.kind,
            "label": self.label,
            "columns": list(self.columns),
            "description": self.description,
        }


@dataclass(frozen=True)
class PageContentCandidate:
    """One table region or prose chunk measured before Page planning."""

    candidate_id: str
    candidate_type: str
    text: str
    index: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class PageContentCandidateAssessment:
    """Jev probabilities for one Page-content candidate by Goal need."""

    candidate_id: str
    candidate_type: str
    index: int
    start_offset: int
    end_offset: int
    probabilities: Mapping[str, float]
    window_probabilities: Mapping[str, tuple[float, ...]]
    text_tokens: int

    def to_dict(self, *, include_windows: bool = True) -> dict[str, Any]:
        record = {
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "index": self.index,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "probabilities": {
                str(name): float(value)
                for name, value in self.probabilities.items()
            },
            "text_tokens": self.text_tokens,
        }
        if include_windows:
            record["window_probabilities"] = {
                str(name): [float(value) for value in values]
                for name, values in self.window_probabilities.items()
            }
        return record


@dataclass(frozen=True)
class PageContentAssessment:
    """One cached Jev measurement pass over a Page's possible child inputs."""

    needs: tuple[PageInformationNeed, ...]
    candidates: tuple[PageContentCandidateAssessment, ...]
    requests: tuple[Mapping[str, Any], ...]
    token_encoding: str = JEV_TOKEN_ENCODING
    version: str = PAGE_CONTENT_ASSESSMENT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "token_encoding": self.token_encoding,
            "information_needs": [need.to_dict() for need in self.needs],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "requests": [dict(item) for item in self.requests],
        }

    def planner_context(
        self,
        *,
        candidate_ids: Sequence[str],
    ) -> dict[str, Any]:
        allowed = set(candidate_ids)
        candidates = [
            candidate
            for candidate in self.candidates
            if candidate.candidate_id in allowed
        ]
        prose = [
            candidate
            for candidate in candidates
            if candidate.candidate_type == "prose_chunk"
        ]
        needs_by_table: dict[str, list[PageInformationNeed]] = {}
        for need in self.needs:
            needs_by_table.setdefault(need.table, []).append(need)
        single_chunk_coverage: list[dict[str, Any]] = []
        for table, needs in needs_by_table.items():
            if not prose or not needs:
                continue
            best = max(
                prose,
                key=lambda candidate: min(
                    candidate.probabilities.get(need.need_id, 0.0)
                    for need in needs
                ),
            )
            single_chunk_coverage.append(
                {
                    "table": table,
                    "candidate_id": best.candidate_id,
                    "joint_min_probability": min(
                        best.probabilities.get(need.need_id, 0.0)
                        for need in needs
                    ),
                    "probabilities": {
                        need.need_id: best.probabilities.get(need.need_id, 0.0)
                        for need in needs
                    },
                }
            )
        top_chunks_by_need: list[dict[str, Any]] = []
        for need in self.needs:
            ranked = sorted(
                prose,
                key=lambda candidate: candidate.probabilities.get(
                    need.need_id, 0.0
                ),
                reverse=True,
            )[:3]
            top_chunks_by_need.append(
                {
                    "need_id": need.need_id,
                    "chunks": [
                        {
                            "candidate_id": candidate.candidate_id,
                            "index": candidate.index,
                            "start_offset": candidate.start_offset,
                            "probability": candidate.probabilities.get(
                                need.need_id, 0.0
                            ),
                        }
                        for candidate in ranked
                    ],
                }
            )
        table_summaries: list[dict[str, Any]] = []
        for candidate in candidates:
            if candidate.candidate_type != PAGE_CHILD_SOURCE_TABLE:
                continue
            ranked_needs = sorted(
                candidate.probabilities.items(),
                key=lambda item: (-float(item[1]), str(item[0])),
            )[:3]
            table_summaries.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "index": candidate.index,
                    "start_offset": candidate.start_offset,
                    "end_offset": candidate.end_offset,
                    "top_information_needs": [
                        {
                            "need_id": str(need_id),
                            "probability": float(probability),
                        }
                        for need_id, probability in ranked_needs
                    ],
                }
            )
        return {
            "version": self.version,
            "information_needs": [need.to_dict() for need in self.needs],
            "source_table_assessments": table_summaries,
            "best_single_chunk_coverage_by_table": single_chunk_coverage,
            "top_chunks_by_need": top_chunks_by_need,
        }


def _page_content_questions(
    windows: Sequence[Mapping[str, Any]],
    needs: Sequence[PageInformationNeed],
) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[str, str]]]:
    questions: dict[str, dict[str, Any]] = {}
    lookup: dict[str, tuple[str, str]] = {}
    for window_index, window in enumerate(windows):
        for need_index, need in enumerate(needs):
            name = f"w{window_index:04d}_n{need_index:04d}"
            questions[name] = {
                "instructions": (
                    f"Could candidate window {window['window_id']!r} contribute "
                    f"source evidence for information need {need.need_id!r} "
                    "when interpreted with the supplied page context? The "
                    "window need not contain a complete output row or repeat "
                    "subject identity that appears elsewhere on this page."
                ),
                "criteria": {
                    "true": (
                        "The window contains a reported value, estimate basis, "
                        "subject identity, relationship, label, or context that "
                        "could help satisfy this specific information need."
                    ),
                    "false": (
                        "The window cannot contribute to this information need, "
                        "even when interpreted with the supplied page context."
                    ),
                },
            }
            lookup[name] = (str(window["candidate_id"]), need.need_id)
    return questions, lookup


def _page_content_state(
    *,
    goal: Mapping[str, Any],
    page_context: Mapping[str, Any],
    needs: Sequence[PageInformationNeed],
    windows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "page_goal": dict(goal),
        "page_context": dict(page_context),
        "information_needs": [need.to_dict() for need in needs],
        "candidate_windows": [dict(window) for window in windows],
    }


async def assess_page_content(
    jev: Any,
    *,
    goal: Mapping[str, Any],
    page_context: Mapping[str, Any],
    information_needs: Sequence[PageInformationNeed],
    candidates: Sequence[PageContentCandidate],
) -> PageContentAssessment:
    """Measure tables and prose chunks once, before the Page parent plans."""

    needs = tuple(information_needs)
    if not needs:
        raise ValueError("Page content assessment requires Goal information needs")
    candidate_values = tuple(candidates)
    if not candidate_values:
        raise ValueError("Page content assessment requires content candidates")

    windows: list[dict[str, Any]] = []
    for candidate in candidate_values:
        pending = [candidate.text]
        fitted: list[str] = []
        while pending:
            text = pending.pop(0)
            probe = {
                "window_id": f"{candidate.candidate_id}#window-probe",
                "candidate_id": candidate.candidate_id,
                "candidate_type": candidate.candidate_type,
                "index": candidate.index,
                "start_offset": candidate.start_offset,
                "end_offset": candidate.end_offset,
                "text": text,
            }
            questions, _ = _page_content_questions((probe,), needs)
            state = _page_content_state(
                goal=goal,
                page_context=page_context,
                needs=needs,
                windows=(probe,),
            )
            request_tokens = jev.nouls_request_token_count(
                state=state,
                questions=questions,
            )
            if request_tokens <= JEV_PAGE_CONTENT_REQUEST_TARGET:
                fitted.append(text)
                continue
            text_tokens = token_count(text)
            if text_tokens <= 1:
                raise ValueError(
                    "Jev Page assessment metadata exceeds its request budget"
                )
            pieces = token_window_text(
                text,
                budget=max(1, text_tokens // 2),
            )
            if len(pieces) < 2:
                raise ValueError("unable to fit Page candidate into Jev request")
            pending[0:0] = pieces
        for window_index, text in enumerate(fitted, start=1):
            windows.append(
                {
                    "window_id": (
                        f"{candidate.candidate_id}#window-{window_index:04d}"
                    ),
                    "candidate_id": candidate.candidate_id,
                    "candidate_type": candidate.candidate_type,
                    "index": candidate.index,
                    "start_offset": candidate.start_offset,
                    "end_offset": candidate.end_offset,
                    "text": text,
                }
            )

    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for window in windows:
        trial = [*current, window]
        questions, _ = _page_content_questions(trial, needs)
        state = _page_content_state(
            goal=goal,
            page_context=page_context,
            needs=needs,
            windows=trial,
        )
        if jev.nouls_request_token_count(
            state=state,
            questions=questions,
        ) <= JEV_PAGE_CONTENT_REQUEST_TARGET:
            current = trial
            continue
        if current:
            batches.append(current)
            current = [window]
            continue
        raise ValueError("one fitted Page candidate still exceeds Jev request budget")
    if current:
        batches.append(current)

    values: dict[str, dict[str, list[float]]] = {
        candidate.candidate_id: {need.need_id: [] for need in needs}
        for candidate in candidate_values
    }
    requests: list[dict[str, Any]] = []
    for request_index, batch in enumerate(batches, start=1):
        questions, lookup = _page_content_questions(batch, needs)
        state = _page_content_state(
            goal=goal,
            page_context=page_context,
            needs=needs,
            windows=batch,
        )
        decision = await jev.nouls(state=state, questions=questions)
        for question_name, probability in decision.probabilities.items():
            candidate_id, need_id = lookup[question_name]
            values[candidate_id][need_id].append(float(probability))
        requests.append(
            {
                "request_index": request_index,
                "candidate_window_ids": [
                    str(window["window_id"]) for window in batch
                ],
                "model": decision.response.model,
                "input_tokens": decision.response.input_tokens,
                "output_tokens": decision.response.output_tokens,
                "attempts": decision.response.attempts,
            }
        )

    assessments = []
    for candidate in candidate_values:
        by_need = values[candidate.candidate_id]
        assessments.append(
            PageContentCandidateAssessment(
                candidate_id=candidate.candidate_id,
                candidate_type=candidate.candidate_type,
                index=candidate.index,
                start_offset=candidate.start_offset,
                end_offset=candidate.end_offset,
                probabilities={
                    need_id: max(probabilities)
                    for need_id, probabilities in by_need.items()
                },
                window_probabilities={
                    need_id: tuple(probabilities)
                    for need_id, probabilities in by_need.items()
                },
                text_tokens=token_count(candidate.text),
            )
        )
    return PageContentAssessment(
        needs=needs,
        candidates=tuple(assessments),
        requests=tuple(requests),
    )


@dataclass(frozen=True)
class PageChildOption:
    """One child the Page parent is allowed to open on this pull."""

    option_id: str
    child_type: str
    context: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "child_type": self.child_type,
            "context": dict(self.context),
        }


@dataclass(frozen=True)
class PageChildProposal:
    """The Page parent's choice of one declared child and its string input."""

    option_id: str
    child_type: str
    query: str = ""
    objective: str = ""
    rationale: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "option_id": self.option_id,
            "child_type": self.child_type,
            "query": self.query,
            "objective": self.objective,
            "rationale": self.rationale,
        }


def _page_child_proposal_from_payload(
    payload: Any,
    *,
    options: Mapping[str, Mapping[str, Any]],
) -> PageChildProposal:
    """Validate one model choice against the Page parent's child catalog."""

    if not isinstance(payload, Mapping):
        raise ValueError("page child proposer must return a JSON object")
    option_id = str(payload.get("option_id") or "").strip()
    option = options.get(option_id)
    if option is None:
        raise ValueError(
            "page child proposer must select one exact declared option_id"
        )
    # The model chooses an option_id. The declared catalog, not duplicated
    # model text, owns the child type associated with that option.
    child_type = str(option.get("child_type") or "").strip()
    if not child_type:
        raise ValueError("declared page child option has no child_type")
    query = " ".join(str(payload.get("query") or "").split())
    if child_type == PAGE_CHILD_LEXICAL_PROBE and not query:
        raise ValueError("lexical_probe child selection requires a query")
    return PageChildProposal(
        option_id=option_id,
        child_type=child_type,
        query=query,
        objective=str(payload.get("objective") or "").strip(),
        rationale=str(payload.get("rationale") or "").strip(),
    )


async def propose_page_child(
    llm: Any,
    *,
    goal: Mapping[str, Any],
    page_summary: Mapping[str, Any],
    valid_children: Sequence[Mapping[str, Any]],
    previous_children: Sequence[Mapping[str, Any]],
    goal_state: Mapping[str, Any],
    content_assessment: Mapping[str, Any],
) -> PageChildProposal:
    """Choose one valid Page child after the Page controller continues."""

    options = {
        str(item.get("option_id") or ""): dict(item)
        for item in valid_children
        if isinstance(item, Mapping) and str(item.get("option_id") or "")
    }
    if not options:
        raise ValueError("page child proposal requires at least one valid child")

    prompt = f"""PAGE EPISODE GOAL:
{json.dumps(dict(goal), ensure_ascii=False, sort_keys=True, default=str)}

CURRENT GOAL STATE:
{json.dumps(dict(goal_state), ensure_ascii=False, default=str)}

PAGE SUMMARY PREPARED WHEN THIS EPISODE OPENED:
{json.dumps(dict(page_summary), ensure_ascii=False, sort_keys=True, default=str)}

JEV ASSESSMENTS OF UNPROCESSED TABLES AND PROSE CHUNKS:
{json.dumps(dict(content_assessment), ensure_ascii=False, sort_keys=True, default=str)}

VALID CHILDREN ON THIS PULL:
{json.dumps(list(options.values()), ensure_ascii=False, sort_keys=True, default=str)}

PREVIOUS CHILDREN AND THEIR MEASURED RESULTS:
{json.dumps([dict(item) for item in previous_children], ensure_ascii=False, sort_keys=True, default=str)}

Choose exactly one option_id from VALID CHILDREN. The Page's numerical
controller has already decided that another child may be attempted. You choose
which child to try; you never decide whether the Page continues or stops.
Option IDs shown only in PREVIOUS CHILDREN have already been consumed and are
not available. Never copy one unless that exact ID is also present in VALID
CHILDREN ON THIS PULL.

A source_table option exists only for a table region actually detected in this
page. Use that region's Jev probabilities to judge whether the table is likely
to contain the requested kinds of information. Do not manufacture a table
option.

A report option reads the remaining prose in document order, using large
windows and compact source-linked memory to resolve information whose identity
or meaning spans sections. The assessment reports the strongest single-chunk
coverage by result table and the locations of likely chunks for each
information need. Choose report when useful pieces appear distributed across
chunks or isolated chunks would lose their relationships.

A lexical_probe option ranks the remaining prose chunks. When choosing it,
write one literal query containing document-native words, phrases, units,
labels, names, dates, or codes likely to occur in useful text. Use previous
measured results and Jev's chunk probabilities to refine productive wording and
avoid repeating wording that returned no useful evidence. Prefer this route
when one or a small number of chunks appears able to supply the needed context.

Jev probabilities are planning evidence. They do not select a child, admit
evidence, assign credit, or decide whether the Page continues.

Return exactly:
{{
  "option_id": "one exact option_id from VALID CHILDREN",
  "query": "required for lexical_probe; otherwise empty",
  "objective": "the Goal information this child should seek",
  "rationale": "how the page context, Goal gaps, and prior outcomes support this choice"
}}"""
    payload = await ask_json(
        llm,
        prompt,
        system_prompt=(
            "You choose one child from a supplied Page-child catalog. Return "
            "one JSON object. Never decide whether acquisition continues."
        ),
        tier=_PAGE_CHILD_PROPOSER_TIER,
        call_site="page-child-proposer",
    )
    try:
        return _page_child_proposal_from_payload(payload, options=options)
    except (TypeError, ValueError) as first_error:
        correction_prompt = f"""YOUR INVALID PAGE-CHILD PROPOSAL:
{json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)}

VALIDATION ERROR:
{type(first_error).__name__}: {first_error}

CURRENTLY VALID CHILDREN:
{json.dumps(list(options.values()), ensure_ascii=False, sort_keys=True, default=str)}

Correct only the structured proposal. The previous option_id is unavailable.
Select one different, exact option_id from CURRENTLY VALID CHILDREN. The
catalog determines its child_type. Preserve the useful objective from the
invalid proposal where the selected option can pursue it. If the selected
option is lexical_probe, include a non-empty literal query. Return one JSON
object and nothing else."""
        corrected = await ask_json(
            llm,
            correction_prompt,
            system_prompt=(
                "You correct one Page-child proposal against a supplied "
                "catalog. Return one JSON object. Never decide whether "
                "acquisition continues."
            ),
            tier=_PAGE_CHILD_PROPOSER_TIER,
            call_site="page-child-proposer",
        )
        try:
            return _page_child_proposal_from_payload(
                corrected,
                options=options,
            )
        except (TypeError, ValueError) as correction_error:
            raise ValueError(
                "page child proposal remained invalid after one correction: "
                f"first={first_error}; corrected={correction_error}"
            ) from correction_error


@dataclass(frozen=True)
class PageResult:
    """The leaf goal transitions and source encounters within one page."""

    goal_transitions: tuple[GoalTransition, ...]
    chunk_encounters: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        unavailable: dict[str, str] = {}
        declared_facets: list[str] = []
        for transition in self.goal_transitions:
            unavailable.update(transition.row_completion_unavailable)
            for facet in transition.declared_facets:
                if facet not in declared_facets:
                    declared_facets.append(facet)
        return {
            "attributions": [
                item.to_dict()
                for transition in self.goal_transitions
                for item in transition.attributions
            ],
            "row_completions": [
                item.to_dict()
                for transition in self.goal_transitions
                for item in transition.row_completions
            ],
            "row_completion_unavailable": unavailable,
            "declared_facets": declared_facets,
            "chunk_encounters": [dict(item) for item in self.chunk_encounters],
        }

class PageChildProposer:
    """Let the Page parent choose one currently valid child per pull."""

    def __init__(
        self,
        *,
        state: PageRunState,
        source_table_regions: Sequence[TableRegion],
        make_source_table: Callable[
            [TableRegion, PageChildProposal, EpisodeGoal], Episode
        ],
        make_report: Callable[[str, PageChildProposal, EpisodeGoal], Episode],
        assess_content: Callable[..., Awaitable[PageContentAssessment]],
        information_needs: Sequence[PageInformationNeed],
        propose: Callable[..., Awaitable[Any]],
        rank: Callable[[Sequence[Any], str], Sequence[Any]],
        make_probe: Callable[
            [str, Any, Sequence[Any], EpisodeGoal], Episode
        ],
        goal_prompt_context: Callable[[], Mapping[str, Any]],
        child_context_chars: int,
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        open_prompt_scope: Callable[
            [str, tuple[tuple[str, str], ...]], Any
        ],
    ) -> None:
        self._state = state
        self._source_table_regions = tuple(source_table_regions)
        self._make_source_table = make_source_table
        self._make_report = make_report
        self._assess_content = assess_content
        self._information_needs = tuple(information_needs)
        self._propose = propose
        self._rank = rank
        self._make_probe = make_probe
        self._goal_prompt_context = goal_prompt_context
        self._child_context_chars = max(1, int(child_context_chars))
        self._open_cost_scope = open_cost_scope
        self._open_prompt_scope = open_prompt_scope

    def _content_candidates(self) -> tuple[PageContentCandidate, ...]:
        table_candidates = tuple(
            PageContentCandidate(
                candidate_id=f"{PAGE_CHILD_SOURCE_TABLE}:{region.region_id}",
                candidate_type=PAGE_CHILD_SOURCE_TABLE,
                text=region.text,
                index=index,
                start_offset=region.start_offset,
                end_offset=region.end_offset,
            )
            for index, region in enumerate(self._source_table_regions)
        )
        chunk_candidates = tuple(
            PageContentCandidate(
                candidate_id=self._state.chunk_id(span),
                candidate_type="prose_chunk",
                text=str(span.text),
                index=int(span.index),
                start_offset=int(span.start_offset),
                end_offset=int(span.end_offset),
            )
            for span in self._state.chunks
        )
        return (*table_candidates, *chunk_candidates)

    async def _ensure_content_assessment(
        self,
        goal: EpisodeGoal,
    ) -> PageContentAssessment:
        current = self._state.content_assessment
        if isinstance(current, PageContentAssessment):
            return current
        page_context = {
            name: self._state.page_summary.get(name)
            for name in (
                "title",
                "url",
                "source_id",
                "text_chars",
                "prose_chunk_count",
                "source_table_count",
                "outline",
                "exact_beginning",
            )
        }
        assessment = await self._assess_content(
            goal=goal.as_record(),
            page_context=page_context,
            information_needs=self._information_needs,
            candidates=self._content_candidates(),
        )
        if not isinstance(assessment, PageContentAssessment):
            raise TypeError("Page content assessor returned an invalid result")
        self._state.content_assessment = assessment
        return assessment

    def _remaining_assessment_ids(self) -> tuple[str, ...]:
        table_ids = tuple(
            f"{PAGE_CHILD_SOURCE_TABLE}:{region.region_id}"
            for region in self._source_table_regions
            if region.region_id not in self._state.selected_source_table_ids
        )
        chunk_ids = tuple(
            self._state.chunk_id(span)
            for span in self._state.remaining_chunks()
        )
        return (*table_ids, *chunk_ids)

    def _valid_children(self) -> tuple[PageChildOption, ...]:
        options = [
            PageChildOption(
                option_id=f"{PAGE_CHILD_SOURCE_TABLE}:{region.region_id}",
                child_type=PAGE_CHILD_SOURCE_TABLE,
                context={
                    "region_id": region.region_id,
                    "parser_hint": region.parser_hint,
                    "start_offset": region.start_offset,
                    "end_offset": region.end_offset,
                    "exact_table_beginning": region.text[
                        : min(
                            self._child_context_chars,
                            PAGE_CHILD_TABLE_PREVIEW_CHARS,
                        )
                    ],
                },
            )
            for region in self._source_table_regions
            if region.region_id not in self._state.selected_source_table_ids
        ]
        remaining = self._state.remaining_chunks()
        if remaining:
            options.append(
                PageChildOption(
                    option_id=PAGE_CHILD_REPORT,
                    child_type=PAGE_CHILD_REPORT,
                    context={
                        "unprocessed_chunk_count": len(remaining),
                        "reading_order": "document_order",
                        "memory": "source_linked_compact_memory",
                    },
                )
            )
            options.append(
                PageChildOption(
                    option_id=PAGE_CHILD_LEXICAL_PROBE,
                    child_type=PAGE_CHILD_LEXICAL_PROBE,
                    context={
                        "unprocessed_chunk_count": len(remaining),
                    },
                )
            )
        return tuple(options)

    def _latest_goal_state(self) -> Mapping[str, Any]:
        state = self._goal_prompt_context()
        if not isinstance(state, Mapping):
            return {}
        keys = (
            "target_table_names",
            "tables",
            "observed_slot_count",
            "open_observed_slot_count",
            "observed_slot_counts",
            "open_observed_slot_counts",
            "sample_open_slots",
            "sample_open_slots_disclosure",
            "sample_gaps",
            "sample_gaps_disclosure",
            "current_universe_estimate",
        )
        return {key: state[key] for key in keys if key in state}

    def _planner_page_summary(self) -> Mapping[str, Any]:
        return {
            key: value
            for key, value in self._state.page_summary.items()
            if key != "source_tables"
        }

    async def next(self, view: EpisodeView) -> Episode | SourceEnd | None:
        valid_children = self._valid_children()
        # Physical exhaustion is authoritative. No model call and no
        # statistical extrapolation may create a child beyond the page.
        if not valid_children:
            return None

        try:
            assessment = await self._ensure_content_assessment(view.goal)
        except Exception as exc:
            self._state.content_assessment_error = (
                f"{type(exc).__name__}: {exc}"
            )
            print(
                "[page-content-assessment] "
                f"{self._state.unit.label} failed: "
                f"{self._state.content_assessment_error}",
                flush=True,
            )
            return SourceEnd(END_SOURCE_FAILED, PAGE_CONTENT_ASSESSMENT_FAILED)

        proposal_index = len(self._state.child_proposals) + 1
        observation_id = f"{self._state.unit.label}#child-{proposal_index:04d}"
        try:
            with self._open_prompt_scope(
                view.episode_ref.episode_id,
                view.path,
            ):
                with self._open_cost_scope(
                    ObservationKind.PAGE_CHILD_PROPOSAL.value,
                    observation_id,
                    view.episode_ref.episode_id,
                    view.path,
                ):
                    proposal = await self._propose(
                        goal=view.goal.as_record(),
                        page_summary=self._planner_page_summary(),
                        valid_children=tuple(
                            option.to_dict() for option in valid_children
                        ),
                        previous_children=tuple(self._state.child_history),
                        goal_state=self._latest_goal_state(),
                        content_assessment=assessment.planner_context(
                            candidate_ids=self._remaining_assessment_ids(),
                        ),
                    )
        except Exception as exc:
            print(
                "[page-child-proposal] "
                f"{self._state.unit.label} failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            return SourceEnd(END_SOURCE_FAILED, PAGE_CHILD_PROPOSAL_FAILED)

        if not isinstance(proposal, PageChildProposal):
            return SourceEnd(END_SOURCE_FAILED, PAGE_CHILD_PROPOSAL_FAILED)
        proposal_record = proposal.to_dict()
        if proposal.child_type == PAGE_CHILD_SOURCE_TABLE:
            region_id = proposal.option_id.split(":", 1)[-1]
            region = next(
                (
                    item
                    for item in self._source_table_regions
                    if item.region_id == region_id
                    and item.region_id
                    not in self._state.selected_source_table_ids
                ),
                None,
            )
            if region is None:
                return SourceEnd(END_SOURCE_FAILED, PAGE_CHILD_PROPOSAL_FAILED)
            self._state.selected_source_table_ids.add(region.region_id)
            self._state.child_proposals[
                (PAGE_CHILD_SOURCE_TABLE, region.region_id)
            ] = proposal_record
            return self._make_source_table(region, proposal, view.goal)

        if proposal.child_type == PAGE_CHILD_REPORT:
            remaining = self._state.remaining_chunks()
            if not remaining:
                return None
            report_count = sum(
                1
                for child_type, _ in self._state.child_proposals
                if child_type == PAGE_CHILD_REPORT
            )
            report_key = f"report-{report_count + 1:04d}"
            self._state.child_proposals[
                (PAGE_CHILD_REPORT, report_key)
            ] = proposal_record
            return self._make_report(report_key, proposal, view.goal)

        if proposal.child_type != PAGE_CHILD_LEXICAL_PROBE:
            return SourceEnd(END_SOURCE_FAILED, PAGE_CHILD_PROPOSAL_FAILED)
        remaining = self._state.remaining_chunks()
        if not remaining:
            return None
        probe_count = sum(
            1
            for child_type, _ in self._state.child_proposals
            if child_type == PAGE_CHILD_LEXICAL_PROBE
        )
        probe_key = f"probe-{probe_count + 1:04d}"
        query = proposal.query
        ranked = tuple(self._rank(remaining, query))
        if not ranked:
            return None
        self._state.child_proposals[
            (PAGE_CHILD_LEXICAL_PROBE, probe_key)
        ] = proposal_record
        return self._make_probe(probe_key, proposal, ranked, view.goal)

class PageBinding:
    """Methods owned by the page Episode."""

    def _page_information_needs(self) -> tuple[PageInformationNeed, ...]:
        """Project the current Goal contract into Jev measurement targets."""

        grouped: dict[str, dict[str, Any]] = {}
        result_columns_by_table: dict[str, set[str]] = {}
        for column in self.goal_view.basis.columns:
            result_columns_by_table.setdefault(column.table, set()).add(
                column.column
            )
            item = grouped.setdefault(
                column.slot_id,
                {
                    "table": column.table,
                    "label": self.goal_view.facet_labels.get(
                        column.slot_id,
                        column.value_slot or column.column,
                    ),
                    "columns": [],
                    "descriptions": [],
                },
            )
            if column.column not in item["columns"]:
                item["columns"].append(column.column)
            description = str(column.description or "").strip()
            if description and description not in item["descriptions"]:
                item["descriptions"].append(description)

        needs = [
            PageInformationNeed(
                need_id=slot_id,
                table=str(item["table"]),
                kind="result",
                label=str(item["label"]),
                columns=tuple(str(value) for value in item["columns"]),
                description=" ".join(item["descriptions"]),
            )
            for slot_id, item in grouped.items()
        ]
        for table, key_columns in self.goal_view.basis.subject_key_columns.items():
            unresolved = tuple(
                str(column)
                for column in key_columns
                if str(column) not in result_columns_by_table.get(str(table), set())
            )
            if not unresolved:
                continue
            needs.append(
                PageInformationNeed(
                    need_id=f"identity:{table}",
                    table=str(table),
                    kind="subject_identity",
                    label=f"identity context for {table}",
                    columns=unresolved,
                    description=(
                        "Information needed to identify or link the subject of "
                        f"a {table} result using: {', '.join(unresolved)}."
                    ),
                )
            )
        return tuple(needs)

    def _make_page_item(
        self,
        task: SearchTask,
        result: Mapping[str, Any],
        rank: int,
        *,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        parent_goal: EpisodeGoal,
    ) -> Any:
        """Return a Page parent that chooses among its declared child Episodes.

        Source-table parsing is an acquisition path. The current tabular Goal
        implementation supplies the extractor that enables this nested page
        path; neither concept is the other.
        """

        goal = EpisodeGoal.for_grain(
            self.page_grain,
            parent=parent_goal,
            objective={
                "search_task_id": task.id,
                "query": task.query,
                "rank": int(rank),
                "title": str(result.get("title") or ""),
                "url": str(result.get("url") or ""),
            },
        )
        if self.get_table_extractor() is None:
            return self._make_page_leaf(
                task,
                result,
                rank,
                episode_id=episode_id,
                episode_path=episode_path,
                goal=goal,
            )

        unit = PageUnit(
            task=task,
            provider_result=result,
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
                return self._material_page_episode(unit, material, goal)
            if not self.goal_view.basis.columns:
                return self._material_page_episode(
                    unit,
                    PageMaterial(
                        fate=page_fate(mechanical=FATE_NO_CREDIT_COLUMNS),
                        text_chars=len(prepared.candidate.text),
                    ),
                    goal,
                )
            source_record = self.harvester.write_source(
                task,
                prepared.candidate,
                outcome,
                rank=rank,
                episode_id=episode_id,
            )

        text = str(source_record.get("text") or "")
        source_table_regions = tuple(self.discover_source_table_regions(text))
        prose_text = self.text_without_source_table_regions(
            text,
            source_table_regions,
        )
        spans = tuple(
            span
            for span in self.chunk_spans(
                prose_text,
                self.chunk_size,
                self.chunk_overlap,
            )
            if str(span.text).strip()
        )
        if not spans and not source_table_regions:
            return self._material_page_episode(
                unit,
                PageMaterial(
                    fate=page_fate(extraction=EXTRACT_OK),
                    source_id=str(source_record.get("id") or ""),
                    source_record=source_record,
                    ingestion=self._open_ingestion_entry(source_record),
                    reduction=prepared.candidate.reduction,
                    text_chars=len(text),
                ),
                goal,
            )

        page_path = episode_path + ((self.page_grain.name, unit.label),)
        page_ref = Episode.identity(
            self.controller.context,
            self.page_grain,
            unit.label,
            parent_path=episode_path,
        )
        outline = self.page_outline(
            text,
            str(source_record.get("title") or ""),
        )
        source_preview = text[: self.chunk_size]
        page_summary = {
            "title": str(source_record.get("title") or ""),
            "url": str(source_record.get("url") or ""),
            "source_id": str(source_record.get("id") or ""),
            "text_chars": len(text),
            "prose_chars": len(prose_text),
            "prose_chunk_count": len(spans),
            "source_table_count": len(source_table_regions),
            "source_tables": [
                {
                    "region_id": region.region_id,
                    "parser_hint": region.parser_hint,
                    "start_offset": region.start_offset,
                    "end_offset": region.end_offset,
                    "beginning": region.text[: self.chunk_size],
                }
                for region in source_table_regions
            ],
            "outline": outline,
            "exact_beginning": source_preview,
        }
        state = PageRunState(
            unit=unit,
            source_record=source_record,
            ingestion=self._open_ingestion_entry(source_record),
            reduction=prepared.candidate.reduction,
            chunks=spans,
            outline=outline,
            page_summary=page_summary,
            source_preview=source_preview,
            source_table_region_ids=tuple(
                region.region_id for region in source_table_regions
            ),
        )
        self._page_states[unit.label] = state
        source = PageChildProposer(
            state=state,
            source_table_regions=source_table_regions,
            make_source_table=lambda region, proposal, parent: self._make_source_table_episode(
                state,
                region,
                proposal=proposal,
                page_path=page_path,
                parent_goal=parent,
            ),
            make_report=lambda key, proposal, parent: self._make_report_episode(
                state,
                key,
                proposal=proposal,
                page_episode_id=page_ref.episode_id,
                page_path=page_path,
                parent_goal=parent,
            ),
            assess_content=lambda **kwargs: assess_page_content(
                self.jev_client,
                **kwargs,
            ),
            information_needs=self._page_information_needs(),
            propose=self.propose_page_child,
            rank=self.rank_chunks,
            make_probe=lambda key, proposal, ranked, parent: self._make_probe_episode(
                state,
                key,
                proposal,
                ranked,
                page_episode_id=page_ref.episode_id,
                page_path=page_path,
                parent_goal=parent,
            ),
            goal_prompt_context=self.goal_prompt_context,
            child_context_chars=self.chunk_size,
            open_cost_scope=self.open_cost_scope,
            open_prompt_scope=self.open_prompt_scope,
        )
        return Episode(
            grain=self.page_grain,
            key=unit.label,
            source=source,
            request=EpisodeRequest(
                goal=goal,
                input={
                    "search_task_id": task.id,
                    "rank": int(rank),
                    "source_id": str(source_record.get("id") or ""),
                },
                prompt_context={"page_summary": page_summary},
            ),
            on_unit=lambda child, contribution, record: self._on_page_child(
                state, child, contribution, record
            ),
            to_parent=lambda record: self._page_episode_result(state, record),
            parent_controller_input=self._parent_controller_input,
        )

    def _material_leaf(self, unit: PageUnit, material: PageMaterial) -> Leaf:
        return Leaf(
            unit=unit,
            extract=lambda _unit: material,
            accept=self.accept_evidence,
            result=self._page_result,
            label=unit.label,
        )

    def _material_page_episode(
        self,
        unit: PageUnit,
        material: PageMaterial,
        goal: EpisodeGoal,
    ) -> Episode:
        """Give an already-resolved page the same Episode boundary as any page."""

        return self._leaf_page_episode(
            unit,
            self._material_leaf(unit, material),
            goal,
        )

    def _leaf_page_episode(
        self,
        unit: PageUnit,
        leaf: Leaf,
        goal: EpisodeGoal,
    ) -> Episode:
        """Wrap one page leaf so every pulled page publishes an EpisodeUpdate."""

        completed_material: Optional[PageMaterial] = None

        def remember_material(
            _item: Any,
            contribution: Any,
            _record: Any,
        ) -> None:
            nonlocal completed_material
            if not isinstance(contribution.output, PageMaterial):
                raise TypeError("page leaf must return PageMaterial")
            transition = contribution.goal_result
            if not isinstance(transition, GoalTransition):
                raise TypeError("page Goal proposal completed without GoalTransition")
            unit.attach_result(
                PageResult(
                    goal_transitions=(transition,),
                    chunk_encounters=tuple(
                        dict(item) for item in contribution.output.chunks
                    ),
                )
            )
            completed_material = contribution.output

        def publish(record: EpisodeRecord) -> EpisodeResult:
            if completed_material is None:
                raise RuntimeError("page leaf completed without PageMaterial")
            result = unit.result
            if not isinstance(result, PageResult):
                raise TypeError("page leaf completed without PageResult")
            return self._episode_result(
                record,
                output=PageEpisodeOutput(
                    unit=unit,
                    material=completed_material,
                    result=result,
                ),
                retain_trace=self.checkpoint_completed_page is not None,
            )

        return Episode(
            grain=self.page_grain,
            key=unit.label,
            source=_SingleAcquirableSource(leaf),
            request=EpisodeRequest(goal=goal),
            on_unit=remember_material,
            to_parent=publish,
            parent_controller_input=self._parent_controller_input,
        )

    def _make_page_leaf(
        self,
        task: SearchTask,
        result: Mapping[str, Any],
        rank: int,
        *,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        goal: EpisodeGoal,
    ) -> Episode:
        unit = PageUnit(
            task=task,
            provider_result=result,
            rank=rank,
            episode_id=episode_id,
            episode_path=episode_path,
            label=f"{task.id}#{rank}",
        )
        return self._leaf_page_episode(
            unit,
            Leaf(
                unit=unit,
                extract=self.fetch_extract,
                accept=self.accept_evidence,
                result=self._page_result,
                label=unit.label,
            ),
            goal,
        )

    def _page_result(
        self,
        unit: PageUnit,
        material: PageMaterial,
    ) -> Any:
        return GoalProposal(TableGoalCandidate(unit=unit, material=material))

    def _on_page_child(
        self,
        state: PageRunState,
        episode: Episode,
        contribution: Any,
        record: Any,
    ) -> None:
        """Expose one completed child outcome to the next Page proposal."""

        update = contribution.episode_update
        child_type = str(episode.grain.name)
        proposal = dict(
            state.child_proposals.get((child_type, episode.key)) or {}
        )
        context = (
            dict(update.prompt_context)
            if update is not None and isinstance(update.prompt_context, Mapping)
            else {}
        )
        by_channel = dict(context.get("results_by_channel") or {})
        step = _incidence_step(record)
        proposal.update(
            {
                "child_type": child_type,
                "child_key": episode.key,
                "units_processed": int(context.get("units_processed") or 0),
                "distinct_findings": int(context.get("distinct_results") or 0),
                "findings_by_channel": {
                    self.goal_view.facet_labels.get(str(name), str(name)): int(value)
                    for name, value in by_channel.items()
                },
                "ended_by": str(context.get("ended_by") or ""),
                "end_reason": str(context.get("end_reason") or ""),
                "unprocessed_chunks": len(state.remaining_chunks()),
                "unprocessed_source_tables": sum(
                    1
                    for region_id in state.source_table_region_ids
                    if region_id not in state.selected_source_table_ids
                ),
                "volume_credit": {
                    key: value
                    for key, value in step.volume_credit.as_record().items()
                    if key != "channels"
                },
            }
        )
        state.child_history.append(proposal)
        if child_type == self.lexical_probe_grain.name:
            state.probe_history.append(dict(proposal))

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
            page_child_history=tuple(
                dict(item) for item in state.child_history
            ),
            page_content_assessment=(
                state.content_assessment.to_dict()
                if isinstance(state.content_assessment, PageContentAssessment)
                else None
            ),
            page_content_assessment_error=state.content_assessment_error,
            probe_history=tuple(dict(item) for item in state.probe_history),
            source_table_history=tuple(
                dict(item) for item in state.source_table_history
            ),
            report_history=tuple(dict(item) for item in state.report_history),
        )

    def _attach_page_result(self, state: PageRunState) -> PageResult:
        if isinstance(state.unit.result, PageResult):
            return state.unit.result
        transitions = [
            unit.result.goal_transition
            for unit in (
                *state.source_table_units,
                *state.report_units,
                *state.chunk_units,
            )
            if getattr(unit, "result", None) is not None
            and isinstance(
                getattr(unit.result, "goal_transition", None),
                GoalTransition,
            )
        ]
        result = PageResult(
            goal_transitions=tuple(transitions),
            chunk_encounters=tuple(
                dict(chunk)
                for material in state.materials
                for chunk in material.chunks
            ),
        )
        state.unit.attach_result(result)
        return result

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
            task, dict(unit.provider_result), outcome, rank=unit.rank
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
        if not self.goal_view.basis.columns:
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

        if (
            not material.fate.judged
            or material.source_record is None
            or not material.records
        ):
            return material
        source_record = material.source_record
        ingestion = dict(material.ingestion)
        chunks = [dict(item) for item in material.chunks]
        try:
            source_content = str(source_record.get("text") or "")
            for chunk in chunks:
                start = int(chunk.get("start_offset"))
                end = int(chunk.get("end_offset"))
                if start < 0 or end < start or end > len(source_content):
                    raise ValueError("chunk offsets fall outside the source-version blob")
                # Lexical extraction sees an offset-preserving view with source
                # tables blanked. Evidence storage must instead carry the exact
                # immutable source slice at those offsets.
                chunk["text"] = source_content[start:end]
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
            spans, direct_candidates = self.goal_view.assertion_candidates(
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
            best_guess_candidates = self.goal_view.best_guess_candidates(
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
            with self.open_prompt_scope(unit.episode_id, unit.episode_path):
                with self.open_cost_scope(
                    ObservationKind.SOURCE.value,
                    f"{unit.label}#goal-judgment",
                    unit.episode_id,
                    unit.episode_path,
                ):
                    decision = await self.evidence_acceptor.evaluate(
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
        except Exception as exc:  # noqa: BLE001 - one leaf fails closed
            error_class = classify_error(exc)
            print(
                f"[evidence-acceptance] {unit.label} failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
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
        tables = self.goal_view.basis.tables
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
        columns = self.goal_view.best_guess_columns_by_table()
        if not records or not any(columns.values()):
            return []
        report = await self.page_best_guess_fn(
            records=records,
            columns_by_table=columns,
            reported_alternatives_by_table=(
                self.goal_view.best_guess_routes_by_table()
            ),
            subject_key_columns_by_table=(
                self.goal_view.basis.subject_key_columns
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
