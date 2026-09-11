"""Swappable evidence-acceptance policy for the acquisition method leaf.

The acceptor decides; the evidence registry persists.  It receives typed
candidates and their already-staged source anchors and returns an immutable
decision over every candidate.  It performs no I/O and knows no ledger path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Protocol, runtime_checkable

from .control import stable_id
from .evidence_registry import (
    BEST_GUESS_ACCEPTANCE_RULE_VERSION,
    DIRECT_ACCEPTANCE_RULE_VERSION,
    BestGuessAssertionCandidate,
    DirectAssertionCandidate,
    SourceChunk,
    TextSpan,
)

ACCEPTANCE_POLICY_VERSION = "typed_evidence_acceptor_v1"


@dataclass(frozen=True)
class CandidateDecision:
    candidate_id: str
    evidence_kind: str
    accepted: bool
    rule_version: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "evidence_kind": self.evidence_kind,
            "accepted": self.accepted,
            "rule_version": self.rule_version,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AcceptanceDecision:
    policy_version: str
    candidates: tuple[CandidateDecision, ...]
    id: str

    @classmethod
    def create(
        cls, candidates: Iterable[CandidateDecision]
    ) -> "AcceptanceDecision":
        rows = tuple(candidates)
        if len({row.candidate_id for row in rows}) != len(rows):
            raise ValueError("acceptance decision contains duplicate candidate ids")
        payload = {
            "policy_version": ACCEPTANCE_POLICY_VERSION,
            "candidates": [row.to_dict() for row in rows],
        }
        return cls(
            policy_version=ACCEPTANCE_POLICY_VERSION,
            candidates=rows,
            id=stable_id({"acceptance_decision": payload}),
        )

    def accepted_ids(self, evidence_kind: str) -> frozenset[str]:
        return frozenset(
            row.candidate_id
            for row in self.candidates
            if row.accepted and row.evidence_kind == evidence_kind
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "policy_version": self.policy_version,
            "candidates": [row.to_dict() for row in self.candidates],
        }


@runtime_checkable
class EvidenceAcceptor(Protocol):
    """The replaceable policy slot bound to one method composition."""

    version: str

    def evaluate(
        self,
        *,
        direct_candidates: Iterable[DirectAssertionCandidate],
        best_guess_candidates: Iterable[BestGuessAssertionCandidate],
        spans: Iterable[TextSpan],
        chunks: Iterable[SourceChunk],
    ) -> AcceptanceDecision: ...


class TypedEvidenceAcceptor:
    """Accept reported exact matches and anchored numeric LLM best guesses."""

    version = ACCEPTANCE_POLICY_VERSION

    def evaluate(
        self,
        *,
        direct_candidates: Iterable[DirectAssertionCandidate],
        best_guess_candidates: Iterable[BestGuessAssertionCandidate],
        spans: Iterable[TextSpan],
        chunks: Iterable[SourceChunk],
    ) -> AcceptanceDecision:
        spans_by_id = {span.id: span for span in spans}
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        rows: list[CandidateDecision] = []
        for candidate in direct_candidates:
            accepted, reason = self._direct(candidate, spans_by_id)
            rows.append(
                CandidateDecision(
                    candidate_id=candidate.id,
                    evidence_kind="reported",
                    accepted=accepted,
                    rule_version=DIRECT_ACCEPTANCE_RULE_VERSION,
                    reason=reason,
                )
            )
        for candidate in best_guess_candidates:
            accepted, reason = self._best_guess(candidate, chunks_by_id)
            rows.append(
                CandidateDecision(
                    candidate_id=candidate.id,
                    evidence_kind="best_guess",
                    accepted=accepted,
                    rule_version=BEST_GUESS_ACCEPTANCE_RULE_VERSION,
                    reason=reason,
                )
            )
        return AcceptanceDecision.create(rows)

    @staticmethod
    def _direct(
        candidate: DirectAssertionCandidate,
        spans: Mapping[str, TextSpan],
    ) -> tuple[bool, str]:
        span = spans.get(candidate.span_id)
        if span is None or span.text != candidate.verbatim_text:
            return False, "missing_exact_source_span"
        if not candidate.subject_bound:
            return False, "unbound_subject"
        try:
            extracted = json.loads(candidate.value_json)
        except json.JSONDecodeError:
            return False, "invalid_extracted_value"
        if candidate.source_match_rule == "exact_text":
            accepted = str(extracted).strip() == span.text.strip()
        else:
            accepted = _numeric_value(extracted) == _numeric_value(span.text)
        return (
            (True, "reported_value_matches_source")
            if accepted
            else (False, "reported_value_does_not_match_source")
        )

    @staticmethod
    def _best_guess(
        candidate: BestGuessAssertionCandidate,
        chunks: Mapping[str, SourceChunk],
    ) -> tuple[bool, str]:
        if not candidate.subject_bound:
            return False, "unbound_subject"
        supporting = [chunks.get(chunk_id) for chunk_id in candidate.supporting_chunk_ids]
        if any(chunk is None for chunk in supporting):
            return False, "unresolved_supporting_chunk"
        if any(
            chunk is not None and chunk.source_version_id != candidate.source_version_id
            for chunk in supporting
        ):
            return False, "supporting_chunk_from_wrong_source_version"
        if not candidate.reasoning_basis.strip():
            return False, "missing_reasoning_basis"
        if candidate.reasoning_operator != "source_chunk_extract":
            return False, "not_llm_source_chunk_reasoning"
        try:
            parsed = json.loads(candidate.value_json)
        except json.JSONDecodeError:
            return False, "invalid_best_guess_value"
        numeric = _numeric_value(parsed)
        if numeric is None:
            return False, "best_guess_is_not_numeric"
        if candidate.value_type == "integer" and numeric != numeric.to_integral_value():
            return False, "best_guess_is_not_integer"
        return True, "anchored_llm_numeric_reasoning"


_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _numeric_value(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    match = _NUMBER_RE.fullmatch(text) or _NUMBER_RE.search(text)
    if match is None:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None
