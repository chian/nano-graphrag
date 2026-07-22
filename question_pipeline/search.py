"""Search frontier and harvest primitives for question-driven graph building."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import uuid
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from paper_fetching.firecrawl_client import extract_text_from_result


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
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_query = self.query.strip()
        object.__setattr__(self, "query", normalized_query)
        if self.id:
            return
        object.__setattr__(self, "id", self.stable_id())

    def stable_id(self) -> str:
        payload = {
            "query": normalize_query(self.query),
            "parent_id": self.parent_id or "",
            "topic": self.topic,
            "expansion_op": self.expansion_op,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SourceRelevanceFn = Callable[
    [SearchTask, dict[str, Any], str],
    "SourceRelevanceDecision | Awaitable[SourceRelevanceDecision]",
]


@dataclass
class SearchOutcome:
    task_id: str
    query: str
    topic: str = "batch"
    expansion_op: str = "direct"
    gap: str = ""
    round_index: int = 0
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
    error: str = ""

    @classmethod
    def for_task(cls, task: SearchTask) -> "SearchOutcome":
        return cls(
            task_id=task.id,
            query=task.query,
            topic=task.topic,
            expansion_op=task.expansion_op,
            gap=task.gap,
            round_index=task.round_index,
            metadata=dict(task.metadata),
        )

    def skip(self, reason: str, count: int = 1) -> None:
        skipped = Counter(self.skipped_by_reason)
        skipped[reason] += count
        self.skipped_by_reason = dict(skipped)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchBatch:
    tasks: list[SearchTask] = field(default_factory=list)
    unattempted_tasks: list[SearchTask] = field(default_factory=list)
    papers: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[SearchOutcome] = field(default_factory=list)
    prompt_arm_summaries: list[dict[str, Any]] = field(default_factory=list)
    fatal_error: str = ""

    def outcome_dicts(self) -> list[dict[str, Any]]:
        return [outcome.to_dict() for outcome in self.outcomes]


@dataclass
class SourceRelevanceDecision:
    accept: bool
    reason: str = ""
    confidence: float = 0.0
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
    ) -> list[SearchTask]:
        tasks = [
            SearchTask(
                query=query,
                parent_id=parent_id,
                topic=topic,
                expansion_op=expansion_op,
                round_index=round_index,
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

    def next_wave(self, limit: int) -> list[SearchTask]:
        wave = []
        for _ in range(max(0, limit)):
            if not self._pending:
                break
            _, task = self._pending.popitem(last=False)
            wave.append(task)
        return wave

    def requeue_front(self, tasks: Iterable[SearchTask]) -> None:
        for task in reversed(list(tasks)):
            if task.id not in self._pending:
                self._pending[task.id] = task
                self._pending.move_to_end(task.id, last=False)

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


class SearchHarvester:
    """Execute search tasks and return accepted paper text plus audit outcomes."""

    def __init__(
        self,
        *,
        search_fn: SearchFn,
        papers_dir: Path,
        seen_urls: set[str],
        scrape_fn: Optional[ScrapeFn] = None,
        source_relevance_fn: Optional[SourceRelevanceFn] = None,
        min_paper_length: int = 500,
        max_paper_length: Optional[int] = None,
        max_extraction_chars_per_paper: Optional[int] = None,
        extract_text_fn: Callable[[dict[str, Any]], str] = extract_text_from_result,
    ):
        self.search_fn = search_fn
        self.scrape_fn = scrape_fn
        self.source_relevance_fn = source_relevance_fn
        self.papers_dir = papers_dir
        self.seen_urls = seen_urls
        self.min_paper_length = min_paper_length
        self.max_paper_length = max_paper_length
        self.max_extraction_chars_per_paper = max_extraction_chars_per_paper
        self.extract_text_fn = extract_text_fn

    def harvest(
        self,
        tasks: list[SearchTask],
        *,
        max_results_per_task: int,
        per_wave_cap: int,
        remaining_paper_budget: int,
    ) -> SearchBatch:
        batch = SearchBatch(tasks=list(tasks))
        paper_budget = max(0, min(per_wave_cap, remaining_paper_budget))

        for task_index, task in enumerate(tasks):
            if len(batch.papers) >= paper_budget:
                batch.unattempted_tasks = tasks[task_index:]
                break

            outcome = SearchOutcome.for_task(task)
            try:
                results = self.search_fn(task.query, max_results_per_task)
            except Exception as exc:  # noqa: BLE001 - one bad query should not abort a wave
                outcome.error = str(exc)
                outcome.skip("search_failed")
                batch.outcomes.append(outcome)
                self._record_outcome(outcome)
                if is_fatal_search_error(exc):
                    batch.fatal_error = str(exc)
                    batch.unattempted_tasks = tasks[task_index + 1 :]
                    break
                continue

            outcome.firecrawl_hits = len(results)
            for rank, result in enumerate(results, start=1):
                outcome.search_result_observations.append(
                    search_result_observation(result, rank=rank)
                )
                if len(batch.papers) >= paper_budget:
                    break
                paper = self._accept_result(task, result, outcome, rank=rank)
                if paper is not None:
                    batch.papers.append(paper)
            batch.outcomes.append(outcome)
            self._record_outcome(outcome)

        batch.prompt_arm_summaries = summarize_prompt_arms(batch)
        self._record_prompt_arm_summaries(batch)
        return batch

    async def harvest_async(
        self,
        tasks: list[SearchTask],
        *,
        max_results_per_task: int,
        per_wave_cap: int,
        remaining_paper_budget: int,
    ) -> SearchBatch:
        batch = SearchBatch(tasks=list(tasks))
        paper_budget = max(0, min(per_wave_cap, remaining_paper_budget))

        for task_index, task in enumerate(tasks):
            if len(batch.papers) >= paper_budget:
                batch.unattempted_tasks = tasks[task_index:]
                break

            outcome = SearchOutcome.for_task(task)
            try:
                results = self.search_fn(task.query, max_results_per_task)
            except Exception as exc:  # noqa: BLE001 - one bad query should not abort a wave
                outcome.error = str(exc)
                outcome.skip("search_failed")
                batch.outcomes.append(outcome)
                self._record_outcome(outcome)
                if is_fatal_search_error(exc):
                    batch.fatal_error = str(exc)
                    batch.unattempted_tasks = tasks[task_index + 1 :]
                    break
                continue

            outcome.firecrawl_hits = len(results)
            for rank, result in enumerate(results, start=1):
                outcome.search_result_observations.append(
                    search_result_observation(result, rank=rank)
                )
                if len(batch.papers) >= paper_budget:
                    break
                paper = await self._accept_result_async(
                    task,
                    result,
                    outcome,
                    rank=rank,
                )
                if paper is not None:
                    batch.papers.append(paper)
            batch.outcomes.append(outcome)
            self._record_outcome(outcome)

        batch.prompt_arm_summaries = summarize_prompt_arms(batch)
        self._record_prompt_arm_summaries(batch)
        return batch

    def _accept_result(
        self,
        task: SearchTask,
        result: dict[str, Any],
        outcome: SearchOutcome,
        *,
        rank: int,
    ) -> Optional[dict[str, Any]]:
        candidate = self._prepare_candidate(task, result, outcome, rank=rank)
        if candidate is None:
            return None
        return self._write_paper(task, candidate, outcome, rank=rank)

    async def _accept_result_async(
        self,
        task: SearchTask,
        result: dict[str, Any],
        outcome: SearchOutcome,
        *,
        rank: int,
    ) -> Optional[dict[str, Any]]:
        candidate = self._prepare_candidate(task, result, outcome, rank=rank)
        if candidate is None:
            return None

        decision = await self._source_relevance_decision(
            task,
            result,
            candidate.text,
        )
        if decision is not None:
            outcome.relevance_decisions.append(
                {
                    "url": candidate.url,
                    "title": result.get("title", ""),
                    **decision.to_dict(),
                }
            )
            if not decision.accept:
                outcome.skip("not_relevant")
                self._record_candidate_outcome(
                    outcome,
                    result,
                    rank=rank,
                    fate="not_relevant",
                    reason=decision.reason,
                    text_length=len(candidate.text),
                )
                return None

        return self._write_paper(task, candidate, outcome, rank=rank)

    def _prepare_candidate(
        self,
        task: SearchTask,
        result: dict[str, Any],
        outcome: SearchOutcome,
        *,
        rank: int,
    ) -> Optional[HarvestCandidate]:
        url = str(result.get("url") or "")
        if url and url in self.seen_urls:
            outcome.duplicate_urls.append(url)
            outcome.skip("duplicate_url")
            self._record_candidate_outcome(
                outcome,
                result,
                rank=rank,
                fate="duplicate_url",
            )
            return None

        text = self._extract_best_text(result, url, outcome)
        if is_blocked_page_text(text):
            outcome.skip("blocked_page")
            self._record_candidate_outcome(
                outcome,
                result,
                rank=rank,
                fate="blocked_page",
                text_length=len(text),
            )
            return None
        if len(text) < self.min_paper_length:
            outcome.skip("too_short")
            self._record_candidate_outcome(
                outcome,
                result,
                rank=rank,
                fate="too_short",
                text_length=len(text),
            )
            return None
        if self.max_paper_length is not None and len(text) > self.max_paper_length:
            outcome.skip("too_large")
            self._record_candidate_outcome(
                outcome,
                result,
                rank=rank,
                fate="too_large",
                text_length=len(text),
            )
            return None
        text, reduction = reduce_text_to_relevant_windows(
            text,
            task.query,
            max_chars=self.max_extraction_chars_per_paper,
        )
        return HarvestCandidate(
            result=result,
            url=url,
            text=text,
            reduction=reduction,
        )

    async def _source_relevance_decision(
        self,
        task: SearchTask,
        result: dict[str, Any],
        text: str,
    ) -> Optional[SourceRelevanceDecision]:
        if self.source_relevance_fn is None:
            return None

        decision = self.source_relevance_fn(task, result, text)
        if inspect.isawaitable(decision):
            decision = await decision
        return decision

    def _write_paper(
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
        self._record_candidate_outcome(
            outcome,
            result,
            rank=rank,
            fate="accepted",
            source_id=paper_id,
            text_length=len(text),
        )
        return paper

    def _record_outcome(self, outcome: SearchOutcome) -> None:
        with (self.papers_dir / "search_outcomes.jsonl").open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(json.dumps(outcome.to_dict(), default=str) + "\n")

    def _record_prompt_arm_summaries(self, batch: SearchBatch) -> None:
        if not batch.prompt_arm_summaries:
            return
        with (self.papers_dir / "prompt_arm_summaries.jsonl").open(
            "a",
            encoding="utf-8",
        ) as handle:
            for summary in batch.prompt_arm_summaries:
                handle.write(json.dumps(summary, default=str) + "\n")

    @staticmethod
    def _record_candidate_outcome(
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
                compact[str(key)] = value
        elif isinstance(value, Mapping):
            nested = {
                str(nested_key): nested_value
                for nested_key, nested_value in value.items()
                if (
                    isinstance(nested_value, (str, int, float, bool))
                    and len(str(nested_value)) <= 500
                )
            }
            if nested:
                compact[str(key)] = nested
    return compact


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


def merge_search_batches(*batches: SearchBatch) -> SearchBatch:
    """Merge harvested batches from one outer loop without losing provenance."""

    merged = SearchBatch()
    for batch in batches:
        merged.tasks.extend(batch.tasks)
        merged.unattempted_tasks.extend(batch.unattempted_tasks)
        merged.papers.extend(batch.papers)
        merged.outcomes.extend(batch.outcomes)
        if batch.fatal_error and not merged.fatal_error:
            merged.fatal_error = batch.fatal_error
    merged.prompt_arm_summaries = summarize_prompt_arms(merged)
    return merged


def summarize_prompt_arms(batch: SearchBatch) -> list[dict[str, Any]]:
    """Aggregate concrete searches by their originating prompt arm."""

    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for outcome in batch.outcomes:
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
    terms = _query_terms(query)

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


def _query_terms(query: str) -> set[str]:
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
