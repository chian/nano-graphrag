"""Prompt-driven progress judgments for table-fill state transitions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .llm_utils import ask_json


_PROGRESS_JUDGE_SYSTEM_PROMPT = """You are a progress judge for iterative
evidence aggregation. Score whether a candidate transition is likely to make
marginal progress toward the declared deliverables and stop criteria.

Judge expected table and coverage yield, not broad topical similarity. Accept
only when the candidate is likely to add source-supported values for declared
final-table slots, improve a source-supported universe/count estimate, or
resolve an explicit stop-criteria deficit. Reject candidates that only share a
domain, define background concepts, mention adjacent methods, list references,
or discuss nearby outcomes without likely values for the requested slots.

Return only valid JSON in the shape requested by the user."""

_DECISIONS = {"accept", "defer", "reject"}
_COVERAGE_DELTAS = {"none", "local", "table", "universe"}


@dataclass(frozen=True)
class ProgressJudgment:
    """A normalized LLM judgment for one candidate state transition."""

    kind: str
    decision: str = "reject"
    fruitfulness_score: float = 0.0
    novelty_score: float = 0.0
    specificity_score: float = 0.0
    coverage_delta: str = "none"
    reason: str = ""
    expected_progress_reason: str = ""
    matched_needs: tuple[str, ...] = ()
    missing_needs: tuple[str, ...] = ()
    offtopic_axes: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    better_search_cues: tuple[str, ...] = ()
    avoid_cues: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.decision == "accept"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["accept"] = self.accepted
        return payload


async def judge_progress(
    llm,
    *,
    kind: str,
    question: str,
    task_state: Mapping[str, Any],
    operation: Mapping[str, Any],
    candidate: Mapping[str, Any],
    observed_result: Mapping[str, Any] | None = None,
    evidence_text: str = "",
    max_evidence_chars: int = 7000,
) -> ProgressJudgment:
    """Judge whether one candidate transition is likely to advance a task."""

    prompt = f"""QUESTION:
{question}

JUDGMENT KIND:
{kind}

CURRENT TASK STATE JSON:
{json.dumps(task_state, indent=2, default=str)[:7000]}

OPERATION JSON:
{json.dumps(operation, indent=2, default=str)[:3000]}

CANDIDATE JSON:
{json.dumps(candidate, indent=2, default=str)[:3000]}

OBSERVED RESULT JSON:
{json.dumps(observed_result or {}, indent=2, default=str)[:3000]}

EVIDENCE PREVIEW:
{evidence_text[:max(0, max_evidence_chars)]}

Decide whether the candidate should be accepted for this operation.

Use this scale:
- fruitfulness_score: likelihood that accepting this candidate will improve the
  final declared deliverables or a source-supported universe estimate.
- novelty_score: likelihood that it adds non-duplicate information relative to
  CURRENT TASK STATE JSON.
- specificity_score: likelihood that it contains values or qualifiers at the
  grain of the requested final rows.
- coverage_delta: "none", "local", "table", or "universe".

Return JSON:
{{
  "decision": "accept | defer | reject",
  "fruitfulness_score": 0.0,
  "novelty_score": 0.0,
  "specificity_score": 0.0,
  "expected_progress": {{
    "coverage_delta": "none | local | table | universe",
    "reason": "short reason"
  }},
  "reason": "one concise sentence",
  "matched_needs": ["specific declared needs the candidate appears to satisfy"],
  "missing_needs": ["specific declared needs absent from the candidate"],
  "offtopic_axes": ["why this may be adjacent rather than useful"],
  "failure_modes": ["short generic failure labels"],
  "better_search_cues": ["external terms that could improve the next search"],
  "avoid_cues": ["external terms or source shapes that look unfruitful"]
}}"""
    parsed = await ask_json(
        llm,
        prompt,
        system_prompt=_PROGRESS_JUDGE_SYSTEM_PROMPT,
    )
    return coerce_progress_judgment(kind, parsed)


def coerce_progress_judgment(kind: str, raw: Any) -> ProgressJudgment:
    """Coerce an arbitrary JSON value into a stable progress judgment."""

    if not isinstance(raw, Mapping):
        return ProgressJudgment(
            kind=kind,
            decision="reject",
            reason="progress judge returned no object",
            raw={"unparseable": raw},
        )

    progress = raw.get("expected_progress")
    if not isinstance(progress, Mapping):
        progress = {}

    decision = str(raw.get("decision") or "").strip().lower()
    if decision not in _DECISIONS:
        accept = raw.get("accept")
        decision = "accept" if accept is True else "reject"

    coverage_delta = str(progress.get("coverage_delta") or "").strip().lower()
    if coverage_delta not in _COVERAGE_DELTAS:
        coverage_delta = "none"

    return ProgressJudgment(
        kind=kind,
        decision=decision,
        fruitfulness_score=_score(raw.get("fruitfulness_score")),
        novelty_score=_score(raw.get("novelty_score")),
        specificity_score=_score(raw.get("specificity_score")),
        coverage_delta=coverage_delta,
        reason=str(raw.get("reason") or progress.get("reason") or "").strip(),
        expected_progress_reason=str(progress.get("reason") or "").strip(),
        matched_needs=tuple(_string_list(raw.get("matched_needs"))),
        missing_needs=tuple(_string_list(raw.get("missing_needs"))),
        offtopic_axes=tuple(_string_list(raw.get("offtopic_axes"))),
        failure_modes=tuple(_string_list(raw.get("failure_modes"))),
        better_search_cues=tuple(_string_list(raw.get("better_search_cues"))),
        avoid_cues=tuple(_string_list(raw.get("avoid_cues"))),
        raw=dict(raw),
    )


def _score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        value = [value]

    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out
