"""Search acquisition, memory, strategy, reward, and path selection."""

from __future__ import annotations


# ============================================================================
# search.py
# ============================================================================

import hashlib
import json
import os
import re
import uuid
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from paper_fetching.firecrawl_client import extract_text_from_result

from question_pipeline.utilities.acquisition import ObservationKind, active_meter, record_fetched_bytes, zero_cost


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
    #: The Episode this task was minted under, when the producer knows it
    #: (a completion probe, a task built inside a strategy's planning pass).
    #: Attribution context only: it is excluded from :meth:`stable_id`, so the
    #: same query minted under two episodes stays one task, and it is never a
    #: continuation offset or an artifact identity.
    episode_id: str = ""
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
    #: Carried through from the task. Attribution context, never an ordinal.
    episode_id: str = ""
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
            episode_id=task.episode_id,
            yields_sources=task.yields_sources,
            metadata=dict(task.metadata),
            cost=zero_cost(
                observation_kind=ObservationKind.SEARCH.value,
                observation_id=task.id,
                episode_id=task.episode_id,
            ),
        )

    def skip(self, reason: str, count: int = 1) -> None:
        skipped = Counter(self.skipped_by_reason)
        skipped[reason] += count
        self.skipped_by_reason = dict(skipped)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HarvestCandidate:
    result: dict[str, Any]
    url: str
    text: str
    reduction: dict[str, Any]


class SearchFrontier:
    """Persistent queue of search tasks, deduplicated across strategies."""

    def __init__(self):
        self._pending: OrderedDict[str, SearchTask] = OrderedDict()
        self._seen_task_ids: set[str] = set()
        self.outcomes: list[SearchOutcome] = []

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def enqueue_queries(
        self,
        queries: Iterable[str],
        *,
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
            if task.id in self._seen_task_ids:
                continue
            pending_key = task.id
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
            "pending_tasks": len(self._pending),
            "pending_task_records": [
                task.to_dict()
                for task in self._pending.values()
            ],
            "seen_tasks": len(self._seen_task_ids),
            "seen_task_ids": sorted(self._seen_task_ids),
            "completed_tasks": len(self.outcomes),
            "completed_task_records": [
                outcome.to_dict() for outcome in self.outcomes
            ],
        }

    def restore_checkpoint_state(self, payload: Mapping[str, Any]) -> None:
        """Replace queue state from one explicit checkpoint generation."""

        pending: OrderedDict[str, SearchTask] = OrderedDict()
        for raw in payload.get("pending_task_records") or ():
            task = _search_task_from_record(raw)
            if task is not None:
                pending[task.id] = task
        allowed = {item.name for item in fields(SearchOutcome)}
        outcomes: list[SearchOutcome] = []
        for raw in payload.get("completed_task_records") or ():
            if not isinstance(raw, Mapping):
                continue
            values = {key: value for key, value in raw.items() if key in allowed}
            if values.get("task_id") and values.get("query"):
                outcomes.append(SearchOutcome(**values))
        seen = {
            str(value) for value in (payload.get("seen_task_ids") or ())
        }
        seen.update(pending)
        seen.update(outcome.task_id for outcome in outcomes)
        self._pending = pending
        self._seen_task_ids = seen
        self.outcomes = outcomes


@dataclass(frozen=True)
class PreparedPage:
    """One page's mechanical preparation: the candidate, or why there is none.

    ``fate`` is one of ``acquisition``'s declared pre-extraction fate labels, or
    ``""`` when the page is ready for extraction. THIS MODULE REPORTS THE FACT AND
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
        sources_dir: Path,
        seen_urls: set[str],
        scrape_fn: Optional[ScrapeFn] = None,
        min_source_length: int = 500,
        max_source_length: Optional[int] = None,
        max_extraction_chars_per_source: Optional[int] = None,
        extract_text_fn: Callable[[dict[str, Any]], str] = extract_text_from_result,
    ):
        self.scrape_fn = scrape_fn
        self.sources_dir = sources_dir
        self.seen_urls = seen_urls
        self.min_source_length = min_source_length
        self.max_source_length = max_source_length
        self.max_extraction_chars_per_source = max_extraction_chars_per_source
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
            from question_pipeline.utilities.acquisition import classify_error

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
        if len(text) < self.min_source_length:
            self.record_candidate_outcome(
                outcome, result, rank=rank, fate="too_short", text_length=len(text)
            )
            return PreparedPage(fate="too_short", text_length=len(text))
        if self.max_source_length is not None and len(text) > self.max_source_length:
            self.record_candidate_outcome(
                outcome, result, rank=rank, fate="too_large", text_length=len(text)
            )
            return PreparedPage(fate="too_large", text_length=len(text))

        text, reduction = reduce_text_to_relevant_windows(
            text,
            task.query,
            max_chars=self.max_extraction_chars_per_source,
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

    def write_source(
        self,
        task: SearchTask,
        candidate: HarvestCandidate,
        outcome: SearchOutcome,
        *,
        rank: int | None = None,
        episode_id: str = "",
    ) -> dict[str, Any]:
        """Persist one accepted source unit.

        ``episode_id`` is the search Episode that acquired it — the acceptance
        identity a later credit joins on, replacing the round stamp the record
        used to carry.
        """

        result = candidate.result
        url = candidate.url
        text = candidate.text
        reduction = candidate.reduction

        if url:
            self.seen_urls.add(url)
        source_id = str(uuid.uuid4())
        (self.sources_dir / f"{source_id}.txt").write_text(text, encoding="utf-8")
        outcome.accepted_source_ids.append(source_id)
        if url:
            outcome.accepted_urls.append(url)
        if reduction:
            reduction["source_id"] = source_id
            reduction["url"] = url
            outcome.text_reductions.append(reduction)
        record = {
            "id": source_id,
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
            "search_episode_id": str(episode_id or task.episode_id or ""),
            "search_expansion_op": task.expansion_op,
            "search_gap": task.gap,
            "search_metadata": dict(task.metadata),
            "search_task": task.to_dict(),
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }
        sidecar = {
            key: value
            for key, value in record.items()
            if key != "text"
        }
        (self.sources_dir / f"{source_id}.json").write_text(
            json.dumps(sidecar, indent=2, default=str),
            encoding="utf-8",
        )
        with (self.sources_dir / "sources.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sidecar, default=str) + "\n")
        self.record_candidate_outcome(
            outcome,
            result,
            rank=rank,
            fate="accepted",
            source_id=source_id,
            text_length=len(text),
        )
        return record

    def record_outcome(self, outcome: SearchOutcome) -> None:
        with (self.sources_dir / "search_outcomes.jsonl").open(
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
        with (self.sources_dir / "prompt_arm_summaries.jsonl").open(
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
        "queries": _search_unique_strings(group.get("queries") or []),
        "search_result_count": int(group.get("search_result_count") or 0),
        "unique_url_count": len(group.get("unique_urls") or []),
        "accepted_source_count": int(group.get("accepted_source_count") or 0),
        "accepted_source_ids": _search_unique_strings(
            group.get("accepted_source_ids") or []
        ),
        "accepted_urls": _search_unique_strings(group.get("accepted_urls") or [])[:20],
        "duplicate_url_count": len(
            _search_unique_strings(group.get("duplicate_urls") or [])
        ),
        "skipped_by_reason": dict(group.get("skipped_by_reason") or {}),
        "candidate_fates": dict(group.get("candidate_fates") or {}),
        "sample_search_results": list(group.get("sample_search_results") or [])[:12],
        "error": "; ".join(_search_unique_strings(group.get("errors") or []))[:500],
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
    """Frontier-bearing artifacts under a run directory.

    Named artifact families only: per-strategy Episode records
    (``strategy_*.json``) and the goal layer's ``*_stop_criteria.json``, both
    of which carry pending-task lists. Nothing here infers continuation from
    numbered round files; that loader family is deleted with the round concept.
    """

    if root.is_file():
        return [root]

    candidates: list[Path] = []
    for directory in (root, root / "answers", root / "answers" / "goals"):
        if directory.exists():
            candidates.extend(directory.glob("strategy_*.json"))
            candidates.extend(directory.glob("*_stop_criteria.json"))
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


def _search_unique_strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


# ============================================================================
# reward.py
# ============================================================================

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from question_pipeline.utilities.tables import CRITERIA_PROJECTION_VERSION, EvidenceBasis




#: Reporting semantics changed when credit assignment moved to the post-table
#: boundary. Historical reward versions are not directly comparable.
REWARD_VERSION = "single_credit_report_v1"

REWARD_COMPONENT_COLUMNS = [
    "component",
    "direction",
    "raw_value",
    "score",
    "interpretation",
]


class DatapointKind(str, Enum):
    """The accepted datapoint kind supported by this reward version."""

    #: A source states the value, joined at field scope.
    VERBATIM = "verbatim"
    BEST_GUESS = "best_guess"


@dataclass(frozen=True)
class CreditedDatapoint:
    """One real datapoint copied from its authoritative assignment record.

    Every field here is an identifier or a closed vocabulary member. Nothing is
    a count, a timestamp, or free text: credit joins by ID, so an attribution
    that survives a rename has to be built out of things that do not change
    when prose does.
    """

    assignment_id: str
    criterion_id: str
    kind: DatapointKind
    basis: EvidenceBasis
    table: str
    field: str
    subject_id: str
    #: The accepted source carried by the authoritative assignment.
    crediting_source_ids: tuple[str, ...]
    #: The Episode in which the assignment was made.
    realized_episode_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "credit_assignment_id": self.assignment_id,
            "criterion_id": self.criterion_id,
            "datapoint_kind": self.kind.value,
            "evidence_basis": self.basis.value,
            "table": self.table,
            "field": self.field,
            "subject_id": self.subject_id,
            "crediting_source_ids": list(self.crediting_source_ids),
            "realized_episode_id": self.realized_episode_id,
        }


@dataclass(frozen=True)
class CostVector:
    """What one scoring pass paid, summed from 1B's per-action records.

    A vector rather than a scalar because the units are different money and no
    exchange rate between them is measurable here. ``billable_calls`` is the one
    place two units are added, and the reason it is defensible is that both
    count discrete paid round trips: a search provider call and a model call are
    each one thing somebody bills for. Tokens and wall time are reported beside
    it so a later phase can adopt a different denominator without this module
    having quietly picked one for it.
    """

    records: int = 0
    provider_calls: int = 0
    llm_calls: int = 0
    provider_credits: float = 0.0
    provider_credits_available: bool = False
    returned_hits: int = 0
    fetched_bytes: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0
    wall_ms: float = 0.0
    errors: int = 0

    @property
    def billable_calls(self) -> int:
        return self.provider_calls + self.llm_calls

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def available(self) -> bool:
        """Whether any cost was recorded at all.

        A pass with records but zero calls really was free. A pass with no
        records at all has unknown cost, and the two must not compare equal.
        """

        return self.records > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_records": self.records,
            "provider_calls": self.provider_calls,
            "llm_calls": self.llm_calls,
            "billable_calls": self.billable_calls,
            "provider_credits": round(self.provider_credits, 6),
            "provider_credits_available": self.provider_credits_available,
            "returned_hits": self.returned_hits,
            "fetched_bytes": self.fetched_bytes,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "tokens": self.tokens,
            "retries": self.retries,
            "wall_ms": round(self.wall_ms, 3),
            "errors": self.errors,
            "cost_available": self.available,
        }


@dataclass(frozen=True)
class RewardReport:
    """One episode's already-assigned yield and measured cost."""

    reward_version: str
    criteria_projection_version: str
    #: The strategy Episode this scoring pass belongs to.
    episode_id: str
    before_table_state_id: str
    after_table_state_id: str
    datapoints: tuple[CreditedDatapoint, ...]
    cost: CostVector
    #: Assignment records that were recurrences rather than new table slots.
    uncredited: Mapping[str, int] = field(default_factory=dict)

    @property
    def datapoint_count(self) -> int:
        return len(self.datapoints)

    @property
    def cost_available(self) -> bool:
        return self.cost.available

    @property
    def score(self) -> float | None:
        """Datapoints per billable call, or ``None`` when cost is unknown.

        ``None`` rather than the datapoint count, because a yield that has not
        been divided by anything is not a yield-per-cost and must not be read as
        one by a consumer that forgot to check.
        """

        return self.yield_per("billable_calls")

    def yield_per(self, unit: str) -> float | None:
        if not self.cost.available:
            return None
        denominators = {
            "billable_calls": float(self.cost.billable_calls),
            "provider_calls": float(self.cost.provider_calls),
            "llm_calls": float(self.cost.llm_calls),
            "tokens": float(self.cost.tokens),
            "wall_ms": float(self.cost.wall_ms),
            "fetched_bytes": float(self.cost.fetched_bytes),
        }
        denominator = denominators.get(unit)
        if denominator is None or denominator <= 0:
            return None
        return round(self.datapoint_count / denominator, 9)

    def by_kind(self) -> dict[str, int]:
        counts = {kind.value: 0 for kind in DatapointKind}
        for datapoint in self.datapoints:
            counts[datapoint.kind.value] += 1
        return counts

    def components(self) -> list[dict[str, Any]]:
        """The report as rows, for the run's own artifact export."""

        rows = [
            {
                "component": "credited_datapoints",
                "direction": "maximize",
                "raw_value": self.datapoint_count,
                "score": self.datapoint_count,
                "interpretation": (
                    "New logical value slots assigned after accepted evidence "
                    "was materialized in typed table state."
                ),
            }
        ]
        for name, count in sorted(self.by_kind().items()):
            rows.append(
                {
                    "component": f"credited_{name}",
                    "direction": "maximize",
                    "raw_value": count,
                    "score": count,
                    "interpretation": f"Credited datapoints of kind {name}.",
                }
            )
        for name, count in sorted(self.uncredited.items()):
            rows.append(
                {
                    "component": f"uncredited_{name}",
                    "direction": "ignore",
                    "raw_value": count,
                    "score": 0,
                    "interpretation": (
                        "An authoritative assignment record that repeated a "
                        "logical slot already present in typed table state."
                    ),
                }
            )
        return rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "reward_version": self.reward_version,
            "criteria_projection_version": self.criteria_projection_version,
            "episode_id": self.episode_id,
            "before_table_state_id": self.before_table_state_id,
            "after_table_state_id": self.after_table_state_id,
            "score": self.score,
            "cost_available": self.cost_available,
            "credited_datapoints": self.datapoint_count,
            "credited_by_kind": self.by_kind(),
            "yield_per": {
                unit: self.yield_per(unit)
                for unit in (
                    "billable_calls",
                    "provider_calls",
                    "llm_calls",
                    "tokens",
                    "wall_ms",
                )
            },
            "cost": self.cost.to_dict(),
            "uncredited_volume": dict(sorted(self.uncredited.items())),
            "datapoints": [datapoint.to_dict() for datapoint in self.datapoints],
        }


def aggregate_cost(
    cost_records: Iterable[Mapping[str, Any]] | None,
) -> CostVector:
    """Sum 1B cost records. The caller decides which records are in scope.

    Selection is the caller's business and is done by ``episode_id`` on the
    records themselves -- never by a round window, which no record carries.

    1B's scopes do not nest their spend -- an inner meter takes the calls and
    records ``nested_in``; the outer does not also count them -- so a plain sum
    over records counts every provider call exactly once. Do not add a
    ``nested_in`` filter here: it would drop the inner records and undercount.
    """

    records = 0
    provider_calls = llm_calls = returned_hits = fetched_bytes = 0
    prompt_tokens = completion_tokens = retries = errors = 0
    credits = 0.0
    credits_available = False
    wall_ms = 0.0

    for record in cost_records or ():
        if not isinstance(record, Mapping):
            continue
        records += 1
        provider_calls += _int(record.get("provider_calls"))
        llm_calls += _int(record.get("llm_calls"))
        returned_hits += _int(record.get("returned_hits"))
        fetched_bytes += _int(record.get("fetched_bytes"))
        prompt_tokens += _int(record.get("prompt_tokens"))
        completion_tokens += _int(record.get("completion_tokens"))
        retries += _int(record.get("retries"))
        wall_ms += _float(record.get("wall_ms"))
        if record.get("provider_credits_available"):
            credits_available = True
            credits += _float(record.get("provider_credits"))
        if str(record.get("error_class") or ""):
            errors += 1

    return CostVector(
        records=records,
        provider_calls=provider_calls,
        llm_calls=llm_calls,
        provider_credits=credits,
        provider_credits_available=credits_available,
        returned_hits=returned_hits,
        fetched_bytes=fetched_bytes,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        retries=retries,
        wall_ms=wall_ms,
        errors=errors,
    )


def report_assigned_credit(
    assignments: Iterable[Mapping[str, Any]],
    *,
    episode_id: str,
    cost_records: Iterable[Mapping[str, Any]] | None = None,
) -> RewardReport:
    """Report the single table-bound credit assignments without reassigning.

    ``new_to_table`` is authored by the live credit assigner after typed table
    storage. This function may aggregate that decision for cost/yield output;
    it never projects tables, evaluates evidence, or decides what deserves
    credit.
    """

    rows = [dict(item) for item in assignments if isinstance(item, Mapping)]
    selected = [row for row in rows if bool(row.get("new_to_table"))]
    repeats = len(rows) - len(selected)

    datapoints: list[CreditedDatapoint] = []
    for row in selected:
        identity = str(row.get("identity") or "")
        source_id = str(row.get("source_id") or "")
        kind = (
            DatapointKind.BEST_GUESS
            if str(row.get("source_kind") or "") == DatapointKind.BEST_GUESS.value
            else DatapointKind.VERBATIM
        )
        datapoints.append(
            CreditedDatapoint(
                assignment_id=str(row.get("assignment_id") or identity),
                criterion_id=str(row.get("criterion_id") or identity),
                kind=kind,
                basis=EvidenceBasis.RESOLVED_ASSERTION_CHAIN,
                table=str(row.get("table") or ""),
                field=str(row.get("field") or ""),
                subject_id=str(row.get("subject_id") or ""),
                crediting_source_ids=(source_id,) if source_id else (),
                realized_episode_id=str(episode_id),
            )
        )

    return RewardReport(
        reward_version=REWARD_VERSION,
        criteria_projection_version=CRITERIA_PROJECTION_VERSION,
        episode_id=str(episode_id),
        before_table_state_id=(
            rows[0].get("before_table_state_id", "") if rows else ""
        ),
        after_table_state_id=(
            rows[-1].get("after_table_state_id", "") if rows else ""
        ),
        datapoints=tuple(datapoints),
        cost=aggregate_cost(cost_records),
        uncredited={
            "repeat_assignment": repeats,
        },
    )


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Best-guess artifact plumbing
# ---------------------------------------------------------------------------
#
# These predate this module's rewrite and are unchanged: they load and merge the
# run's own best-guess context exports. They carry no score. They exist because
# the accepted, judged best guesses are an *input* to the projection now rather
# than a component of a coverage count.


def load_seed_best_guess_rows(path: str | Path | None) -> list[dict[str, Any]]:
    """Load previous best-guess context rows adjacent to seeded table exports."""

    if not path:
        return []

    root = Path(path)
    candidates = []
    if root.name == "tables":
        candidates.append(root.parent / "derived")
    if root.name == "answers":
        candidates.append(root / "derived")
    candidates.extend(
        [
            root / "derived",
            root / "answers" / "derived",
        ]
    )

    seen_paths: set[Path] = set()
    rows: list[dict[str, Any]] = []
    for directory in candidates:
        if not directory.is_dir():
            continue
        # Any artifact stem: matches both this tree's Episode-labelled exports
        # and legacy round-numbered ones without inferring anything from the
        # number.
        for json_path in sorted(directory.glob("*_best_guess_context.json")):
            if json_path in seen_paths:
                continue
            seen_paths.add(json_path)
            rows.extend(_read_dict_rows(json_path))
    return rows


def merge_best_guess_rows(
    *groups: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge best-guess context rows by their stable row-slot keys."""

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for row in group:
            if not isinstance(row, Mapping):
                continue
            row_dict = dict(row)
            key = str(row_dict.get("row_slot_id") or "").strip() or _stable_json(row_dict)
            if key in seen:
                continue
            seen.add(key)
            merged.append(row_dict)
    return merged


def _read_dict_rows(path: Path) -> list[dict[str, Any]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


# ============================================================================
# search_memory.py
# ============================================================================

import hashlib
import json
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from question_pipeline.utilities.acquisition import stable_id


_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.+-]*")
_STOPWORDS = {
    "about",
    "after",
    "against",
    "and",
    "are",
    "between",
    "from",
    "into",
    "not",
    "of",
    "or",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "with",
}


@dataclass
class SearchMemory:
    """Durable, generic memory of search attempts for table-fill deficits."""

    records: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_outcomes(cls, outcomes: Iterable[Mapping[str, Any]]) -> "SearchMemory":
        records: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        # ``sequence`` is the outcome's position in the stream this memory was
        # built from -- arrival order, which is chronology because outcomes are
        # appended as searches complete. It is an ORDERING KEY for recency
        # comparisons inside this build only: never a continuation offset,
        # never an artifact identity, and never emitted as a global counter.
        for sequence, outcome in enumerate(outcomes):
            if outcome.get("topic") != "target_deficit":
                continue
            metadata = outcome.get("metadata")
            if not isinstance(metadata, Mapping):
                metadata = {}
            key = memory_key(metadata)
            if not key:
                continue
            record = records.setdefault(key, _new_record(key, metadata))
            _merge_target(record, metadata)
            _merge_outcome(record, outcome, sequence=sequence)

        return cls(records=[_finalize_record(record) for record in records.values()])

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_count": len(self.records),
            "records": self.records,
        }

    def to_deficit_context(
        self,
        target: Mapping[str, Any],
        *,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """Return the most relevant memory records for a newly built deficit."""
        scored = []
        for record in self.records:
            score = _match_score(target, record)
            if score > 0:
                scored.append((score, _latest_sequence(record), record))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            _compact_record(record, score=score)
            for score, _, record in scored[:limit]
        ]


def memory_key(metadata: Mapping[str, Any]) -> str:
    """Build a stable key from generic target metadata, not a transient task id."""
    table = _memory_clean(metadata.get("target_table"))
    deficit_type = _memory_clean(metadata.get("fill_deficit_type"))
    identity = (
        _memory_clean(metadata.get("target_id"))
        or _memory_clean(metadata.get("target_name"))
        or _anchor_signature(metadata.get("anchor_values"))
    )
    if not table or not identity:
        return ""

    payload = {
        "table": table,
        "deficit_type": deficit_type,
        "identity": identity,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _new_record(key: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "key": key,
        "target": {
            "target_table": str(metadata.get("target_table") or ""),
            "target_id": str(metadata.get("target_id") or ""),
            "target_name": str(metadata.get("target_name") or ""),
            "deficit_type": str(metadata.get("fill_deficit_type") or ""),
            "key_columns": list(metadata.get("key_columns") or []),
            "missing_fields": list(metadata.get("missing_fields") or []),
            "anchor_values": (
                dict(metadata.get("anchor_values"))
                if isinstance(metadata.get("anchor_values"), Mapping)
                else {}
            ),
        },
        "attempt_count": 0,
        "accepted_source_ids": [],
        "accepted_urls": [],
        "skipped_by_reason": Counter(),
        "strategy_families": Counter(),
        "strategy_operators": Counter(),
        "successful_query_terms": Counter(),
        "failed_query_terms": Counter(),
        "attempts": [],
    }


def _merge_target(record: dict[str, Any], metadata: Mapping[str, Any]) -> None:
    target = record["target"]
    for field_name in ("target_table", "target_id", "target_name", "deficit_type"):
        metadata_name = (
            "fill_deficit_type" if field_name == "deficit_type" else field_name
        )
        value = str(metadata.get(metadata_name) or "")
        if value:
            target[field_name] = value
    for field_name in ("key_columns", "missing_fields"):
        target[field_name] = _unique(
            [*target.get(field_name, []), *list(metadata.get(field_name) or [])],
        )
    anchor_values = metadata.get("anchor_values")
    if isinstance(anchor_values, Mapping):
        target.setdefault("anchor_values", {}).update(
            {str(key): value for key, value in anchor_values.items() if value}
        )


def _merge_outcome(
    record: dict[str, Any],
    outcome: Mapping[str, Any],
    *,
    sequence: int = 0,
) -> None:
    metadata = outcome.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}

    accepted_source_ids = [
        str(value) for value in outcome.get("accepted_source_ids") or [] if value
    ]
    accepted_urls = [
        str(value) for value in outcome.get("accepted_urls") or [] if value
    ]
    duplicate_urls = [
        str(value) for value in outcome.get("duplicate_urls") or [] if value
    ]
    skipped = Counter(
        {
            str(key): int(value or 0)
            for key, value in dict(outcome.get("skipped_by_reason") or {}).items()
        }
    )

    strategy_family = str(metadata.get("strategy_family") or "")
    if strategy_family:
        record["strategy_families"][strategy_family] += 1
    strategy_operator = str(metadata.get("strategy_operator") or strategy_family)
    if strategy_operator:
        record["strategy_operators"][strategy_operator] += 1

    query = str(outcome.get("query") or "")
    terms = _query_terms(query)
    if accepted_source_ids:
        record["successful_query_terms"].update(terms)
    elif not outcome.get("error"):
        record["failed_query_terms"].update(terms)

    record["attempt_count"] += 1
    record["accepted_source_ids"].extend(accepted_source_ids)
    record["accepted_urls"].extend(accepted_urls)
    record["skipped_by_reason"].update(skipped)
    record["attempts"].append(
        {
            "sequence": int(sequence),
            "episode_id": str(outcome.get("episode_id") or ""),
            "query": query,
            "strategy_attempt_id": (
                metadata.get("strategy_attempt_id")
                or metadata.get("strategy_wave_id")
                or ""
            ),
            "evolution_index": _first_present(
                metadata,
                "evolution_index",
                "strategy_evolution_index",
            ),
            "prompt_arm_id": metadata.get("prompt_arm_id", ""),
            "prompt_arm_name": metadata.get("prompt_arm_name", ""),
            "prompt_arm_index": metadata.get("prompt_arm_index"),
            "prompt_delta": metadata.get("prompt_delta", ""),
            "prompt_hypothesis": metadata.get("prompt_hypothesis", ""),
            "expected_source_shape": metadata.get("expected_source_shape", ""),
            "query_index": _first_present(
                metadata,
                "query_index",
                "strategy_query_index",
            ),
            "strategy_family": strategy_family,
            "strategy_operator": strategy_operator,
            "source_family": metadata.get("source_family", ""),
            "strategy_origin": metadata.get("strategy_origin", ""),
            "operator_attempt": metadata.get("operator_attempt"),
            "operator_last_failure_class": metadata.get(
                "operator_last_failure_class",
                "",
            ),
            "rationale": metadata.get("rationale", ""),
            "firecrawl_hits": int(outcome.get("firecrawl_hits") or 0),
            "search_result_count": len(
                outcome.get("search_result_observations") or []
            ),
            "accepted_source_count": len(accepted_source_ids),
            "accepted_source_ids": accepted_source_ids,
            "accepted_urls": accepted_urls[:5],
            "duplicate_url_count": len(duplicate_urls),
            "skipped_by_reason": dict(skipped),
            "candidate_fates": dict(
                Counter(
                    str(candidate.get("fate") or "")
                    for candidate in outcome.get("candidate_source_outcomes") or []
                    if isinstance(candidate, Mapping)
                    and str(candidate.get("fate") or "")
                )
            ),
            "search_results": [
                dict(observation)
                for observation in (
                    outcome.get("search_result_observations") or []
                )[:5]
                if isinstance(observation, Mapping)
            ],
            "post_episode_observed_delta": metadata.get("post_episode_observed_delta"),
            "post_episode_graph_node_delta": metadata.get(
                "post_episode_graph_node_delta",
            ),
            "post_episode_graph_edge_delta": metadata.get(
                "post_episode_graph_edge_delta",
            ),
            "post_episode_deficit_count": metadata.get("post_episode_deficit_count"),
            "post_episode_table_row_hits": metadata.get("post_episode_table_row_hits"),
            "post_episode_best_guess_hits": metadata.get("post_episode_best_guess_hits"),
            # Real semantic yield, joined by ID from 3A's own instrument
            # (`reward.score_criterion_yield`) once the strategy Episode that
            # ran this query has materialized and been scored -- never a row,
            # source, or graph-delta count.  Absent (``None``) until that join
            # has happened; ``[]`` once it has and found nothing.  See
            # ``pipeline.py:_annotate_recent_target_outcomes``, which is the
            # only writer of these two keys.
            "post_episode_credited_criterion_ids": metadata.get(
                "post_episode_credited_criterion_ids"
            ),
            "post_episode_credited_datapoint_kinds": metadata.get(
                "post_episode_credited_datapoint_kinds"
            ),
            "post_episode_cost_records": metadata.get("post_episode_cost_records") or [],
            "error": str(outcome.get("error") or "")[:500],
        }
    )


def _finalize_record(record: dict[str, Any]) -> dict[str, Any]:
    attempts = sorted(
        record["attempts"],
        key=lambda attempt: (
            _memory_as_int(attempt.get("sequence")),
            _memory_as_int(attempt.get("evolution_index")),
            _memory_as_int(attempt.get("prompt_arm_index")),
            _memory_as_int(attempt.get("query_index")),
            str(attempt.get("query") or ""),
        ),
    )
    strategy_attempts = _summarize_strategy_attempts(attempts)
    return {
        "key": record["key"],
        "target": record["target"],
        "attempt_count": record["attempt_count"],
        "accepted_source_count": len(set(record["accepted_source_ids"])),
        "accepted_source_ids": _unique(record["accepted_source_ids"])[:20],
        "accepted_urls": _unique(record["accepted_urls"])[:20],
        "skipped_by_reason": dict(record["skipped_by_reason"]),
        "strategy_families": dict(record["strategy_families"]),
        "strategy_operators": dict(record["strategy_operators"]),
        "successful_query_terms": _top_counter(record["successful_query_terms"], 12),
        "failed_query_terms": _top_counter(record["failed_query_terms"], 12),
        # Unclipped, for the same reason as `strategy_history` in
        # `pipeline._deficits_with_strategy_history`: this is the memory the
        # next planner call uses to avoid reissuing a query, and a tail bounds
        # how far back "avoid repeating" can reach. Clipping here would also
        # have made the fix one layer up ineffective -- the pipeline's own
        # limit of 8 was reading from a list this had already cut to 12.
        # LATENT on every recorded run: largest observed is 2 attempts.
        "strategy_attempts": strategy_attempts,
        "attempts": attempts,
    }


def _compact_record(record: Mapping[str, Any], *, score: int) -> dict[str, Any]:
    return {
        "match_score": score,
        "target": record.get("target", {}),
        "attempt_count": record.get("attempt_count", 0),
        "accepted_source_count": record.get("accepted_source_count", 0),
        "skipped_by_reason": record.get("skipped_by_reason", {}),
        "strategy_families": record.get("strategy_families", {}),
        "strategy_operators": record.get("strategy_operators", {}),
        "successful_query_terms": record.get("successful_query_terms", []),
        "failed_query_terms": record.get("failed_query_terms", []),
        "attempts": (
            record.get("strategy_attempts")
            or record.get("search_waves")
            or record.get("attempts", [])
        )[-6:],
        "query_attempts": record.get("attempts", [])[-6:],
    }


def _summarize_strategy_attempts(
    attempts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for attempt in attempts:
        key = _strategy_attempt_key(attempt)
        strategy_attempt = groups.setdefault(
            key,
            {
                "strategy_attempt_id": str(
                    attempt.get("strategy_attempt_id") or key
                ),
                "sequence": attempt.get("sequence"),
                "evolution_index": attempt.get("evolution_index"),
                "strategy_family": attempt.get("strategy_family", ""),
                "strategy_operator": attempt.get("strategy_operator", ""),
                "source_family": attempt.get("source_family", ""),
                "operator_attempt": attempt.get("operator_attempt"),
                "operator_last_failure_class": attempt.get(
                    "operator_last_failure_class",
                    "",
                ),
                "queries": [],
                "firecrawl_hits": 0,
                "search_result_count": 0,
                "accepted_source_count": 0,
                "duplicate_url_count": 0,
                "skipped_by_reason": Counter(),
                "candidate_fates": Counter(),
                "search_results": [],
                "accepted_urls": [],
                "prompt_arms": OrderedDict(),
                # Real semantic yield for the whole strategy attempt.
                # `None` means no query in this attempt has had its yield
                # measured yet -- distinct from `[]`, which means measured
                # and found zero. Routing reads this
                # (`strategy_state._credited_yield_productive`), so
                # collapsing the two would make "not known" indistinguishable
                # from "known to be nothing".
                "post_episode_credited_criterion_ids": None,
                "post_episode_credited_datapoint_kinds": None,
                "outcome_count": 0,
                "error_count": 0,
                "errors": [],
            },
        )
        query = str(attempt.get("query") or "")
        if query:
            strategy_attempt["queries"].append(query)
            strategy_attempt["query"] = query
        strategy_attempt["sequence"] = attempt.get("sequence")
        strategy_attempt["firecrawl_hits"] += _memory_as_int(attempt.get("firecrawl_hits"))
        strategy_attempt["search_result_count"] += _memory_as_int(
            attempt.get("search_result_count")
        )
        strategy_attempt["accepted_source_count"] += _memory_as_int(
            attempt.get("accepted_source_count")
        )
        strategy_attempt["duplicate_url_count"] += _memory_as_int(
            attempt.get("duplicate_url_count")
        )
        strategy_attempt["skipped_by_reason"].update(
            _memory_mapping(attempt.get("skipped_by_reason"))
        )
        strategy_attempt["candidate_fates"].update(
            _memory_mapping(attempt.get("candidate_fates"))
        )
        strategy_attempt["accepted_urls"].extend(attempt.get("accepted_urls") or [])
        if len(strategy_attempt["search_results"]) < 12:
            strategy_attempt["search_results"].extend(
                (attempt.get("search_results") or [])[
                    : max(0, 12 - len(strategy_attempt["search_results"]))
                ]
            )
        _merge_prompt_arm(strategy_attempt, attempt)
        strategy_attempt["outcome_count"] += 1
        for field_name in (
            "post_episode_observed_delta",
            "post_episode_graph_node_delta",
            "post_episode_graph_edge_delta",
            "post_episode_deficit_count",
            "post_episode_table_row_hits",
            "post_episode_best_guess_hits",
        ):
            value = attempt.get(field_name)
            if value is not None:
                strategy_attempt[field_name] = value

        # The credited fields are **list-valued**, unlike the six scalars
        # above, and are merged by **union over criterion ID** rather than
        # last-write-wins. A strategy attempt spans several concrete
        # queries; a criterion credited by any one of them was credited by
        # the attempt, and the last query is not more authoritative than the
        # first. Union, never a count -- a criterion credited twice is one
        # criterion, and turning this into a tally would put volume back on
        # the routing path that cycles 1 and 2 removed it from.
        credited_ids = attempt.get("post_episode_credited_criterion_ids")
        if credited_ids is not None:
            merged_ids = strategy_attempt["post_episode_credited_criterion_ids"] or []
            strategy_attempt["post_episode_credited_criterion_ids"] = _unique(
                [*merged_ids, *credited_ids]
            )
        credited_kinds = attempt.get("post_episode_credited_datapoint_kinds")
        if credited_kinds is not None:
            merged_kinds = strategy_attempt["post_episode_credited_datapoint_kinds"] or []
            # Distinct kinds observed, not one entry per datapoint: the
            # membership is diagnostic, the multiplicity would be volume.
            strategy_attempt["post_episode_credited_datapoint_kinds"] = sorted(
                set(merged_kinds) | set(credited_kinds)
            )
        error = str(attempt.get("error") or "")
        if error:
            strategy_attempt["error_count"] += 1
            strategy_attempt["errors"].append(error)

    return [
        _finalize_strategy_attempt(strategy_attempt)
        for strategy_attempt in groups.values()
    ]


def _merge_prompt_arm(
    strategy_attempt: dict[str, Any],
    attempt: Mapping[str, Any],
) -> None:
    arm_key = _prompt_arm_key(attempt)
    arms: OrderedDict[str, dict[str, Any]] = strategy_attempt["prompt_arms"]
    arm = arms.setdefault(
        arm_key,
        {
            "prompt_arm_id": str(attempt.get("prompt_arm_id") or arm_key),
            "prompt_arm_name": str(attempt.get("prompt_arm_name") or ""),
            "prompt_arm_index": attempt.get("prompt_arm_index"),
            # WHERE THIS ARM CAME FROM, carried rather than derived. The
            # deterministic fallback arm carries a declared constant delta
            # ("deterministic fallback") and no sibling, so a strategy attempt
            # consisting only of fallback arms produces a contrast of identical
            # declared deltas that LOOKS like contrast and carries none. The
            # field is already on the task and on the control action, so this is
            # a field to forward, not a fact to reconstruct -- and nothing
            # reconstructs arm provenance from wording.
            "strategy_origin": str(attempt.get("strategy_origin") or ""),
            "prompt_delta": str(attempt.get("prompt_delta") or ""),
            "prompt_hypothesis": str(attempt.get("prompt_hypothesis") or ""),
            "expected_source_shape": str(
                attempt.get("expected_source_shape") or ""
            ),
            "queries": [],
            "firecrawl_hits": 0,
            "search_result_count": 0,
            "accepted_source_count": 0,
            "accepted_source_ids": [],
            "duplicate_url_count": 0,
            # Operational volume. Recorded for diagnostics, never scored --
            # see `_prompt_arm_score`.
            "table_row_hits": 0,
            "best_guess_hits": 0,
            # Real semantic yield, joined from 3A's reward once the round is
            # scored. `_yield_known` distinguishes "not measured yet" from
            # "measured, zero" -- the same distinction `RewardReport.score`
            # makes for cost.
            "_yield_known": False,
            "credited_criterion_ids": set(),
            "credited_datapoint_kinds": Counter(),
            "cost_records": [],
            "skipped_by_reason": Counter(),
            "candidate_fates": Counter(),
            "search_results": [],
            "accepted_urls": [],
            "error_count": 0,
            "errors": [],
        },
    )

    query = str(attempt.get("query") or "")
    if query:
        arm["queries"].append(query)
    arm["firecrawl_hits"] += _memory_as_int(attempt.get("firecrawl_hits"))
    arm["search_result_count"] += _memory_as_int(attempt.get("search_result_count"))
    arm["accepted_source_count"] += _memory_as_int(attempt.get("accepted_source_count"))
    arm["accepted_source_ids"].extend(attempt.get("accepted_source_ids") or [])
    arm["duplicate_url_count"] += _memory_as_int(attempt.get("duplicate_url_count"))
    arm["table_row_hits"] += _memory_as_int(attempt.get("post_episode_table_row_hits"))
    arm["best_guess_hits"] += _memory_as_int(attempt.get("post_episode_best_guess_hits"))
    if attempt.get("post_episode_credited_criterion_ids") is not None:
        arm["_yield_known"] = True
        arm["credited_criterion_ids"].update(
            attempt.get("post_episode_credited_criterion_ids") or []
        )
        arm["credited_datapoint_kinds"].update(
            attempt.get("post_episode_credited_datapoint_kinds") or []
        )
    arm["cost_records"].extend(attempt.get("post_episode_cost_records") or [])
    arm["skipped_by_reason"].update(_memory_mapping(attempt.get("skipped_by_reason")))
    arm["candidate_fates"].update(_memory_mapping(attempt.get("candidate_fates")))
    arm["accepted_urls"].extend(attempt.get("accepted_urls") or [])
    if len(arm["search_results"]) < 12:
        arm["search_results"].extend(
            (attempt.get("search_results") or [])[
                : max(0, 12 - len(arm["search_results"]))
            ]
        )
    error = str(attempt.get("error") or "")
    if error:
        arm["error_count"] += 1
        arm["errors"].append(error)


def _finalize_strategy_attempt(wave: Mapping[str, Any]) -> dict[str, Any]:
    query_count = len(wave.get("queries") or [])
    outcome_count = _memory_as_int(wave.get("outcome_count"))
    error_count = _memory_as_int(wave.get("error_count"))
    error = ""
    if outcome_count > 0 and error_count >= outcome_count:
        error = "; ".join(wave.get("errors") or [])[:500]
    raw_arms = list((wave.get("prompt_arms") or {}).values())
    # Every other arm's accepted sources, per arm -- the set an arm's own
    # accepted sources are checked against for "contributed no independent
    # evidence".  Computed before any arm is finalized so each arm sees its
    # siblings' full accepted set, not a partial one built up during a single
    # pass.
    accepted_by_identity = {id(arm): set(arm.get("accepted_source_ids") or []) for arm in raw_arms}
    prompt_arms = []
    for arm in raw_arms:
        own_identity = id(arm)
        sibling_union: set[str] = set()
        for other_identity, other_ids in accepted_by_identity.items():
            if other_identity != own_identity:
                sibling_union |= other_ids
        prompt_arms.append(
            _finalize_prompt_arm(arm, sibling_accepted_source_ids=frozenset(sibling_union))
        )
    return {
        "strategy_attempt_id": wave.get("strategy_attempt_id", ""),
        "sequence": wave.get("sequence"),
        "evolution_index": wave.get("evolution_index"),
        "strategy_family": wave.get("strategy_family", ""),
        "strategy_operator": wave.get("strategy_operator", ""),
        "source_family": wave.get("source_family", ""),
        "operator_attempt": wave.get("operator_attempt"),
        "operator_last_failure_class": wave.get("operator_last_failure_class", ""),
        "query_count": query_count,
        "queries": _unique(wave.get("queries") or []),
        "query": str(wave.get("query") or ""),
        "firecrawl_hits": _memory_as_int(wave.get("firecrawl_hits")),
        "search_result_count": _memory_as_int(wave.get("search_result_count")),
        "accepted_source_count": _memory_as_int(wave.get("accepted_source_count")),
        "accepted_urls": _unique(wave.get("accepted_urls") or [])[:10],
        "duplicate_url_count": _memory_as_int(wave.get("duplicate_url_count")),
        "skipped_by_reason": dict(wave.get("skipped_by_reason") or {}),
        "candidate_fates": dict(wave.get("candidate_fates") or {}),
        "search_results": list(wave.get("search_results") or [])[:12],
        "post_episode_observed_delta": wave.get("post_episode_observed_delta"),
        "post_episode_graph_node_delta": wave.get("post_episode_graph_node_delta"),
        "post_episode_graph_edge_delta": wave.get("post_episode_graph_edge_delta"),
        "post_episode_deficit_count": wave.get("post_episode_deficit_count"),
        "post_episode_table_row_hits": wave.get("post_episode_table_row_hits"),
        "post_episode_best_guess_hits": wave.get("post_episode_best_guess_hits"),
        # Carried onto the finalized attempt because this is the shape
        # `pipeline._deficits_with_strategy_history` puts into
        # `strategy_history`, which is what `strategy_state._target_attempts`
        # hands to the routing exhaustion guard. Dropping it here starved
        # `_credited_yield_productive` of the only input it reads, so every
        # attempt read unmeasured and routing collapsed onto
        # `_default_target_order`.
        "post_episode_credited_criterion_ids": wave.get(
            "post_episode_credited_criterion_ids"
        ),
        "post_episode_credited_datapoint_kinds": wave.get(
            "post_episode_credited_datapoint_kinds"
        ),
        "prompt_arms": prompt_arms,
        "arm_contrast": _arm_contrast(prompt_arms),
        "error": error,
    }


def _finalize_prompt_arm(
    arm: Mapping[str, Any],
    *,
    sibling_accepted_source_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    query_count = len(arm.get("queries") or [])
    own_accepted_ids = _unique(arm.get("accepted_source_ids") or [])
    duplicate_with_sibling_ids = sorted(
        set(own_accepted_ids) & set(sibling_accepted_source_ids)
    )
    yield_known = bool(arm.get("_yield_known"))
    credited_criterion_ids = (
        sorted(arm.get("credited_criterion_ids") or set()) if yield_known else None
    )
    cost_vector = aggregate_cost(arm.get("cost_records") or [])
    outcome = _prompt_arm_outcome(
        arm,
        duplicate_with_sibling_count=len(duplicate_with_sibling_ids),
        credited_criterion_ids=credited_criterion_ids,
    )
    return {
        "prompt_arm_id": arm.get("prompt_arm_id", ""),
        "prompt_arm_name": arm.get("prompt_arm_name", ""),
        "prompt_arm_index": arm.get("prompt_arm_index"),
        "strategy_origin": arm.get("strategy_origin", ""),
        "prompt_delta": arm.get("prompt_delta", ""),
        "prompt_hypothesis": arm.get("prompt_hypothesis", ""),
        "expected_source_shape": arm.get("expected_source_shape", ""),
        "query_count": query_count,
        "queries": _unique(arm.get("queries") or []),
        "firecrawl_hits": _memory_as_int(arm.get("firecrawl_hits")),
        "search_result_count": _memory_as_int(arm.get("search_result_count")),
        "accepted_source_count": _memory_as_int(arm.get("accepted_source_count")),
        "accepted_source_ids": own_accepted_ids[:20],
        "duplicate_url_count": _memory_as_int(arm.get("duplicate_url_count")),
        # The duplicate penalty, individually observable: sources this arm
        # accepted that a sibling arm in the same evolution step also
        # accepted -- non-overlapping evidence contributed nothing new.
        "duplicate_with_sibling_source_ids": duplicate_with_sibling_ids,
        "duplicate_with_sibling_count": len(duplicate_with_sibling_ids),
        # Operational volume. Recorded for diagnostics, never scored -- see
        # `_prompt_arm_score`. Rows materialized and best-guess candidates
        # are not goodness; an arm that produced a hundred of either and
        # zero credited criteria scores as zero yield, not as volume.
        "table_row_hits": _memory_as_int(arm.get("table_row_hits")),
        "best_guess_hits": _memory_as_int(arm.get("best_guess_hits")),
        "skipped_by_reason": dict(arm.get("skipped_by_reason") or {}),
        "candidate_fates": dict(arm.get("candidate_fates") or {}),
        "accepted_urls": _unique(arm.get("accepted_urls") or [])[:10],
        "search_results": list(arm.get("search_results") or [])[:12],
        # The yield term: real datapoints from 3A's own instrument
        # (`reward.score_criterion_yield`), joined here by ID
        # (`crediting_source_ids` intersected against this arm's own
        # `accepted_source_ids`) -- not a source-local hit count, not an
        # accepted-source count, not a row materialized.
        "yield_known": yield_known,
        "credited_criterion_ids": credited_criterion_ids,
        "credited_criterion_count": (
            len(credited_criterion_ids) if credited_criterion_ids is not None else None
        ),
        "credited_datapoint_kinds": dict(arm.get("credited_datapoint_kinds") or {}),
        # The cost penalty, individually observable: 1B's own per-action
        # records, joined by `observation_id`/`nested_in` against this arm's
        # search task IDs -- never estimated or re-derived.
        "cost": cost_vector.to_dict(),
        # Whether the cost axis is meaningful for this arm at all. An
        # uninstrumented arm is charged no cost penalty, which would read as
        # "free" rather than "unknown" if a consumer could not tell them
        # apart -- so it is stated rather than inferred.
        "cost_known": cost_vector.available,
        "score": _prompt_arm_score(
            credited_criterion_ids=credited_criterion_ids,
            duplicate_with_sibling_count=len(duplicate_with_sibling_ids),
            cost_vector=cost_vector,
        ),
        "outcome": outcome,
        "error": "; ".join(arm.get("errors") or [])[:500],
    }


def _strategy_attempt_key(attempt: Mapping[str, Any]) -> str:
    attempt_id = str(attempt.get("strategy_attempt_id") or "")
    if attempt_id:
        return attempt_id
    payload = {
        "episode_id": attempt.get("episode_id"),
        "evolution_index": attempt.get("evolution_index"),
        "operator": _memory_operator_name(attempt),
        "operator_attempt": attempt.get("operator_attempt"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _prompt_arm_key(attempt: Mapping[str, Any]) -> str:
    return str(
        attempt.get("prompt_arm_id")
        or attempt.get("strategy_attempt_id")
        or _strategy_attempt_key(attempt)
    )


def _arm_contrast(prompt_arms: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Nested per-arm contrast: each penalty axis stays a separate column.

    Routing reads this list, never an aggregate over it -- see
    `strategy_state.route_next_family`. Sorted so a known score always
    outranks an unmeasured one (`None`), and higher known scores come first;
    among unmeasured arms the order is the input order.
    """
    rows = [
        {
            "prompt_arm_id": arm.get("prompt_arm_id", ""),
            "prompt_arm_name": arm.get("prompt_arm_name", ""),
            # So a contrast row can distinguish a planner arm from the
            # deterministic fallback. Without it, an attempt made entirely of
            # fallback arms produces rows with identical declared deltas that
            # read as contrast and carry none. Carried as a field; no consumer
            # infers it from the arm's wording.
            "strategy_origin": arm.get("strategy_origin", ""),
            "expected_source_shape": arm.get("expected_source_shape", ""),
            "score": arm.get("score"),
            "yield_known": arm.get("yield_known", False),
            "credited_criterion_count": arm.get("credited_criterion_count"),
            "duplicate_with_sibling_count": arm.get("duplicate_with_sibling_count", 0),
            "cost": arm.get("cost", {}),
            "cost_known": arm.get("cost_known", False),
            "accepted_source_count": arm.get("accepted_source_count", 0),
            "outcome": arm.get("outcome", ""),
        }
        for arm in prompt_arms
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.get("score") is not None,
            float(row.get("score") or 0.0),
        ),
        reverse=True,
    )


#: Relative importances *within* the penalty term, never against yield.
#:
#: These are ratios, not magnitudes: the summed penalty is squashed into
#: ``[0, 1)`` by :func:`_penalty` before it reaches the score, so no
#: combination of them can ever cross an integer credited-criterion
#: boundary.  Changing one changes which arm wins a tie; none of them can
#: change whether a crediting arm outranks a non-crediting one.
_DUPLICATE_PENALTY_WEIGHT = 1.0
_COST_PENALTY_WEIGHT = 0.01


def _penalty(
    *,
    duplicate_with_sibling_count: int,
    cost_vector: CostVector,
) -> float:
    """Duplicate and cost penalties, squashed below one credited datapoint.

    ``raw / (1 + raw)`` maps ``[0, inf)`` onto ``[0, 1)``: strictly
    increasing, so ordering among arms that tied on yield is preserved
    exactly, and bounded, so the penalty is always worth less than one
    credited criterion.

    **This is the fix for a volume-scoring defect.**  The predecessor added
    the raw sum directly, with ``_DUPLICATE_PENALTY_WEIGHT = 1.0`` putting a
    *count of accepted sources* -- operational volume -- at parity with a
    real datapoint.  An arm crediting one criterion on a source a sibling
    also accepted scored 0.0, tying an arm that credited nothing; with two
    shared sources it scored -1.0 and ranked *below* it.  Since
    :func:`_arm_contrast` sorts by score and ``_route_from_contrast`` reads
    ``contrast[0]``, that arm's family would stop being exploited because a
    sibling happened to see the same paper.  A credited criterion is real
    data added whether or not a sibling also saw the source it came from.

    The module docstring's invariant is now enforced here rather than
    asserted: *a penalty axis can only reorder arms that already tied on
    real yield, and can never outrank one that credited more.*
    """

    raw = _DUPLICATE_PENALTY_WEIGHT * max(0, duplicate_with_sibling_count)
    if cost_vector.available:
        raw += _COST_PENALTY_WEIGHT * max(0, cost_vector.billable_calls)
    return raw / (1.0 + raw)


def _prompt_arm_score(
    *,
    credited_criterion_ids: list[str] | None,
    duplicate_with_sibling_count: int,
    cost_vector: CostVector,
) -> float | None:
    """Real yield, with duplicate and cost as strict tie-breaks.

    ``None`` -- not zero -- until the round this arm's queries ran in has
    been scored by `reward.score_criterion_yield` and joined back by ID.
    Comparing an unmeasured arm's score to a measured zero would silently
    treat "not yet known" as "measured and found wanting".

    The penalty is bounded strictly below 1 (see :func:`_penalty`), so for
    integer credited counts the ranking is lexicographic: credited count
    first, penalties only within a tie.

    **Cost caveat.** When an arm's cost is unknown (`cost_vector.available`
    false -- nothing instrumented it) no cost penalty is charged, so an
    uninstrumented arm reads as cheaper than an instrumented one rather than
    as unknown.  The arm carries ``cost_known`` so a consumer can see this
    rather than infer it; contrast rows within one evolution step come from
    one run and are normally all-known or all-unknown together.

    **Rounding caveat.** The result is rounded to 6 decimals, so a crediting
    arm whose raw penalty exceeds roughly ``2e6`` rounds to exactly the
    barren arm's ``0.0`` and ties it.  ``sorted`` is stable, so on a tie the
    earlier arm keeps ``contrast[0]`` and a crediting arm could lose the
    exploitation slot to input order.  It ties, never inverts -- the squash
    keeps the true value strictly above -- and the counts required
    (millions of shared sources or billable calls in one evolution step) are
    unreachable in practice.  Recorded rather than guarded, because a guard
    here would cost a branch on every scoring call to fix an arithmetic
    boundary no real run can reach.
    """
    if credited_criterion_ids is None:
        return None
    return round(
        len(credited_criterion_ids)
        - _penalty(
            duplicate_with_sibling_count=duplicate_with_sibling_count,
            cost_vector=cost_vector,
        ),
        6,
    )


def _prompt_arm_outcome(
    arm: Mapping[str, Any],
    *,
    duplicate_with_sibling_count: int,
    credited_criterion_ids: list[str] | None,
) -> str:
    """One of the pseudo-gradient's named classes.

    Matches `docs/TABLE_FILL_PROMPT_MUTATION_EXPERIMENTS.md`'s definition of
    the pseudo-gradient directly: which arms found non-overlapping useful
    evidence (`credited_yield`), which returned only duplicates
    (`all_duplicates` / `sibling_duplicate`), and which found promising
    sources that failed to support the target criteria (`accepted_no_yield`).
    """
    if credited_criterion_ids:
        return "credited_yield"
    if _memory_as_int(arm.get("search_result_count")) <= 0:
        return "no_hits"
    skipped = _memory_mapping(arm.get("skipped_by_reason"))
    if _memory_as_int(skipped.get("duplicate_url")) >= _memory_as_int(
        arm.get("search_result_count")
    ):
        return "all_duplicates"
    if duplicate_with_sibling_count > 0 and duplicate_with_sibling_count >= _memory_as_int(
        arm.get("accepted_source_count")
    ):
        return "sibling_duplicate"
    if _memory_as_int(arm.get("accepted_source_count")) > 0 and credited_criterion_ids is None:
        return "accepted_pending_yield"
    if _memory_as_int(arm.get("accepted_source_count")) > 0:
        return "accepted_no_yield"
    return "no_accepted_sources"


def _match_score(target: Mapping[str, Any], record: Mapping[str, Any]) -> int:
    previous = record.get("target")
    if not isinstance(previous, Mapping):
        return 0

    score = 0
    if _memory_clean(target.get("target_table")) == _memory_clean(previous.get("target_table")):
        score += 20
    else:
        return 0

    if _memory_clean(target.get("target_id")) and _memory_clean(target.get("target_id")) == _memory_clean(
        previous.get("target_id")
    ):
        score += 40
    if _memory_clean(target.get("target_name")) and _memory_clean(
        target.get("target_name")
    ) == _memory_clean(previous.get("target_name")):
        score += 30
    target_deficit_type = _memory_clean(
        target.get("deficit_type") or target.get("fill_deficit_type")
    )
    if target_deficit_type == _memory_clean(previous.get("deficit_type")):
        score += 10

    score += 4 * len(
        set(_clean_list(target.get("key_columns")))
        & set(_clean_list(previous.get("key_columns")))
    )
    score += 3 * len(
        set(_clean_list(target.get("missing_fields")))
        & set(_clean_list(previous.get("missing_fields")))
    )
    score += 8 * len(
        set(_clean_list(dict(target.get("anchor_values") or {}).values()))
        & set(_clean_list(dict(previous.get("anchor_values") or {}).values()))
    )
    return score


def _top_counter(counter: Counter, limit: int) -> list[str]:
    return [value for value, _ in counter.most_common(limit) if value]


def _latest_sequence(record: Mapping[str, Any]) -> int:
    """Recency of a record's newest attempt within THIS memory build.

    An ordering key over the build's own outcome stream and nothing more --
    see :meth:`SearchMemory.from_outcomes`.
    """

    attempts = record.get("attempts")
    if not isinstance(attempts, list):
        return -1
    return max(
        (_memory_as_int(attempt.get("sequence")) for attempt in attempts),
        default=-1,
    )


def _memory_as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _memory_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _memory_operator_name(attempt: Mapping[str, Any]) -> str:
    return str(
        attempt.get("strategy_operator")
        or attempt.get("operator")
        or attempt.get("strategy_family")
        or ""
    )


def _anchor_signature(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    return "|".join(_clean_list(value.values())[:6])


def _query_terms(query: str) -> list[str]:
    """Content words of one query, for the term-frequency memory. NOT an identity.

    Every surviving term, not the first twelve. These feed the
    `successful_query_terms` / `failed_query_terms` Counters, which the planner
    prompt reads to steer the next query's vocabulary, so a `[:12]` dropped the
    thirteenth-onward content word of a long query out of that memory purely
    for standing late in the string -- and a term that never enters the counter
    can never be learned from, in this round or any later one. The emitted
    payload is bounded downstream by `_top_counter(..., 12)`, which ranks by
    observed frequency; that is a bound on what is *reported*, and it was
    already doing the job this slice appeared to be doing.

    Explicitly not an identity tokenizer, and nothing here uses it as one: its
    only consumers are the two `Counter.update` calls above. A key built from a
    fixed-length token prefix would collide for two different long queries
    sharing their first twelve terms, which is why this must not acquire such a
    use without becoming single-owner and versioned first.
    """

    return [
        word
        for word in _WORD_RE.findall(_memory_clean(query))
        if len(word) > 2 and word not in _STOPWORDS
    ]


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes, Mapping)):
        values = [values]
    return _unique(_memory_clean(value) for value in values if value)


def _memory_clean(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).strip().lower()


def _unique(values: Iterable[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for value in values:
        if value is None or value == "":
            continue
        key = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


# ---------------------------------------------------------------------------
# Path outcomes (phase 2C)
# ---------------------------------------------------------------------------
#
# One accepted source, one target criterion family, exactly one of five
# outcomes.  The five are the stages of a single chain -- graph evidence, a
# route worth walking, a candidate value for the target criterion, and finally
# a criterion transition -- and the recorded outcome names the furthest stage
# the source actually reached for that family.
#
# Why the furthest stage rather than the first break: the stages are nested by
# construction, so "candidate evidence exists" already implies a route reached
# the table.  Naming the first break would let one weakly scored route mask a
# transition that did happen, and the whole point of this record is to say what
# the next round should change.


#: Bumped when a change would move an existing (source, family) pair to a
#: different outcome.  Carried on every record so a consumer comparing outcomes
#: across versions sees a mismatch rather than a difference in yield.
PATH_OUTCOME_VERSION = "path_outcome_v1"


class PathOutcome(str, Enum):
    """Where the chain broke for one accepted source and one target family.

    Closed, ordered, and deliberately not prose.  A downstream stage groups by
    the identifier; nothing anywhere branches on a sentence.
    """

    #: The source contributed nothing to the traversal at all: no node, edge,
    #: or candidate row in the round's traversal state cites it.
    NO_GRAPH_EVIDENCE = "no_graph_evidence"

    #: Traversal rows cite the source, but no route to the family's table
    #: scored at or above the caller's selection threshold.
    ROUTES_ALL_LOW_SCORE = "routes_all_low_score"

    #: At least one route scored high, and still no row carries a value for
    #: this family's field on the strength of this source.
    NO_CANDIDATE_EVIDENCE = "no_candidate_evidence"

    #: A criterion in this family is supported citing this source, and no
    #: criterion newly gained support attributable to it.  Re-traversal of a
    #: source the graph already held lands here, which is the point.
    CANDIDATE_WITHOUT_TRANSITION = "candidate_without_transition"

    #: A criterion newly gained support, attributable to this source by ID.
    SUPPORT_GAINED_ATTRIBUTED = "support_gained_attributed"


#: Stage number of each outcome, weakest first.  A consumer that wants "how far
#: did this get" compares through this map rather than re-deriving an order,
#: and :class:`PathOutcomeMemory` uses it to keep the furthest stage a
#: (source, family) pair ever reached across rounds.
PATH_OUTCOME_STAGE: Mapping[PathOutcome, int] = {
    PathOutcome.NO_GRAPH_EVIDENCE: 1,
    PathOutcome.ROUTES_ALL_LOW_SCORE: 2,
    PathOutcome.NO_CANDIDATE_EVIDENCE: 3,
    PathOutcome.CANDIDATE_WITHOUT_TRANSITION: 4,
    PathOutcome.SUPPORT_GAINED_ATTRIBUTED: 5,
}


@dataclass(frozen=True)
class CriterionFamilyRef:
    """One target family: a table and a field, identified rather than described.

    This is 1D's criterion grouping with the subject coordinate projected out.
    A criterion is *(table, subject, field)*; a family is every criterion that
    asks the same question of a different subject, which is the grain a deficit
    search actually attacks and the grain a next-action decision is made at.

    The version-4 table-spec contract's ``required_criterion_families`` do not
    exist at baseline and are **not** what this is.
    """

    id: str
    table: str
    field: str

    @classmethod
    def create(cls, *, table: str, field: str) -> "CriterionFamilyRef":
        table = str(table or "").strip()
        field = str(field or "").strip()
        return cls(
            id=stable_id(
                {
                    "version": PATH_OUTCOME_VERSION,
                    "table": table,
                    "field": field,
                }
            ),
            table=table,
            field=field,
        )

    @classmethod
    def of_criterion(cls, ref: Any) -> "CriterionFamilyRef":
        """The family a criterion belongs to.

        Accepts a :class:`~question_pipeline.utilities.tables.CriterionRef`, its
        ``to_dict()`` payload, or anything else exposing ``table`` and
        ``field`` -- so a caller reading a serialized snapshot does not have to
        rebuild the ref first.
        """

        if isinstance(ref, Mapping):
            table = ref.get("table", "")
            name = ref.get("field", "")
        else:
            table = getattr(ref, "table", "")
            name = getattr(ref, "field", "")
        return cls.create(table=table, field=name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_family_id": self.id,
            "table": self.table,
            "field": self.field,
        }


@dataclass(frozen=True)
class SemanticClaimPair:
    """One attributable semantic-claim / canonical-source pair.

    The pair outcome 5 is defined by: a criterion that newly gained support,
    and the source that gain is attributable to.  Both are IDs, and the
    transition and snapshot IDs travel with them so the pair can be traced back
    to the exact projection pair it was computed from.

    ``subject_bound`` is recorded, never gated on.  An unbound subject's ID is
    a content hash that moves as soon as a field fills, so a pair carrying
    ``False`` is a weaker claim about identity; that is reported rather than
    silently dropped or silently counted.
    """

    criterion_id: str
    source_id: str
    transition_id: str
    before_snapshot_id: str = ""
    after_snapshot_id: str = ""
    after_basis: str = ""
    subject_id: str = ""
    subject_bound: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "source_id": self.source_id,
            "criteria_transition_id": self.transition_id,
            "before_criteria_snapshot_id": self.before_snapshot_id,
            "after_criteria_snapshot_id": self.after_snapshot_id,
            "after_evidence_basis": self.after_basis,
            "subject_id": self.subject_id,
            "subject_bound": self.subject_bound,
        }


@dataclass(frozen=True)
class PathOutcomeEvidence:
    """What one accepted source produced for one target family in one scoring pass.

    Every field is an ID or a set of IDs.  There is no count anywhere, and no
    text: the classifier reads emptiness and membership, so a busy round and a
    productive one are distinguishable rather than the same number twice.

    ``graph_row_ids`` is every traversal row citing the source; ``route_ids``
    is the subset that carries route slots and reached this family's table;
    ``high_score_route_ids`` is the subset of those the caller's path-selection
    threshold admitted.  The threshold is the caller's policy -- scoring is
    2A's and gating is 2B's -- so it is applied before this record is built and
    is not re-decided here.
    """

    source_id: str
    family: CriterionFamilyRef
    graph_row_ids: tuple[str, ...] = ()
    route_ids: tuple[str, ...] = ()
    high_score_route_ids: tuple[str, ...] = ()
    supporting_criterion_ids: tuple[str, ...] = ()
    claim_pairs: tuple[SemanticClaimPair, ...] = ()
    before_snapshot_id: str = ""
    after_snapshot_id: str = ""
    #: The strategy Episode whose scoring pass produced this evidence bundle.
    #: Attribution of the source's own acquisition lives on the source record
    #: (``search_episode_id``), joined by ``source_id``.
    episode_id: str = ""
    decision_id: str = ""
    action_id: str = ""
    task_id: str = ""

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("a path outcome is recorded against a source ID")
        routes = set(self.route_ids)
        if not set(self.high_score_route_ids) <= routes:
            raise ValueError("every high-scoring route must also be a route")
        if not routes <= set(self.graph_row_ids):
            raise ValueError("every route must also be graph evidence")
        for pair in self.claim_pairs:
            if pair.source_id != self.source_id:
                raise ValueError(
                    "a claim pair on this record must be attributable to this "
                    "source; a pair naming another source belongs to that "
                    "source's record"
                )


def classify_path_outcome(evidence: PathOutcomeEvidence) -> PathOutcome:
    """Which of the five outcomes this evidence is, deterministically.

    Reads set emptiness only.  It never reads a cardinality, a timestamp, a
    round distance, or a string, so:

    * one high-scoring route and five hundred of them classify alike -- volume
      does not buy progress; and
    * two bundles with identical cardinalities everywhere and different
      criterion transitions do not classify alike.

    Outcome 5 requires the criterion transition.  Accepted sources, graph
    deltas, and source-local hits are outcome 4 at best, by construction: they
    reach ``supporting_criterion_ids`` and stop there.
    """

    if evidence.claim_pairs:
        return PathOutcome.SUPPORT_GAINED_ATTRIBUTED
    if evidence.supporting_criterion_ids:
        return PathOutcome.CANDIDATE_WITHOUT_TRANSITION
    if evidence.high_score_route_ids:
        return PathOutcome.NO_CANDIDATE_EVIDENCE
    if evidence.graph_row_ids:
        return PathOutcome.ROUTES_ALL_LOW_SCORE
    return PathOutcome.NO_GRAPH_EVIDENCE


def attributable_claim_pairs(
    transitions: Iterable[Any],
    *,
    source_id: str,
    family: CriterionFamilyRef,
    new_source_ids: Iterable[str],
    snapshot: Any = None,
) -> tuple[SemanticClaimPair, ...]:
    """The pairs that license outcome 5, and nothing weaker.

    Three conditions, all joins by ID:

    1. the transition is ``SUPPORT_GAINED``.  ``BASIS_CHANGED`` is a source
       being accepted under a criterion that was already supported, and
       ``EVIDENCE_CHANGED`` is an extractor rewording a value; neither is new
       support and neither may be credited as one;
    2. the criterion belongs to this family;
    3. ``source_id`` is in the transition's ``gained_source_ids`` **and** in
       ``new_source_ids``.

    ``snapshot`` is optional and is read only to record whether the criterion's
    subject was bound.  It may be a :class:`~question_pipeline.utilities.tables.CriteriaSnapshot`
    or the ``by_criterion()`` index of one; a caller classifying many
    (source, family) pairs against one snapshot should build that index once
    and pass it, because rebuilding it per call is linear in the number of
    criteria and there can be hundreds of thousands of those.

    The third condition is the load-bearing one.  ``gained_source_ids`` means
    new *to the criterion*, not new to the run, and a freshly minted criterion
    has no "before", so its gained set is every source it cites however
    old.  Classifying outcome 5 on a non-empty gained set would therefore
    report re-traversal of an already-held graph as discovery -- which is what
    this corpus mostly does.  Intersecting with the sources newly accepted in
    the pass being classified is what separates the two, and it is an ID join,
    so it survives the gap when credit arrives passes after the ingest that
    earned it.
    """

    new_ids = {str(value) for value in new_source_ids if value}
    pairs: list[SemanticClaimPair] = []
    states = _states_by_criterion(snapshot)
    for transition in transitions or ():
        payload = _transition_payload(transition)
        if payload.get("kind") != "support_gained":
            continue
        if str(payload.get("table") or "") != family.table:
            continue
        if str(payload.get("field") or "") != family.field:
            continue
        gained = {str(value) for value in payload.get("gained_source_ids") or ()}
        if source_id not in gained or source_id not in new_ids:
            continue
        criterion_id = str(payload.get("criterion_id") or "")
        state = states.get(criterion_id)
        pairs.append(
            SemanticClaimPair(
                criterion_id=criterion_id,
                source_id=source_id,
                transition_id=str(payload.get("id") or ""),
                before_snapshot_id=str(payload.get("before_snapshot_id") or ""),
                after_snapshot_id=str(payload.get("after_snapshot_id") or ""),
                after_basis=str(payload.get("after_basis") or ""),
                subject_id=str(payload.get("subject_id") or ""),
                subject_bound=bool(getattr(getattr(state, "ref", None), "subject_bound", False)),
            )
        )
    return tuple(sorted(pairs, key=lambda pair: (pair.criterion_id, pair.transition_id)))


@dataclass(frozen=True)
class PathOutcomeRecord:
    """One (source, family) outcome, with the IDs it was joined on.

    ``id`` is content-addressed over the source, the family, and the snapshot
    pair -- not over the outcome -- so re-deriving the same round's evidence
    lands on the same record and a changed classification is visible as a
    changed field rather than as a new row.
    """

    id: str
    version: str
    source_id: str
    family: CriterionFamilyRef
    outcome: PathOutcome
    evidence: PathOutcomeEvidence

    @classmethod
    def create(cls, evidence: PathOutcomeEvidence) -> "PathOutcomeRecord":
        return cls(
            id=stable_id(
                {
                    "version": PATH_OUTCOME_VERSION,
                    "source_id": evidence.source_id,
                    "criterion_family_id": evidence.family.id,
                    "before_snapshot_id": evidence.before_snapshot_id,
                    "after_snapshot_id": evidence.after_snapshot_id,
                }
            ),
            version=PATH_OUTCOME_VERSION,
            source_id=evidence.source_id,
            family=evidence.family,
            outcome=classify_path_outcome(evidence),
            evidence=evidence,
        )

    @property
    def stage(self) -> int:
        return PATH_OUTCOME_STAGE[self.outcome]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_outcome_id": self.id,
            "path_outcome_version": self.version,
            "path_outcome": self.outcome.value,
            "path_outcome_stage": self.stage,
            "source_id": self.source_id,
            **self.family.to_dict(),
            "episode_id": self.evidence.episode_id,
            "before_criteria_snapshot_id": self.evidence.before_snapshot_id,
            "after_criteria_snapshot_id": self.evidence.after_snapshot_id,
            "control_decision_id": self.evidence.decision_id,
            "control_action_id": self.evidence.action_id,
            "search_task_id": self.evidence.task_id,
            "graph_row_ids": list(self.evidence.graph_row_ids),
            "route_ids": list(self.evidence.route_ids),
            "high_score_route_ids": list(self.evidence.high_score_route_ids),
            "supporting_criterion_ids": list(self.evidence.supporting_criterion_ids),
            "semantic_claim_pairs": [pair.to_dict() for pair in self.evidence.claim_pairs],
        }


class PathOutcomeMemory:
    """Path outcomes across scoring passes, keyed by (source, family).

    The key is two IDs, so the record survives the gap between a source being
    accepted and a criterion it supports passes later.  What is kept per
    key is the **furthest stage** that pair ever reached, and the union of its
    attributable claim pairs; a later pass that reaches no further does not
    erase what an earlier one established, and no pass's contribution is a
    count.
    """

    def __init__(self) -> None:
        self._records: "OrderedDict[tuple[str, str], PathOutcomeRecord]" = OrderedDict()
        self._pairs: dict[tuple[str, str], dict[tuple[str, str], SemanticClaimPair]] = {}

    def observe(self, record: PathOutcomeRecord) -> PathOutcomeRecord:
        """Fold one pass's record in, and return what is now held for its key."""

        key = (record.source_id, record.family.id)
        seen = self._pairs.setdefault(key, {})
        for pair in record.evidence.claim_pairs:
            seen[(pair.criterion_id, pair.transition_id)] = pair
        held = self._records.get(key)
        if held is None or record.stage > held.stage:
            self._records[key] = record
        return self._records[key]

    def observe_evidence(self, evidence: PathOutcomeEvidence) -> PathOutcomeRecord:
        return self.observe(PathOutcomeRecord.create(evidence))

    @property
    def records(self) -> tuple[PathOutcomeRecord, ...]:
        return tuple(self._records.values())

    def claim_pairs(self, source_id: str, family_id: str) -> tuple[SemanticClaimPair, ...]:
        held = self._pairs.get((str(source_id), str(family_id)), {})
        return tuple(sorted(held.values(), key=lambda pair: (pair.criterion_id, pair.transition_id)))

    def for_family(self, family_id: str) -> tuple[PathOutcomeRecord, ...]:
        return tuple(
            record for record in self._records.values() if record.family.id == str(family_id)
        )

    def for_source(self, source_id: str) -> tuple[PathOutcomeRecord, ...]:
        return tuple(
            record for record in self._records.values() if record.source_id == str(source_id)
        )

    def outcome_counts(self) -> dict[str, int]:
        """How many (source, family) pairs sit at each outcome.

        A report, never an input: nothing in this module branches on it, and a
        larger number here is a bigger run rather than a better one.
        """

        counts = {outcome.value: 0 for outcome in PathOutcome}
        for record in self._records.values():
            counts[record.outcome.value] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_outcome_version": PATH_OUTCOME_VERSION,
            "record_count": len(self._records),
            "outcome_counts": self.outcome_counts(),
            "records": [record.to_dict() for record in self._records.values()],
        }


def _transition_payload(transition: Any) -> dict[str, Any]:
    """Read a criterion transition from the object or its serialized form."""

    if isinstance(transition, Mapping):
        kind = transition.get("kind")
        return {
            "id": transition.get("criteria_transition_id") or transition.get("id"),
            "kind": getattr(kind, "value", kind),
            "criterion_id": transition.get("criterion_id"),
            "table": transition.get("table"),
            "field": transition.get("field"),
            "subject_id": transition.get("subject_id"),
            "before_snapshot_id": transition.get("before_criteria_snapshot_id")
            or transition.get("before_snapshot_id"),
            "after_snapshot_id": transition.get("after_criteria_snapshot_id")
            or transition.get("after_snapshot_id"),
            "after_basis": transition.get("after_evidence_basis")
            or transition.get("after_basis"),
            "gained_source_ids": transition.get("gained_source_ids") or (),
        }
    kind = getattr(transition, "kind", None)
    return {
        "id": getattr(transition, "id", ""),
        "kind": getattr(kind, "value", kind),
        "criterion_id": getattr(transition, "criterion_id", ""),
        "table": getattr(transition, "table", ""),
        "field": getattr(transition, "field", ""),
        "subject_id": getattr(transition, "subject_id", ""),
        "before_snapshot_id": getattr(transition, "before_snapshot_id", ""),
        "after_snapshot_id": getattr(transition, "after_snapshot_id", ""),
        "after_basis": getattr(transition, "after_basis", ""),
        "gained_source_ids": getattr(transition, "gained_source_ids", ()) or (),
    }


def _states_by_criterion(snapshot: Any) -> Mapping[str, Any]:
    if snapshot is None:
        return {}
    if isinstance(snapshot, Mapping):
        return snapshot
    by_criterion = getattr(snapshot, "by_criterion", None)
    if callable(by_criterion):
        return dict(by_criterion())
    return {}


# ============================================================================
# strategy_state.py
# ============================================================================

from collections import Counter
from typing import Any, Mapping, Sequence



QUERY_OPERATORS: dict[str, dict[str, Any]] = {
    "catalog_broad_review": {
        "phase": "catalog",
        "source_family": "review table",
        "max_attempts": 3,
        "description": (
            "Find broad sources that enumerate the answer universe or expose "
            "large row families."
        ),
        "constraints": [
            "Prefer review, comparison, benchmark, table, and database wording.",
            "Avoid one narrow anchor unless it can reveal a broader row family.",
        ],
    },
    "catalog_source_shift": {
        "phase": "catalog",
        "source_family": "dataset appendix",
        "max_attempts": 2,
        "description": (
            "Switch discovery away from broad review wording toward other "
            "published source shapes."
        ),
        "constraints": [
            "Try appendix, supplement, dataset, registry, benchmark, or table wording.",
            "Avoid repeating source-title terms that only produced duplicates.",
        ],
    },
    "catalog_terminology_swap": {
        "phase": "catalog",
        "source_family": "terminology_probe",
        "max_attempts": 2,
        "description": (
            "Change the external vocabulary used to find universe-estimating "
            "sources."
        ),
        "constraints": [
            "Use synonyms or neighboring source terminology from accepted sources.",
            "Keep the query broad enough to surface multi-row sources.",
        ],
    },
    "target_batch_family": {
        "phase": "target",
        "source_family": "review table",
        "max_attempts": 3,
        "description": (
            "Find a source likely to fill many sibling rows in the same target "
            "family."
        ),
        "constraints": [
            "Prefer table, review, comparison, supplement, or database wording.",
            "Do not overfit to a single partial row when the deficit is a count shortfall.",
        ],
    },
    "target_exact_anchor": {
        "phase": "target",
        "source_family": "primary_specific",
        "max_attempts": 2,
        "anchor_limit": 3,
        "description": "Use concrete anchors from one partial row to fill its missing fields.",
        "constraints": [
            "Use the strongest external subject/context anchors.",
            "Keep internal column names and workflow phrases out of the query.",
        ],
    },
    "target_anchor_drop": {
        "phase": "target",
        "source_family": "broadened_anchor",
        "max_attempts": 2,
        "anchor_limit": 1,
        "description": (
            "Broaden an over-specific target search by dropping most row anchors."
        ),
        "constraints": [
            "Use at most one row anchor.",
            "Prefer a broader source-family term over a long exact row description.",
        ],
    },
    "target_terminology_swap": {
        "phase": "target",
        "source_family": "terminology_probe",
        "max_attempts": 2,
        "description": (
            "Search the same missing piece with terms learned from failed and "
            "successful attempts."
        ),
        "constraints": [
            "Avoid repeating failed query terms when a substitute is available.",
            "Use terms learned from accepted evidence and prior query outcomes.",
        ],
    },
    "target_source_shift": {
        "phase": "target",
        "source_family": "dataset appendix",
        "max_attempts": 2,
        "description": (
            "Keep the same missing piece but change the expected source shape."
        ),
        "constraints": [
            "Try supplement, appendix, dataset, table, benchmark, or report wording.",
            "Avoid source neighborhoods that only produced duplicates.",
        ],
    },
    "target_context_pivot": {
        "phase": "target",
        "source_family": "stratified table",
        "max_attempts": 2,
        "description": (
            "Search the same row family using alternate source terms for "
            "the target's row qualifiers and key columns."
        ),
        "query_terms": [
            "stratified",
            "table",
        ],
        "constraints": [
            "Vary terms for the row qualifiers instead of assuming one wording.",
            "Prefer sources that split estimates by the target key columns.",
        ],
    },
}

_CATALOG_DEFAULT_ORDER = (
    "catalog_broad_review",
    "catalog_source_shift",
    "catalog_terminology_swap",
)
_CATALOG_PRODUCTIVE_FAILURES = (
    "useful_catalog_delta",
    "useful_table_delta",
)
_TARGET_PRODUCTIVE_FAILURES = ("useful_table_delta",)
_TARGET_COUNT_ORDER = (
    "target_batch_family",
    "target_source_shift",
    "target_terminology_swap",
    "target_anchor_drop",
    "target_exact_anchor",
)
_TARGET_ROW_ORDER = (
    "target_exact_anchor",
    "target_anchor_drop",
    "target_terminology_swap",
    "target_source_shift",
    "target_batch_family",
)
_CONTEXT_RECOVERY_FAILURES = {
    "accepted_no_graph_delta",
    "all_duplicates",
    "graph_delta_no_table_delta",
    "no_accepted_source",
    "no_hits",
    "source_unusable",
}
_FAILURE_ROUTES = {
    "useful_table_delta": (
        "same",
        "target_batch_family",
        "target_exact_anchor",
        "target_source_shift",
    ),
    "accepted_no_graph_delta": (
        "target_source_shift",
        "target_terminology_swap",
        "target_anchor_drop",
    ),
    "graph_delta_no_table_delta": (
        "target_batch_family",
        "target_anchor_drop",
        "target_source_shift",
    ),
    "all_duplicates": (
        "target_source_shift",
        "target_terminology_swap",
        "target_batch_family",
    ),
    "source_unusable": (
        "target_source_shift",
        "target_terminology_swap",
        "target_anchor_drop",
    ),
    "no_hits": (
        "target_anchor_drop",
        "target_terminology_swap",
        "target_batch_family",
    ),
    "search_error": (
        "same",
        "target_terminology_swap",
        "target_source_shift",
    ),
    "no_accepted_source": (
        "target_terminology_swap",
        "target_source_shift",
        "target_anchor_drop",
    ),
}
_CATALOG_FAILURE_ROUTES = {
    "useful_catalog_delta": ("same", "catalog_source_shift", "catalog_terminology_swap"),
    "useful_table_delta": ("same", "catalog_source_shift", "catalog_terminology_swap"),
    "accepted_no_catalog_delta": ("catalog_source_shift", "catalog_terminology_swap"),
    "accepted_no_graph_delta": (
        "catalog_source_shift",
        "catalog_terminology_swap",
    ),
    "graph_delta_no_table_delta": (
        "catalog_source_shift",
        "catalog_terminology_swap",
    ),
    "all_duplicates": ("catalog_source_shift", "catalog_terminology_swap"),
    "no_hits": ("catalog_terminology_swap", "catalog_source_shift"),
    "source_unusable": ("catalog_source_shift", "catalog_terminology_swap"),
    "search_error": ("same", "catalog_terminology_swap"),
    "no_accepted_source": ("catalog_terminology_swap", "catalog_source_shift"),
}


#: Which operators a path outcome argues for next, per
#: ``docs/TABLE_FILL_PATH_SELECTION.md`` §4.  Each outcome names a *different*
#: deficiency -- the source family was wrong, the terminology was too indirect,
#: the subject anchor was too broad, or the evidence arrived and its provenance
#: did not -- and that is the whole reason the five are worth distinguishing.
#:
#: **Nothing branches on this in phase 2C.**  Path outcomes are recorded, not
#: routed; routing them into the operator plan is a later phase's decision and
#: needs its own experiment.  The mapping lives here, beside the operators it
#: names, so that phase inherits a typed table rather than re-deriving one from
#: the prose of a document.  Every value is a key of :data:`QUERY_OPERATORS`.
PATH_OUTCOME_NEXT_OPERATORS: Mapping[PathOutcome, tuple[str, ...]] = {
    # Nothing in the graph cites the source: look in other source families.
    PathOutcome.NO_GRAPH_EVIDENCE: (
        "target_source_shift",
        "target_batch_family",
    ),
    # The graph has it and no route carried it: ask more directly.
    PathOutcome.ROUTES_ALL_LOW_SCORE: (
        "target_terminology_swap",
        "target_source_shift",
    ),
    # Routes arrived and the field stayed empty: narrow the subject anchor.
    PathOutcome.NO_CANDIDATE_EVIDENCE: (
        "target_exact_anchor",
        "target_context_pivot",
    ),
    # A value is there and nothing became supported: the gap is provenance or
    # normalisation, so keep the source context rather than searching wider.
    PathOutcome.CANDIDATE_WITHOUT_TRANSITION: (
        "target_context_pivot",
        "target_exact_anchor",
    ),
    # It worked.  Keep doing it.
    PathOutcome.SUPPORT_GAINED_ATTRIBUTED: (
        "target_batch_family",
        "target_exact_anchor",
    ),
}


def next_operators_for_path_outcome(outcome: PathOutcome) -> tuple[str, ...]:
    """The operators a recorded path outcome argues for, as identifiers.

    A lookup, not a decision: it selects nothing and changes no plan.  See
    :data:`PATH_OUTCOME_NEXT_OPERATORS`.
    """

    return PATH_OUTCOME_NEXT_OPERATORS[PathOutcome(outcome)]


# ---------------------------------------------------------------------------
# Phase 3B -- routing the next mutation family from nested arm contrast
# ---------------------------------------------------------------------------
#
# `plan_target_operator` above routes on `classify_attempt_failure`, which
# reads post-Episode row/best-guess *counts* -- operational volume.  The
# functions below route the same decision (which named family the next
# evolution step should instantiate) from real per-arm semantic yield
# instead: `search_memory._finalize_prompt_arm`'s `arm_contrast`, itself
# joined by ID from 3A's `reward.score_criterion_yield`.  Everything here is a
# pure function over that typed contrast -- no query string is assumed to
# exist, and nothing is inferred from prose.  Surface-agnostic by
# construction: the same shape (named arms, a score, a duplicate/cost
# breakdown, an outcome class) would serve a catalog probe or a schema-
# synthesis arm exactly as it serves search.


#: Version of the **routing** exhaustion rule.
#:
#: ``arm_routing_v1`` keyed "was this family productive?" on
#: :data:`_TARGET_PRODUCTIVE_FAILURES`, i.e. on
#: ``classify_attempt_failure``'s ``useful_table_delta`` -- which fires on
#: ``post_episode_table_row_hits``, ``post_episode_best_guess_hits``, or
#: ``post_episode_observed_delta``.  All three are operational volume; none is
#: a credited criterion transition.  The consequence was that a family which
#: credited real criteria but materialized no rows was classed
#: non-productive, counted toward exhaustion, and routed away from, while a
#: family that materialized rows and credited nothing was kept alive and
#: exploited -- volume deciding the deliverable's own exploitation decision
#: through a path other than the criteria transition.
#:
#: ``arm_routing_v2`` keys it on credited yield instead
#: (:func:`_credited_yield_productive`).  ``classify_attempt_failure`` is
#: deliberately **not** changed: it is baseline behaviour used elsewhere, and
#: ``useful_table_delta`` remains exactly what it was for diagnostics.  Only
#: what *routing* treats as productive moved.
ARM_ROUTING_RULE_VERSION = "arm_routing_v2"


def _credited_yield_productive(attempt: Mapping[str, Any]) -> bool:
    """Whether an attempt was productive **for routing purposes**.

    Real semantic yield only: did this attempt's sources credit a criterion
    transition, per 3A's ``reward.score_criterion_yield`` joined back by ID
    (``post_episode_credited_criterion_ids``).  Rows materialized, best-guess
    hits, and observed-count deltas are operational volume and are ignored
    here however large they are.

    ``None`` -- yield not yet measured -- is **not** productivity.  An
    unmeasured attempt cannot be evidence that a family is working, so it
    does not keep that family alive past its attempt budget.  This resolves
    conservatively toward abandoning a family rather than pinning routing to
    one whose value is unknown.
    """

    credited = attempt.get("post_episode_credited_criterion_ids")
    if credited is None:
        return False
    return len(credited) > 0


def route_next_family(
    target: Mapping[str, Any],
    *,
    catalog: Mapping[str, Mapping[str, Any]] = QUERY_OPERATORS,
) -> dict[str, Any]:
    """Choose the next mutation family for one target deficit.

    ``target`` is an enriched deficit carrying ``strategy_memory`` (compact
    per-target memory records, each with ``attempts`` -- finalized strategy
    attempts, each carrying ``arm_contrast`` and ``strategy_operator``; see
    ``search_memory._finalize_strategy_attempt``).

    Returns the same shape :func:`plan_target_operator` does (``operator``,
    ``phase``, ``source_family``, ``description``, ``constraints``, attempt
    bookkeeping) plus ``routing_reason`` and the
    ``arm_contrast`` the decision was read from, so a reader can verify the
    decision without re-deriving it.
    """
    attempts = _target_attempts(target)
    # The default order is a *preference over the catalog*, not a source of
    # operator names. Its built-in entries are the shipped QUERY_OPERATORS
    # keys, so an injected catalog (another surface's operators) shares none
    # of them; filtering here is what stops the injection being discarded at
    # every later step that consults the order. With the default catalog this
    # is an identity -- every built-in order entry is a QUERY_OPERATORS key.
    default_order = tuple(
        name for name in _default_target_order(target) if name in catalog
    ) or tuple(catalog)
    latest_attempt = _latest_strategy_attempt(target)
    contrast = list((latest_attempt or {}).get("arm_contrast") or [])
    previous_operator = str((latest_attempt or {}).get("strategy_operator") or "")

    chosen, reason = _route_from_contrast(
        contrast,
        default_order,
        previous_operator=previous_operator,
        catalog=catalog,
    )

    if chosen not in catalog or _operator_exhausted(
        chosen,
        attempts,
        productive_failures=_TARGET_PRODUCTIVE_FAILURES,
        catalog=catalog,
        productive_predicate=_credited_yield_productive,
    ):
        chosen = (
            _first_available(
                default_order,
                attempts,
                productive_failures=_TARGET_PRODUCTIVE_FAILURES,
                catalog=catalog,
                productive_predicate=_credited_yield_productive,
            )
            or chosen
        )

    plan = _operator_plan(
        chosen,
        attempts,
        reason,
        phase="target",
        operators=default_order,
        productive_failures=_TARGET_PRODUCTIVE_FAILURES,
        context_tags=_target_context_tags(target),
        catalog=catalog,
        productive_predicate=_credited_yield_productive,
    )
    plan["arm_routing_rule_version"] = ARM_ROUTING_RULE_VERSION
    plan["routing_reason"] = reason
    plan["arm_contrast"] = contrast
    return plan


def _route_from_contrast(
    contrast: Sequence[Mapping[str, Any]],
    default_order: tuple[str, ...],
    *,
    previous_operator: str,
    catalog: Mapping[str, Mapping[str, Any]] = QUERY_OPERATORS,
) -> tuple[str, str]:
    """The deterministic decision made from nested arm contrast.

    Reads the nested per-arm rows directly -- never an aggregate over them.
    Each branch below corresponds to one of the pseudo-gradient's named
    classes (`search_memory._prompt_arm_outcome`): a real winner is exploited
    by repeating its family; duplicate-dominant contrast routes away from the
    family that produced it; sources found but nothing
    supported routes to a narrower, provenance-preserving family rather than
    a broader one; unmeasured contrast (mid-round, yield not landed yet)
    holds the current family rather than switching blind.
    """

    if not contrast:
        return (
            default_order[0] if default_order else "target_batch_family"
        ), "new_target"

    best = contrast[0]
    outcomes: Counter = Counter(str(row.get("outcome") or "") for row in contrast)
    n = len(contrast)

    if best.get("score") is not None and _strategy_as_int(best.get("credited_criterion_count")) > 0:
        family = (
            previous_operator
            if previous_operator in catalog
            else (default_order[0] if default_order else "target_batch_family")
        )
        return family, "credited_yield"

    if outcomes.get("sibling_duplicate", 0) + outcomes.get("all_duplicates", 0) > n / 2:
        return (
            _named_family("target_source_shift", default_order, catalog),
            "duplicate_dominant",
        )

    if outcomes.get("no_hits", 0) > n / 2:
        return (
            _named_family("target_anchor_drop", default_order, catalog),
            "no_hits_dominant",
        )

    if outcomes.get("accepted_no_yield", 0) > 0:
        return (
            _named_family("target_context_pivot", default_order, catalog),
            "accepted_no_yield",
        )

    if previous_operator in catalog:
        return previous_operator, "pending_yield"
    return (default_order[0] if default_order else "target_batch_family"), "pending_yield"


def _named_family(
    named: str,
    order: tuple[str, ...],
    catalog: Mapping[str, Mapping[str, Any]],
) -> str:
    """The family this contrast class actually argues for.

    **This is the routing decision.**  Each branch of
    :func:`_route_from_contrast` names one destination -- broaden the source
    shape when siblings duplicated, drop anchors when nothing was found, pivot
    context when sources
    landed but supported nothing -- and that named family is what gets
    returned whenever the catalog has it.

    The predecessor of this function took the named family as a *last-resort*
    third argument, after a loop over ``order`` that always returned early on
    any non-degenerate order.  The named family was therefore unreachable and
    all contrast classes collapsed onto one operator, which made contrast
    condition ``routing_reason`` and nothing else.  Found by review after the
    run; see ``experiments/log/3B.md`` -- Route 1's original result is void.

    Falling back to ``order`` happens only when the named family is not in the
    catalog at all.  The *exhausted* case is handled by
    :func:`route_next_family`'s own guard, which runs after this returns and
    re-selects from ``order`` when the named family has spent its attempts --
    so a family that keeps failing is still abandoned, without this function
    having to know about attempt history.

    Reads only closed-vocabulary operator identifiers.  No LLM prose --
    ``expected_source_shape``, ``prompt_delta``, ``prompt_hypothesis`` -- ever
    reaches a routing predicate.
    """

    if named in catalog:
        return named
    for name in order:
        if name in catalog:
            return name
    return named


def _latest_strategy_attempt(target: Mapping[str, Any]) -> Mapping[str, Any] | None:
    attempts: list[Mapping[str, Any]] = []
    for record in target.get("strategy_memory") or []:
        if not isinstance(record, Mapping):
            continue
        for attempt in record.get("attempts") or []:
            if isinstance(attempt, Mapping) and attempt.get("prompt_arms"):
                attempts.append(attempt)
    if not attempts:
        return None
    # ``sequence`` is the memory build's own arrival order; ``evolution_index``
    # is monotone per target. Between them the newest attempt is identified
    # without any global round number, and the enumerate index keeps the max
    # stable when both are absent on legacy records.
    return max(
        enumerate(attempts),
        key=lambda item: (
            _strategy_as_int(item[1].get("sequence")),
            _strategy_as_int(item[1].get("evolution_index")),
            item[0],
        ),
    )[1]


def plan_catalog_operator(outcomes: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Choose the next catalog-search operator from prior catalog outcomes."""
    attempts = _catalog_attempts_from_outcomes(outcomes)
    latest = attempts[-1] if attempts else {}
    failure = classify_attempt_failure(latest) if latest else "new_target"
    order = _catalog_order(failure, latest)
    operator = _first_available(
        order,
        attempts,
        productive_failures=_CATALOG_PRODUCTIVE_FAILURES,
    )
    return _operator_plan(
        operator,
        attempts,
        failure,
        phase="catalog",
        operators=_CATALOG_DEFAULT_ORDER,
        productive_failures=_CATALOG_PRODUCTIVE_FAILURES,
    )


def plan_target_operator(target: Mapping[str, Any]) -> dict[str, Any]:
    """Choose the next concrete search operator for one fill deficit."""
    attempts = _target_attempts(target)
    latest = attempts[-1] if attempts else {}
    failure = classify_attempt_failure(latest) if latest else "new_target"
    order = _target_order(target, failure, latest)
    default_order = _default_target_order(target)
    operator = _first_available(
        order,
        attempts,
        productive_failures=_TARGET_PRODUCTIVE_FAILURES,
    )
    context_tags = _target_context_tags(target)
    return _operator_plan(
        operator,
        attempts,
        failure,
        phase="target",
        operators=default_order,
        productive_failures=_TARGET_PRODUCTIVE_FAILURES,
        context_tags=context_tags,
    )


def fallback_query_for_operator(target: Mapping[str, Any]) -> str:
    """Build a deterministic generic fallback query for the selected operator."""
    plan = _strategy_mapping(target.get("operator_plan"))
    operator = str(plan.get("operator") or "target_batch_family")
    spec = QUERY_OPERATORS.get(operator, QUERY_OPERATORS["target_batch_family"])
    source_terms = [
        *str(spec.get("source_family") or "").replace("_", " ").split(),
        *[
            _search_text(term)
            for term in spec.get("query_terms") or []
            if _search_text(term)
        ],
    ]

    examples = [
        _search_text(example)
        for example in list(target.get("known_missing_examples") or [])[:3]
        if _search_text(example)
    ]
    anchor_limit = int(spec.get("anchor_limit") or 0)
    anchors = [
        _search_text(value)
        for value in _strategy_mapping(target.get("anchor_values")).values()
        if _search_text(value)
    ][:anchor_limit]
    memory_terms = _memory_terms(target)
    field_terms = _field_terms(target, limit=4)

    cold_start = str(target.get("deficit_type") or "") == "schema_cold_start"
    candidates = [
        # A cold-start anchor identifies whose rows to acquire; it does not say
        # which missing value the source must carry.  Keep one declared field
        # beside the anchor so `Haiti` becomes `Haiti GDP per capita ...`
        # rather than a broad search for the key alone.  Other deficit types
        # retain their established fallback shape.
        [
            *anchors,
            *(field_terms[:1] if cold_start else []),
            *examples[:1],
            *source_terms[:2],
            *memory_terms[:2],
        ],
        [*examples[:2], *source_terms[:3], *memory_terms[:3]],
        [*memory_terms[:4], *source_terms[:2]],
        [*anchors, *memory_terms[:3], *source_terms[:2]],
        # Field-name candidates come last so a deficit that already had
        # anchors, examples or memory keeps producing exactly the query it
        # produced before. They are reached only by a deficit whose entire
        # payload is the list of empty columns -- which previously fell off
        # the end of this loop and returned "".
        [*field_terms[:1], *source_terms[:3]],
        [*field_terms[:3], *source_terms[:2]],
    ]
    attempted = {
        str(attempt.get("query") or "").strip().lower()
        for attempt in target.get("strategy_history") or []
        if isinstance(attempt, Mapping)
    }
    for parts in candidates:
        if not any(
            part in parts
            for part in (*anchors, *examples, *memory_terms, *field_terms)
        ):
            continue
        query = _dedupe_words(parts)
        if query and query.lower() not in attempted:
            return query
    return ""


def classify_attempt_failure(attempt: Mapping[str, Any]) -> str:
    """Classify one attempt using search yield and post-Episode table delta."""
    if not attempt:
        return "new_target"
    if (
        _strategy_as_int(attempt.get("post_episode_table_row_hits")) > 0
        or _strategy_as_int(attempt.get("post_episode_best_guess_hits")) > 0
    ):
        return "useful_table_delta"
    table_delta = _strategy_as_int(attempt.get("post_episode_observed_delta"))
    if table_delta > 0:
        return "useful_table_delta"

    if str(attempt.get("error") or "").strip():
        return "search_error"

    accepted = _strategy_as_int(attempt.get("accepted_source_count"))
    catalog_delta = attempt.get("post_catalog_progress_delta")
    if catalog_delta is not None:
        if _strategy_as_int(catalog_delta) > 0:
            return "useful_catalog_delta"
        if accepted > 0:
            return "accepted_no_catalog_delta"

    if accepted > 0:
        graph_delta = _strategy_as_int(attempt.get("post_episode_graph_node_delta"))
        graph_delta += _strategy_as_int(attempt.get("post_episode_graph_edge_delta"))
        if graph_delta <= 0:
            return "accepted_no_graph_delta"
        return "graph_delta_no_table_delta"

    firecrawl_hits = _strategy_as_int(attempt.get("firecrawl_hits"))
    if firecrawl_hits <= 0:
        return "no_hits"

    skipped = _strategy_mapping(attempt.get("skipped_by_reason"))
    duplicate_count = _strategy_as_int(attempt.get("duplicate_url_count")) + _strategy_as_int(
        skipped.get("duplicate_url")
    )
    if duplicate_count >= firecrawl_hits:
        return "all_duplicates"
    if any(
        _strategy_as_int(skipped.get(reason)) > 0
        for reason in (
            "blocked_page",
            "blocked_scrape",
            "scrape_failed",
            "too_large",
            "too_short",
        )
    ):
        return "source_unusable"
    return "no_accepted_source"


def _catalog_order(failure: str, latest: Mapping[str, Any]) -> tuple[str, ...]:
    routed = _CATALOG_FAILURE_ROUTES.get(failure, ())
    previous = str(latest.get("strategy_operator") or "")
    return _expand_same(routed, previous) + _CATALOG_DEFAULT_ORDER


def _target_order(
    target: Mapping[str, Any],
    failure: str,
    latest: Mapping[str, Any],
) -> tuple[str, ...]:
    routed = _FAILURE_ROUTES.get(failure, ())
    previous = str(
        latest.get("strategy_operator")
        or latest.get("strategy_family")
        or ""
    )
    if failure in _CONTEXT_RECOVERY_FAILURES:
        routed = (*_target_context_order(target), *routed)
    return _dedupe_order(_expand_same(routed, previous) + _default_target_order(target))


def _default_target_order(target: Mapping[str, Any]) -> tuple[str, ...]:
    context_order = _target_context_order(target)
    if str(target.get("deficit_type") or "") in {
        "count_shortfall",
        "table_gap_saturation",
    }:
        return _dedupe_order(
            (_TARGET_COUNT_ORDER[0], *context_order, *_TARGET_COUNT_ORDER[1:]),
        )
    return _dedupe_order(
        (*_TARGET_ROW_ORDER[:2], *context_order, *_TARGET_ROW_ORDER[2:]),
    )


def _expand_same(order: tuple[str, ...], previous: str) -> tuple[str, ...]:
    if not previous:
        return tuple(value for value in order if value != "same")
    return tuple(previous if value == "same" else value for value in order)


def _first_available(
    order: tuple[str, ...],
    attempts: list[dict[str, Any]],
    *,
    productive_failures: tuple[str, ...],
    catalog: Mapping[str, Mapping[str, Any]] = QUERY_OPERATORS,
    productive_predicate: Any = None,
) -> str:
    for operator in order:
        if operator in catalog and not _operator_exhausted(
            operator,
            attempts,
            productive_failures=productive_failures,
            catalog=catalog,
            productive_predicate=productive_predicate,
        ):
            return operator
    return ""


def _operator_exhausted(
    operator: str,
    attempts: list[dict[str, Any]],
    *,
    productive_failures: tuple[str, ...],
    catalog: Mapping[str, Mapping[str, Any]] = QUERY_OPERATORS,
    productive_predicate: Any = None,
) -> bool:
    """Whether ``operator`` has spent its attempts without being productive.

    ``productive_predicate`` decides what "productive" means.  Routing passes
    :func:`_credited_yield_productive` (real credited yield); legacy callers
    pass nothing and keep ``classify_attempt_failure`` against
    ``productive_failures``, which is volume-based and deliberately
    unchanged for them.  See :data:`ARM_ROUTING_RULE_VERSION`.
    """

    spec = catalog[operator]
    max_attempts = int(spec.get("max_attempts") or 1)
    matching = [
        attempt
        for attempt in attempts
        if _strategy_operator_name(attempt) == operator
    ]
    if len(matching) < max_attempts:
        return False
    latest = matching[-1] if matching else {}
    if productive_predicate is not None:
        return not productive_predicate(latest)
    return classify_attempt_failure(latest) not in set(productive_failures)


def _operator_plan(
    operator: str,
    attempts: list[dict[str, Any]],
    failure: str,
    *,
    phase: str,
    operators: tuple[str, ...],
    productive_failures: tuple[str, ...],
    context_tags: tuple[str, ...] = (),
    catalog: Mapping[str, Mapping[str, Any]] = QUERY_OPERATORS,
    productive_predicate: Any = None,
) -> dict[str, Any]:
    spec = dict(catalog.get(operator) or {})
    counts = Counter(
        _strategy_operator_name(attempt) or str(attempt.get("strategy_family") or "")
        for attempt in attempts
    )
    counts.pop("", None)
    # `operators` is the default order, whose names need not all exist in an
    # injected catalog -- `_operator_exhausted` indexes the catalog directly,
    # so unknown names are filtered out rather than raising.
    exhausted = [
        name
        for name in operators
        if name in catalog
        and _operator_exhausted(
            name,
            attempts,
            productive_failures=productive_failures,
            catalog=catalog,
            productive_predicate=productive_predicate,
        )
    ]
    return {
        "operator": operator,
        "phase": spec.get("phase", phase),
        "source_family": spec.get("source_family", ""),
        "description": spec.get("description", ""),
        "constraints": list(spec.get("constraints") or []),
        "last_failure_class": failure,
        "attempt_index": counts.get(operator, 0) + 1 if operator else 0,
        "attempted_operator_counts": dict(counts),
        "context_tags": list(context_tags),
        "exhausted": not bool(operator),
        "exhausted_operators": exhausted,
    }


def _target_context_order(target: Mapping[str, Any]) -> tuple[str, ...]:
    tags = set(_target_context_tags(target))
    if "context_pivot" in tags:
        return ("target_context_pivot",)
    return ()


def _target_context_tags(target: Mapping[str, Any]) -> tuple[str, ...]:
    if (
        target.get("key_columns")
        or target.get("missing_fields")
        or _strategy_mapping(target.get("anchor_values"))
    ):
        return ("context_pivot",)
    return ()


def _dedupe_order(order: tuple[str, ...]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in order:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def _catalog_attempts_from_outcomes(
    outcomes: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    current_key: tuple[str, Any] | None = None

    for outcome in outcomes:
        if outcome.get("topic") != "goal_catalog":
            continue
        attempt = _attempt_from_outcome(outcome)
        operator = _strategy_operator_name(attempt)
        if not operator:
            continue

        operator_attempt = attempt.get("operator_attempt")
        if operator_attempt:
            key: tuple[str, Any] = (operator, operator_attempt)
        elif current_key and current_key[0] == operator:
            key = current_key
        else:
            key = (operator, len(attempts) + 1)

        if key != current_key:
            if current:
                attempts.append(_finalize_catalog_attempt(current))
            current = {
                "strategy_operator": operator,
                "strategy_family": attempt.get("strategy_family", ""),
                "source_family": attempt.get("source_family", ""),
                "operator_attempt": operator_attempt,
                "queries": [],
                "firecrawl_hits": 0,
                "accepted_source_count": 0,
                "duplicate_url_count": 0,
                "skipped_by_reason": Counter(),
                "outcome_count": 0,
                "error_count": 0,
                "errors": [],
            }
            current_key = key

        _merge_catalog_attempt(current, attempt)

    if current:
        attempts.append(_finalize_catalog_attempt(current))
    return attempts


def _merge_catalog_attempt(
    aggregate: dict[str, Any],
    attempt: Mapping[str, Any],
) -> None:
    query = str(attempt.get("query") or "")
    if query:
        aggregate["queries"].append(query)
        aggregate["query"] = query
    aggregate["firecrawl_hits"] += _strategy_as_int(attempt.get("firecrawl_hits"))
    aggregate["accepted_source_count"] += _strategy_as_int(
        attempt.get("accepted_source_count")
    )
    aggregate["duplicate_url_count"] += _strategy_as_int(attempt.get("duplicate_url_count"))
    aggregate["skipped_by_reason"].update(_strategy_mapping(attempt.get("skipped_by_reason")))
    aggregate["outcome_count"] += 1
    for field_name in (
        "baseline_catalog_status",
        "baseline_catalog_count_target_count",
        "baseline_catalog_unestimated_count",
        "baseline_catalog_target_family_count",
        "post_catalog_status",
        "post_catalog_count_target_count",
        "post_catalog_unestimated_count",
        "post_catalog_target_family_count",
        "post_catalog_status_delta",
        "post_catalog_count_target_delta",
        "post_catalog_unestimated_delta",
        "post_catalog_target_family_delta",
        "post_catalog_progress_delta",
    ):
        value = attempt.get(field_name)
        if value is not None:
            aggregate[field_name] = value
    error = str(attempt.get("error") or "")
    if error:
        aggregate["error_count"] += 1
        aggregate["errors"].append(error)


def _finalize_catalog_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    skipped = Counter(attempt.get("skipped_by_reason") or {})
    finalized = {
        **attempt,
        "query_count": len(attempt.get("queries") or []),
        "skipped_by_reason": dict(skipped),
        "duplicate_url_count": _strategy_as_int(attempt.get("duplicate_url_count")),
    }
    if _strategy_as_int(attempt.get("error_count")) < _strategy_as_int(attempt.get("outcome_count")):
        finalized["error"] = ""
    else:
        finalized["error"] = "; ".join(attempt.get("errors") or [])[:500]
    return finalized


def _target_attempts(target: Mapping[str, Any]) -> list[dict[str, Any]]:
    attempts = [
        dict(attempt)
        for attempt in target.get("strategy_history") or []
        if isinstance(attempt, Mapping)
    ]
    return sorted(
        attempts,
        key=lambda attempt: (
            _strategy_as_int(attempt.get("sequence")),
            _strategy_as_int(attempt.get("evolution_index")),
            _strategy_as_int(attempt.get("prompt_arm_index")),
            _strategy_as_int(attempt.get("operator_attempt")),
            str(attempt.get("strategy_attempt_id") or attempt.get("query") or ""),
        ),
    )


def _attempt_from_outcome(outcome: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _strategy_mapping(outcome.get("metadata"))
    return {
        "episode_id": outcome.get("episode_id"),
        "query": outcome.get("query"),
        "strategy_operator": metadata.get("strategy_operator", ""),
        "strategy_family": metadata.get("strategy_family", ""),
        "source_family": metadata.get("source_family", ""),
        "operator_attempt": metadata.get("operator_attempt"),
        "firecrawl_hits": outcome.get("firecrawl_hits"),
        "accepted_source_count": len(outcome.get("accepted_source_ids") or []),
        "duplicate_url_count": len(outcome.get("duplicate_urls") or []),
        "skipped_by_reason": dict(outcome.get("skipped_by_reason") or {}),
        "post_episode_observed_delta": metadata.get("post_episode_observed_delta"),
        "post_episode_graph_node_delta": metadata.get("post_episode_graph_node_delta"),
        "post_episode_graph_edge_delta": metadata.get("post_episode_graph_edge_delta"),
        "post_episode_table_row_hits": metadata.get("post_episode_table_row_hits"),
        "post_episode_best_guess_hits": metadata.get("post_episode_best_guess_hits"),
        "baseline_catalog_status": metadata.get("baseline_catalog_status"),
        "baseline_catalog_count_target_count": metadata.get(
            "baseline_catalog_count_target_count",
        ),
        "baseline_catalog_unestimated_count": metadata.get(
            "baseline_catalog_unestimated_count",
        ),
        "baseline_catalog_target_family_count": metadata.get(
            "baseline_catalog_target_family_count",
        ),
        "post_catalog_status": metadata.get("post_catalog_status"),
        "post_catalog_count_target_count": metadata.get(
            "post_catalog_count_target_count",
        ),
        "post_catalog_unestimated_count": metadata.get(
            "post_catalog_unestimated_count",
        ),
        "post_catalog_target_family_count": metadata.get(
            "post_catalog_target_family_count",
        ),
        "post_catalog_status_delta": metadata.get("post_catalog_status_delta"),
        "post_catalog_count_target_delta": metadata.get(
            "post_catalog_count_target_delta",
        ),
        "post_catalog_unestimated_delta": metadata.get(
            "post_catalog_unestimated_delta",
        ),
        "post_catalog_target_family_delta": metadata.get(
            "post_catalog_target_family_delta",
        ),
        "post_catalog_progress_delta": metadata.get("post_catalog_progress_delta"),
        "error": outcome.get("error", ""),
    }


def _strategy_operator_name(attempt: Mapping[str, Any]) -> str:
    return str(
        attempt.get("strategy_operator")
        or attempt.get("operator")
        or attempt.get("strategy_family")
        or ""
    )


def _memory_terms(target: Mapping[str, Any]) -> list[str]:
    terms: list[str] = []
    for memory in target.get("strategy_memory") or []:
        if not isinstance(memory, Mapping):
            continue
        for field_name in ("successful_query_terms",):
            for value in memory.get(field_name) or []:
                text = _search_text(value)
                if text:
                    terms.append(text)
    return terms


#: Longest suffix, in tokens, that still reads as a structural tag on a base
#: column name rather than as a distinct column of its own.
_SIDECAR_SUFFIX_TOKENS = 2


def _field_terms(target: Mapping[str, Any], *, limit: int) -> list[str]:
    """Search terms taken from the field names a deficit reports as empty.

    For a deficit whose subject is a table's empty columns, these names are the
    entire payload: it carries no anchor values, no known examples and no
    search memory, because nothing has been retrieved for it yet. Without them
    the deterministic fallback has nothing target-specific to say and returns
    the empty string, so the one deficit type that names missing columns could
    never express a query at all -- the columns stayed empty because nothing
    ever searched for them.

    Derived variants are dropped in favour of the name they extend. Rows carry
    sidecar columns built by suffixing a base column name, and a suffix like
    that is run plumbing rather than anything an external source calls its
    data. The test is purely structural -- one normalized name extending
    another present in the same set by no more than a couple of tokens -- so it
    assumes no vocabulary and stays correct for any question or domain.

    The token limit is what keeps the rule from eating real columns. A sidecar
    appends a short structural tag; a genuinely different column appends a
    qualifying phrase. Without the limit, a table carrying both a bare measure
    and the same measure qualified by a year would lose the qualified one --
    silently discarding the more specific column of the pair.
    """

    fields = [
        text
        for text in (str(field or "").strip() for field in target.get("missing_fields") or [])
        if text
    ]
    normalized = {field: _search_text(field).lower().replace(" ", "-") for field in fields}
    bases = set(normalized.values())

    terms: list[str] = []
    for field in fields:
        key = normalized[field]
        if not key:
            continue
        if any(
            key.startswith(f"{other}-")
            and len(key[len(other) + 1 :].split("-")) <= _SIDECAR_SUFFIX_TOKENS
            for other in bases
            if other != key
        ):
            continue
        text = _search_text(field)
        if text and text not in terms:
            terms.append(text)
        if len(terms) >= limit:
            break
    return terms


def _dedupe_words(parts: list[str], *, limit: int = 10) -> str:
    seen: set[str] = set()
    words: list[str] = []
    for part in parts:
        for word in str(part or "").split():
            normalized = word.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            words.append(word)
            if len(words) >= limit:
                return " ".join(words)
    return " ".join(words)


def _search_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        value = " ".join(str(inner) for inner in value.values() if inner is not None)
    elif isinstance(value, (list, tuple, set)):
        value = " ".join(str(inner) for inner in value if inner is not None)
    return " ".join(str(value).replace("_", " ").replace("-", " ").split())


def _strategy_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _strategy_as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


# ============================================================================
# estimator.py
# ============================================================================

import hashlib
import json
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from question_pipeline.utilities.tables import result_count_bucket
from question_pipeline.utilities.model import ask_json

# `estimator-evidence` is gone with the count. That call asked a model whether
# a document was "count-bearing", which was only a question because a count was
# being produced. Nothing downstream asks it now, so the call site is retired
# rather than repurposed: a provider call with no stated question is a cost
# with no claim attached to it.

# `estimator-synthesis` is gone: no model produces the numeric universe
# estimate any more. 0M measured that call site at 0.322 agreement, which was
# read as "needs a reasoning model" when it should have been read as "this is
# not a job for a model at all."


EstimatorSearchFn = Callable[[str, int], list[dict[str, Any]]]


#: The system prompt carries the role framing, so it has to say the same thing
#: the user prompt says. It previously read "design external searches that
#: measure how many final-table data points exist" and told the model to reason
#: from "prior estimate state" -- the retired question, surviving in the other
#: argument to the same provider call while the user prompt asked for breadth.
#: Two contradictory instructions in one call, and the sweep missed it because
#: `system_prompt` is a separate argument that a check over the prompt body
#: never sees.
_PLANNER_SYSTEM_PROMPT = """You are a search-space breadth planner for an
iterative table-aggregation run. Your job is to design external searches that
reach parts of the search space earlier probes did not reach, so the breadth of
the space can be observed. You do not estimate how many rows or data points
exist, and no count is derived from what you return. Reason from the user's
question, declared tables, current row samples, and previous search
observations. Return only valid JSON."""

# The synthesis and critique prompts that used to live here are deleted, not
# disabled. They asked a model to emit `expected_count` bands from prose.
# Chao1 replaced them with arithmetic, and Chao1 is now deleted too: no count
# is produced here by any route, asked or computed. Families are reported as
# unestimated with a reason. There is no prompt to fall back to and no
# estimator to fall back to either.


async def estimate_count_expectations(
    llm,
    question: str,
    *,
    goal_context: Mapping[str, Any],
    completion_state: Mapping[str, Any],
    previous_estimate: Mapping[str, Any],
    search_fn: EstimatorSearchFn,
    max_iterations: int,
    queries_per_iteration: int,
    results_per_query: int,
) -> dict[str, Any]:
    """Work out executable count expectations through targeted search probes."""

    max_iterations = max(1, int(max_iterations or 1))
    queries_per_iteration = max(1, int(queries_per_iteration or 1))
    results_per_query = max(1, int(results_per_query or 1))

    current_estimate = dict(previous_estimate or {})
    families: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    critique: dict[str, Any] = {}

    for iteration in range(max_iterations):
        plan = await _plan_expectation_searches(
            llm,
            question,
            goal_context=goal_context,
            completion_state=completion_state,
            previous_estimate=current_estimate,
            iteration=iteration,
            n=queries_per_iteration,
        )
        families = _coerce_families(plan) or families
        queries = _coerce_queries(plan, limit=queries_per_iteration)
        if not queries:
            break

        attempts.extend(
            _run_search_attempts(
                queries,
                search_fn=search_fn,
                results_per_query=results_per_query,
                iteration=iteration,
            )
        )

    # There is no computed estimate any more, and therefore no saturation gate
    # to stop the loop early. Chao1 produced both, and it is deleted: every
    # family it would have sized is reported as unestimated with the reason,
    # which is what "we have not measured this" should have looked like all
    # along. The loop now runs its configured waves and stops.
    current_estimate = _fallback_unestimated_estimate(
        families,
        attempts=attempts,
    )

    return {
        "estimate": current_estimate,
        "critique": critique,
        "attempts": attempts,
        "search_space_probes": search_space_probes_from_attempts(attempts),
    }


def search_space_probes_from_attempts(
    attempts: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for attempt in attempts:
        results = [
            dict(result)
            for result in attempt.get("results") or []
            if isinstance(result, Mapping)
        ]
        urls = _estimator_unique_strings(result.get("url") for result in results)
        domains = _estimator_unique_strings(_domain(url) for url in urls)
        probes.append(
            {
                "id": str(attempt.get("id") or ""),
                "artifact_label": attempt.get("artifact_label"),
                "episode_id": str(attempt.get("episode_id") or ""),
                "query": str(attempt.get("query") or ""),
                "purpose": str(attempt.get("purpose") or ""),
                "axis_bindings": {
                    "family": str(attempt.get("family_name") or ""),
                    "source_shape": str(attempt.get("expected_source_shape") or ""),
                },
                "result_count": len(results),
                "unique_url_count": len(urls),
                "unique_domain_count": len(domains),
                "result_count_bucket": result_count_bucket(len(results)),
                "domains": domains[:12],
                "titles": _estimator_unique_strings(result.get("title") for result in results)[
                    :12
                ],
                "results": results[:10],
            }
        )
    return probes


async def _plan_expectation_searches(
    llm,
    question: str,
    *,
    goal_context: Mapping[str, Any],
    completion_state: Mapping[str, Any],
    previous_estimate: Mapping[str, Any],
    iteration: int,
    n: int,
) -> dict[str, Any]:
    """Plan the next wave of BREADTH probes for the completion scope.

    This call survived the Chao1 deletion and it needs its own justification,
    because its old one went with the estimator: it no longer plans searches to
    measure how many rows exist. What it plans are breadth probes whose
    RESULTS -- urls, domains, result-count buckets -- become
    `search_space_probes` and feed the completion scope. That question survives
    the count's retirement: "how broad is the space this question ranges over"
    is answerable from what a probe returns, without extrapolating a richness
    estimate from it.

    The prompt below previously instructed the model to read
    `chao1_coverage_fraction`, `accumulation_curve` and
    `sample_size_rarefaction`, and serialized the whole rarefaction dict as a
    payload. All of those are deleted. Leaving the instruction would have told
    the model to read an absent field -- which it cannot report, it just plans
    differently and nothing records that it did.
    """

    prompt = f"""QUESTION:
{question}

CURRENT COVERAGE STATE JSON:
{json_for_prompt(goal_context, budget=8000)}

COMPLETION SCOPE STATE JSON:
{json_for_prompt(completion_state, budget=6000)}

PREVIOUS EXPECTATION ESTIMATE JSON:
{json_for_prompt(previous_estimate, budget=6000)}

Plan iteration {iteration}. Name the unresolved final-row families and propose
up to {n} searches that probe how BROAD the space is for those families -- how
many distinct sources and source shapes exist to be found, not how many rows
exist. Prefer probes that would surface parts of the space earlier probes did
not reach: different terminology, different source shapes, different
subdomains of the question. Reaching a region already covered is a weaker
probe than reaching one that is not.

Do not use internal column names as query text unless they are also natural
source terminology. Do not estimate or state a count, and do not treat any
number a source reports as the size of the space.

Return JSON:
{{
  "families": [
    {{
      "name": "required final-row family",
      "target_table": "declared final table for this family",
      "key_columns": ["columns that identify distinct final rows"],
      "reason": "why this row family is still unresolved"
    }}
  ],
  "queries": [
    {{
      "family_name": "matching family name",
      "query": "concise web search text",
      "purpose": "region of the search space this query should reach",
      "expected_source_shape": "review | appendix | dashboard | repository | dataset | paper | catalog",
      "mutation": "how this query differs from prior failed searches"
    }}
  ]
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_PLANNER_SYSTEM_PROMPT,
    )
    return parsed if isinstance(parsed, dict) else {}


def _run_search_attempts(
    queries: list[Mapping[str, Any]],
    *,
    search_fn: EstimatorSearchFn,
    results_per_query: int,
    iteration: int,
) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for index, item in enumerate(queries):
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        error = ""
        try:
            raw_results = search_fn(query, results_per_query)
        except Exception as exc:  # noqa: BLE001 - failed probes are estimator evidence
            raw_results = []
            error = str(exc)

        results: list[dict[str, Any]] = []
        for rank, result in enumerate(raw_results, start=1):
            if not isinstance(result, Mapping):
                continue
            compact = compact_search_result(dict(result))
            url = str(result.get("url") or compact.get("url") or "")
            compact["result_id"] = _stable_id(
                {
                    "query": normalize_query(query),
                    "rank": rank,
                    "url": url,
                }
            )
            compact["rank"] = rank
            compact["url"] = url
            compact["title"] = str(result.get("title") or compact.get("title") or "")
            results.append(compact)

        urls = _estimator_unique_strings(result.get("url") for result in results)
        domains = _estimator_unique_strings(_domain(url) for url in urls)
        attempts.append(
            {
                "id": _stable_id(
                    {
                        "iteration": iteration,
                        "index": index,
                        "query": normalize_query(query),
                    }
                ),
                "iteration": iteration,
                "query_index": index,
                "family_name": str(item.get("family_name") or "").strip(),
                "target_table": str(item.get("target_table") or "").strip(),
                "query": query,
                "purpose": str(item.get("purpose") or item.get("rationale") or ""),
                "expected_source_shape": str(
                    item.get("expected_source_shape") or ""
                ).strip(),
                "mutation": str(item.get("mutation") or "").strip(),
                "result_count": len(results),
                "unique_url_count": len(urls),
                "unique_domain_count": len(domains),
                "result_count_bucket": result_count_bucket(len(results)),
                "domains": domains[:12],
                "error": error,
                "results": results,
            }
        )
    return attempts


# --------------------------------------------------------------------------- #
# Plan and result coercion.
#
# RESTORED AFTER A DELETION OVERREACH, not re-added as new behaviour. These three
# went out as collateral when the Chao1 machinery was cut: 915 lines were removed
# and these were inside the swept ranges while their call sites -- lines 92, 93
# and 540 -- were not. Every one is Chao1-free at `a9cfd8c` and reintroduces
# nothing the deletion mandate retired: no chao1, rarefaction, richness,
# expected_count, singleton or doubleton reference appears in any of them.
#
# The file still imported cleanly with them missing, because a NameError on a
# module-level function is only raised when the line executes. Nothing caught it
# until a live `--pipeline-mode table-fill` run reached
# `_estimate_task_goal_universe` and aborted before round 0.
# --------------------------------------------------------------------------- #


def _coerce_families(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    families = plan.get("families") or plan.get("row_families") or []
    out: list[dict[str, Any]] = []
    for item in families:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or item.get("family_name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "target_table": str(item.get("target_table") or "").strip(),
                "key_columns": _estimator_unique_strings(item.get("key_columns")),
                "reason": str(item.get("reason") or item.get("description") or ""),
            }
        )
    return out


def _coerce_queries(
    plan: Mapping[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    items = plan.get("queries") or plan.get("search_queries") or []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            item = {"query": item}
        if not isinstance(item, Mapping):
            continue
        query = str(item.get("query") or "").strip()
        key = normalize_query(query)
        if len(query) < 4 or not key or key in seen:
            continue
        seen.add(key)
        out.append({**dict(item), "query": query})
        if len(out) >= limit:
            break
    return out


def _attempt_results(attempt: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        result
        for result in attempt.get("results") or []
        if isinstance(result, Mapping)
    ]


def _fallback_unestimated_estimate(
    families: list[Mapping[str, Any]],
    *,
    attempts: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if not families:
        families = [
            {
                "name": "answer_universe",
                "target_table": "",
                "key_columns": [],
                "reason": "No final-row family has been resolved yet.",
            }
        ]

    return {
        "status": "insufficient_evidence",
        "scope_summary": (
            "No count is estimated. Breadth probes run and are reported; "
            "nothing extrapolates a universe size from them."
        ),
        "search_space_summary": f"Ran {len(attempts)} breadth probe(s).",
        "expected_axes": [],
        "count_targets": [],
        "unestimated_count_targets": [
            {
                "name": str(family.get("name") or f"family_{index + 1}"),
                "description": str(family.get("reason") or ""),
                "target_table": str(family.get("target_table") or ""),
                "key_columns": _estimator_unique_strings(family.get("key_columns")),
                "reason": (
                    "No count is estimated for this family. Only the observed "
                    "census is measured, counted from exported rows; nothing "
                    "extrapolates a universe size from it."
                ),
            }
            for index, family in enumerate(families)
        ],
        # NO MANUFACTURED BINS. This used to emit one open, high-severity
        # underexplored bin for EVERY family, unconditionally, because every
        # family is unestimated -- and after the Chao1 deletion every family is
        # always unestimated. A flag raised on every subject every time
        # distinguishes nothing; it is a constant wearing a finding's shape.
        #
        # It was also load-bearing in the wrong direction:
        # `completion_scope_actionable` refuses to proceed while any bin is
        # open, so a bin emitted unconditionally here held the pre-GASL gate
        # shut on every from-scratch run. An open bin should mean a scope
        # critic looked and objected, and those still arrive via
        # `completion_update_from_critique`.
        "underexplored_bins": [],
        "unresolved_questions": [
            "Which external sources provide numeric coverage for each final-row family?"
        ],
        "suggested_queries": [],
    }


def _preserve_unestimated_families(
    estimate: Mapping[str, Any],
    families: list[Mapping[str, Any]],
) -> dict[str, Any]:
    out = dict(estimate or {})
    if not families:
        return out

    covered = set()
    for key in (
        "count_targets",
        "unestimated_count_targets",
        "out_of_scope_count_targets",
    ):
        for target in out.get(key) or []:
            if not isinstance(target, Mapping):
                continue
            name = _family_key(target.get("name") or target.get("family_name"))
            if name:
                covered.add(name)

    missing = []
    for family in families:
        if not isinstance(family, Mapping):
            continue
        name = str(family.get("name") or family.get("family_name") or "").strip()
        key = _family_key(name)
        if not name or not key or key in covered:
            continue
        covered.add(key)
        missing.append(
            {
                "name": name,
                "description": str(
                    family.get("description") or family.get("reason") or ""
                ),
                "target_table": str(family.get("target_table") or "").strip(),
                "key_columns": _estimator_unique_strings(family.get("key_columns")),
                "reason": (
                    "The estimator planned searches for this required final-row "
                    "family, but the synthesis did not produce numeric count "
                    "evidence for it."
                ),
            }
        )

    if not missing:
        return out

    out["unestimated_count_targets"] = [
        *[
            target
            for target in out.get("unestimated_count_targets") or []
            if isinstance(target, Mapping)
        ],
        *missing,
    ]
    if out.get("status") == "estimated":
        out["status"] = "insufficient_evidence"
    unresolved = _estimator_unique_strings(out.get("unresolved_questions"))
    unresolved.append(
        "Which external sources provide numeric coverage for each omitted final-row family?"
    )
    out["unresolved_questions"] = _estimator_unique_strings(unresolved)
    return out


def _estimator_unique_strings(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _estimator_clean(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _family_bucket(value: Any) -> str:
    """Join key for the probe-observation namespace: attempt and probe ids.

    Those three derive their key here and nowhere else. When the grouping side
    cleaned the family name and the lookup side did not, the URL signal was
    silently `None` for every family that had actually been probed -- a miss
    that reads as "unprobed" rather than as an error, so nothing downstream
    could notice it. One derivation removes that class within this namespace.

    It is not the module's only family key: `_family_key` normalizes the same
    field differently for a different join. See its docstring.
    """

    return _estimator_clean(value) or "unspecified"


def _family_key(value: Any) -> str:
    """Join key for the estimate namespace: planned families against targets.

    Deliberately not `_family_bucket`. This one collapses whitespace runs and
    keeps spaces, and it maps an empty name to `""` rather than to a real
    bucket -- `_preserve_unestimated_families` relies on that falsiness to skip
    unnamed entries instead of collapsing them together under one key. Both
    sides of this join call this function, so it is self-consistent; the two
    keys never meet, and unifying them would change that skip behaviour for no
    gain.
    """

    return " ".join(str(value or "").lower().split())


def _domain(url: Any) -> str:
    return urlparse(str(url or "")).netloc.lower().lstrip("www.")


def _stable_id(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


SUPPORTING_SOURCE_ID_KIND_PROBE_URL = "probe_url"


def _observed_source_ids_for_family(
    attempts: list[Mapping[str, Any]] | None,
    family_name: str,
) -> list[str]:
    """The URLs this run actually retrieved while probing one family.

    This is the sample the family's breadth probes drew from, joined on
    the same key and deduplicated the same way, so the count and the support
    cited for it can never describe different evidence: when the URL signal is
    primary, ``len()`` of this list *is* ``expected_minimum_count``.

    Nothing here is synthesized. A family whose probes returned no URL yields
    no ids, and a count with no observation behind it is not one this function
    is willing to claim support for.
    """

    bucket = _family_bucket(family_name)
    urls: list[str] = []
    seen: set[str] = set()
    for attempt in attempts or []:
        if not isinstance(attempt, Mapping):
            continue
        if _family_bucket(attempt.get("family_name")) != bucket:
            continue
        for result in _attempt_results(attempt):
            url = str(result.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def _iter_lists(value: Any, path: tuple = ()) -> list[tuple[tuple, list]]:
    found: list[tuple[tuple, list]] = []
    if isinstance(value, Mapping):
        for key, inner in value.items():
            found.extend(_iter_lists(inner, path + (key,)))
    elif isinstance(value, list):
        found.append((path, value))
        for index, inner in enumerate(value):
            found.extend(_iter_lists(inner, path + (index,)))
    return found


def _at_path(root: Any, path: tuple) -> Any:
    node = root
    for step in path:
        node = node[step]
    return node


def _rendered_payload(
    reduced: Any,
    dropped: Mapping[str, int],
    *,
    budget_note: Mapping[str, Any] | None = None,
) -> str:
    """Serialize a reduced payload with its disclosure attached, if any.

    A dict root carries `_reduction` as one more key. Any other root -- a list
    of records is the common case -- is wrapped as `{"items": ..., "_reduction":
    ...}`, because there is nowhere else to put the disclosure.

    Wrapping is preferred to appending a sentinel element to the list. These
    lists are arrays of homogeneous records, and one call site asks a model to
    return exactly one judgment per element; a meta-object sitting among the
    records invites a judgment about a record that does not exist. The wrapper
    keeps every real element homogeneous and puts the disclosure beside them,
    not among them.
    """

    disclosure: dict[str, Any] = {}
    if dropped:
        disclosure = {
            "note": (
                "Lists were shortened to fit the prompt budget. Counts "
                "below are elements omitted per path. No value was cut "
                "mid-structure."
            ),
            "omitted_elements_by_path": dict(dropped),
        }
    if budget_note:
        disclosure = {**disclosure, **budget_note}
    if not disclosure:
        return json.dumps(reduced, indent=2, default=str)
    if isinstance(reduced, dict):
        return json.dumps(
            {**reduced, "_reduction": disclosure},
            indent=2,
            default=str,
        )
    return json.dumps(
        {"items": reduced, "_reduction": disclosure},
        indent=2,
        default=str,
    )


def json_for_prompt(value: Any, *, budget: int) -> str:
    """Serialize within ``budget`` characters without ever cutting mid-structure.

    Returns valid JSON. When reduction was necessary the payload carries a
    ``_reduction`` key naming every path that lost elements and how many, so
    the omission is visible to the model and in the recorded prompt.

    That promise used to hold only for dict roots. A list root had its elements
    deleted and no disclosure attached at all -- so the largest call site here,
    which hands a model a list of search attempts, silently dropped half of
    them and returned a judgment nothing downstream could tell apart from one
    made on the whole input. The disclosure is the entire point of preferring
    structural reduction to a character slice, and it now covers every root.

    The loop measures the payload it will actually emit, disclosure included,
    rather than reserving a guessed number of characters for it.
    """

    text = json.dumps(value, indent=2, default=str)
    if len(text) <= budget:
        return text

    reduced = json.loads(json.dumps(value, default=str))
    dropped: dict[str, int] = {}

    def render() -> str:
        # `budget_met` rides along with the omission note rather than being
        # attached afterwards, so the string measured against the budget is
        # byte-for-byte the string returned. It is stated positively on
        # success because a missing flag cannot distinguish "fitted" from
        # "written before anything recorded whether it fitted".
        return _rendered_payload(
            reduced,
            dropped,
            budget_note={"budget_met": True, "budget": budget} if dropped else None,
        )

    for _ in range(200):
        text = render()
        if len(text) <= budget:
            return text
        lists = [(p, l) for p, l in _iter_lists(reduced) if len(l) > 1]
        if not lists:
            break
        path, longest = max(lists, key=lambda item: len(item[1]))
        keep = max(1, len(longest) // 2)
        label = ".".join(str(step) for step in path) or "(root)"
        dropped[label] = dropped.get(label, 0) + (len(longest) - keep)
        del _at_path(reduced, path)[keep:]

    text = render()
    if len(text) <= budget:
        return text

    # The irreducible structure -- scalar measurements plus one element per
    # list -- is itself larger than the budget. Overshooting is the right trade
    # against dropping measured values or emitting a fragment, but it is
    # declared rather than left for the reader to discover.
    return _rendered_payload(
        reduced,
        dropped,
        budget_note={
            "budget_met": False,
            "budget": budget,
            "actual_chars": len(text),
            "note_budget": (
                "Every list is already at one element; what remains is scalar "
                "measurement that cannot be dropped without losing data. "
                "actual_chars is the payload size before this note was added."
            ),
        },
    )


# ============================================================================
# strategy.py
# ============================================================================

import json
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from question_pipeline.utilities.model import ModelTier, ask_json, register_call_site_tier
from question_pipeline.utilities.model import measured_size, window_items, window_stamps

#: 0M-strategy-arms: `gpt-5.4-mini` agreed on 0.600 of planned queries against a
#: registered 0.95 threshold, with both sensitivity controls discriminating
#: cleanly (weak 0.000, truncated 0.154) and the comparator perfectly symmetric
#: and consistent. Arm generation stays on the reasoning model.
_TARGET_DEFICIT_QUERIES_TIER = register_call_site_tier("strategy-arms", ModelTier.REASONING)

#: The acquisition composition's run-grain source (phase 4E-c). 0M never tested
#: it, and 0M's own rule for a call site it did not measure is that the site
#: stays on `REASONING`.
_STRATEGY_PROPOSER_TIER = register_call_site_tier(
    "strategy-proposer", ModelTier.REASONING
)

#: 0M-best-guess: `gpt-5.4-mini` agreed on 0.175 of candidates — the lowest of
#: any tested site. The models disagree about *whether* to guess at all, not
#: only about the value. Stays on the reasoning model.
_BEST_GUESS_TIER = register_call_site_tier("best-guess", ModelTier.REASONING)


_SEARCH_SYSTEM_PROMPT = """You are a scientific search strategist.
Generate concise web-search queries that retrieve source material needed to
answer the user's research question. Infer the domain and target categories
from the question and current run state. Return only valid JSON in the shape
requested by the user."""

_ASSESSMENT_SYSTEM_PROMPT = """You are a rigorous evidence-coverage reviewer.
Judge whether a graph-derived answer is supported by enough retrieved evidence
to answer the user's research question. Return only valid JSON in the shape
requested by the user."""

_BEST_GUESS_SYSTEM_PROMPT = """You derive missing sidecar values for an
iterative table-aggregation run. Use only the provided row state and local
evidence. Return null when the evidence does not support a value. Keep hard
reported fields separate from inferred sidecar values. Return only valid JSON
in the shape requested by the user."""


def _coerce_query_list(parsed: Any, limit: int) -> List[str]:
    """Pull a clean list of query strings out of assorted JSON shapes."""
    if limit <= 0:
        return []
    if isinstance(parsed, dict):
        parsed = parsed.get("queries") or parsed.get("search_queries") or []
    queries: List[str] = []
    seen = set()
    for item in parsed or []:
        text = item.get("query") if isinstance(item, dict) else item
        text = str(text or "").strip()
        key = text.lower()
        if len(text) >= 4 and key not in seen:
            seen.add(key)
            queries.append(text)
        if len(queries) >= limit:
            break
    return queries


async def initial_queries(
    llm,
    question: str,
    *,
    n: int = 6,
    schema_hint: str = "",
) -> List[str]:
    """Derive the first batch of web-search queries straight from the question."""
    prompt = f"""QUESTION:
{question}
{("DOMAIN FOCUS: " + schema_hint if schema_hint else "")}

Produce {n} complementary web-search queries that would surface the evidence
needed to answer the question. Infer the appropriate source ecosystem from the
question and domain focus: useful routes may include primary datasets and
catalogs, government or institutional repositories, scholarly literature,
technical reports, historical archives, and authoritative compilations.

Make each query pursue a distinct, task-relevant evidence route. Collectively,
the queries should cover the entities, attributes, quantitative values,
qualifiers, and source types required by the question rather than varying
wording for its own sake. Keep each query concise (3-9 words), no boolean
operators.

Return JSON: {{"queries": ["...", "..."]}}"""
    parsed = await ask_json(llm, prompt, system_prompt=_SEARCH_SYSTEM_PROMPT)
    return _coerce_query_list(parsed, n)


async def followup_queries(
    llm,
    question: str,
    *,
    current_answer: str,
    gaps: List[str],
    top_entities: List[str],
    n: int = 6,
) -> List[str]:
    """Generate the next batch of queries aimed at the current answer's gaps."""
    gap_text = "\n".join(f"- {g}" for g in gaps) if gaps else "- (none identified)"
    entity_text = ", ".join(top_entities[:25]) if top_entities else "(graph is empty)"
    prompt = f"""QUESTION:
{question}

CURRENT BEST ANSWER FROM THE GRAPH (complete and unabridged):
{current_answer}

IDENTIFIED GAPS:
{gap_text}

ENTITIES ALREADY IN THE GRAPH (avoid redundant searches):
{entity_text}

Produce {n} NEW search queries targeting the gaps and unexplored but relevant
directions. Do not repeat what the graph already covers well. Concise queries
(3-9 words), no boolean operators.

Return JSON: {{"queries": ["...", "..."]}}"""
    parsed = await ask_json(llm, prompt, system_prompt=_SEARCH_SYSTEM_PROMPT)
    return _coerce_query_list(parsed, n)


#: Serialized-character budget for ONE planner call's slice of the deficit
#: catalog. It bounds a call, not the catalog: a catalog larger than this
#: becomes more calls, never a shortened one. A single deficit that exceeds it
#: gets a window to itself, uncut.
#:
#: Sized so the recorded catalogs need one or two windows rather than a dozen
#: -- the largest is 35,694 characters over 6 deficits, largest single deficit
#: 2,875 -- while still splitting a catalog that grows past that. There is no
#: cost cliff here to tune against: the observed ceiling on this client is
#: 658,611 tokens, so this is a guard against pathological growth and a lever
#: on how much context one call reasons over, not a budget in the money sense.
_DEFICIT_WINDOW_BUDGET = 40000

async def target_deficit_queries(
    llm,
    question: str,
    *,
    goal_context: Dict[str, Any],
    deficits: List[Dict[str, Any]],
    n: int = 4,
    arms_per_target: int = 1,
    queries_per_arm: int = 1,
    seed_queries: Sequence[str] = (),
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Generate focused prompt-arm experiments for table-fill deficits.

    The catalog is split across as many calls as its measured size needs, and
    the returned queries are the union over those calls. Returns the queries
    and a window report describing the split, which the caller persists: a
    reader should be able to see three windows over sixteen deficits yielding
    N tasks without inferring any of it.

    Windows are unioned *within* the round rather than spread across rounds. A
    deficit in the second window of a three-round run would otherwise wait a
    third of the run to be planned at all, which is positional starvation with
    a longer period -- the same defect as ranking deficits and keeping a
    prefix, which is what this replaced.

    ``seed_queries`` are phrasings a proposed strategy suggested (phase 4E-c
    §11). They are forwarded to **every** window call as declared prompt
    context, empty by default so every existing call renders a byte-identical
    prompt. They are context and nothing else: no predicate reads them, and what
    reaches a predicate is ``control.stable_id`` over the normalized seed set,
    which is content-addressing rather than text-steering. They are a declared
    parameter with a declared render site rather than something smuggled through
    ``goal_context``, and they are shared across every arm of the call, so they
    cannot differentially bias one sibling against another and the contrast
    between siblings stays meaningful.

    **They must reach a prompt if they are hashed into a key.** If a caller
    hashes seeds into a strategy's content key while they reach no prompt, the
    untried test discriminates on content the run never used, two proposals
    differing only in seeds instantiate byte-identical arms, and the proposer's
    novelty is fictional.
    """

    seeds = [str(seed).strip() for seed in seed_queries if str(seed).strip()]
    if n <= 0 or not deficits:
        return [], {
            "window_count": 0,
            "deficit_count": 0,
            "windows": [],
            "union_size": 0,
            "goal_context_chars": measured_size(goal_context),
            "goal_context_windowed": False,
            "seed_query_count": len(seeds),
            "seed_query_chars": measured_size(seeds),
        }

    arms_per_target = max(1, arms_per_target)
    queries_per_arm = max(1, queries_per_arm)

    windows = window_items(deficits, budget=_DEFICIT_WINDOW_BUDGET)
    queries: List[Dict[str, Any]] = []
    seen: set[str] = set()
    window_records: List[Dict[str, Any]] = []

    for index, window in enumerate(windows):
        planned = await _plan_deficit_window(
            llm,
            question,
            goal_context=goal_context,
            window=window,
            stamps=window_stamps(index, len(windows)),
            n=n,
            arms_per_target=arms_per_target,
            queries_per_arm=queries_per_arm,
            seed_queries=seeds,
        )
        accepted = 0
        for item in planned:
            query = str(item.get("query") or "").strip()
            key = query.lower()
            if len(query) < 4 or key in seen:
                continue
            seen.add(key)
            queries.append(item | {"query": query})
            accepted += 1
        window_records.append(
            {
                **window_stamps(index, len(windows)),
                "deficit_count": len(window),
                "deficit_ids": [
                    str(deficit.get("id") or "")
                    for deficit in window
                    if isinstance(deficit, Mapping)
                ],
                "chars": sum(measured_size(deficit) for deficit in window),
                "planned_queries": len(planned),
                "accepted_queries": accepted,
            }
        )

    report = {
        "window_count": len(windows),
        "deficit_count": len(deficits),
        "window_budget_chars": _DEFICIT_WINDOW_BUDGET,
        "union_size": len(queries),
        # Sent whole in every window call rather than clipped. Declared so a
        # reader can see what the per-call payload actually was, and so growth
        # here is visible in emitted data instead of being absorbed silently.
        "goal_context_chars": measured_size(goal_context),
        "goal_context_windowed": False,
        # What each call carried of the proposed-seed block, so a reader can see
        # whether a proposal's seeds reached the arms it claims novelty over.
        "seed_query_count": len(seeds),
        "seed_query_chars": measured_size(seeds),
        "windows": window_records,
    }
    return queries, report


async def _plan_deficit_window(
    llm,
    question: str,
    *,
    goal_context: Dict[str, Any],
    window: List[Dict[str, Any]],
    stamps: Dict[str, int],
    n: int,
    arms_per_target: int,
    queries_per_arm: int,
    seed_queries: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """One planner call over one window of the deficit catalog.

    The deficit catalog is the windowed axis. `goal_context` is not windowed
    and is not clipped: it is a mapping whose members describe one coverage
    state, and a planner shown half of it would plan against a coverage picture
    that never existed. It is therefore treated as one oversized item and sent
    whole, which is the rule `windowing.py` already states for an item larger
    than its budget. Its measured size is reported by the caller so a reader
    can see what each call carried.

    ``seed_queries`` renders as its own declared block, before the instructions,
    and is omitted entirely when empty so an unseeded call is byte-identical to
    the pre-4E-c prompt.
    """

    seed_block = ""
    if seed_queries:
        seed_block = f"""
PROPOSED SEED QUERIES JSON (complete and unabridged):
{json.dumps(list(seed_queries), indent=2, default=str)}

These are seed phrasings proposed for this strategy. Treat them as starting
vocabulary for the arms below. Do not return any of them unchanged, and do not
treat them as a constraint on which deficit an arm attacks.
"""

    prompt = f"""QUESTION:
{question}

CURRENT COVERAGE STATE JSON (complete and unabridged):
{json.dumps(goal_context, indent=2, default=str)}

UNMET FILL DEFICITS JSON (window {stamps["window_index"] + 1} of {stamps["window_count"]}, {len(window)} deficits, complete and unabridged):
{json.dumps(window, indent=2, default=str)}
{seed_block}
Produce up to {n} concrete focused searches organized as prompt-mutation
experiments. Each experiment attacks exactly one fill-deficit id. Each
experiment may contain up to {arms_per_target} prompt arms, and each arm may
contain up to {queries_per_arm} concrete external-search queries.

Prefer high-priority deficits, but diversify across target tables and deficit
types when several deficits have similar priority. Each query must map to one
fill-deficit id through its parent experiment.

A prompt arm is one explicit delta in how to phrase searches for the same
deficit. Mutate one thing per arm: the expected source shape, the external
terminology, the anchoring breadth, or the context qualifier emphasis. Use
previous arm contrast, accepted-source terms, matched needs, missing needs,
search-result samples, rejection reasons, failed query terms, and exhausted
operators to choose arms whose results will be informative relative to prior
arms.

Each deficit has an operator_plan selected by deterministic code. Instantiate
that operator only; do not invent a different strategy_family. Use each
deficit's strategy_history and strategy_memory to avoid stalled search
behavior. Treat accepted-source terms, matched needs, missing needs, rejection
reasons, failed query terms, and exhausted_operators as memory that must shape
the next query text.

Queries must use terms that could appear in external source titles, abstracts,
tables, appendices, or dataset descriptions. Do not repeat a previous query for
the same deficit. Do not include internal table names, column identifiers,
deficit descriptions, count strings, or workflow phrases unless they also occur
as real subject terms in known examples or accepted source context. Prefer
source queries that can fill multiple missing rows in the target table, and use
known missing examples only when they are present in the deficit.

When the selected operator asks for a context-pivot expansion, vary the
external vocabulary for the target's key columns, missing fields, or row
qualifiers. Preserve the specific qualifiers reported by source authors
instead of collapsing every row to one broad bucket.

Keep each query concise (3-10 words), no boolean operators.

Return JSON:
{{
  "experiments": [
    {{
      "target_id": "matching fill-deficit id",
      "target_name": "matching target or table name",
      "strategy_family": "exact_anchor | review_or_table | dataset_or_appendix | terminology_mutation | context_expansion",
      "arms": [
        {{
          "name": "short generic label",
          "prompt_delta": "what search-phrasing change this arm tests",
          "hypothesis": "why this arm should find non-overlapping useful evidence",
          "expected_source_shape": "kind of external source this arm should retrieve",
          "queries": [
            {{
              "query": "search text",
              "rationale": "why this can add missing rows"
            }}
          ]
        }}
      ]
    }}
  ]
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_SEARCH_SYSTEM_PROMPT,
        tier=_TARGET_DEFICIT_QUERIES_TIER,
    )
    # `n` bounds each window's plan. Deduplication and the run's own task
    # budget bound the union, which is the caller's business: capping here
    # would let an early window spend the whole allowance and starve a later
    # one, which is the positional defect windowing exists to remove.
    return list(
        _iter_target_query_items(
            parsed,
            arms_per_target=arms_per_target,
            queries_per_arm=queries_per_arm,
        )
    )[: max(1, n)]


def _iter_target_query_items(
    parsed: Any,
    *,
    arms_per_target: int = 1,
    queries_per_arm: int = 1,
) -> Iterable[Dict[str, Any]]:
    arms_per_target = max(1, arms_per_target)
    queries_per_arm = max(1, queries_per_arm)
    if isinstance(parsed, dict) and isinstance(parsed.get("experiments"), list):
        experiments = parsed.get("experiments") or []
        arm_counts_by_target: dict[str, int] = {}
        for experiment in experiments:
            if not isinstance(experiment, Mapping):
                continue
            target_key = str(
                experiment.get("target_id")
                or experiment.get("target_name")
                or ""
            ).strip()
            if not target_key:
                target_key = "__unknown__"
            base = {
                "target_id": str(experiment.get("target_id") or "").strip(),
                "target_name": str(experiment.get("target_name") or "").strip(),
                "strategy_family": str(
                    experiment.get("strategy_family") or ""
                ).strip(),
            }
            for arm in experiment.get("arms") or []:
                arm_index = arm_counts_by_target.get(target_key, 0)
                if arm_index >= arms_per_target:
                    break
                if isinstance(arm, str):
                    arm = {"queries": [arm]}
                if not isinstance(arm, Mapping):
                    continue
                arm_counts_by_target[target_key] = arm_index + 1
                arm_base = {
                    **base,
                    "prompt_arm_name": str(arm.get("name") or "").strip(),
                    "prompt_arm_index": arm_index,
                    "prompt_delta": str(arm.get("prompt_delta") or "").strip(),
                    "prompt_hypothesis": str(arm.get("hypothesis") or "").strip(),
                    "expected_source_shape": str(
                        arm.get("expected_source_shape") or ""
                    ).strip(),
                }
                arm_queries = list(
                    arm.get("queries") or arm.get("search_queries") or []
                )[:queries_per_arm]
                for query_index, query_item in enumerate(arm_queries):
                    if isinstance(query_item, Mapping):
                        yield {
                            **arm_base,
                            "query": str(query_item.get("query") or ""),
                            "rationale": str(
                                query_item.get("rationale")
                                or arm.get("hypothesis")
                                or ""
                            ).strip(),
                            "query_index": query_index,
                        }
                    else:
                        yield {
                            **arm_base,
                            "query": str(query_item or ""),
                            "rationale": str(
                                arm.get("hypothesis") or ""
                            ).strip(),
                            "query_index": query_index,
                        }
        return

    items = parsed.get("queries") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return

    for query_index, item in enumerate(items):
        if not isinstance(item, Mapping):
            item = {"query": str(item or "")}
        yield {
            "query": str(item.get("query") or ""),
            "target_id": str(item.get("target_id") or "").strip(),
            "target_name": str(item.get("target_name") or "").strip(),
            "strategy_family": str(item.get("strategy_family") or "").strip(),
            "rationale": str(item.get("rationale") or "").strip(),
            "prompt_arm_name": str(
                item.get("prompt_arm_name")
                or item.get("strategy_family")
                or "default"
            ).strip(),
            "prompt_arm_index": _coerce_int(item.get("prompt_arm_index"), 0),
            "prompt_delta": str(item.get("prompt_delta") or "").strip(),
            "prompt_hypothesis": str(
                item.get("prompt_hypothesis")
                or item.get("rationale")
                or ""
            ).strip(),
            "expected_source_shape": str(
                item.get("expected_source_shape") or ""
            ).strip(),
            "query_index": _coerce_int(item.get("query_index"), query_index),
        }


#: The prose fields a proposer's payload may carry as CONTEXT and that no
#: predicate may read. Declared by name here so the boundary is checkable
#: rather than assumed: these are one module's model-emitted prose aggregated by
#: another (`search_memory`'s cue counters, the page gate's need lists), and the
#: charter licenses them as "the run's view ... rendered as text" while banning
#: them from any branch. The accept rule reads `(content key, distance)` and
#: nothing else, so no predicate can reach them by construction.
PROPOSER_CONTEXT_PROSE_FIELDS = (
    "avoid_cues",
    "better_search_cues",
    "matched_needs",
    "missing_needs",
    "offtopic_axes",
)


async def propose_distant_strategy(
    llm,
    question: str,
    *,
    run_view: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]],
    tried: Sequence[Mapping[str, Any]],
    n: int = 3,
) -> List[Dict[str, Any]]:
    """Sample outcome-informed strategies for the run grain's switch edge.

    THE MODEL'S WHOLE JOB HERE IS STRING WORK AND ONE NUMBER. It samples
    candidate ``(operator, targets, seed phrasings)`` combinations using the
    completed strategies' measured outcomes, and reports how far each candidate
    sits from the ones already tried -- because semantic distance is a property
    of two strings.

    It does **not** decide whether to propose: that is the run grain's own
    verdict, read by the loop after every unit. It does **not** decide whether a
    candidate is distant enough: `control.select_first_clearing` compares the
    reported number against a written floor. It emits no count, no estimate and
    no verdict that a branch consumes, and the prompt names no floor, no
    threshold and no consequence of the number -- a model told what the floor is
    has been handed the rule back.

    Three returned fields reach a predicate and they are named here so the
    boundary is checkable: ``operator`` (a set-membership test against the
    injected ``catalog``, applied by the caller -- `acquisition.StrategyProposer`
    drops a non-member before selection and records it with
    ``rejection_class: operator_not_in_catalog``; a non-member is rejected,
    never renamed onto the nearest member),
    ``target_ids`` (intersected with the run's declared target ids), and
    ``distance`` (a float against a written floor). ``query_seeds`` are
    normalized and hashed into a code-minted content key and otherwise forwarded
    to the arm planner as context. ``label`` and ``rationale`` reach no
    predicate at all.

    ``catalog`` is injected rather than imported so this function assumes no
    particular operator vocabulary, and ``run_view`` is built by the caller from
    the run's own view -- finished strategy records, the declared contract, the
    criteria snapshot, the observed deficits, accepted-source terms. Nothing
    question-specific is written here.
    """

    if n <= 0 or not catalog:
        return []

    prompt = f"""QUESTION:
{question}

RUN VIEW JSON (complete and unabridged):
{json.dumps(dict(run_view), indent=2, default=str)}

STRATEGIES ALREADY OPENED IN THIS RUN JSON (complete and unabridged):
{json.dumps(list(tried), indent=2, default=str)}

AVAILABLE OPERATOR CATALOG JSON (complete and unabridged):
{json.dumps(dict(catalog), indent=2, default=str)}

Propose up to {n} further search strategies for this run. A strategy is one
operator from the catalog above, applied to one or more of the target ids the
run has declared, with a few seed phrasings that show how its searches would be
worded.

Use the completed strategy outcomes as empirical memory. Compare what each
prior query attempted with its distinct findings overall and by column, its
incidence estimate, acquired sources, duplicate URLs, page fates, failures, and
unprocessed results. Identify which search vocabulary and source shapes yielded
new evidence, which saturated, which mostly repeated prior material, and which
were not actually judged because acquisition or extraction failed.

Propose searches that are likely to add distinct findings for the observed
deficits. Build on productive vocabulary or source shapes when they still have
estimated findings remaining. Change the terminology, source shape, target, or
operator when prior work saturated or produced mostly repeats. Do not treat an
instrument failure as evidence that a subject direction is barren. Do not
repeat an unproductive query unless the proposal states the concrete change
that makes the new search materially different.

Use an `operator` value that appears as a key of the catalog. Use `target_ids`
that appear in the run view. Order proposals by expected marginal contribution
of distinct evidence to the observed deficits, highest first. Semantic novelty
is a constraint, not the objective: a different query that is unlikely to fill
a deficit is not useful merely because it is different.

For each proposal report `distance` on a 0.0-1.0 scale: how far this
combination of operator, targets and seed phrasing sits from the nearest
strategy already opened, where 0.0 is the same strategy reworded and 1.0 is a
combination sharing nothing with any of them.

Return JSON:
{{
  "proposals": [
    {{
      "operator": "one key of the catalog",
      "target_ids": ["declared target ids this strategy attacks"],
      "query_seeds": ["seed phrasing", "seed phrasing"],
      "distance": 0.0,
      "label": "short generic name",
      "rationale": "which measured prior outcomes support this choice, what it changes, and which deficit it should fill"
    }}
  ]
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_SEARCH_SYSTEM_PROMPT,
        tier=_STRATEGY_PROPOSER_TIER,
    )
    if isinstance(parsed, Mapping):
        parsed = parsed.get("proposals") or parsed.get("strategies")
    if not isinstance(parsed, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in parsed[: max(1, n)]:
        if not isinstance(item, Mapping):
            continue
        out.append(
            {
                "operator": str(item.get("operator") or "").strip(),
                "target_ids": [
                    str(value).strip()
                    for value in (item.get("target_ids") or [])
                    if str(value).strip()
                ],
                "query_seeds": [
                    str(value).strip()
                    for value in (item.get("query_seeds") or [])
                    if str(value).strip()
                ],
                "distance": item.get("distance"),
                "label": str(item.get("label") or "").strip(),
                "rationale": str(item.get("rationale") or "").strip(),
            }
        )
    return out


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def infer_best_guess_candidates(
    llm,
    question: str,
    *,
    operator: str,
    tasks: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract best-guess sidecar candidates from existing local evidence."""
    prompt = f"""QUESTION:
{question}

BEST-GUESS OPERATOR:
{operator}

MISSING ROW-SLOT TASKS JSON:
{json.dumps(tasks, indent=2, default=str)}

LOCAL EVIDENCE JSON:
{json.dumps(evidence, indent=2, default=str)}

For each task, infer the requested sidecar value only if the local evidence
supports it. These are derived best guesses for grouping or plotting. They do
not overwrite hard reported table columns.

Rules:
- Use the task's canonical_column as the requested slot.
- Use only LOCAL EVIDENCE JSON and the row_values already attached to the task.
- Return no candidate when the provided evidence is ambiguous or irrelevant.
- Preserve the qualifier grain implied by the evidence.
- Explain the exact basis without citing outside knowledge.
- confidence should be 0.5-1.0 only when a value is supported.

Return JSON:
{{
  "candidates": [
    {{
      "task_id": "matching task id",
      "value": "inferred sidecar value or null",
      "confidence": 0.0,
      "basis": "short evidence-grounded reason",
      "source_ids": ["optional existing source ids"],
      "source_chunks": ["optional existing source chunks"]
    }}
  ]
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_BEST_GUESS_SYSTEM_PROMPT,
        tier=_BEST_GUESS_TIER,
    )
    if isinstance(parsed, dict):
        parsed = parsed.get("candidates")
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


async def assess_answer(
    llm,
    question: str,
    *,
    answer: str,
    graph_summary: str,
) -> Dict[str, Any]:
    """Judge whether the current answer sufficiently answers the question.

    The answer is sent whole. It is not windowed and not clipped: sufficiency
    and completeness are properties of the whole answer, so a judgment made
    from a window is not a partial version of the real judgment -- it is a
    judgment of a different object. The clip this replaced showed the judge the
    first 2,500 characters of an answer measured at 8,165 characters on the
    live run, which meant "insufficient, gaps remain" was partly a report about
    the scissors.
    """
    prompt = f"""QUESTION:
{question}

CANDIDATE ANSWER (produced by graph traversal, complete and unabridged):
{answer}

GRAPH SUMMARY:
{graph_summary}

Decide whether the answer is well-supported and complete, or whether more
evidence is needed. Be strict: a vague or hedged answer is NOT sufficient.

Return JSON:
{{
  "sufficient": true | false,
  "confidence": 0.0-1.0,
  "gaps": ["what is still missing or weakly supported", "..."],
  "rationale": "one or two sentences"
}}"""
    parsed = await ask_json(llm, prompt, system_prompt=_ASSESSMENT_SYSTEM_PROMPT)
    if not isinstance(parsed, dict):
        return {"sufficient": False, "confidence": 0.0, "gaps": [], "rationale": ""}
    parsed.setdefault("sufficient", False)
    parsed.setdefault("confidence", 0.0)
    parsed.setdefault("gaps", [])
    parsed.setdefault("rationale", "")
    if not isinstance(parsed["gaps"], list):
        parsed["gaps"] = [str(parsed["gaps"])]
    return parsed


# ============================================================================
# path_features.py
# ============================================================================

import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

from question_pipeline.utilities.acquisition import PathExclusionReason, PathSelectionReason, RouteStep, TargetRef, TerminalRef
from question_pipeline.utilities.tables import CriteriaSnapshot, CriterionState, normalize_key_value, subject_key



#: Bumped when a change would move an existing route's score.  A consumer that
#: compares scores across versions is comparing two different measurements, and
#: the version is carried on every scored record so that shows up as a mismatch
#: rather than as a difference in route quality.
#:
#: ``v1`` -> ``v2``: the subject key was re-derived locally instead of imported
#: from :mod:`question_pipeline.utilities.tables`, and the two spellings diverged on
#: list-, mapping- and bool-valued key columns and on anything past
#: ``MAX_VALUE_LENGTH``.  A row whose key failed to join silently contributed
#: nothing to the relation and terminal-type priors, so ``relation_sequence``
#: and ``terminal_type`` could fall to their no-input levels with no error.  On
#: the corpus behind ``experiments/runs/2A`` that affected **28% of the prior
#: rows** in the one table family that had declared key columns -- their
#: ``source_refs`` are JSON lists.  Scores recorded under ``v1`` are therefore
#: **not reproducible** from this module and must not be compared to ``v2``
#: scores; the version mismatch is the intended way to discover that.
#:
#: **This version does not cover everything that can move a score.**  Two
#: feature buckets -- ``relation_sequence`` and ``terminal_type`` -- spell their
#: relation and entity types through
#: :func:`question_pipeline.utilities.tables.normalize_key_value`, which is *not* a join
#: into the criteria projection: both sets are built and read entirely inside
#: this module.  Borrowing the projection's spelling is deliberate, because it
#: leaves this module with no normaliser of its own, but it means a change to
#: ``criteria.MAX_VALUE_LENGTH`` would move scores through a path that has
#: nothing to do with criterion identity, and **this constant would not trip**.
#: A change to that limit is therefore a path-features version bump as well as a
#: criteria one.  The alternative -- a path-features-owned spelling for those
#: two buckets -- was rejected: it buys version independence at the cost of
#: reintroducing exactly the duplicate normaliser that produced the v1 defect.
PATH_FEATURES_VERSION = "path_features_v2"

#: Decimal places retained on every emitted float.  Scoring is a weighted sum
#: of rationals; rounding at a fixed precision is what makes the emitted record
#: byte-identical rather than merely equal to within floating-point noise.
SCORE_PRECISION = 6


# ---------------------------------------------------------------------------
# Feature names
# ---------------------------------------------------------------------------

FEATURE_SOURCE_OVERLAP = "source_overlap"
FEATURE_PATH_DEPTH = "path_depth"
FEATURE_RELATION_SEQUENCE = "relation_sequence"
FEATURE_TERMINAL_TYPE = "terminal_type"
FEATURE_ANCHOR_CONSISTENCY = "anchor_consistency"
FEATURE_HUB_DEGREE = "hub_degree"

#: The six generic features, in a fixed order.  Every feature is oriented the
#: same way -- 1.0 is the *good* end -- so a reader never has to remember which
#: ones are penalties, and a weight is never accidentally applied with the
#: wrong sign.
FEATURE_NAMES: tuple[str, ...] = (
    FEATURE_SOURCE_OVERLAP,
    FEATURE_PATH_DEPTH,
    FEATURE_RELATION_SEQUENCE,
    FEATURE_TERMINAL_TYPE,
    FEATURE_ANCHOR_CONSISTENCY,
    FEATURE_HUB_DEGREE,
)


# ---------------------------------------------------------------------------
# Closed reason vocabularies
# ---------------------------------------------------------------------------
#
# :class:`PathSelectionReason` and :class:`PathExclusionReason` are defined in
# :mod:`question_pipeline.utilities.acquisition` and re-exported here.  They are this
# module's output vocabulary but ``control.PathCandidate`` carries them as
# typed fields, and ``control`` may not import this module -- the dependency
# runs the other way.  Naming them in the vocabulary module is what makes the
# closure a constraint on the receiving field rather than a convention on the
# producing one.


# ---------------------------------------------------------------------------
# Weights and calibration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathScoreWeights:
    """Relative weight of each feature in the combined score.

    Hand-set, which is the correct first version: there is no labelled corpus
    of good and bad routes to fit against, and a fitted weight vector with no
    held-out set would be a stronger-looking claim resting on less.  The
    reasoning behind the defaults:

    ``source_overlap`` and ``anchor_consistency`` carry the most weight because
    they name the two halves of the failure this module exists for -- evidence
    that belongs to some other source, and an endpoint that belongs to some
    other subject.  ``path_depth`` and ``hub_degree`` describe *how* a route
    drifts and get the next tier.  ``relation_sequence`` and ``terminal_type``
    are priors learned from what already worked; they are weighted lowest
    because on a sparse graph they are frequently unobserved, and an unobserved
    prior contributes its neutral level to every route it touches.

    Weights need not sum to 1: the score is the weighted mean, so only ratios
    matter and a weight can be set to zero to ablate a feature.
    """

    source_overlap: float = 0.25
    path_depth: float = 0.15
    relation_sequence: float = 0.10
    terminal_type: float = 0.10
    anchor_consistency: float = 0.25
    hub_degree: float = 0.15

    def weight(self, feature: str) -> float:
        return float(getattr(self, feature))

    def as_mapping(self) -> dict[str, float]:
        return {name: self.weight(name) for name in FEATURE_NAMES}

    def total(self) -> float:
        return sum(self.as_mapping().values())

    def to_dict(self) -> dict[str, Any]:
        return {"path_score_weights": self.as_mapping()}


@dataclass(frozen=True)
class PathFeatureCalibration:
    """The level each feature takes in each qualitative case.

    Every number a feature can produce is named here.  Nothing is buried in an
    expression, so re-tuning is an argument to :func:`score_rows` and never an
    edit to the arithmetic -- and a reader can see the whole scoring surface
    without reading the code that applies it.
    """

    # -- source_overlap ---------------------------------------------------
    #: Route evidence includes a chunk of the source accepted this round.
    source_overlap_current_chunk: float = 1.0
    #: Route evidence includes the source accepted this round, other chunk.
    source_overlap_current_source: float = 0.85
    #: Route evidence includes some previously accepted source.
    source_overlap_accepted_source: float = 0.60
    #: Route carries provenance, none of it accepted (or nothing to check against).
    source_overlap_unaccepted: float = 0.25
    #: Route carries no provenance reference at all.
    source_overlap_absent: float = 0.0

    # -- path_depth -------------------------------------------------------
    #: Hops that cost nothing.  A one-hop route is a direct edge.
    depth_free_hops: int = 1
    #: Penalty per hop beyond the free allowance.
    depth_penalty_per_hop: float = 0.30
    #: Multiplier applied to that penalty when the route preserves its anchor
    #: end to end.  Length is only evidence of drift when the route drifted.
    depth_anchored_relief: float = 0.40
    #: Level for a route whose depth is unknown.
    depth_unknown: float = 0.50

    # -- relation_sequence ------------------------------------------------
    #: A hop whose relation type previously supported a criterion here.
    relation_productive: float = 1.0
    #: A hop whose relation type has been seen but never supported anything.
    relation_unproductive: float = 0.20
    #: No productivity evidence exists yet: this feature knows nothing.
    relation_unknown: float = 0.50

    # -- terminal_type ----------------------------------------------------
    #: Terminal type associated with prior supported criteria of this kind.
    terminal_type_productive: float = 1.0
    #: Terminal type seen before, never on a supported criterion.
    terminal_type_unproductive: float = 0.20
    #: No prior association exists yet.
    terminal_type_unknown: float = 0.50

    # -- anchor_consistency -----------------------------------------------
    #: Origin and terminal resolve to the same criterion subject.
    anchor_same_subject: float = 1.0
    #: Origin resolves to a subject; the terminal is not a subject at all.
    #: Arriving on a measure, a method, or a context node is normal.
    anchor_open_terminal: float = 0.75
    #: Terminal resolves to a subject the route did not start from.
    anchor_terminal_only: float = 0.50
    #: Neither endpoint resolves to a known subject.
    anchor_unanchored: float = 0.35
    #: Origin and terminal resolve to two *different* subjects.  This is the
    #: shape the module exists to catch and it is the floor.
    anchor_crossed: float = 0.0
    #: No declared key columns, so subject identity is unavailable rather than
    #: violated.  Not a penalty -- an absence.
    anchor_identity_unavailable: float = 0.50

    # -- hub_degree -------------------------------------------------------
    #: Candidate rows a node may touch before it counts as a connector.
    hub_free_degree: int = 8
    #: Additional rows over the free allowance at which the penalty saturates.
    hub_saturation_degree: int = 120
    #: Level for a route whose nodes carry no degree information.
    hub_unknown: float = 0.50
    #: At or below this hub_degree level, the route is *reported* as running
    #: through a high-degree connector.  A reporting threshold only.
    hub_connector_level: float = 0.40

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in sorted(self.__dataclass_fields__)  # type: ignore[attr-defined]
        }


DEFAULT_WEIGHTS = PathScoreWeights()
DEFAULT_CALIBRATION = PathFeatureCalibration()


# ---------------------------------------------------------------------------
# Row adapter
# ---------------------------------------------------------------------------

#: Row-scoped provenance slots.  Engine-generic, not question-specific, and
#: read here only to rank a route -- see the module docstring on why this is
#: kept separate from the criteria projection's field-scoped basis.
PROVENANCE_SOURCE_SLOTS: tuple[str, ...] = ("source_refs", "source_ids")
PROVENANCE_CHUNK_SLOTS: tuple[str, ...] = ("source_chunks", "chunk_ids")

#: Slot naming a route's length when the row carries the terminal only.
DEPTH_SLOT = "path_depth"

#: Slot carrying an explicit multi-hop route, when an adapter supplies one.
ROUTE_SLOT = "route"

_SOURCE_SPLIT_RE = re.compile(r"[,;\s]+")
_CHUNK_SUFFIX_RE = re.compile(r"^(?P<source_id>.+)_chunk_\d+$")

_MISSING_STRINGS = frozenset(
    {
        "",
        "-",
        "--",
        "[null]",
        "<null>",
        "n/a",
        "na",
        "none",
        "not applicable",
        "not available",
        "not found",
        "not provided",
        "not reported",
        "not specified",
        "not stated",
        "null",
        "unknown",
    }
)


@dataclass(frozen=True)
class PathRow:
    """One candidate route, in canonical slots only.

    Two row shapes reach this module and both are supported without either
    being privileged.  A traversal row carries the terminal it arrived at plus
    the hop that got there and a ``path_depth``; an adapter that keeps the full
    walk carries an explicit ``route`` of hops.  Everything downstream reads
    :attr:`route`, :attr:`terminal`, and :attr:`depth`, so the two shapes are
    indistinguishable to the features.
    """

    row_id: str = ""
    route: tuple[RouteStep, ...] = ()
    terminal: TerminalRef = field(default_factory=TerminalRef)
    declared_depth: int | None = None
    source_ids: frozenset[str] = frozenset()
    chunk_ids: frozenset[str] = frozenset()
    key_values: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_mapping(
        cls,
        row: Mapping[str, Any] | None,
        *,
        key_columns: Sequence[str] = (),
        row_id: str = "",
    ) -> "PathRow":
        row = row or {}
        steps = _steps_from_mapping(row)
        terminal = TerminalRef(
            id=_text(row.get("tgt_id")) or _text(row.get("id")),
            name=_text(row.get("name")) or _text(row.get("target")) or _text(row.get("id")),
            entity_type=_text(row.get("entity_type")),
        )
        if not (terminal.id or terminal.name) and steps:
            last = steps[-1]
            terminal = TerminalRef(id=last.tgt_id, name=last.target or last.tgt_id)

        chunk_ids = _collect(row, PROVENANCE_CHUNK_SLOTS)
        source_ids = _collect(row, PROVENANCE_SOURCE_SLOTS) | {
            match.group("source_id")
            for match in (_CHUNK_SUFFIX_RE.match(chunk) for chunk in chunk_ids)
            if match is not None
        }

        declared = row.get(DEPTH_SLOT)
        depth = _optional_int(declared)

        return cls(
            row_id=_text(row_id) or _text(row.get("row_id")) or _text(row.get("id")),
            route=steps,
            terminal=terminal,
            declared_depth=depth,
            source_ids=frozenset(source_ids),
            chunk_ids=frozenset(chunk_ids),
            key_values=subject_key(row, key_columns) or (),
        )

    @property
    def depth(self) -> int | None:
        """Route length in hops.

        The declared slot wins over the hops actually carried, because a
        traversal row records the *terminal* it arrived at plus the last hop
        that got there: its route tuple is length one however far the walk
        went, and ``path_depth`` is the engine's own statement of how far that
        was.  Falling back to the carried hops would report every deep walk as
        a direct edge -- the exact routes this module exists to notice.
        """

        if self.declared_depth is not None:
            return self.declared_depth
        if self.route:
            return len(self.route)
        return None

    @property
    def origin(self) -> str:
        """The node the route started from, id preferred over name."""

        if self.route:
            first = self.route[0]
            return first.src_id or first.source
        return ""

    @property
    def endpoint(self) -> str:
        """The node the route arrived at, id preferred over name."""

        if self.terminal.id or self.terminal.name:
            return self.terminal.id or self.terminal.name
        if self.route:
            last = self.route[-1]
            return last.tgt_id or last.target
        return ""

    @property
    def nodes(self) -> tuple[str, ...]:
        """Every node the route touches, in order, duplicates collapsed."""

        seen: list[str] = []
        for step in self.route:
            for node in (step.src_id or step.source, step.tgt_id or step.target):
                if node and node not in seen:
                    seen.append(node)
        endpoint = self.endpoint
        if endpoint and endpoint not in seen:
            seen.append(endpoint)
        return tuple(seen)

    @property
    def is_scoreable(self) -> bool:
        return bool(self.route) or bool(self.endpoint)


def _steps_from_mapping(row: Mapping[str, Any]) -> tuple[RouteStep, ...]:
    explicit = row.get(ROUTE_SLOT)
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        steps = tuple(
            RouteStep.from_mapping(hop) for hop in explicit if isinstance(hop, Mapping)
        )
        if steps:
            return steps
    step = RouteStep.from_mapping(row)
    if step.identity == ("", "", ""):
        return ()
    return (step,)


# ---------------------------------------------------------------------------
# Scoring context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathScoringContext:
    """Everything outside a row that a route's score depends on.

    Built from the criteria snapshot, the table contract, and the rows already
    held -- never from question-specific literals.  A context is immutable and
    hashable-by-content, so the same context and the same rows always produce
    the same scores.
    """

    table: str = ""
    key_columns: tuple[str, ...] = ()
    accepted_source_ids: frozenset[str] = frozenset()
    current_source_ids: frozenset[str] = frozenset()
    current_chunk_ids: frozenset[str] = frozenset()
    #: Normalised anchor value -> subject id, over *bound* subjects only.
    anchor_subjects: Mapping[str, str] = field(default_factory=dict)
    productive_relations: frozenset[str] = frozenset()
    observed_relations: frozenset[str] = frozenset()
    productive_terminal_types: frozenset[str] = frozenset()
    observed_terminal_types: frozenset[str] = frozenset()

    @property
    def has_subject_identity(self) -> bool:
        """Whether declared key columns bought any usable subject identity.

        False when no key columns were declared, or when they were declared and
        no subject in the snapshot came out bound.  Either way the anchor
        feature reports identity as unavailable rather than inventing one.
        """

        return bool(self.key_columns) and bool(self.anchor_subjects)

    @property
    def has_relation_prior(self) -> bool:
        return bool(self.productive_relations) or bool(self.observed_relations)

    @property
    def has_terminal_prior(self) -> bool:
        return bool(self.productive_terminal_types) or bool(self.observed_terminal_types)

    @property
    def has_source_check(self) -> bool:
        return bool(self.accepted_source_ids or self.current_source_ids or self.current_chunk_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "key_columns": list(self.key_columns),
            "accepted_source_count": len(self.accepted_source_ids),
            "current_source_count": len(self.current_source_ids),
            "current_chunk_count": len(self.current_chunk_ids),
            "anchor_subject_count": len(set(self.anchor_subjects.values())),
            "anchor_value_count": len(self.anchor_subjects),
            "productive_relations": sorted(self.productive_relations),
            "observed_relations": sorted(self.observed_relations),
            "productive_terminal_types": sorted(self.productive_terminal_types),
            "observed_terminal_types": sorted(self.observed_terminal_types),
            "has_subject_identity": self.has_subject_identity,
            "has_relation_prior": self.has_relation_prior,
            "has_terminal_prior": self.has_terminal_prior,
            "has_source_check": self.has_source_check,
        }


def build_context(
    snapshot: CriteriaSnapshot | None,
    *,
    table: str = "",
    key_columns: Sequence[str] = (),
    target: TargetRef | None = None,
    accepted_source_ids: Iterable[str] = (),
    current_source_ids: Iterable[str] = (),
    current_chunk_ids: Iterable[str] = (),
    prior_rows: Iterable[Mapping[str, Any]] = (),
) -> PathScoringContext:
    """Assemble a scoring context from the criteria snapshot and prior rows.

    ``snapshot`` is the criteria projection's, imported whole.  Which criteria
    are supported is read off it and is never recomputed here.

    ``key_columns`` are the *declared* key columns of the target table, from the
    table contract.  They are what buys semantic subject identity; omitting them
    is not a smaller version of supplying them, it removes the anchor feature's
    ability to say anything, and the context reports that through
    :attr:`PathScoringContext.has_subject_identity`.

    ``prior_rows`` are rows already held for the target table.  They are joined
    to the snapshot by subject key -- a *join*, not a second opinion about
    status -- to learn which relation types and terminal types have previously
    landed on a supported criterion.
    """

    if target is not None:
        table = table or target.table
        key_columns = tuple(key_columns) or tuple(target.key_columns)
    key_columns = tuple(str(name) for name in key_columns)

    states = _states_for_table(snapshot, table)
    anchor_subjects = _anchor_index(states)
    supported_keys = {
        state.ref.subject_key
        for state in states
        if state.supported and state.ref.subject_bound and state.ref.subject_key
    }

    productive_relations: set[str] = set()
    observed_relations: set[str] = set()
    productive_terminals: set[str] = set()
    observed_terminals: set[str] = set()
    for row in prior_rows:
        if not isinstance(row, Mapping):
            continue
        relations = {
            normalize_key_value(step.relation_type)
            for step in _steps_from_mapping(row)
            if step.relation_type
        }
        terminal_type = normalize_key_value(row.get("entity_type"))
        observed_relations |= relations
        if terminal_type:
            observed_terminals.add(terminal_type)
        row_key = subject_key(row, key_columns)
        if row_key is not None and row_key in supported_keys:
            productive_relations |= relations
            if terminal_type:
                productive_terminals.add(terminal_type)

    return PathScoringContext(
        table=str(table or ""),
        key_columns=key_columns,
        accepted_source_ids=frozenset(_clean_ids(accepted_source_ids)),
        current_source_ids=frozenset(_clean_ids(current_source_ids)),
        current_chunk_ids=frozenset(_clean_ids(current_chunk_ids)),
        anchor_subjects=dict(sorted(anchor_subjects.items())),
        productive_relations=frozenset(productive_relations),
        observed_relations=frozenset(observed_relations),
        productive_terminal_types=frozenset(productive_terminals),
        observed_terminal_types=frozenset(observed_terminals),
    )


def _states_for_table(
    snapshot: CriteriaSnapshot | None, table: str
) -> tuple[CriterionState, ...]:
    if snapshot is None:
        return ()
    if not table:
        return tuple(snapshot.states)
    return tuple(state for state in snapshot.states if state.ref.table == table)


def _anchor_index(states: Sequence[CriterionState]) -> dict[str, str]:
    """Map every declared key value of a *bound* subject to its subject id.

    Unbound subjects are excluded, not weakly included.  Their identity is the
    projection's content-hash fallback: it reports almost every subject as
    distinct and moves as soon as a field fills, so treating it as identity
    would make the anchor feature confidently wrong rather than silent.
    """

    index: dict[str, str] = {}
    for state in states:
        ref = state.ref
        if not ref.subject_bound:
            continue
        for _name, value in ref.subject_key:
            key = normalize_key_value(value)
            if key and key not in index:
                index[key] = ref.subject_id
    return index


def node_degrees(rows: Iterable[PathRow]) -> dict[str, int]:
    """How many candidate rows each node appears on.

    Degree is measured against the candidate population being scored rather
    than against the graph, which is what keeps this module free of a graph
    adapter -- and is also the more direct reading of the signal: the concern
    is a node that connects many unrelated *candidate records*, not a node with
    many edges nobody walked.
    """

    degrees: dict[str, int] = {}
    for row in rows:
        for node in set(row.nodes):
            degrees[node] = degrees.get(node, 0) + 1
    return degrees


# ---------------------------------------------------------------------------
# Scored output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathScore:
    """One route's features, score, reason, and how much of it was measured."""

    row_id: str
    path_score: float
    path_score_features: Mapping[str, float]
    path_selection_reason: PathSelectionReason
    #: Per feature: did it have the inputs it reads, or did it return a
    #: no-input level?  Six booleans in :data:`FEATURE_NAMES` order.
    inputs: Mapping[str, bool] = field(default_factory=dict)
    path_exclusion_reason: PathExclusionReason | None = None
    version: str = PATH_FEATURES_VERSION

    def to_dict(self) -> dict[str, Any]:
        """The record fields a candidate carries.

        ``path_exclusion_reason`` is absent unless the route was excluded, so a
        consumer testing for the key gets a truthful answer instead of an empty
        string that reads as "excluded for no reason".

        ``path_score_inputs`` is what makes the record honest about its own
        resolution.  Several features return the same number for a measurement
        and for an absence -- ``anchor_consistency`` is 0.50 both when a route
        was measured to end on a non-subject node and when no key columns were
        declared at all, and the ``*_unknown`` levels collapse the same way.
        A consumer reading the number alone cannot tell those apart, and once a
        score is persisted onto a candidate and read a phase later, the fact
        that it was a two-feature score is gone.  So the count travels with the
        score.  **A score that degrades is not a defect; a score that degrades
        without the record saying so is.**
        """

        payload: dict[str, Any] = {
            "path_features_version": self.version,
            "path_score": self.path_score,
            "path_score_features": dict(self.path_score_features),
            "path_score_inputs": dict(self.inputs),
            "path_score_inputs_present": self.inputs_present,
            "path_selection_reason": self.path_selection_reason.value,
        }
        if self.path_exclusion_reason is not None:
            payload["path_exclusion_reason"] = self.path_exclusion_reason.value
        return payload

    @property
    def inputs_present(self) -> int:
        """How many of the six features actually had something to read."""

        return sum(1 for name in FEATURE_NAMES if self.inputs.get(name))

    @property
    def starved(self) -> bool:
        """Whether any feature fell back to a no-input level."""

        return self.inputs_present < len(FEATURE_NAMES)


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
#
# Every feature returns ``(value, measured)``.  ``measured`` is False when the
# feature had nothing to read and returned a declared no-input level -- which
# several of them share a number with, deliberately: the calibration is a scale
# of route quality, and "unavailable" sits mid-scale because an absence is not
# evidence of a bad route.  The flag is what keeps that from being ambiguous
# downstream, and it is carried on the emitted record rather than recomputed by
# each consumer from a context it may no longer hold.


def _source_overlap(
    row: PathRow,
    context: PathScoringContext,
    calibration: PathFeatureCalibration,
) -> tuple[float, bool]:
    measured = context.has_source_check
    if row.chunk_ids & context.current_chunk_ids:
        return calibration.source_overlap_current_chunk, measured
    if row.source_ids & context.current_source_ids:
        return calibration.source_overlap_current_source, measured
    if row.source_ids & context.accepted_source_ids:
        return calibration.source_overlap_accepted_source, measured
    if row.source_ids or row.chunk_ids:
        return calibration.source_overlap_unaccepted, measured
    return calibration.source_overlap_absent, measured


def _path_depth(
    row: PathRow,
    anchor: float,
    calibration: PathFeatureCalibration,
) -> tuple[float, bool]:
    depth = row.depth
    if depth is None:
        return calibration.depth_unknown, False
    excess = max(0, int(depth) - calibration.depth_free_hops)
    if excess == 0:
        return 1.0, True
    penalty = calibration.depth_penalty_per_hop * excess
    if anchor >= calibration.anchor_same_subject:
        penalty *= calibration.depth_anchored_relief
    return _clamp(1.0 - penalty), True


def _relation_sequence(
    row: PathRow,
    context: PathScoringContext,
    calibration: PathFeatureCalibration,
) -> tuple[float, bool]:
    if not context.has_relation_prior:
        return calibration.relation_unknown, False
    relations = [normalize_key_value(step.relation_type) for step in row.route]
    relations = [name for name in relations if name]
    if not relations:
        return calibration.relation_unknown, False
    levels = [
        calibration.relation_productive
        if name in context.productive_relations
        else calibration.relation_unproductive
        for name in relations
    ]
    return sum(levels) / len(levels), True


def _terminal_type(
    row: PathRow,
    context: PathScoringContext,
    calibration: PathFeatureCalibration,
) -> tuple[float, bool]:
    if not context.has_terminal_prior:
        return calibration.terminal_type_unknown, False
    entity_type = normalize_key_value(row.terminal.entity_type)
    if not entity_type:
        return calibration.terminal_type_unknown, False
    if entity_type in context.productive_terminal_types:
        return calibration.terminal_type_productive, True
    return calibration.terminal_type_unproductive, True


def _anchor_consistency(
    row: PathRow,
    context: PathScoringContext,
    calibration: PathFeatureCalibration,
) -> tuple[float, bool]:
    if not context.has_subject_identity:
        return calibration.anchor_identity_unavailable, False
    origin_subject = context.anchor_subjects.get(normalize_key_value(row.origin))
    endpoint_subject = context.anchor_subjects.get(normalize_key_value(row.endpoint))
    if origin_subject and endpoint_subject:
        if origin_subject == endpoint_subject:
            return calibration.anchor_same_subject, True
        return calibration.anchor_crossed, True
    if origin_subject:
        return calibration.anchor_open_terminal, True
    if endpoint_subject:
        return calibration.anchor_terminal_only, True
    return calibration.anchor_unanchored, True


def _hub_degree(
    row: PathRow,
    degrees: Mapping[str, int],
    calibration: PathFeatureCalibration,
) -> tuple[float, bool]:
    observed = [degrees[node] for node in row.nodes if node in degrees]
    if not observed:
        return calibration.hub_unknown, False
    excess = max(observed) - calibration.hub_free_degree
    if excess <= 0:
        return 1.0, True
    span = max(1, calibration.hub_saturation_degree)
    return _clamp(1.0 - min(1.0, excess / span)), True


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_row(
    row: PathRow | Mapping[str, Any],
    context: PathScoringContext | None = None,
    *,
    degrees: Mapping[str, int] | None = None,
    weights: PathScoreWeights = DEFAULT_WEIGHTS,
    calibration: PathFeatureCalibration = DEFAULT_CALIBRATION,
) -> PathScore:
    """Score one route.

    ``degrees`` comes from :func:`node_degrees` over the candidate population.
    Passing none scores the row as if its nodes' degrees were unobserved, which
    is honest for a single row: hub-ness is a property of a population and a
    population of one has none.
    """

    context = context or PathScoringContext()
    if isinstance(row, Mapping):
        row = PathRow.from_mapping(row, key_columns=context.key_columns)
    degrees = degrees or {}

    if not row.is_scoreable:
        return PathScore(
            row_id=row.row_id,
            path_score=0.0,
            path_score_features={name: 0.0 for name in FEATURE_NAMES},
            inputs={name: False for name in FEATURE_NAMES},
            path_selection_reason=PathSelectionReason.UNSCORED,
            path_exclusion_reason=PathExclusionReason.NO_ROUTE_EVIDENCE,
        )

    anchor, anchor_measured = _anchor_consistency(row, context, calibration)
    measured = {
        FEATURE_SOURCE_OVERLAP: _source_overlap(row, context, calibration),
        FEATURE_PATH_DEPTH: _path_depth(row, anchor, calibration),
        FEATURE_RELATION_SEQUENCE: _relation_sequence(row, context, calibration),
        FEATURE_TERMINAL_TYPE: _terminal_type(row, context, calibration),
        FEATURE_ANCHOR_CONSISTENCY: (anchor, anchor_measured),
        FEATURE_HUB_DEGREE: _hub_degree(row, degrees, calibration),
    }
    features = {name: value for name, (value, _flag) in measured.items()}
    inputs = {name: flag for name, (_value, flag) in measured.items()}

    total = weights.total()
    if total <= 0.0:
        score = 0.0
    else:
        score = sum(weights.weight(name) * features[name] for name in FEATURE_NAMES) / total

    return PathScore(
        row_id=row.row_id,
        path_score=_round(_clamp(score)),
        path_score_features={name: _round(features[name]) for name in FEATURE_NAMES},
        inputs={name: inputs[name] for name in FEATURE_NAMES},
        path_selection_reason=_selection_reason(features, context, calibration),
    )


def score_rows(
    rows: Iterable[PathRow | Mapping[str, Any]],
    context: PathScoringContext | None = None,
    *,
    weights: PathScoreWeights = DEFAULT_WEIGHTS,
    calibration: PathFeatureCalibration = DEFAULT_CALIBRATION,
) -> list[PathScore]:
    """Score a whole candidate population, in input order.

    The population is scored jointly because ``hub_degree`` is defined against
    it.  That makes the function pure in the *set* of rows rather than in each
    row alone, which is a real property of the signal and not an implementation
    accident: the same route through a node shared by three records and by
    three hundred is not the same route.
    """

    context = context or PathScoringContext()
    prepared = [
        row
        if isinstance(row, PathRow)
        else PathRow.from_mapping(row, key_columns=context.key_columns)
        for row in rows
    ]
    degrees = node_degrees(prepared)
    return [
        score_row(
            row,
            context,
            degrees=degrees,
            weights=weights,
            calibration=calibration,
        )
        for row in prepared
    ]


def _selection_reason(
    features: Mapping[str, float],
    context: PathScoringContext,
    calibration: PathFeatureCalibration,
) -> PathSelectionReason:
    """The one class label that best explains this route's score.

    Ordered, deterministic, and total.  Crossing a subject boundary is reported
    ahead of everything else because it is the failure this module exists to
    catch; positive provenance is reported next because it is the strongest
    thing that can be said for a route.
    """

    overlap = features[FEATURE_SOURCE_OVERLAP]
    if (
        context.has_subject_identity
        and features[FEATURE_ANCHOR_CONSISTENCY] <= calibration.anchor_crossed
    ):
        return PathSelectionReason.ANCHOR_CROSSED_SUBJECT
    if overlap >= calibration.source_overlap_current_chunk:
        return PathSelectionReason.CURRENT_CHUNK_EVIDENCE
    if overlap >= calibration.source_overlap_current_source:
        return PathSelectionReason.CURRENT_SOURCE_EVIDENCE
    if features[FEATURE_HUB_DEGREE] <= calibration.hub_connector_level:
        return PathSelectionReason.HIGH_DEGREE_CONNECTOR
    if overlap >= calibration.source_overlap_accepted_source:
        return PathSelectionReason.ACCEPTED_SOURCE_EVIDENCE
    if features[FEATURE_PATH_DEPTH] < 1.0:
        return PathSelectionReason.EXTENDED_ROUTE
    if overlap <= calibration.source_overlap_absent:
        return PathSelectionReason.NO_PROVENANCE
    if overlap <= calibration.source_overlap_unaccepted:
        return PathSelectionReason.UNACCEPTED_PROVENANCE
    if (
        context.has_subject_identity
        and features[FEATURE_ANCHOR_CONSISTENCY] >= calibration.anchor_same_subject
    ):
        return PathSelectionReason.ANCHOR_PRESERVED
    return PathSelectionReason.NEUTRAL_CONTEXT


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else float(value)


def _round(value: float) -> float:
    return round(float(value), SCORE_PRECISION)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _missing_provenance_token(value: Any) -> bool:
    """Whether a parsed provenance token is a placeholder rather than an id.

    Deliberately *not* the projection's ``_missing``: this filters tokens split
    out of a ``source_refs`` string, where the question is only "is this a real
    identifier".  It is never used on a key value -- every value that
    participates in a join goes through
    :func:`question_pipeline.utilities.tables.normalize_key_value`, which that module
    owns.
    """

    if value is None:
        return True
    if isinstance(value, str):
        return " ".join(value.split()).lower() in _MISSING_STRINGS
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_ids(values: Iterable[str] | None) -> set[str]:
    out: set[str] = set()
    for value in values or ():
        text = _text(value)
        if text:
            out.add(text)
    return out


def _collect(row: Mapping[str, Any], slots: Sequence[str]) -> set[str]:
    out: set[str] = set()
    for slot in slots:
        value = row.get(slot)
        if value is None:
            continue
        if isinstance(value, str):
            parts = _SOURCE_SPLIT_RE.split(value)
        elif isinstance(value, (list, tuple, set, frozenset)):
            parts = [str(item) for item in value]
        else:
            parts = [str(value)]
        for part in parts:
            text = part.strip()
            if text and not _missing_provenance_token(text):
                out.add(text)
    return out


# ``replace`` is re-exported through the dataclasses it is used on; naming it
# here keeps a linter from pruning the import that ``PathScoreWeights`` users
# rely on for tuning (``replace(DEFAULT_WEIGHTS, hub_degree=0.0)``).
_ = replace


# ============================================================================
# path_gate.py
# ============================================================================

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from question_pipeline.utilities.acquisition import ControlSurface, DecisionContext, PathCandidate, PolicyDecision, TableFillControlPolicy, TargetRef
from question_pipeline.utilities.tables import CriteriaSnapshot, row_subject_ids



#: Bumped when a change would move which rows this gate admits for an unchanged
#: input.  Carried on every result, so a consumer comparing two runs' admitted
#: sets across a version change sees a mismatch rather than a difference it
#: attributes to the data.
#:
#: ``v1`` -> ``v2``: a row the scorer could not score at all -- no route, no
#: terminal, no endpoint, reported as
#: :attr:`~question_pipeline.utilities.acquisition.PathExclusionReason.NO_ROUTE_EVIDENCE` --
#: was demotable, because the scorer gives it 0.0 and 0.0 is below any
#: threshold.  **An absence of a route is not a weak route.**  This gate exists
#: to demote routes, and it has nothing to say about a record that is not one.
#: The hole was invisible at the shipped default, where
#: ``min_inputs_present`` is all six features and an unscoreable row is
#: admitted as unresolved anyway; experiment 2B set it to 0 to make the gate
#: act at all and exposed it.  It mattered: on the corpus behind
#: ``experiments/runs/2B``, **87.2% of the rows at this boundary carry no route
#: evidence**, so under ``v1`` the threshold's reach was almost entirely over
#: records it had not measured.  Admitted sets recorded under ``v1`` are
#: therefore not reproducible from this module.
PATH_GATE_VERSION = "path_gate_v2"


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class PathGateDisposition(str, Enum):
    """What the gate did with one row.

    Two members, because there are two outcomes.  A third that meant "kept but
    marked" would be a synonym for :attr:`ADMITTED` that invited a later reader
    to treat it as a partial deletion.
    """

    #: The row goes on to operational table formation.
    ADMITTED = "admitted"
    #: The route was judged too weak to be worth an expensive batch, and no
    #: record of its subject is lost by holding it back.
    DEMOTED = "demoted"


class PathGateReason(str, Enum):
    """Why the gate reached that disposition, as a class label.

    This is the gate's own vocabulary.  ``path_features`` names why a route
    *scored* as it did; the two are recorded side by side and never merged,
    because a route can score badly and be admitted anyway -- which is the
    single most important thing this record has to be able to say.
    """

    # -- admitted -------------------------------------------------------- #

    #: No threshold is configured.  Nothing was judged.
    GATE_DISABLED = "gate_disabled"
    #: The row's subject already carries at least one supported criterion.
    #: This is the preservation exemption: the record reports real evidence
    #: alongside whatever it leaves unresolved, and it stays.
    SUBJECT_SUPPORTED = "subject_supported"
    #: Too few of the six features had inputs for the score to mean anything
    #: at this context's resolution, so the gate declines to act on it.
    SCORE_UNRESOLVED = "score_unresolved"
    #: The scorer could not score this row at all: it carries no route, no
    #: terminal, and no endpoint.  There is no route here to call weak, so the
    #: gate has nothing to say and says nothing.
    NO_ROUTE_TO_JUDGE = "no_route_to_judge"
    #: The route was scored, with inputs, at or above the threshold.
    SCORE_ADMITTED = "score_admitted"
    #: Some row of the subject was admitted, so the whole subject is kept:
    #: dropping part of a subject would change the criteria of the part left.
    SUBJECT_PARTIALLY_ADMITTED = "subject_partially_admitted"

    # -- demoted --------------------------------------------------------- #

    #: Every row of this subject scored below the threshold on a resolved
    #: score, and the subject carries no supported criterion.
    SUBJECT_BELOW_THRESHOLD = "subject_below_threshold"


#: The reasons that pair with each disposition.  Written down because a reason
#: on the wrong side of the gate is the kind of defect that reads correctly.
ADMISSION_REASONS: frozenset[PathGateReason] = frozenset(
    {
        PathGateReason.GATE_DISABLED,
        PathGateReason.SUBJECT_SUPPORTED,
        PathGateReason.SCORE_UNRESOLVED,
        PathGateReason.NO_ROUTE_TO_JUDGE,
        PathGateReason.SCORE_ADMITTED,
        PathGateReason.SUBJECT_PARTIALLY_ADMITTED,
    }
)

DEMOTION_REASONS: frozenset[PathGateReason] = frozenset(
    {PathGateReason.SUBJECT_BELOW_THRESHOLD}
)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathGateSettings:
    """Every parameter that can move which rows are admitted.

    All of it is here rather than spread through the call, so an experiment
    registers one object and a run records one object, and the two can be
    compared without reconstructing a call site.
    """

    #: Off by default.  See the module docstring: 2A left the score's validity
    #: unestablished, and a disabled gate still records everything.
    enabled: bool = False

    #: A route scoring **below** this is demotable.  The comparison is strictly
    #: less-than, so a threshold of 0.0 is a gate that demotes nothing however
    #: it is otherwise configured.
    min_score: float = 0.0

    #: How many of the six features must have had real inputs before the score
    #: is allowed to decide anything.  Defaults to all six: 2A measured four of
    #: them pinned to their no-input level on 89% of a real corpus, and a
    #: two-feature score is a different measurement wearing the same number.
    min_inputs_present: int = len(FEATURE_NAMES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_gate_enabled": self.enabled,
            "path_gate_min_score": float(self.min_score),
            "path_gate_min_inputs_present": int(self.min_inputs_present),
        }

    @property
    def gates(self) -> bool:
        """Whether this configuration can demote anything at all."""

        return bool(self.enabled) and float(self.min_score) > 0.0


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GatedRow:
    """One row's trip through the gate, joined to its candidate by ID."""

    row_index: int
    subject_id: str
    candidate: PathCandidate
    score: PathScore
    disposition: PathGateDisposition
    reason: PathGateReason

    @property
    def admitted(self) -> bool:
        return self.disposition is PathGateDisposition.ADMITTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_index": self.row_index,
            "row_id": self.candidate.row_id,
            "subject_id": self.subject_id,
            "control_action_id": self.candidate.id,
            "path_gate_disposition": self.disposition.value,
            "path_gate_reason": self.reason.value,
            **self.score.to_dict(),
        }


@dataclass(frozen=True)
class PathGateResult:
    """What the gate considered, what it admitted, and the decision record.

    ``decision`` is the policy's ranking of every candidate, with no budget
    applied -- the gate is not a budget, and pretending otherwise would put a
    ``selected_action_ids`` in the ledger that disagreed with the run.  What
    the gate actually did is :attr:`admitted_action_ids` and the per-row
    dispositions, which are recorded alongside it.
    """

    table: str
    version: str
    settings: PathGateSettings
    decision: PolicyDecision
    rows: tuple[GatedRow, ...] = ()
    #: Column keys observed on the rows before and after the gate.  Equal in
    #: every case the construction covers; recorded so the one residual the
    #: module docstring names is measured rather than assumed.
    columns_before: tuple[str, ...] = ()
    columns_after: tuple[str, ...] = ()

    @property
    def admitted_indices(self) -> tuple[int, ...]:
        return tuple(row.row_index for row in self.rows if row.admitted)

    @property
    def admitted_action_ids(self) -> tuple[str, ...]:
        return tuple(row.candidate.id for row in self.rows if row.admitted)

    @property
    def demoted_action_ids(self) -> tuple[str, ...]:
        return tuple(row.candidate.id for row in self.rows if not row.admitted)

    @property
    def preserves_columns(self) -> bool:
        return self.columns_before == self.columns_after

    def admitted_rows(
        self, rows: Sequence[Mapping[str, Any]]
    ) -> list[Mapping[str, Any]]:
        """The admitted subset of ``rows``, **in input order**.

        Input order, not ranked order, and deliberately: a gate configured to
        demote nothing must return its input unchanged down to the ordering,
        or the A/A comparison between gate-on and gate-off is measuring the
        reordering rather than the gate.  The ranking is a property of the
        decision record, which is where a consumer that wants it should read
        it.
        """

        keep = set(self.admitted_indices)
        return [row for index, row in enumerate(rows) if index in keep]

    def counts_by_reason(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.reason.value] = counts.get(row.reason.value, 0) + 1
        return dict(sorted(counts.items()))

    def summary(self) -> dict[str, Any]:
        """Counts and labels only -- no per-route identifiers.

        These are **observations**, not a score.  How many routes got through
        is a fact about the traversal and the threshold; it is not progress,
        and nothing downstream may read it as yield.  Progress is the criteria
        transition, and this module cannot produce one.
        """

        return {
            "path_gate_version": self.version,
            "path_gate_table": self.table,
            **self.settings.to_dict(),
            "path_gate_considered": len(self.rows),
            "path_gate_admitted": len(self.admitted_action_ids),
            "path_gate_demoted": len(self.demoted_action_ids),
            "path_gate_reason_counts": self.counts_by_reason(),
            "path_gate_preserves_columns": self.preserves_columns,
        }

    def to_ledger_record(self, *, artifact_path: str = "") -> dict[str, Any]:
        """The compact record that goes in the decision ledger.

        Deliberately *not* :meth:`to_dict`.  One traversal round on this corpus
        produces tens of thousands of routes, and
        ``PolicyDecision.to_dict()`` carries every candidate id four times
        over; the ledger is rewritten in full on every append, so embedding it
        would make each round quadratic in routes and the artifact unreadable.

        What survives here is the decision's identity and the shape of what it
        decided.  The routes themselves live in the sidecar artifact this
        record points at, joined back by ``decision_id`` -- so "what was
        considered and what was taken" is still answerable, at one hop.
        """

        return {
            "decision_id": self.decision.id,
            "policy_name": self.decision.policy_name,
            **self.decision.context.to_dict(),
            "policy_state_id": self.decision.state.id,
            "policy_state_version": self.decision.state.version,
            **self.summary(),
            "path_gate_artifact": str(artifact_path or ""),
        }

    def to_dict(self) -> dict[str, Any]:
        """Full detail: the decision, every candidate, every disposition.

        This is the sidecar artifact's payload and the experiment's unit.  See
        :meth:`to_ledger_record` for what the ledger itself carries.
        """

        return {
            **self.decision.to_dict(),
            "path_gate_version": self.version,
            "path_gate_table": self.table,
            **self.settings.to_dict(),
            "path_gate_considered": len(self.rows),
            # Smaller than ``considered`` when the policy's own admissibility
            # rule collapsed duplicate proposals -- same target, same row id,
            # same route.  Recorded because the gate's per-row dispositions and
            # the decision's candidate list are then different lengths, and a
            # reader who did not know that would call it a join failure.
            "path_gate_policy_candidates": len(self.decision.candidate_action_ids),
            "path_gate_admitted": len(self.admitted_action_ids),
            "path_gate_demoted": len(self.demoted_action_ids),
            "path_gate_admitted_action_ids": list(self.admitted_action_ids),
            "path_gate_demoted_action_ids": list(self.demoted_action_ids),
            "path_gate_reason_counts": self.counts_by_reason(),
            "path_gate_preserves_columns": self.preserves_columns,
            "path_gate_rows": [row.to_dict() for row in self.rows],
        }


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def gate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    policy: TableFillControlPolicy,
    episode_id: str = "",
    table: str = "",
    target: TargetRef | None = None,
    context: PathScoringContext | None = None,
    snapshot: CriteriaSnapshot | None = None,
    table_specs: Any = None,
    settings: PathGateSettings = PathGateSettings(),
    criteria_snapshot_id: str = "",
    pending_actions: int = 0,
    remaining_source_budget: int = 0,
) -> PathGateResult:
    """Score, rank, record, and admit one table's candidate routes.

    ``snapshot`` must be the projection of **these** rows -- the pre-gate
    state.  The exemption asks "does this subject already have support", and a
    snapshot of some other row set answers a different question.  Passing
    ``None`` means no subject is exempt, which is only safe when the gate is
    not demoting anything.

    Deterministic in the strong sense the control layer requires: the same rows
    with the same context and settings produce the same admitted set, the same
    candidate IDs, and the same decision ID, across processes.
    """

    context = context or PathScoringContext()
    ordered = list(rows)
    scores = score_rows(ordered, context)
    subject_ids = row_subject_ids(table, ordered, table_specs)

    candidates = tuple(
        _candidate(
            row=row,
            score=score,
            index=index,
            episode_id=episode_id,
            target=target,
            key_columns=context.key_columns,
        )
        for index, (row, score) in enumerate(zip(ordered, scores))
    )

    dispositions = _dispositions(
        scores=scores,
        subject_ids=subject_ids,
        supported_subjects=_supported_subjects(snapshot, table),
        settings=settings,
    )

    gated = tuple(
        GatedRow(
            row_index=index,
            subject_id=subject_ids[index],
            candidate=candidates[index],
            score=scores[index],
            disposition=disposition,
            reason=reason,
        )
        for index, (disposition, reason) in enumerate(dispositions)
    )

    decision_context = DecisionContext(
        surface=ControlSurface.PATH_SELECTION,
        episode_id=str(episode_id or ""),
        # Every candidate is inside the policy's budget: the gate is not a
        # budget, and this surface rejects nothing by ranking.
        max_actions=len(candidates),
        pending_actions=int(pending_actions),
        remaining_source_budget=int(remaining_source_budget),
        criteria_snapshot_id=str(criteria_snapshot_id or ""),
    )
    decision = policy.rank_actions(decision_context, list(candidates))

    keep = {row.row_index for row in gated if row.admitted}
    return PathGateResult(
        table=str(table or ""),
        version=PATH_GATE_VERSION,
        settings=settings,
        decision=decision,
        rows=gated,
        columns_before=_columns(ordered),
        columns_after=_columns(
            [row for index, row in enumerate(ordered) if index in keep]
        ),
    )


def _dispositions(
    *,
    scores: Sequence[PathScore],
    subject_ids: Sequence[str],
    supported_subjects: frozenset[str],
    settings: PathGateSettings,
) -> list[tuple[PathGateDisposition, PathGateReason]]:
    """Per-row disposition, decided per **subject**.

    The two-pass shape is the safety property, not an optimisation: pass one
    asks of each row "would the score alone demote this", pass two demotes a
    subject only when the answer was yes for all of its rows.  A subject that
    survives keeps every row it had, so its projected criteria cannot move.
    """

    admit_all = [
        (PathGateDisposition.ADMITTED, PathGateReason.GATE_DISABLED)
        for _ in scores
    ]
    if not settings.gates:
        return admit_all

    demotable: list[bool] = []
    for score in scores:
        # A row the scorer could not score is never demotable, at any
        # threshold and at any `min_inputs_present`.  Its score is 0.0 because
        # there was nothing to measure, not because the route was bad, and
        # demoting on it would be reading an absence as a verdict.
        if score.path_exclusion_reason is not None:
            demotable.append(False)
            continue
        resolved = score.inputs_present >= int(settings.min_inputs_present)
        demotable.append(resolved and score.path_score < float(settings.min_score))

    by_subject: dict[str, list[int]] = {}
    for index, subject in enumerate(subject_ids):
        by_subject.setdefault(subject, []).append(index)

    out: list[tuple[PathGateDisposition, PathGateReason]] = list(admit_all)
    for subject, indices in by_subject.items():
        if subject in supported_subjects:
            for index in indices:
                out[index] = (
                    PathGateDisposition.ADMITTED,
                    PathGateReason.SUBJECT_SUPPORTED,
                )
            continue
        if all(demotable[index] for index in indices):
            for index in indices:
                out[index] = (
                    PathGateDisposition.DEMOTED,
                    PathGateReason.SUBJECT_BELOW_THRESHOLD,
                )
            continue
        for index in indices:
            if demotable[index]:
                reason = PathGateReason.SUBJECT_PARTIALLY_ADMITTED
            elif scores[index].path_exclusion_reason is not None:
                reason = PathGateReason.NO_ROUTE_TO_JUDGE
            elif scores[index].inputs_present < int(settings.min_inputs_present):
                reason = PathGateReason.SCORE_UNRESOLVED
            else:
                reason = PathGateReason.SCORE_ADMITTED
            out[index] = (PathGateDisposition.ADMITTED, reason)
    return out


def _supported_subjects(
    snapshot: CriteriaSnapshot | None, table: str
) -> frozenset[str]:
    """Subject ids with at least one supported criterion on this table.

    Read off the projection; never recomputed here.  An absent snapshot yields
    an empty set, which exempts nothing -- so a caller that forgets to pass one
    while demoting gets a *smaller* admitted set, never a preservation failure
    it cannot see.
    """

    if snapshot is None:
        return frozenset()
    wanted = str(table or "")
    return frozenset(
        state.ref.subject_id
        for state in snapshot.supported
        if not wanted or state.ref.table == wanted
    )


def _candidate(
    *,
    row: Mapping[str, Any],
    score: PathScore,
    index: int,
    episode_id: str,
    target: TargetRef | None,
    key_columns: Sequence[str],
) -> PathCandidate:
    path_row = (
        row
        if isinstance(row, PathRow)
        else PathRow.from_mapping(row, key_columns=key_columns)
    )
    return PathCandidate.create(
        episode_id=episode_id,
        route=path_row.route,
        terminal=path_row.terminal,
        target=target,
        # Positional only as a last resort.  A row that carries no ``row_id``
        # and no ``id`` has no identity to join on, and without *something*
        # distinct every such row shares a dedupe key and the policy keeps one
        # of them.  A positional id is unstable across rounds and says so.
        row_id=path_row.row_id or f"row:{index}",
        path_score=score.path_score,
        path_score_features=score.path_score_features,
        path_selection_reason=score.path_selection_reason,
        path_exclusion_reason=score.path_exclusion_reason,
    )


def _columns(rows: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, Mapping):
            seen.update(str(key) for key in row)
    return tuple(sorted(seen))
