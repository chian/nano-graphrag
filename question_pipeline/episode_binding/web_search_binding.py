from __future__ import annotations

import json

from method_loop import EpisodeGoal
from question_pipeline.episode_binding.provider_binding import *
from question_pipeline.utilities.model import (
    JEV_REQUEST_TOKEN_BUDGET,
    JEV_TOKEN_ENCODING,
    JevTokenLimitError,
    ModelTier,
    ask_json,
    register_call_site_tier,
    token_count,
    token_window_text,
)

JEV_SEARCH_REQUEST_TOKEN_RESERVE = 5_000
JEV_PAGE_TEXT_TOKEN_LIMIT = (
    JEV_REQUEST_TOKEN_BUDGET - JEV_SEARCH_REQUEST_TOKEN_RESERVE
)
SEARCH_PAGE_SELECTION_VERSION = "model_planned_from_jev_evidence_v5"
LEGACY_SEARCH_PAGE_SELECTION_VERSIONS = frozenset(
    {"jev_relevance_then_provider_rank_v4"}
)
PAGE_CANDIDATE_ASSESSMENT_FAILED = "page_candidate_assessment_failed"
SEARCH_PAGE_PROPOSAL_FAILED = "search_page_proposal_failed"

_SEARCH_PAGE_PROPOSER_TIER = register_call_site_tier(
    "search-page-proposer",
    ModelTier.FAST,
)


@dataclass(frozen=True)
class SearchPageProposal:
    """The Search parent's choice of one assessed Page child."""

    option_id: str
    provider_rank: int
    objective: str = ""
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "provider_rank": self.provider_rank,
            "objective": self.objective,
            "rationale": self.rationale,
        }


async def propose_search_page(
    llm: Any,
    *,
    goal: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    previous_pages: Sequence[Mapping[str, Any]],
) -> SearchPageProposal:
    """Choose one Page child using measurements supplied by the Search binding."""

    options = {
        str(item.get("option_id") or ""): dict(item)
        for item in candidates
        if isinstance(item, Mapping) and str(item.get("option_id") or "")
    }
    if not options:
        raise ValueError("search page proposal requires at least one candidate")

    prompt = f"""SEARCH EPISODE GOAL:
{json.dumps(dict(goal), ensure_ascii=False, sort_keys=True, default=str)}

UNPROCESSED PAGE CANDIDATES:
{json.dumps(list(options.values()), ensure_ascii=False, sort_keys=True, default=str)}

PREVIOUS PAGE CHILDREN AND THEIR MEASURED RESULTS:
{json.dumps([dict(item) for item in previous_pages], ensure_ascii=False, sort_keys=True, default=str)}

Choose exactly one option_id from UNPROCESSED PAGE CANDIDATES.

Each candidate contains its original provider rank and a Jev probability that
the page can contribute to the Search Goal. These are measurements for your
planning, not a rule that the largest probability must be selected. Use the
candidate's title, description, provider rank, Jev assessment, and the realized
results of previous Page children to choose the next Page worth processing.

The Search Episode's numerical controller has already decided that another
Page may be attempted. You choose which Page to try; you never decide whether
the Search continues or stops.

Return exactly:
{{
  "option_id": "one exact option_id from UNPROCESSED PAGE CANDIDATES",
  "objective": "the Goal information this Page should seek",
  "rationale": "how candidate evidence and prior measured Page results support this choice"
}}"""
    payload = await ask_json(
        llm,
        prompt,
        system_prompt=(
            "You choose one Page child from a supplied Search candidate "
            "catalog. Return one JSON object. Never decide whether "
            "acquisition continues."
        ),
        tier=_SEARCH_PAGE_PROPOSER_TIER,
        call_site="search-page-proposer",
    )
    if not isinstance(payload, Mapping):
        raise ValueError("search page proposer must return a JSON object")
    option_id = str(payload.get("option_id") or "").strip()
    option = options.get(option_id)
    if option is None:
        raise ValueError("search page proposer selected an undeclared option_id")
    provider_rank = int(option.get("provider_rank") or 0)
    if provider_rank <= 0:
        raise ValueError("selected Page candidate has no valid provider rank")
    return SearchPageProposal(
        option_id=option_id,
        provider_rank=provider_rank,
        objective=str(payload.get("objective") or "").strip(),
        rationale=str(payload.get("rationale") or "").strip(),
    )


def _candidate_text_source(result: Mapping[str, Any]) -> str:
    for name in ("markdown", "content", "description"):
        if str(result.get(name) or "").strip():
            return name
    return "empty"


@dataclass(frozen=True)
class PageCandidateAssessment:
    """Jev's persisted estimate for one possible Page child."""

    task_id: str
    provider_rank: int
    title: str
    url: str
    relevance_probability: float
    window_probabilities: tuple[float, ...]
    window_token_counts: tuple[int, ...]
    token_encoding: str
    model_ids: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    attempts: int
    text_source: str
    text_chars: int
    text_tokens: int
    provider_token_limit_splits: int

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "PageCandidateAssessment":
        return cls(
            task_id=str(value.get("task_id") or ""),
            provider_rank=int(value.get("provider_rank") or 0),
            title=str(value.get("title") or ""),
            url=str(value.get("url") or ""),
            relevance_probability=float(
                value.get("relevance_probability") or 0.0
            ),
            window_probabilities=tuple(
                float(item)
                for item in (value.get("window_probabilities") or ())
            ),
            window_token_counts=tuple(
                int(item)
                for item in (value.get("window_token_counts") or ())
            ),
            token_encoding=str(value.get("token_encoding") or ""),
            model_ids=tuple(
                str(item) for item in (value.get("model_ids") or ())
            ),
            input_tokens=int(value.get("input_tokens") or 0),
            output_tokens=int(value.get("output_tokens") or 0),
            attempts=int(value.get("attempts") or 0),
            text_source=str(value.get("text_source") or ""),
            text_chars=int(value.get("text_chars") or 0),
            text_tokens=int(value.get("text_tokens") or 0),
            provider_token_limit_splits=int(
                value.get("provider_token_limit_splits") or 0
            ),
        )

    def __post_init__(self) -> None:
        if self.provider_rank <= 0:
            raise ValueError("page candidate provider_rank must be positive")
        if not 0.0 <= self.relevance_probability <= 1.0:
            raise ValueError(
                "page candidate relevance_probability must be between zero and one"
            )
        if any(not 0.0 <= value <= 1.0 for value in self.window_probabilities):
            raise ValueError("page candidate window probabilities must be calibrated")
        if len(self.window_token_counts) != len(self.window_probabilities):
            raise ValueError(
                "page candidate token counts must match its probability windows"
            )
        if any(value < 0 for value in self.window_token_counts):
            raise ValueError("page candidate window token counts cannot be negative")
        if not self.token_encoding:
            raise ValueError("page candidate token encoding must be recorded")
        if self.text_source not in {"markdown", "content", "description", "empty"}:
            raise ValueError("page candidate text source is not declared")
        if self.provider_token_limit_splits < 0:
            raise ValueError("page candidate token-limit splits cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "provider_rank": self.provider_rank,
            "title": self.title,
            "url": self.url,
            "relevance_probability": self.relevance_probability,
            "window_probabilities": list(self.window_probabilities),
            "window_token_counts": list(self.window_token_counts),
            "token_encoding": self.token_encoding,
            "model_ids": list(self.model_ids),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "attempts": self.attempts,
            "text_source": self.text_source,
            "text_chars": self.text_chars,
            "text_tokens": self.text_tokens,
            "provider_token_limit_splits": self.provider_token_limit_splits,
        }


async def assess_page_candidate(
    jev: Any,
    *,
    goal: EpisodeGoal,
    task: Any,
    result: Mapping[str, Any],
    provider_rank: int,
    extract_text: Callable[[dict[str, Any]], str],
) -> PageCandidateAssessment:
    """Measure whether one Firecrawl result can contribute to the Search Goal."""

    text = str(extract_text(dict(result)) or "")
    instructions = (
        "Does `candidate_text_window` contain evidence that could fill "
        "at least one result requested by `search_goal`, for an "
        "identifiable subject of that goal? Judge possible contribution "
        "to the declared result, not general topical similarity."
    )
    criteria = {
        "true": (
            "The text contains a reported value, an evidence-based basis "
            "for a permitted estimate, or identity/context needed to "
            "connect such a value to a requested subject."
        ),
        "false": (
            "The text cannot contribute any requested result even if it "
            "mentions the broad topic."
        ),
    }
    candidate = search_result_observation(
        dict(result),
        rank=provider_rank,
    )

    def state_for(window: str, index: int, count: int) -> dict[str, Any]:
        return {
            "search_goal": goal.as_record(),
            "search_query": str(task.query),
            "candidate": candidate,
            "candidate_text_window": window,
            "window_index": index,
            "window_count": count,
        }

    page_budget = JEV_PAGE_TEXT_TOKEN_LIMIT
    while True:
        windows = token_window_text(text, budget=page_budget) or [""]
        request_tokens = [
            jev.noul_request_token_count(
                state=state_for(window, index, len(windows)),
                instructions=instructions,
                criteria=criteria,
            )
            for index, window in enumerate(windows, start=1)
        ]
        overflow = max(request_tokens) - JEV_REQUEST_TOKEN_BUDGET
        if overflow <= 0:
            break
        if not text or page_budget <= overflow:
            raise ValueError(
                "Jev Search assessment metadata exceeds its 64,000-token "
                "request budget before page text can be included"
            )
        page_budget -= max(1, overflow)

    probabilities: list[float] = []
    models: list[str] = []
    input_tokens = 0
    output_tokens = 0
    attempts = 0
    provider_token_limit_splits = 0
    evaluated_windows: list[str] = []
    pending_windows = list(windows)
    while pending_windows:
        window = pending_windows.pop(0)
        window_index = len(evaluated_windows) + 1
        window_count = window_index + len(pending_windows)
        try:
            decision = await jev.noul(
                state=state_for(window, window_index, window_count),
                instructions=instructions,
                criteria=criteria,
            )
        except JevTokenLimitError:
            attempts += 1
            window_tokens = token_count(window)
            if window_tokens <= 1:
                raise
            pieces = token_window_text(
                window,
                budget=max(1, window_tokens // 2),
            )
            if len(pieces) < 2:
                raise
            provider_token_limit_splits += 1
            pending_windows[0:0] = pieces
            continue
        evaluated_windows.append(window)
        probabilities.append(float(decision.probability))
        models.append(decision.response.model)
        input_tokens += decision.response.input_tokens
        output_tokens += decision.response.output_tokens
        attempts += decision.response.attempts
    windows = evaluated_windows
    window_token_counts = tuple(token_count(window) for window in windows)
    return PageCandidateAssessment(
        task_id=str(task.id),
        provider_rank=int(provider_rank),
        title=str(result.get("title") or ""),
        url=str(result.get("url") or ""),
        relevance_probability=max(probabilities),
        window_probabilities=tuple(probabilities),
        window_token_counts=window_token_counts,
        token_encoding=JEV_TOKEN_ENCODING,
        model_ids=tuple(dict.fromkeys(models)),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        attempts=attempts,
        text_source=_candidate_text_source(result),
        text_chars=len(text),
        text_tokens=token_count(text),
        provider_token_limit_splits=provider_token_limit_splits,
    )


class SearchPageProposer:
    """The Search parent plans Page children from one provider result list.

    Firecrawl supplies a ranked candidate set. Jev measures each candidate
    against this Search Episode's Goal once. On every pull, the bound planner
    receives all unprocessed candidates, those measurements, and the measured
    outcomes of prior Page children, then chooses one declared candidate. The
    numerical controller remains the sole owner of when the Search Episode
    stops.
    """

    def __init__(
        self,
        *,
        task: Any,
        search_fn: SearchFn,
        make_page: PageFactory,
        assess_candidate: Callable[..., Awaitable[PageCandidateAssessment]],
        propose_page: Callable[..., Awaitable[SearchPageProposal]],
        extract_candidate_text: Callable[[dict[str, Any]], str],
        budget: SourceBudget,
        health: ProviderHealth,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        open_prompt_scope: Callable[
            [str, tuple[tuple[str, str], ...]], Any
        ],
        on_results: Optional[Callable[[Any, Sequence[Mapping[str, Any]]], None]] = None,
        on_assessments: Optional[
            Callable[[Any, Sequence[PageCandidateAssessment]], None]
        ] = None,
        on_selection: Optional[
            Callable[[Any, Mapping[str, Any]], None]
        ] = None,
        on_assessment_error: Optional[
            Callable[[Any, BaseException], None]
        ] = None,
        on_proposal_error: Optional[
            Callable[[Any, BaseException], None]
        ] = None,
        on_error: Optional[Callable[[Any, BaseException, bool], None]] = None,
        is_fatal: Callable[[BaseException], bool] = lambda _exc: False,
    ) -> None:
        self._task = task
        self._search_fn = search_fn
        self._make_page = make_page
        self._assess_candidate = assess_candidate
        self._propose_page = propose_page
        self._extract_candidate_text = extract_candidate_text
        self._budget = budget
        self._health = health
        self._episode_id = str(episode_id)
        self._episode_path = tuple(episode_path)
        self._open_cost_scope = open_cost_scope
        self._open_prompt_scope = open_prompt_scope
        self._on_results = on_results
        self._on_assessments = on_assessments
        self._on_selection = on_selection
        self._on_assessment_error = on_assessment_error
        self._on_proposal_error = on_proposal_error
        self._on_error = on_error
        self._is_fatal = is_fatal
        self._results: list[Mapping[str, Any]] = []
        self._assessments: dict[int, PageCandidateAssessment] = {}
        self._processed_ranks: set[int] = set()
        self._selection_history: list[dict[str, Any]] = []
        self._page_outcomes: list[dict[str, Any]] = []
        self._issued = False
        #: The provider call's finished meter, for the search's own outcome.
        #: The SEARCH scope now closes when that call returns, so per-page work
        #: no longer nests inside it: a page's SOURCE record carries
        #: ``nested_in=""`` and its own ``fetched_bytes``, where those bytes
        #: used to land on the search's meter.
        self.cost: Optional[Mapping[str, Any]] = None

    @property
    def remaining(self) -> int:
        """Buffered results not processed because the episode ended."""

        return max(0, len(self._results) - len(self._processed_ranks))

    @property
    def result_buffer(self) -> dict[str, Any]:
        """Provider results split into processed and still-unprocessed counts."""

        return {
            "buffered_results": len(self._results),
            "assessed_results": len(self._assessments),
            "processed_results": len(self._processed_ranks),
            "unprocessed_results": self.remaining,
            "selection_version": SEARCH_PAGE_SELECTION_VERSION,
        }

    def checkpoint_state(self) -> dict[str, Any]:
        """The exact provider buffer position after one completed page unit."""

        return {
            "selection_version": SEARCH_PAGE_SELECTION_VERSION,
            "results": [dict(item) for item in self._results],
            "assessments": [
                self._assessments[rank].to_dict()
                for rank in sorted(self._assessments)
            ],
            "processed_ranks": sorted(self._processed_ranks),
            "selection_history": [dict(item) for item in self._selection_history],
            "page_outcomes": [dict(item) for item in self._page_outcomes],
            "issued": self._issued,
            "cost": dict(self.cost) if self.cost is not None else None,
        }

    def restore_checkpoint_state(self, state: Mapping[str, Any]) -> None:
        """Resume the saved buffer without issuing the provider search again."""

        results = state.get("results") or ()
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            raise TypeError("active search results must be a sequence")
        restored = [dict(item) for item in results if isinstance(item, Mapping)]
        restored_version = str(state.get("selection_version") or "")
        if restored_version not in {
            SEARCH_PAGE_SELECTION_VERSION,
            *LEGACY_SEARCH_PAGE_SELECTION_VERSIONS,
        }:
            raise ValueError(
                "active search checkpoint has an unknown Page-selection "
                f"contract {restored_version!r}"
            )
        assessments = {
            item.provider_rank: item
            for item in (
                PageCandidateAssessment.from_record(raw)
                for raw in (state.get("assessments") or ())
                if isinstance(raw, Mapping)
            )
        }
        if set(assessments) != set(range(1, len(restored) + 1)):
            raise ValueError(
                "active search checkpoint must assess every buffered result"
            )
        for rank, result in enumerate(restored, start=1):
            assessment = assessments[rank]
            if assessment.task_id != str(self._task.id):
                raise ValueError(
                    "active search assessment does not match its Search task"
                )
            if assessment.url != str(result.get("url") or ""):
                raise ValueError(
                    "active search assessment does not match its provider result"
                )
        processed_ranks = {
            int(value) for value in (state.get("processed_ranks") or ())
        }
        if not processed_ranks.issubset(assessments):
            raise ValueError("active search checkpoint has an invalid processed rank")
        if not bool(state.get("issued")):
            raise ValueError("a checkpointed active search must have issued its provider call")
        self._results = restored
        self._assessments = assessments
        self._processed_ranks = processed_ranks
        selection_history = [
            dict(item)
            for item in (state.get("selection_history") or ())
            if isinstance(item, Mapping)
        ]
        selected_ranks = [
            int(item.get("provider_rank") or 0)
            for item in selection_history
        ]
        if (
            len(selected_ranks) != len(set(selected_ranks))
            or set(selected_ranks) != processed_ranks
        ):
            raise ValueError(
                "active search selection history does not match processed results"
            )
        self._selection_history = selection_history
        self._page_outcomes = [
            dict(item)
            for item in (state.get("page_outcomes") or ())
            if isinstance(item, Mapping)
        ]
        self._issued = True
        cost = state.get("cost")
        self.cost = dict(cost) if isinstance(cost, Mapping) else None

    def restore_page_outcomes(
        self,
        outcomes: Sequence[Mapping[str, Any]],
        *,
        facet_labels: Mapping[str, str],
    ) -> None:
        """Load compact prior Page results missing from a legacy source state."""

        if self._page_outcomes:
            return
        restored: list[dict[str, Any]] = []
        prefix = f"{self._task.id}#"
        for raw in outcomes:
            item = dict(raw)
            label = str(item.get("label") or "")
            provider_rank = int(item.get("provider_rank") or 0)
            if provider_rank <= 0 and label.startswith(prefix):
                try:
                    provider_rank = int(label[len(prefix):])
                except ValueError:
                    provider_rank = 0
            restored.append(
                {
                    "provider_rank": provider_rank,
                    "page_label": label,
                    "status": (
                        "observed"
                        if bool(item.get("active", True))
                        else "failed"
                    ),
                    "distinct_findings": len(item.get("credits") or ()),
                    "findings_by_channel": {
                        str(facet_labels.get(str(name), str(name))): len(
                            values or ()
                        )
                        for name, values in dict(item.get("facets") or {}).items()
                    },
                    "note": str(item.get("note") or ""),
                }
            )
        self._page_outcomes = restored

    def record_page_outcome(self, outcome: Mapping[str, Any]) -> None:
        """Make one completed Page's compact measured result available to planning."""

        item = dict(outcome)
        provider_rank = int(item.get("provider_rank") or 0)
        if provider_rank <= 0:
            raise ValueError("Page planning outcome requires its provider rank")
        self._page_outcomes = [
            prior
            for prior in self._page_outcomes
            if int(prior.get("provider_rank") or 0) != provider_rank
        ]
        self._page_outcomes.append(item)

    def _candidate_options(self, pending: Sequence[int]) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        for rank in pending:
            result = self._results[rank - 1]
            assessment = self._assessments[rank]
            options.append(
                {
                    "option_id": f"page:{rank}",
                    "provider_rank": rank,
                    "title": str(result.get("title") or assessment.title),
                    "url": str(result.get("url") or assessment.url),
                    "description": str(result.get("description") or ""),
                    "jev_assessment": {
                        "relevance_probability": assessment.relevance_probability,
                        "window_probabilities": list(
                            assessment.window_probabilities
                        ),
                        "text_source": assessment.text_source,
                        "text_tokens": assessment.text_tokens,
                    },
                }
            )
        return options

    async def next(self, view: EpisodeView) -> Any:
        if self._health.fatal:
            # The run already knows the provider refused. A search must not pay
            # another round trip to rediscover it.
            return SourceEnd(END_SOURCE_FAILED, FATAL_SEARCH_ERROR)
        if self._budget.exhausted:
            return SourceEnd(END_BOUND_HIT, BOUND_KIND_RUN_SOURCE_BUDGET)
        if not self._issued:
            self._issued = True
            end = await self._issue(view.goal)
            if end is not None:
                return end
        pending = [
            rank
            for rank in range(1, len(self._results) + 1)
            if rank not in self._processed_ranks
        ]
        if not pending:
            return None
        proposal_index = len(self._selection_history) + 1
        observation_id = f"{self._task.id}#page-selection-{proposal_index:04d}"
        try:
            with self._open_prompt_scope(self._episode_id, self._episode_path):
                with self._open_cost_scope(
                    ObservationKind.PAGE_CHILD_PROPOSAL.value,
                    observation_id,
                    self._episode_id,
                    self._episode_path,
                ):
                    proposal = await self._propose_page(
                        goal=view.goal.as_record(),
                        candidates=self._candidate_options(pending),
                        previous_pages=tuple(self._page_outcomes),
                    )
        except Exception as exc:  # noqa: BLE001 - typed source failure, no fallback
            if self._on_proposal_error is not None:
                self._on_proposal_error(self._task, exc)
            return SourceEnd(END_SOURCE_FAILED, SEARCH_PAGE_PROPOSAL_FAILED)
        if not isinstance(proposal, SearchPageProposal):
            error = TypeError("search page planner returned an invalid proposal")
            if self._on_proposal_error is not None:
                self._on_proposal_error(self._task, error)
            return SourceEnd(END_SOURCE_FAILED, SEARCH_PAGE_PROPOSAL_FAILED)
        rank = proposal.provider_rank
        if rank not in pending:
            error = ValueError("search page planner selected a processed candidate")
            if self._on_proposal_error is not None:
                self._on_proposal_error(self._task, error)
            return SourceEnd(END_SOURCE_FAILED, SEARCH_PAGE_PROPOSAL_FAILED)
        self._processed_ranks.add(rank)
        assessment = self._assessments[rank]
        selection = {
            "selection_index": proposal_index,
            "provider_rank": rank,
            "relevance_probability": assessment.relevance_probability,
            "remaining_candidates_after": self.remaining,
            "selection_version": SEARCH_PAGE_SELECTION_VERSION,
            "proposal": proposal.to_dict(),
        }
        self._selection_history.append(selection)
        if self._on_selection is not None:
            self._on_selection(self._task, selection)
        result = self._results[rank - 1]
        return self._make_page(
            self._task, result, rank, view.goal
        )

    async def _issue(self, goal: EpisodeGoal) -> Optional[SourceEnd]:
        """The provider call, inside its own cost scope, on the first pull."""

        end: Optional[SourceEnd] = None
        results: list[Mapping[str, Any]] = []
        with self._open_cost_scope(
            ObservationKind.SEARCH.value,
            str(self._task.id),
            self._episode_id,
            self._episode_path,
        ) as meter:
            try:
                # ``None`` is the acquisition framework's explicit absence of
                # an item cap. The real Firecrawl adapter resolves it to that
                # provider's own default batch size; an injected adapter owns
                # its own interpretation and is never stamped as Firecrawl.
                results = list(self._search_fn(self._task.query, None))
            except Exception as exc:  # noqa: BLE001 - classified once, then named
                fatal = bool(self._is_fatal(exc))
                if meter is not None:
                    error_class = classify_error(exc)
                    if error_class == CostErrorClass.OTHER.value:
                        error_class = CostErrorClass.SEARCH_FAILED.value
                    meter.add_provider_call(error_class=error_class)
                if self._on_error is not None:
                    self._on_error(self._task, exc, fatal)
                if fatal:
                    self._health.fatal = FATAL_SEARCH_ERROR
                    end = SourceEnd(END_SOURCE_FAILED, FATAL_SEARCH_ERROR)
                else:
                    end = SourceEnd(END_SOURCE_FAILED, SEARCH_ERROR)
            else:
                if meter is not None:
                    meter.add_provider_call(returned_hits=len(results))
            if meter is not None:
                self.cost = meter.snapshot().to_dict()
        if end is not None:
            return end
        self._results = results
        if self._on_results is not None:
            self._on_results(self._task, results)
        assessments: list[PageCandidateAssessment] = []
        try:
            for rank, result in enumerate(results, start=1):
                assessments.append(
                    await self._assess_candidate(
                        goal=goal,
                        task=self._task,
                        result=result,
                        provider_rank=rank,
                        extract_text=self._extract_candidate_text,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - typed source failure, no fallback
            if self._on_assessment_error is not None:
                self._on_assessment_error(self._task, exc)
            return SourceEnd(
                END_SOURCE_FAILED,
                PAGE_CANDIDATE_ASSESSMENT_FAILED,
            )
        self._assessments = {
            assessment.provider_rank: assessment
            for assessment in assessments
        }
        if self._on_assessments is not None:
            self._on_assessments(self._task, assessments)
        return None


class WebSearchBinding:
    """Methods owned by the search Episode."""

    def _page_episode_result(
        self,
        state: PageRunState,
        record: EpisodeRecord,
    ) -> EpisodeResult:
        result = self._attach_page_result(state)
        return self._episode_result(
            record,
            output=PageEpisodeOutput(
                unit=state.unit,
                material=self._page_material(state),
                result=result,
            ),
            retain_trace=self.checkpoint_completed_page is not None,
        )

    def _build_search_episode(
        self,
        task: SearchTask,
        strategy_key: str,
        family: str,
        *,
        parent_goal: EpisodeGoal,
        resume_state: Optional[Mapping[str, Any]] = None,
    ) -> Episode:
        goal = EpisodeGoal.for_grain(
            self.search_grain,
            parent=parent_goal,
            objective={
                "search_task_id": task.id,
                "query": task.query,
                "strategy_key": str(strategy_key),
                "strategy_family": str(family),
            },
        )
        if resume_state is None:
            outcome = SearchOutcome.for_task(task)
        else:
            raw_outcome = resume_state.get("outcome") or {}
            if not isinstance(raw_outcome, Mapping):
                raise TypeError("active search outcome must be a mapping")
            allowed = set(SearchOutcome.__dataclass_fields__)
            values = {
                key: value for key, value in raw_outcome.items() if key in allowed
            }
            outcome = SearchOutcome(**values)
            if outcome.task_id != task.id:
                raise ValueError("active search outcome does not match its task")
        self._open_outcomes[task.id] = outcome
        search_path = (
            (self.run_grain.name, self.run_key),
            (self.strategy_grain.name, strategy_key),
            (self.search_grain.name, task.id),
        )
        search_episode_id = Episode.identity(
            self.controller.context,
            self.search_grain,
            task.id,
            parent_path=search_path[:-1],
        ).episode_id
        source = SearchPageProposer(
            task=task,
            search_fn=self.search_fn,
            make_page=lambda task, result, rank, parent: self._make_page_item(
                task,
                result,
                rank,
                episode_id=search_episode_id,
                episode_path=search_path,
                parent_goal=parent,
            ),
            assess_candidate=lambda **kwargs: assess_page_candidate(
                self.jev_client,
                **kwargs,
            ),
            propose_page=self.propose_search_page,
            extract_candidate_text=self.harvester.extract_text_fn,
            budget=self.budget,
            health=self.health,
            episode_id=search_episode_id,
            episode_path=search_path,
            open_cost_scope=self.open_cost_scope,
            open_prompt_scope=self.open_prompt_scope,
            on_results=self._note_search_results,
            on_assessments=self._note_page_assessments,
            on_selection=self._note_page_selection,
            on_assessment_error=self._note_page_assessment_error,
            on_proposal_error=self._note_page_proposal_error,
            on_error=self._note_search_error,
            is_fatal=is_fatal_search_error,
        )
        if resume_state is not None:
            source_state = resume_state.get("source") or {}
            if not isinstance(source_state, Mapping):
                raise TypeError("active search source state must be a mapping")
            source.restore_checkpoint_state(source_state)
            source.restore_page_outcomes(
                tuple(resume_state.get("completed_page_units") or ()),
                facet_labels=self.goal_view.facet_labels,
            )
        self._open_sources[task.id] = source
        resume_units = tuple(
            ResumeUnit(
                label=str(item["label"]),
                controller_input=_restored_observation(item),
            )
            for item in (
                (resume_state or {}).get("completed_page_units") or ()
            )
        )
        return Episode(
            grain=self.search_grain,
            key=task.id,
            source=source,
            request=EpisodeRequest(goal=goal),
            on_unit=lambda unit, contribution, record: self._on_page(
                unit, contribution, record, outcome, strategy_key, family
            ),
            on_close=lambda record: self._close_search(
                record, strategy_key, family
            ),
            to_parent=self._search_episode_result,
            parent_controller_input=self._parent_controller_input,
            resume_units=resume_units,
        )

    def _on_page(
        self,
        item: Any,
        contribution: Any,
        record: Any,
        outcome: SearchOutcome,
        strategy_key: str,
        family: str,
    ) -> None:
        if isinstance(item, Episode):
            output = contribution.output
            self._page_states.pop(item.key, None)
            if not isinstance(output, PageEpisodeOutput):
                self.record_hook_failure(
                    "on_page",
                    item.key,
                    TypeError(f"page update missing for {item.key!r}"),
                )
                return
            unit = output.unit
            material = output.material
        else:
            unit = item.unit
            material = contribution.output
        try:
            self.budget.charge(1)
            self.set_units_pulled(self.budget.spent)
            if isinstance(material, PageMaterial):
                skip = fate_skip_reason(material.fate)
                if skip:
                    outcome.skip(skip)
                if material.source_record is not None:
                    source = dict(material.source_record)
                    self._accepted_sources.append(source)
                    self.record_goal_discovery_sources([source])
                    if material.entities or material.relationships:
                        graph = self.enrich_graph_fn(
                            self.get_graph(),
                            dict(material.entities),
                            list(material.relationships),
                            material.source_id,
                            similarity_threshold=self.similarity_threshold,
                            auto_merge=self.auto_merge_entities,
                        )
                        self.set_graph(graph)
                self._write_page_detail(
                    unit, record, material, strategy_key, family
                )
                observation = _incidence_input(contribution.controller_input)
                active_page_unit = {
                    "label": str(unit.label),
                    "provider_rank": int(unit.rank),
                    "credits": list(observation.identities),
                    "active": observation.status == OBSERVATION_OBSERVED,
                    "note": observation.note,
                    "facets": {
                        str(name): list(values)
                        for name, values in observation.channels.items()
                    },
                    "counts_toward_verdict": (
                        observation.status != OBSERVATION_EXCLUDED
                    ),
                }
                self._active_page_units.append(active_page_unit)
                source = self._open_sources.get(unit.task.id)
                if source is not None:
                    source.record_page_outcome(
                        {
                            "provider_rank": int(unit.rank),
                            "page_label": str(unit.label),
                            "status": observation.status,
                            "distinct_findings": len(observation.identities),
                            "findings_by_channel": {
                                self.goal_view.facet_labels.get(
                                    str(name), str(name)
                                ): len(values)
                                for name, values in observation.channels.items()
                            },
                            "note": observation.note,
                        }
                    )
                if self.checkpoint_completed_page is not None:
                    if contribution.episode_update is None:
                        raise TypeError("page checkpoint requires an EpisodeUpdate")
                    page_record = self.take_episode_record(
                        contribution.episode_update.record_id
                    )
                    self.checkpoint_completed_page(
                        page_record,
                        strategy_key,
                        family,
                    )
        except Exception as exc:  # noqa: BLE001 - hook must not unwind the tree
            self.record_hook_failure("on_page", unit.label, exc)

    def _close_search(
        self,
        record: EpisodeRecord,
        strategy_key: str,
        family: str,
    ) -> None:
        """Finalize a search from its own trace before publishing its update."""

        try:
            task_id = record.scope_key
            outcome = self._open_outcomes.pop(task_id, None)
            source = self._open_sources.pop(task_id, None)
            if outcome is None:
                return
            if record.ended_by == END_YIELD_STOP:
                remaining = source.remaining if source is not None else 0
                if remaining > 0:
                    outcome.skip("yield_stop", remaining)
                self.append_control_decision(
                    self.controller.write_decision(
                        record,
                        decision_point=DECISION_SEARCH_ITEM_YIELD,
                        family=family,
                    )
                )
            if source is not None and source.cost is not None:
                outcome.cost = dict(source.cost)
            outcome.provider_batch = dict(self.search_provider_batch)
            if source is not None:
                outcome.result_buffer = source.result_buffer
            self.last_search_outcomes.append(outcome)
            self.frontier.record([outcome])
            self.search_outcomes.append(outcome.to_dict())
            self.queries_used.append(outcome.query)
            self.harvester.record_outcome(outcome)
            self.refresh_search_memory()
            self.record_prompt_attempt_counts([outcome])
            self._pending_followup_outcomes.append(outcome)
            observation = _episode_observation(record)
            self._active_search_units.append(
                {
                    "label": str(record.scope_key),
                    "credits": list(observation.identities),
                    "active": observation.status == OBSERVATION_OBSERVED,
                    "note": observation.note,
                    "facets": {
                        str(name): list(values)
                        for name, values in observation.channels.items()
                    },
                    "counts_toward_verdict": (
                        observation.status != OBSERVATION_EXCLUDED
                    ),
                }
            )
            if self.checkpoint_completed_search is not None:
                self.checkpoint_completed_search(record, strategy_key, family)
            self._active_page_units = []
            self._resume_search_state = {}
        except Exception as exc:  # noqa: BLE001 - hook must not unwind the tree
            self.record_hook_failure("close_search", record.scope_key, exc)

    def _note_search_results(
        self,
        task: SearchTask,
        results: Sequence[Mapping[str, Any]],
    ) -> None:
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            return
        outcome.firecrawl_hits = len(results)
        for rank, result in enumerate(results, start=1):
            outcome.search_result_observations.append(
                search_result_observation(dict(result), rank=rank)
            )

    def _note_page_assessments(
        self,
        task: SearchTask,
        assessments: Sequence[PageCandidateAssessment],
    ) -> None:
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            return
        outcome.page_candidate_assessments = [
            assessment.to_dict() for assessment in assessments
        ]

    def _note_page_selection(
        self,
        task: SearchTask,
        selection: Mapping[str, Any],
    ) -> None:
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            return
        outcome.page_selection_history.append(dict(selection))

    def _note_page_assessment_error(
        self,
        task: SearchTask,
        exc: BaseException,
    ) -> None:
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            return
        outcome.error = str(exc)
        outcome.skip(PAGE_CANDIDATE_ASSESSMENT_FAILED)

    def _note_page_proposal_error(
        self,
        task: SearchTask,
        exc: BaseException,
    ) -> None:
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            return
        outcome.error = str(exc)
        outcome.skip(SEARCH_PAGE_PROPOSAL_FAILED)

    def _note_search_error(
        self,
        task: SearchTask,
        exc: BaseException,
        fatal: bool,
    ) -> None:
        outcome = self._open_outcomes.get(task.id)
        if outcome is not None:
            outcome.error = str(exc)
            outcome.skip("search_failed")
        if fatal:
            self.set_search_provider_error(str(exc))
            print(f"  Search provider stopped the run: {exc}")
