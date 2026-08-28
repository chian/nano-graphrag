"""Search frontier and page-acquisition primitives.

**This module holds no loop over units.** Until phase 4E-c it owned a ``for``
over one search's result list that consulted a controller between pages and
broke on a verdict -- charter rules 1 and 2 exactly, and the shape the
phase-batched flow was condemned for. The loop is now the kernel's, once, and
what survives here is the acquisition *mechanics* the leaf's ``extract`` calls
as functions: prepare a page, write an accepted one, record an outcome. The
frontier stays the queue and the ``strategy`` episode became its consumer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from paper_fetching.firecrawl_client import extract_text_from_result

from .costs import (
    ObservationKind,
    active_meter,
    record_fetched_bytes,
    zero_cost,
)


SearchFn = Callable[[str, int], list[dict[str, Any]]]
ScrapeFn = Callable[[str], Optional[dict[str, Any]]]


_BLOCKED_PAGE_MARKERS = (
    "checking your browser before accessing",
    "recaptcha requires verification",
    "protected by recaptcha",
    "cf-browser-verification",
    "attention required! | cloudflare",
)
_FATAL_SEARCH_STATUS_CODES = {401, 402, 403, 429}
_COMPACT_RESULT_SKIP_KEYS = {
    "actions",
    "content",
    "html",
    "links",
    "llm_extraction",
    "markdown",
    "metadata",
    "rawHtml",
    "screenshot",
}
_COMPACT_RESULT_MAX_STRING = 800


@dataclass(frozen=True)
class SearchTask:
    query: str
    id: str = ""
    parent_id: Optional[str] = None
    topic: str = "batch"
    expansion_op: str = "direct"
    gap: str = ""
    round_index: int = 0
    depth: int = 0
    #: Whether this task can produce accepted sources at all.
    #:
    #: False for tasks that issue provider calls purely to measure the search
    #: space -- the completion probe harvests nothing by construction, holding
    #: zero `candidate_source_outcomes` and zero acceptances no matter what it
    #: finds. Such a task belongs in a cost denominator and must be excluded
    #: from a yield denominator, and a consumer needs a typed way to say that.
    #:
    #: Typed rather than inferred: the alternative is every reader matching on
    #: `expansion_op == "completion_probe"`, which puts a correctness
    #: requirement in every future consumer and silently breaks the moment a
    #: second non-harvesting op appears. The producer knows; it should say so.
    yields_sources: bool = True
    #: Which producer built this task, as a typed class label. Declared rather
    #: than inferred because only ONE producer mints prompt arms: the deficit
    #: planner. Gap, catalog, seed-frontier and probe tasks carry an empty
    #: `prompt_arm_id` **by declaration**, and minting a synthetic one to make
    #: them look arm-bearing would create an arm with no delta, no hypothesis
    #: and no sibling, whose contrast means nothing.
    producer_class: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_query = self.query.strip()
        object.__setattr__(self, "query", normalized_query)
        if self.id:
            return
        object.__setattr__(self, "id", self.stable_id())

    def stable_id(self) -> str:
        """This task's identity, INCLUDING the prompt arm that produced it.

        Without the arm, two arms of one attempt emitting identical query text
        mint one id -- and the frontier's persistent-mode dedupe then drops the
        second silently, handing the first-seen arm the attribution. That is the
        order-dependent credit assignment `control.SearchCandidate` already
        fixed one layer up, surviving at the frontier; and under the acquisition
        composition, where a search episode is keyed by this id, the same
        collision would either drop the task or re-open an already-open scope
        and unwind the whole record tree.

        ``metadata`` is a dataclass field bound before ``__post_init__`` runs,
        so it is readable here. Direction: strictly more distinct task ids,
        never fewer. Every task id changes, so nothing compares an id minted
        here against one from before this change.
        """

        payload = {
            "query": normalize_query(self.query),
            "parent_id": self.parent_id or "",
            "topic": self.topic,
            "expansion_op": self.expansion_op,
            "prompt_arm_id": str(self.metadata.get("prompt_arm_id") or ""),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def task_strategy_family(task: SearchTask) -> str:
    """The deterministic operator family this task belongs to.

    ONE RESOLUTION, IMPORTED RATHER THAN RESTATED. `expansion_op` is a plumbing
    label that lumps every deficit-targeted search into a single strategy, which
    would make the strategy grain a synonym for the run; `strategy_operator` is
    the family `strategy_state.route_next_family` selects from a closed catalog,
    which is what a strategy episode is an episode *of*. Code-written
    closed-vocabulary fields, never model prose.
    """

    metadata = task.metadata if isinstance(task.metadata, Mapping) else {}
    return (
        str(metadata.get("strategy_operator") or "").strip()
        or str(task.expansion_op or "").strip()
        or "direct"
    )


@dataclass
class SearchOutcome:
    task_id: str
    query: str
    topic: str = "batch"
    expansion_op: str = "direct"
    gap: str = ""
    round_index: int = 0
    #: Carried through from the task, so a consumer reading outcomes never has
    #: to reach back to the task or match on `expansion_op` to know whether a
    #: zero acceptance count means "found nothing" or "cannot find anything".
    yields_sources: bool = True
    firecrawl_hits: int = 0
    accepted_source_ids: list[str] = field(default_factory=list)
    accepted_urls: list[str] = field(default_factory=list)
    duplicate_urls: list[str] = field(default_factory=list)
    skipped_by_reason: dict[str, int] = field(default_factory=dict)
    scrape_failed_urls: list[str] = field(default_factory=list)
    search_result_observations: list[dict[str, Any]] = field(default_factory=list)
    candidate_source_outcomes: list[dict[str, Any]] = field(default_factory=list)
    text_reductions: list[dict[str, Any]] = field(default_factory=list)
    relevance_decisions: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: The provider/request limit that filled this search's result buffer.
    #: Provider-specific and observational: no stop rule reads it.
    provider_batch: dict[str, Any] = field(default_factory=dict)
    #: Returned results split by whether the one-page source processed them.
    result_buffer: dict[str, int] = field(default_factory=dict)
    error: str = ""
    #: What this search cost. Present on every outcome, as a typed zero when
    #: cost accounting is off, so a consumer can tell "no cost" from "no field".
    cost: dict[str, Any] = field(default_factory=zero_cost)

    @classmethod
    def for_task(cls, task: SearchTask) -> "SearchOutcome":
        return cls(
            task_id=task.id,
            query=task.query,
            topic=task.topic,
            expansion_op=task.expansion_op,
            gap=task.gap,
            round_index=task.round_index,
            yields_sources=task.yields_sources,
            metadata=dict(task.metadata),
            cost=zero_cost(
                observation_kind=ObservationKind.SEARCH.value,
                observation_id=task.id,
                round_index=task.round_index,
            ),
        )

    def skip(self, reason: str, count: int = 1) -> None:
        skipped = Counter(self.skipped_by_reason)
        skipped[reason] += count
        self.skipped_by_reason = dict(skipped)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceRelevanceDecision:
    """The page gate's outcome, as a record. Nothing here is a model's verdict.

    ``accept`` is written from ``acquisition.page_clears_relevance``'s returned
    boolean -- the rule's outcome, not a label. **NO MODEL-EMITTED FIELD MAY
    EVER BE WRITTEN INTO IT AGAIN**: this field used to be
    ``bool(assessment["accept"])`` over a model's own accept/defer/reject word,
    which put a model on the switch that decides whether a page is extracted,
    hence on the numerator of the rule that decides whether to keep fetching.

    The gate fields are carried so route 2 recomputes the decision from the
    record without the pipeline, and so a later phase can set the floor from the
    observed distribution rather than from the constant's docstring.

    ``confidence`` IS RETIRED, NOT BACKFILLED. It was
    ``judgment.fruitfulness_score``, and that score is no longer asked for --
    its declared meaning was a progress estimate over the run's state rather
    than a property of this page. It is deliberately NOT filled from
    ``gate_score``: one number wearing two names, one of them "confidence", is
    how a gate score acquires a second meaning nobody registered. No predicate
    read it, and that is what must stay true.
    """

    accept: bool
    reason: str = ""
    #: The reported score the rule compared. ``None`` when none arrived.
    gate_score: float | None = None
    gate_floor: float = 0.0
    gate_outcome: str = ""
    gate_rule: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HarvestCandidate:
    result: dict[str, Any]
    url: str
    text: str
    reduction: dict[str, Any]


class SearchFrontier:
    """Queue search tasks while optionally deduplicating across waves."""

    def __init__(self, *, mode: str = "batch"):
        if mode not in {"batch", "persistent"}:
            raise ValueError("search frontier mode must be 'batch' or 'persistent'")
        self.mode = mode
        self._pending: OrderedDict[str, SearchTask] = OrderedDict()
        self._sequence = 0
        self._seen_task_ids: set[str] = set()
        self.outcomes: list[SearchOutcome] = []

    @property
    def persistent(self) -> bool:
        return self.mode == "persistent"

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def enqueue_queries(
        self,
        queries: Iterable[str],
        *,
        round_index: int,
        topic: str,
        expansion_op: str,
        parent_id: Optional[str] = None,
        producer_class: str = "",
    ) -> list[SearchTask]:
        """Enqueue bare query strings. THESE CARRY NO PROMPT ARM, BY DECLARATION.

        Only the deficit planner mints arms. A seed or catalog query has no
        delta, no hypothesis and no sibling, so it has no arm, and minting a
        synthetic ``prompt_arm_id`` to make one look arm-bearing would create an
        arm whose contrast means nothing. ``producer_class`` records which
        producer built it, so the absence is a declaration rather than a gap.
        """

        tasks = [
            SearchTask(
                query=query,
                parent_id=parent_id,
                topic=topic,
                expansion_op=expansion_op,
                round_index=round_index,
                producer_class=producer_class or topic,
            )
            for query in queries
        ]
        return self.enqueue(tasks)

    def enqueue(self, tasks: Iterable[SearchTask]) -> list[SearchTask]:
        accepted = []
        for task in tasks:
            if not task.query:
                continue
            if self.persistent and task.id in self._seen_task_ids:
                continue
            pending_key = task.id if self.persistent else f"{self._sequence}:{task.id}"
            self._sequence += 1
            self._pending[pending_key] = task
            self._seen_task_ids.add(task.id)
            accepted.append(task)
        return accepted

    def next_for(self, family: str) -> Optional[SearchTask]:
        """Pop the first pending task of one strategy family, or ``None``.

        A POP, and no loop that reads a verdict: the frontier stays the queue
        and the ``strategy`` episode is its consumer. ``None`` means this family
        has no pending task *right now* -- which ends that strategy instance by
        exhaustion, not by abandonment, and leaves the family free to open a new
        instance once follow-up planning refills the queue.

        ``next_wave`` and ``requeue_front`` are gone with the wave loop and the
        within-round demotion gate that were their only callers. A strategy that
        yield-stops leaves its remaining tasks IN the frontier, which is how
        "never deleted, never domain-filtered" survives without them.
        """

        wanted = str(family)
        for key, task in self._pending.items():
            if task_strategy_family(task) == wanted:
                del self._pending[key]
                return task
        return None

    def pending_by_family(self) -> dict[str, list[SearchTask]]:
        """Pending tasks grouped by family, for the stranded-work disclosure."""

        out: dict[str, list[SearchTask]] = {}
        for task in self._pending.values():
            out.setdefault(task_strategy_family(task), []).append(task)
        return out

    def record(self, outcomes: Iterable[SearchOutcome]) -> None:
        self.outcomes.extend(outcomes)

    def mark_seen(self, tasks: Iterable[SearchTask]) -> None:
        for task in tasks:
            if task.id:
                self._seen_task_ids.add(task.id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "pending_tasks": len(self._pending),
            "pending_task_records": [
                task.to_dict()
                for task in self._pending.values()
            ],
            "seen_tasks": len(self._seen_task_ids),
            "completed_tasks": len(self.outcomes),
        }


@dataclass(frozen=True)
class PreparedPage:
    """One page's mechanical preparation: the candidate, or why there is none.

    ``fate`` is one of ``acquisition``'s declared pre-gate fate labels, or
    ``""`` when the page is ready to be gated. THIS MODULE REPORTS THE FACT AND
    MINTS NO FATE CLASS: what a fate means for ``(active,
    counts_toward_verdict)`` is decided once, in ``acquisition``, because two
    modules holding opinions about that is how a model's boolean ended up on the
    kernel's ``crediting_active`` flag in the first place.
    """

    candidate: Optional["HarvestCandidate"] = None
    fate: str = ""
    error_class: str = ""
    text_length: int = 0


class SearchHarvester:
    """Page-acquisition mechanics, called as functions by the leaf's ``extract``.

    NO LOOP AND NO SINK. It holds no ``item_sink``, issues no provider search of
    its own, and never learns what a credit is. The provider call belongs to the
    ``search`` grain's source, which issues it once on the first pull and hands
    the result list out one rank at a time, after each verdict.
    """

    def __init__(
        self,
        *,
        papers_dir: Path,
        seen_urls: set[str],
        scrape_fn: Optional[ScrapeFn] = None,
        min_paper_length: int = 500,
        max_paper_length: Optional[int] = None,
        max_extraction_chars_per_paper: Optional[int] = None,
        extract_text_fn: Callable[[dict[str, Any]], str] = extract_text_from_result,
    ):
        self.scrape_fn = scrape_fn
        self.papers_dir = papers_dir
        self.seen_urls = seen_urls
        self.min_paper_length = min_paper_length
        self.max_paper_length = max_paper_length
        self.max_extraction_chars_per_paper = max_extraction_chars_per_paper
        self.extract_text_fn = extract_text_fn

    def prepare_page(
        self,
        task: SearchTask,
        result: dict[str, Any],
        outcome: SearchOutcome,
        *,
        rank: int,
    ) -> PreparedPage:
        """Fetch and screen one page. Reports its fate; decides nothing."""

        url = str(result.get("url") or "")
        if url and url in self.seen_urls:
            outcome.duplicate_urls.append(url)
            self.record_candidate_outcome(
                outcome, result, rank=rank, fate="duplicate_url"
            )
            return PreparedPage(fate="duplicate_url")

        try:
            text = self._extract_best_text(result, url, outcome)
        except Exception as exc:  # noqa: BLE001 - classified, never raised at a leaf
            from .costs import classify_error

            self.record_candidate_outcome(
                outcome,
                result,
                rank=rank,
                fate="fetch_failed",
                reason=type(exc).__name__,
            )
            return PreparedPage(fate="fetch_failed", error_class=classify_error(exc))

        # Bytes fetched for this page, counted before any acceptance test: a
        # page that turned out to be blocked or too short was still paid for.
        # Under the composition the open meter is this page's SOURCE scope, so
        # these bytes land on the page's own record rather than on the search's.
        if active_meter() is not None:
            record_fetched_bytes(len(text.encode("utf-8", "ignore")))
        if is_blocked_page_text(text):
            self.record_candidate_outcome(
                outcome, result, rank=rank, fate="blocked_page", text_length=len(text)
            )
            return PreparedPage(fate="blocked_page", text_length=len(text))
        if len(text) < self.min_paper_length:
            self.record_candidate_outcome(
                outcome, result, rank=rank, fate="too_short", text_length=len(text)
            )
            return PreparedPage(fate="too_short", text_length=len(text))
        if self.max_paper_length is not None and len(text) > self.max_paper_length:
            self.record_candidate_outcome(
                outcome, result, rank=rank, fate="too_large", text_length=len(text)
            )
            return PreparedPage(fate="too_large", text_length=len(text))

        text, reduction = reduce_text_to_relevant_windows(
            text,
            task.query,
            max_chars=self.max_extraction_chars_per_paper,
        )
        return PreparedPage(
            candidate=HarvestCandidate(
                result=result,
                url=url,
                text=text,
                reduction=reduction,
            ),
            text_length=len(text),
        )

    def write_paper(
        self,
        task: SearchTask,
        candidate: HarvestCandidate,
        outcome: SearchOutcome,
        *,
        rank: int | None = None,
    ) -> dict[str, Any]:
        result = candidate.result
        url = candidate.url
        text = candidate.text
        reduction = candidate.reduction

        if url:
            self.seen_urls.add(url)
        paper_id = str(uuid.uuid4())
        (self.papers_dir / f"{paper_id}.txt").write_text(text, encoding="utf-8")
        outcome.accepted_source_ids.append(paper_id)
        if url:
            outcome.accepted_urls.append(url)
        if reduction:
            reduction["source_id"] = paper_id
            reduction["url"] = url
            outcome.text_reductions.append(reduction)
        paper = {
            "id": paper_id,
            "text": text,
            "url": url,
            "title": result.get("title", ""),
            "source_metadata": compact_search_result(result),
            "original_text_length": reduction.get("original_length") if reduction else len(text),
            "text_length": len(text),
            "text_reduction": reduction,
            "source_query": task.query,
            "search_task_id": task.id,
            "search_topic": task.topic,
            "search_round_index": task.round_index,
            "search_expansion_op": task.expansion_op,
            "search_gap": task.gap,
            "search_metadata": dict(task.metadata),
            "search_task": task.to_dict(),
        }
        source_record = {
            key: value
            for key, value in paper.items()
            if key != "text"
        }
        (self.papers_dir / f"{paper_id}.json").write_text(
            json.dumps(source_record, indent=2, default=str),
            encoding="utf-8",
        )
        with (self.papers_dir / "sources.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(source_record, default=str) + "\n")
        self.record_candidate_outcome(
            outcome,
            result,
            rank=rank,
            fate="accepted",
            source_id=paper_id,
            text_length=len(text),
        )
        return paper

    def record_outcome(self, outcome: SearchOutcome) -> None:
        with (self.papers_dir / "search_outcomes.jsonl").open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(json.dumps(outcome.to_dict(), default=str) + "\n")

    def record_prompt_arm_summaries(
        self,
        summaries: Sequence[Mapping[str, Any]],
    ) -> None:
        if not summaries:
            return
        with (self.papers_dir / "prompt_arm_summaries.jsonl").open(
            "a",
            encoding="utf-8",
        ) as handle:
            for summary in summaries:
                handle.write(json.dumps(summary, default=str) + "\n")

    @staticmethod
    def record_candidate_outcome(
        outcome: SearchOutcome,
        result: dict[str, Any],
        *,
        rank: int | None,
        fate: str,
        reason: str = "",
        source_id: str = "",
        text_length: int | None = None,
    ) -> None:
        record = {
            **search_result_observation(result, rank=rank),
            "fate": fate,
            "reason": reason,
            "source_id": source_id,
        }
        if text_length is not None:
            record["text_length"] = text_length
        outcome.candidate_source_outcomes.append(record)

    def _extract_best_text(
        self,
        result: dict[str, Any],
        url: str,
        outcome: SearchOutcome,
    ) -> str:
        if self.scrape_fn is None or not url:
            return self.extract_text_fn(result)

        try:
            scraped = self.scrape_fn(url)
        except Exception:  # noqa: BLE001 - fall back to embedded search text
            scraped = None
        if scraped:
            text = self.extract_text_fn(scraped)
            if text:
                if is_blocked_page_text(text):
                    outcome.scrape_failed_urls.append(url)
                    outcome.skip("blocked_scrape")
                    return self.extract_text_fn(result)
                return text
        outcome.scrape_failed_urls.append(url)
        outcome.skip("scrape_failed")
        return self.extract_text_fn(result)


def is_blocked_page_text(text: str) -> bool:
    normalized = normalize_query(text)
    return any(marker in normalized for marker in _BLOCKED_PAGE_MARKERS)


def is_fatal_search_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in _FATAL_SEARCH_STATUS_CODES:
        return True

    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "401 client error",
            "402 client error",
            "403 client error",
            "429 client error",
            "payment required",
            "too many requests",
            "unauthorized",
            "forbidden",
        )
    )


def compact_search_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep searchable source metadata while dropping scraped body payloads."""

    compact: dict[str, Any] = {}
    for key, value in result.items():
        if key in _COMPACT_RESULT_SKIP_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            if value not in ("", None):
                compact[str(key)] = _compact_result_value(value)
        elif isinstance(value, Mapping):
            nested = {
                str(nested_key): _compact_result_value(nested_value)
                for nested_key, nested_value in value.items()
                if (
                    isinstance(nested_value, (str, int, float, bool))
                    and len(str(nested_value)) <= _COMPACT_RESULT_MAX_STRING
                )
            }
            if nested:
                compact[str(key)] = nested
    return compact


def _compact_result_value(value: str | int | float | bool) -> str | int | float | bool:
    if not isinstance(value, str):
        return value
    if len(value) <= _COMPACT_RESULT_MAX_STRING:
        return value
    return value[: _COMPACT_RESULT_MAX_STRING - 3].rstrip() + "..."


def search_result_observation(
    result: dict[str, Any],
    *,
    rank: int | None,
) -> dict[str, Any]:
    """Return compact, backend-neutral metadata for one search result."""

    compact = compact_search_result(result)
    observation = {
        "rank": rank,
        "url": str(result.get("url") or compact.get("url") or ""),
        "title": str(result.get("title") or compact.get("title") or ""),
        "metadata": compact,
    }
    return {
        key: value
        for key, value in observation.items()
        if value not in ("", None, {})
    }


def summarize_prompt_arms(
    outcomes: Sequence[SearchOutcome],
) -> list[dict[str, Any]]:
    """Aggregate finished searches by their originating prompt arm.

    Takes the outcomes directly. ``SearchBatch`` and ``merge_search_batches``
    existed to carry a wave's papers and outcomes between the deleted harvest
    loop and the deleted round loop; with one page acquired per pull and one
    ``SearchOutcome`` written per completed search episode, there is no batch to
    merge and a surviving unused container is scaffolding.
    """

    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for outcome in outcomes:
        metadata = outcome.metadata if isinstance(outcome.metadata, Mapping) else {}
        key = _prompt_arm_group_key(outcome, metadata)
        group = groups.setdefault(
            key,
            _new_prompt_arm_summary(outcome, metadata),
        )
        group["query_count"] += 1
        group["queries"].append(outcome.query)
        group["search_result_count"] += len(outcome.search_result_observations)
        group["accepted_source_count"] += len(outcome.accepted_source_ids)
        group["accepted_source_ids"].extend(outcome.accepted_source_ids)
        group["accepted_urls"].extend(outcome.accepted_urls)
        group["duplicate_urls"].extend(outcome.duplicate_urls)
        group["skipped_by_reason"].update(outcome.skipped_by_reason)
        if outcome.error:
            group["errors"].append(outcome.error)
        for observation in outcome.search_result_observations:
            url = str(observation.get("url") or "")
            if url:
                group["unique_urls"].add(url)
            if len(group["sample_search_results"]) < 12:
                group["sample_search_results"].append(observation)
        for candidate in outcome.candidate_source_outcomes:
            fate = str(candidate.get("fate") or "")
            if fate:
                group["candidate_fates"][fate] += 1

    return [_finalize_prompt_arm_summary(group) for group in groups.values()]


def _prompt_arm_group_key(
    outcome: SearchOutcome,
    metadata: Mapping[str, Any],
) -> str:
    return str(
        metadata.get("prompt_arm_id")
        or metadata.get("strategy_attempt_id")
        or metadata.get("strategy_wave_id")
        or outcome.task_id
    )


def _new_prompt_arm_summary(
    outcome: SearchOutcome,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "round_index": outcome.round_index,
        "target_id": metadata.get("target_id", ""),
        "target_table": metadata.get("target_table", ""),
        "strategy_attempt_id": (
            metadata.get("strategy_attempt_id")
            or metadata.get("strategy_wave_id")
            or ""
        ),
        "evolution_index": (
            metadata.get("evolution_index")
            if metadata.get("evolution_index") is not None
            else metadata.get("strategy_evolution_index")
        ),
        "prompt_arm_id": metadata.get("prompt_arm_id", ""),
        "prompt_arm_name": metadata.get("prompt_arm_name", ""),
        "prompt_arm_index": metadata.get("prompt_arm_index"),
        "prompt_delta": metadata.get("prompt_delta", ""),
        "prompt_hypothesis": metadata.get("prompt_hypothesis", ""),
        "expected_source_shape": metadata.get("expected_source_shape", ""),
        "strategy_operator": metadata.get("strategy_operator", ""),
        "strategy_family": metadata.get("strategy_family", ""),
        "source_family": metadata.get("source_family", ""),
        "query_count": 0,
        "queries": [],
        "search_result_count": 0,
        "unique_urls": set(),
        "accepted_source_count": 0,
        "accepted_source_ids": [],
        "accepted_urls": [],
        "duplicate_urls": [],
        "skipped_by_reason": Counter(),
        "candidate_fates": Counter(),
        "sample_search_results": [],
        "errors": [],
    }


def _finalize_prompt_arm_summary(group: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "round_index": group.get("round_index"),
        "target_id": group.get("target_id", ""),
        "target_table": group.get("target_table", ""),
        "strategy_attempt_id": group.get("strategy_attempt_id", ""),
        "evolution_index": group.get("evolution_index"),
        "prompt_arm_id": group.get("prompt_arm_id", ""),
        "prompt_arm_name": group.get("prompt_arm_name", ""),
        "prompt_arm_index": group.get("prompt_arm_index"),
        "prompt_delta": group.get("prompt_delta", ""),
        "prompt_hypothesis": group.get("prompt_hypothesis", ""),
        "expected_source_shape": group.get("expected_source_shape", ""),
        "strategy_operator": group.get("strategy_operator", ""),
        "strategy_family": group.get("strategy_family", ""),
        "source_family": group.get("source_family", ""),
        "query_count": int(group.get("query_count") or 0),
        "queries": _unique_strings(group.get("queries") or []),
        "search_result_count": int(group.get("search_result_count") or 0),
        "unique_url_count": len(group.get("unique_urls") or []),
        "accepted_source_count": int(group.get("accepted_source_count") or 0),
        "accepted_source_ids": _unique_strings(
            group.get("accepted_source_ids") or []
        ),
        "accepted_urls": _unique_strings(group.get("accepted_urls") or [])[:20],
        "duplicate_url_count": len(
            _unique_strings(group.get("duplicate_urls") or [])
        ),
        "skipped_by_reason": dict(group.get("skipped_by_reason") or {}),
        "candidate_fates": dict(group.get("candidate_fates") or {}),
        "sample_search_results": list(group.get("sample_search_results") or [])[:12],
        "error": "; ".join(_unique_strings(group.get("errors") or []))[:500],
    }


_REDUCTION_STOPWORDS = {
    "and",
    "are",
    "for",
    "from",
    "how",
    "into",
    "not",
    "the",
    "this",
    "with",
}


def reduce_text_to_relevant_windows(
    text: str,
    query: str,
    *,
    max_chars: Optional[int],
    window_chars: int = 4000,
    overlap: int = 400,
) -> tuple[str, dict[str, Any]]:
    """Trim long harvested text to query-relevant windows before extraction."""
    if max_chars is None or len(text) <= max_chars:
        return text, {}

    max_chars = max(1, max_chars)
    window_chars = max(1, min(window_chars, max_chars))
    overlap = max(0, min(overlap, window_chars // 4))
    step = max(1, window_chars - overlap)
    terms = _reduction_terms(query)

    windows: list[tuple[int, int, str]] = []
    for start in range(0, len(text), step):
        window = text[start : start + window_chars]
        if window.strip():
            windows.append((_window_score(window, terms), start, window))
        if start + window_chars >= len(text):
            break

    max_windows = max(1, (max_chars + window_chars - 1) // window_chars)
    ranked = sorted(windows, key=lambda item: (-item[0], item[1]))
    selected = [window for window in ranked if window[0] > 0][:max_windows]
    if not selected:
        selected = windows[:max_windows]
    selected.sort(key=lambda item: item[1])

    remaining = max_chars
    sections: list[str] = []
    for _, _, window in selected:
        piece = window.strip()
        if not piece:
            continue
        if sections:
            remaining -= 2
        if remaining <= 0:
            break
        sections.append(piece[:remaining].rstrip())
        remaining -= len(sections[-1])

    reduced = "\n\n".join(sections).strip()
    return reduced, {
        "original_length": len(text),
        "reduced_length": len(reduced),
        "candidate_windows": len(windows),
        "selected_windows": len(sections),
    }


def table_gap_search_tasks(
    rows: Iterable[dict[str, Any]],
    *,
    round_index: int,
    max_tasks: int,
) -> list[SearchTask]:
    """Build deterministic search tasks from table gap rows."""
    if max_tasks <= 0:
        return []

    tasks: list[SearchTask] = []
    seen_queries: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        anchor = _gap_anchor(row)
        missing = str(row.get("missing_measurement") or "").strip().upper()
        gap_type = str(row.get("gap_type") or "").strip()
        evidence_gap = str(row.get("evidence_gap") or "").strip()
        topic = "table_gap"
        queries = _gap_queries(
            anchor=anchor,
            missing=missing,
            gap_type=gap_type,
            evidence_gap=evidence_gap,
        )

        for query in queries:
            normalized = normalize_query(query)
            if normalized in seen_queries:
                continue
            seen_queries.add(normalized)
            tasks.append(
                SearchTask(
                    query=query,
                    topic=topic,
                    gap=str(evidence_gap or gap_type or missing),
                    expansion_op="table_gap",
                    round_index=round_index,
                    # NO PROMPT ARM, BY DECLARATION. A gap task is derived from
                    # a row's own reported gap and has no delta, no hypothesis
                    # and no sibling; minting a synthetic arm id for it would
                    # put a contrast row into the pseudo-gradient that means
                    # nothing.
                    producer_class="table_gap",
                    metadata={
                        "missing_measurement": missing,
                        "gap_type": gap_type,
                        "anchor": anchor,
                    },
                )
            )
            if len(tasks) >= max_tasks:
                return tasks
    return tasks


measurement_gap_search_tasks = table_gap_search_tasks


def _gap_queries(
    *,
    anchor: str,
    missing: str,
    gap_type: str,
    evidence_gap: str,
) -> list[str]:
    parts = [anchor, missing, gap_type, evidence_gap]
    query = " ".join(part for part in parts if part).strip()
    if query:
        return [query]
    return []


def _gap_anchor(row: dict[str, Any]) -> str:
    ignored = {
        "completeness",
        "evidence_gap",
        "gap_type",
        "missing_measurement",
        "source_chunks",
        "source_refs",
    }
    values: list[str] = []
    for key, value in row.items():
        if key in ignored or isinstance(value, (dict, list, tuple, set)):
            continue
        text = str(value or "").strip()
        if not text:
            continue
        if text.lower() in {"0", "0.0", "none", "null", "unknown"}:
            continue
        values.append(text)
        if len(values) >= 3:
            break
    return " ".join(values)


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def normalize_text(value: str) -> str:
    return normalize_query(value)


def load_seen_urls(path: str | Path | None) -> set[str]:
    """Load accepted source URLs from a previous harvester metadata directory."""
    urls: set[str] = set()
    for root in _seed_source_roots(path):
        for file_path in _seed_source_metadata_files(root):
            if file_path.suffix == ".jsonl":
                _load_urls_from_jsonl(file_path, urls)
            elif file_path.suffix == ".json":
                _collect_urls(_read_json(file_path), urls)
    return urls


def load_seed_source_records(path: str | Path | None) -> list[dict[str, Any]]:
    """Load accepted source metadata and text from previous harvester output."""
    records: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for root in _seed_source_roots(path):
        for file_path in _seed_source_metadata_files(root):
            for record in _iter_source_records(file_path):
                source_id = str(record.get("id") or "").strip()
                if not source_id or source_id in records:
                    continue

                text_path = file_path.parent / f"{source_id}.txt"
                if not text_path.exists():
                    continue

                try:
                    text = text_path.read_text(encoding="utf-8")
                except OSError:
                    continue
                if not text:
                    continue

                records[source_id] = {**record, "id": source_id, "text": text}

    return list(records.values())


def load_seed_search_outcomes(path: str | Path | None) -> list[dict[str, Any]]:
    """Load durable search-task outcomes from previous harvester output."""
    outcomes: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for root in _seed_source_roots(path):
        for file_path in _seed_search_outcome_files(root):
            for outcome in _iter_search_outcome_records(file_path):
                raw_key = json.dumps(
                    outcome,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                key = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()
                outcomes.setdefault(key, outcome)
    return list(outcomes.values())


def load_seed_frontier_tasks(path: str | Path | None) -> list[SearchTask]:
    """Load still-pending search tasks from previous frontier artifacts."""
    tasks: "OrderedDict[str, SearchTask]" = OrderedDict()
    for root in _seed_source_roots(path):
        for file_path in _seed_frontier_files(root):
            for task in _iter_frontier_tasks(_read_json(file_path)):
                tasks.setdefault(task.id, task)
    return list(tasks.values())


def _seed_source_roots(path: str | Path | None) -> list[Path]:
    if not path:
        return []

    roots = []
    for value in str(path).split(os.pathsep):
        value = value.strip()
        if not value:
            continue
        root = Path(value)
        if not root.exists():
            raise FileNotFoundError(f"Seed source path not found: {root}")
        roots.append(root)
    return roots


def _seed_source_metadata_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(
        candidate
        for pattern in ("*.json", "*.jsonl")
        for candidate in root.glob(pattern)
    )


def _seed_search_outcome_files(root: Path) -> list[Path]:
    names = {"search_outcomes.jsonl", "seed_search_outcomes.jsonl"}
    if root.is_file():
        return sorted(
            candidate
            for candidate in [
                root if root.name in names else None,
                root.parent / "seed_search_outcomes.jsonl",
                root.parent / "search_outcomes.jsonl",
            ]
            if candidate is not None and candidate.exists()
        )
    return sorted(candidate for name in names for candidate in root.glob(name))


def _seed_frontier_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]

    candidates: list[Path] = []
    for directory in (root, root / "answers", root / "answers" / "goals"):
        if directory.exists():
            candidates.extend(directory.glob("round_*.json"))
    return sorted(set(candidates))


def _iter_frontier_tasks(payload: Any) -> Iterable[SearchTask]:
    if isinstance(payload, list):
        for item in payload:
            task = _search_task_from_record(item)
            if task is not None:
                yield task
        return

    if not isinstance(payload, dict):
        return

    for key in ("gap_search_tasks", "goal_search_tasks", "pending_task_records"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            task = _search_task_from_record(item)
            if task is not None:
                yield task

    search_frontier = payload.get("search_frontier")
    if isinstance(search_frontier, dict):
        for item in search_frontier.get("pending_task_records") or []:
            task = _search_task_from_record(item)
            if task is not None:
                yield task


def _search_task_from_record(payload: Any) -> Optional[SearchTask]:
    if not isinstance(payload, dict):
        return None

    query = str(payload.get("query") or "").strip()
    if not query:
        return None

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    return SearchTask(
        query=query,
        id=str(payload.get("id") or ""),
        parent_id=payload.get("parent_id"),
        topic=str(payload.get("topic") or "batch"),
        expansion_op=str(payload.get("expansion_op") or "direct"),
        gap=str(payload.get("gap") or ""),
        round_index=int(payload.get("round_index") or 0),
        depth=int(payload.get("depth") or 0),
        metadata=dict(metadata),
    )


def _iter_source_records(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix == ".jsonl":
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return

        for line in lines:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _is_source_record(payload):
                yield payload
        return

    if path.suffix == ".json":
        payload = _read_json(path)
        if _is_source_record(payload):
            yield payload


def _iter_search_outcome_records(path: Path) -> Iterable[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _is_search_outcome_record(payload):
            yield payload


def _load_urls_from_jsonl(path: Path, urls: set[str]) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        _collect_urls(payload, urls)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _collect_urls(payload: Any, urls: set[str]) -> None:
    if isinstance(payload, dict):
        _add_url(payload.get("url"), urls)
        for key in ("accepted_urls", "duplicate_urls", "scrape_failed_urls"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    _add_url(item, urls)
        for value in payload.values():
            if isinstance(value, (dict, list)):
                _collect_urls(value, urls)
    elif isinstance(payload, list):
        for item in payload:
            _collect_urls(item, urls)


def _add_url(value: Any, urls: set[str]) -> None:
    url = str(value or "").strip()
    if url:
        urls.add(url)


def _is_source_record(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and bool(str(payload.get("id") or "").strip())
        and "search_topic" in payload
    )


def _is_search_outcome_record(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and bool(str(payload.get("task_id") or "").strip())
        and bool(str(payload.get("query") or "").strip())
    )


def _reduction_terms(query: str) -> set[str]:
    """Query tokens used to SCORE text windows for relevance. Not an identity.

    Renamed from `_query_terms` because `search_memory` has a function of that
    name with a different return type (list vs set), a different length filter
    (>2 vs >=2) and a different stopword list. Two same-named functions that
    tokenize differently invite exactly one mistake -- using either as a key, or
    assuming a change to one applies to both -- and the names were the only
    thing suggesting they were interchangeable. They are not, and neither is an
    identity tokenizer: this one weights `_window_score`, that one feeds a
    term-frequency counter.
    """

    return {
        token
        for token in re.findall(r"[a-z0-9_]+", normalize_query(query))
        if len(token) >= 2 and token not in _REDUCTION_STOPWORDS
    }


def _window_score(window: str, terms: set[str]) -> int:
    if not terms:
        return 0
    normalized = normalize_query(window)
    return sum(normalized.count(term) * (len(term) + 1) for term in terms)


def _unique_strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
