"""Validate semantic mention communities and combine their evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable, Mapping, Sequence

from .types import FieldAssertion, LanguageResult, Mention, RuleResult


def _stable_id(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def candidate_components(result: LanguageResult) -> tuple[tuple[str, ...], ...]:
    """Return connected candidate sets; isolated mentions remain singletons."""

    neighbors = {mention.mention_id: set() for mention in result.mentions}
    for connection in result.connections:
        if (
            connection.left_mention_id not in neighbors
            or connection.right_mention_id not in neighbors
        ):
            raise ValueError("candidate connection references an unknown mention")
        neighbors[connection.left_mention_id].add(connection.right_mention_id)
        neighbors[connection.right_mention_id].add(connection.left_mention_id)

    components: list[tuple[str, ...]] = []
    remaining = set(neighbors)
    while remaining:
        seed = min(remaining)
        stack = [seed]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(neighbors[current] - component)
        remaining -= component
        components.append(tuple(sorted(component)))
    return tuple(components)


def resolution_view(result: LanguageResult) -> dict[str, object]:
    """Source-grounded input for one semantic partition over all mentions.

    Deterministic candidate connections are included as hints, never as a
    boundary on which mentions the semantic resolver may combine.  Exact
    identity-string agreement is therefore useful evidence without becoming a
    prerequisite for recognizing two differently written mentions of the same
    entity.
    """

    mentions = [
        {
            "mention_id": mention.mention_id,
            "entity_type": mention.entity_type,
            "source_row_ids": list(mention.source_row_ids),
            "admission_status": mention.admission_status,
            "assertions": [
                {
                    "field": assertion.field,
                    "raw_value": assertion.raw_value,
                    "comparison_value": assertion.comparison_value,
                    "comparison_type": assertion.comparison_type,
                    "source_row_ids": list(assertion.source_row_ids),
                    "source_span_ids": list(assertion.source_span_ids),
                }
                for assertion in mention.assertions
            ],
            "rule_results": [
                {
                    "rule_id": rule.rule_id,
                    "status": rule.status,
                    "evidence_ids": list(rule.evidence_ids),
                }
                for rule in mention.rule_results
            ],
        }
        for mention in result.mentions
    ]
    return {
        "mentions": mentions,
        "candidate_connections": [
            {
                "left_mention_id": connection.left_mention_id,
                "right_mention_id": connection.right_mention_id,
                "agreements": list(connection.agreements),
                "conflicts": list(connection.conflicts),
                "structural_basis": connection.structural_basis,
            }
            for connection in result.connections
        ],
    }


def _combined_rule_results(mentions: Sequence[Mention]) -> tuple[RuleResult, ...]:
    by_rule: dict[str, list[RuleResult]] = {}
    for mention in mentions:
        for result in mention.rule_results:
            by_rule.setdefault(result.rule_id, []).append(result)

    combined: list[RuleResult] = []
    for rule_id, results in by_rule.items():
        informative = {
            result.status
            for result in results
            if result.status != "unresolved"
        }
        status = (
            "unresolved"
            if len(informative) != 1
            else next(iter(informative))
        )
        combined.append(
            RuleResult(
                rule_id=rule_id,
                status=status,
                evidence_ids=tuple(
                    dict.fromkeys(
                        evidence_id
                        for result in results
                        for evidence_id in result.evidence_ids
                    )
                ),
                reason=(
                    "community evidence conflicts on this admission rule"
                    if len(informative) > 1
                    else ""
                ),
            )
        )
    return tuple(combined)


def _admission_status(results: Sequence[RuleResult]) -> str:
    if any(result.status == "rejected" for result in results):
        return "rejected"
    if any(result.status != "satisfied" for result in results):
        return "unresolved"
    return "accepted"


def _combine_mentions(mentions: Sequence[Mention]) -> Mention:
    member_ids = tuple(sorted(mention.mention_id for mention in mentions))
    mention_id = _stable_id({"community_members": member_ids})
    assertions: list[FieldAssertion] = []
    for mention in mentions:
        assertions.extend(mention.assertions)
    rules = _combined_rule_results(mentions)
    return Mention(
        mention_id=mention_id,
        entity_type=mentions[0].entity_type,
        source_row_ids=tuple(
            dict.fromkeys(
                row_id for mention in mentions for row_id in mention.source_row_ids
            )
        ),
        assertions=tuple(assertions),
        rule_results=rules,
        admission_status=_admission_status(rules),
    )


def apply_resolution(
    result: LanguageResult,
    communities: Iterable[Iterable[str]],
) -> LanguageResult:
    """Apply a model-proposed partition over the complete mention set.

    Every source-grounded mention must occur exactly once and no new mention
    may be invented.  Those are the deterministic address-space boundaries.
    Which presented mentions denote the same entity is the semantic decision;
    deterministic exact-match components are deliberately not a merge gate.
    """

    mention_by_id: Mapping[str, Mention] = {
        mention.mention_id: mention for mention in result.mentions
    }
    proposed = [tuple(dict.fromkeys(str(item) for item in group)) for group in communities]
    flattened = [mention_id for group in proposed for mention_id in group]
    if len(flattened) != len(set(flattened)):
        raise ValueError("mention resolution repeats a mention")
    if set(flattened) != set(mention_by_id):
        raise ValueError("mention resolution must partition every mention exactly once")
    for group in proposed:
        if not group:
            raise ValueError("mention resolution contains an empty community")
        entity_types = {mention_by_id[item].entity_type for item in group}
        if len(entity_types) != 1:
            raise ValueError("mention resolution joined different entity types")

    return LanguageResult(
        program=result.program,
        mentions=tuple(
            _combine_mentions([mention_by_id[item] for item in group])
            for group in proposed
        ),
        # Connections address the pre-resolution mentions and are consumed by
        # this operation. Keeping them would leave dangling mention ids.
        connections=(),
        spans=result.spans,
    )
