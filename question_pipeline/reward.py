"""Reward: real datapoints added, per unit cost.

This module replaced ``table_fill_v3``, a coverage scorer over table cells. The
thing it scored -- distinct field/value pairs, cited source IDs, capped source
repeats -- is **operational volume**. Every one of those numbers rises when the
pipeline materializes more rows, accepts more sources, or re-extracts what it
already had, whether or not anything was learned. A system optimized against it
gets busier without getting better, and the failure is invisible because every
number goes up.

What replaces it counts **datapoints**. There are exactly two kinds, and they
are the two the reward charter names:

1. **Verbatim** -- a value a source states, resolved through a field-scoped
   join into the set of sources the run actually accepted.
2. **Evidenced best guess** -- a derived value carrying the decision that
   accepted it and the sources named for that field. The judgment and the
   sources are part of the datapoint; without them it is a candidate.

Both arrive here the same way: as a :class:`~question_pipeline.criteria.
CriterionTransition` produced by ``criteria.diff_snapshots``. This module does
**not** define what a criterion or a transition is. ``criteria.py`` owns that,
and 3B joins the same IDs; a second definition here would make the two
incomparable while still producing numbers.

What is never credited, at any weight
-------------------------------------

Operational volume in every disguise, and the disguises are the point:

* ``CRITERION_ADDED`` -- rows materialized, with an ID on it. It outnumbers
  ``SUPPORT_GAINED`` by an order of magnitude on real runs.
* ``EVIDENCE_CHANGED`` -- re-extraction churn. Values fold into the snapshot ID
  and normalization only casefolds, so an extractor rephrasing "12 patients" as
  "twelve patients" emits one. Rewording must not become yield.
* ``BASIS_CHANGED`` -- on real runs every occurrence was
  ``row_ref_unmatched -> row_ref_accepted``. The status did not move; a source
  got accepted. Crediting it pays per accepted source times criterion fan-out.
* ``CRITERION_REMOVED``, and any function of snapshot cardinality -- counts,
  ratios, per-round deltas. Cardinality rises with traversal as a numerator and
  falls with it as a denominator.
* ``len(values)``, per-value counts, per-source counts.
* ``basis_strength`` as a weight, summand, or average. See
  :data:`~question_pipeline.criteria.BASIS_STRENGTH`: it is non-monotone in
  trustworthiness and ``accepted_source_ids`` is optional, so a
  strength-weighted reward is *raised by declining to verify*. It is used here
  as nothing at all -- :data:`CREDITABLE_EVIDENCE_BASES` names the admissible
  bases outright, so there is no threshold to slip.
* ``ROW_REF_ACCEPTED`` and below as verified support. Blind re-derivation put it
  at 0.450 against unresolved's 0.417 -- 0.033 of discrimination, inside noise --
  and 22,461 ``row_ref_unmatched`` states sit one source-acceptance away from it
  with no new data.
* Producer self-verdicts (``completeness``, ``evidence_gap``) by any route.
* Any table that is not a declared deliverable. The caller passes an allowlist
  into the projection; see :func:`~question_pipeline.criteria.project_rows`.
* Completion scope. It is a constraint and a state input. A run may be
  scope-satisfied and still incomplete.

There is no negative term
-------------------------

Nothing here subtracts. The reason recorded here was that ``SUPPORT_LOST`` was
observed zero times across every round pair of a real run and that the
supported count is therefore monotone. **That is false and should not be
repeated.** A recorded table-fill run reports ``support_lost: 734`` and
``criterion_removed: 2874`` in a single round's ``uncredited_volume``; support
is lost routinely, most visibly when a re-traversal re-keys a subject and the
old criterion IDs cease to exist.

What survives is the narrower claim: with no ``conflicting`` status, a
criterion does not leave ``supported`` by being *discovered wrong*, so a loss
here does not carry the meaning a penalty would need. Whether that warrants a
negative term is a reward-design question owned by a phase, not something to
settle in a comment. It is left open deliberately rather than closed by an
argument that does not hold.

Delayed credit
--------------

A source accepted at round N may not yield a criterion until round N+2 --
traversal and extraction lag ingest. Crediting only same-round yield would
discard that, and crediting any yield that touches any accepted source would
credit re-traversal of papers the run has held for ten rounds, which is where
nearly all of the raw ``SUPPORT_GAINED`` volume actually comes from.

The rule that does neither is the **first-harvest credit window**: a source is
creditable from the round it is first accepted until the first round in which it
credits something, and is retired after that. An acquisition is credited for one
harvest, whenever that harvest lands. It reduces exactly to the round-scoped
rule when yield is immediate, it never pays twice for one paper, and it has no
tunable parameter. The window and the set of already-credited criteria live in
:class:`CreditLedger`, which the caller carries across rounds.

Cost
----

Costs are 1B's :class:`~question_pipeline.costs.CostRecord`, summed over one
round. **Round level is the finest granularity that is honest here.**
``CriterionTransition`` carries no action, decision, or task ID. A
source-attributable transition has an exact path through ``gained_source_ids``,
but searches that returned nothing, traversal, extraction, and best-guess
operators join only through the snapshot ID, which every action in the round
shares -- that is attribution by timing coincidence. Dividing one transition by
one action's cost would produce a precise number about nothing.

When no cost record exists -- every run recorded before cost accounting landed
-- the ratios are ``None`` and :attr:`RewardReport.cost_available` is false.
They are not zero and they are not infinity: a run whose cost is unknown must
not compare equal to a run that was free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .criteria import (
    CRITERIA_PROJECTION_VERSION,
    BASIS_STRENGTH,
    CriteriaSnapshot,
    CriterionTransition,
    EvidenceBasis,
    TransitionKind,
    diff_snapshots,
)


__all__ = [
    "REWARD_VERSION",
    "REWARD_COMPONENT_COLUMNS",
    "CREDITABLE_EVIDENCE_BASES",
    "CREDITABLE_TRANSITION_KINDS",
    "DatapointKind",
    "CreditedDatapoint",
    "CreditLedger",
    "CostVector",
    "RewardReport",
    "score_criterion_yield",
    "aggregate_round_cost",
    "load_seed_best_guess_rows",
    "merge_best_guess_rows",
]


#: Bumped from ``table_fill_v3``.
#:
#: **What changed.** The unit of reward moved from a table cell to a criterion
#: transition, and from coverage to yield. ``table_fill_v3`` scored six
#: components -- new cell values, new source-backed cell values, new capped
#: source-support units, new best-guess slots, new cited source IDs, and a
#: saturation penalty -- each through a ``sqrt`` transform with a hand-set
#: weight. Five of the six are operational volume; the sixth penalized volume,
#: which is not the same as rewarding yield. ``criterion_yield_v1`` scores one
#: thing: criteria that became supported on a field-scoped accepted basis
#: because of a source the run had not yet harvested, divided by what the round
#: paid.
#:
#: **What it means for historical traces.** Nothing scored under
#: ``table_fill_v3`` is comparable to anything scored under this version, and
#: the two must not be plotted on one axis or differenced. The old score is
#: unbounded above and grows with row count; this one is a rate whose numerator
#: is capped by the number of criteria that can ever exist. A rise from a
#: ``table_fill_v3`` run to a ``criterion_yield_v1`` run is not an improvement,
#: it is a unit change. Traces carry :data:`REWARD_VERSION` so the mismatch
#: surfaces as a refused comparison rather than as a trend.
#:
#: This version also depends on the projection version, and **this comment no
#: longer names it**. It named v2 while runs recorded v3, then named v3 while
#: the code carried v4, and the code has since moved to v5. A version comment
#: that lies is the exact instrument the versioning rule depends on, and the
#: only fix that holds is to stop restating a value that lives somewhere else:
#: :data:`~question_pipeline.criteria.CRITERIA_PROJECTION_VERSION` is the one
#: place it is declared, and every trace stamps it. Criterion IDs differ between
#: projection versions, so traces from two of them will not join at all -- read
#: the version off the trace.
REWARD_VERSION = "criterion_yield_v1"

REWARD_COMPONENT_COLUMNS = [
    "component",
    "direction",
    "raw_value",
    "score",
    "interpretation",
]


class DatapointKind(str, Enum):
    """The two kinds of real datapoint, and there are only two."""

    #: A source states the value, joined at field scope.
    VERBATIM = "verbatim"

    #: A derived value carrying the decision that accepted it and the sources
    #: named for that field.
    EVIDENCED_BEST_GUESS = "evidenced_best_guess"


#: The only evidence bases a credited datapoint may rest on, named outright
#: rather than derived from a strength threshold.
#:
#: Naming them is deliberate. A ``basis_strength >= 7`` predicate looks
#: equivalent and is not: it couples credit to a ladder that is explicitly not
#: an ordering of trustworthiness, so a later reordering, or a new member
#: inserted at a convenient rung, would silently widen what counts as evidence.
#: A set changes only when someone edits this line.
CREDITABLE_EVIDENCE_BASES: Mapping[EvidenceBasis, DatapointKind] = {
    EvidenceBasis.RESOLVED_ASSERTION_CHAIN: DatapointKind.VERBATIM,
    EvidenceBasis.FIELD_REF_ACCEPTED: DatapointKind.VERBATIM,
    EvidenceBasis.JUDGED_BEST_GUESS_ACCEPTED: DatapointKind.EVIDENCED_BEST_GUESS,
}

#: The only transition kind that can carry credit. The other five are counters.
CREDITABLE_TRANSITION_KINDS = frozenset({TransitionKind.SUPPORT_GAINED})


@dataclass(frozen=True)
class CreditedDatapoint:
    """One real datapoint, joined to the transition that established it.

    Every field here is an identifier or a closed vocabulary member. Nothing is
    a count, a timestamp, or free text: credit joins by ID, so an attribution
    that survives a rename has to be built out of things that do not change
    when prose does.
    """

    transition_id: str
    criterion_id: str
    kind: DatapointKind
    basis: EvidenceBasis
    table: str
    field: str
    subject_id: str
    #: The sources whose first harvest this datapoint is. The exact ID path
    #: from a datapoint back to the acquisition that bought it.
    crediting_source_ids: tuple[str, ...]
    #: The round those sources were first accepted -- which is what the cost of
    #: this datapoint is measured against, not the round it surfaced in.
    attributed_round: int
    #: The round the transition was actually observed. Equal to
    #: ``attributed_round`` when yield is immediate, later when it is delayed.
    realized_round: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_transition_id": self.transition_id,
            "criterion_id": self.criterion_id,
            "datapoint_kind": self.kind.value,
            "evidence_basis": self.basis.value,
            "table": self.table,
            "field": self.field,
            "subject_id": self.subject_id,
            "crediting_source_ids": list(self.crediting_source_ids),
            "attributed_round_index": self.attributed_round,
            "realized_round_index": self.realized_round,
        }


@dataclass(frozen=True)
class CreditLedger:
    """What credit has already been paid. Carried across rounds by the caller.

    Two sets, both of IDs:

    ``credited_criterion_ids`` -- a criterion is a datapoint once. Support is
    monotone, so without this a criterion re-emitting ``SUPPORT_GAINED`` after a
    re-projection would be paid for twice.

    ``harvested_source_ids`` -- sources that have already credited something and
    are retired from the credit window. This is what stops re-traversal of a
    long-held paper from reading as new yield, and what lets a source whose
    yield arrives three rounds late still be paid once.
    """

    credited_criterion_ids: frozenset[str] = frozenset()
    harvested_source_ids: frozenset[str] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {
            "reward_version": REWARD_VERSION,
            "credited_criterion_ids": sorted(self.credited_criterion_ids),
            "harvested_source_ids": sorted(self.harvested_source_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "CreditLedger":
        payload = payload or {}
        return cls(
            credited_criterion_ids=frozenset(
                str(value) for value in payload.get("credited_criterion_ids") or ()
            ),
            harvested_source_ids=frozenset(
                str(value) for value in payload.get("harvested_source_ids") or ()
            ),
        )


@dataclass(frozen=True)
class CostVector:
    """What one round paid, summed from 1B's per-action records.

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

        A round with records but zero calls really was free. A round with no
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
    """One round's yield, its cost, and the ledger the next round starts from."""

    reward_version: str
    criteria_projection_version: str
    round_index: int
    before_snapshot_id: str
    after_snapshot_id: str
    datapoints: tuple[CreditedDatapoint, ...]
    cost: CostVector
    ledger: CreditLedger
    #: Volume observed and deliberately not scored, recorded so a reader can see
    #: what the reward declined to pay for.
    uncredited: Mapping[str, int] = field(default_factory=dict)
    #: The transitions behind every `uncredited` count, keyed by the same key.
    #: A count says how many negative observations there were; this says WHICH,
    #: so they can be joined to sources and criteria instead of re-run.
    uncredited_instances: Mapping[str, tuple[Mapping[str, Any], ...]] = field(
        default_factory=dict
    )

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
                    "Criteria that became supported on a field-scoped accepted "
                    "basis, on the first harvest of the source that carried them."
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
                        "Observed and deliberately not scored: operational "
                        "volume, not a datapoint."
                    ),
                }
            )
        return rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "reward_version": self.reward_version,
            "criteria_projection_version": self.criteria_projection_version,
            "round_index": self.round_index,
            "before_criteria_snapshot_id": self.before_snapshot_id,
            "after_criteria_snapshot_id": self.after_snapshot_id,
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
            "uncredited_instances": {
                key: [dict(item) for item in values]
                for key, values in sorted(self.uncredited_instances.items())
            },
            "datapoints": [datapoint.to_dict() for datapoint in self.datapoints],
            "credit_ledger": self.ledger.to_dict(),
        }


def aggregate_round_cost(
    cost_records: Iterable[Mapping[str, Any]] | None,
    round_index: int | None = None,
) -> CostVector:
    """Sum 1B cost records, optionally restricted to one round.

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
        if round_index is not None and _int(record.get("round_index")) != int(round_index):
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


def score_criterion_yield(
    before: CriteriaSnapshot | None,
    after: CriteriaSnapshot | None,
    *,
    round_index: int,
    first_accepted_round: Mapping[str, int] | None = None,
    ledger: CreditLedger | None = None,
    cost_records: Iterable[Mapping[str, Any]] | None = None,
    cost: CostVector | None = None,
) -> RewardReport:
    """Score one round: real datapoints added, over what the round paid.

    ``first_accepted_round`` maps a source ID to the round it was first
    accepted. It comes from the run's own source records or 1C's ledger --
    **never from the transition**. ``gained_source_ids`` is new *to the
    criterion*, not new to the run: ``_transition_kind`` emits
    ``SUPPORT_GAINED`` when the criterion did not exist before, so for a
    criterion minted this round it lists every source cited however old.
    Crediting on its non-emptiness would credit nearly all re-traversal.

    ``ledger`` carries credit state across rounds; pass the previous round's
    :attr:`RewardReport.ledger` back in. Omitting it re-opens every source's
    credit window and re-credits every criterion, which is why the returned
    report carries the next ledger rather than leaving the caller to rebuild it.

    Costs come from ``cost_records`` (filtered to ``round_index``) or from an
    already-summed ``cost``. Supplying neither is legitimate -- runs recorded
    before cost accounting have none -- and yields a report whose ratios are
    ``None``.
    """

    before = before if before is not None else None
    transitions = diff_snapshots(before, after)
    first_accepted = {
        str(source): _int(value)
        for source, value in (first_accepted_round or {}).items()
        if str(source)
    }
    ledger = ledger if ledger is not None else CreditLedger()

    credited: list[CreditedDatapoint] = []
    newly_credited: set[str] = set()
    newly_harvested: set[str] = set()
    uncredited: dict[str, int] = {}
    # THE NEGATIVE INSTANCES, KEPT RATHER THAN COUNTED.
    #
    # `uncredited` is a histogram, and a histogram cannot be joined, audited, or
    # re-derived. The transitions counted here are precisely the negative
    # observations the yield question needs -- a criterion that gained support
    # which did not clear the credit floor is the "examined, credited nothing"
    # case -- and they were constructed in memory, tallied, and dropped. One
    # recorded round holds 751 of them.
    #
    # Every instance keeps its criterion id and its source ids, so the counts
    # remain exactly what they were and the same data can now be joined back to
    # sources and criteria. Nothing is sampled or capped: dropping the ids while
    # keeping the count is a truncation to zero, and the whole point is that the
    # negative cases are the scarce ones.
    uncredited_instances: dict[str, list[dict[str, Any]]] = {}

    def _note_uncredited(key: str, transition: CriterionTransition) -> None:
        uncredited[key] = uncredited.get(key, 0) + 1
        uncredited_instances.setdefault(key, []).append(
            {
                "criteria_transition_id": transition.id,
                "criterion_id": transition.criterion_id,
                "table": transition.table,
                "field": transition.field,
                "subject_id": transition.subject_id,
                "before_status": transition.before_status,
                "after_status": transition.after_status,
                "before_basis": transition.before_basis,
                "after_basis": transition.after_basis,
                "gained_source_ids": list(transition.gained_source_ids),
                "after_source_ids": list(transition.after_source_ids),
            }
        )

    for transition in sorted(transitions, key=lambda item: item.id):
        if transition.kind not in CREDITABLE_TRANSITION_KINDS:
            _note_uncredited(transition.kind.value, transition)
            continue

        basis = _basis(transition.after_basis)
        kind = CREDITABLE_EVIDENCE_BASES.get(basis) if basis is not None else None
        if kind is None:
            _note_uncredited(
                f"support_gained_below_floor:{transition.after_basis or 'unknown'}",
                transition,
            )
            continue

        if transition.criterion_id in ledger.credited_criterion_ids:
            _note_uncredited("support_gained_already_credited", transition)
            continue

        crediting = _crediting_sources(
            transition,
            round_index=round_index,
            first_accepted=first_accepted,
            harvested=ledger.harvested_source_ids,
        )
        if not crediting:
            _note_uncredited("support_gained_no_unharvested_source", transition)
            continue

        credited.append(
            CreditedDatapoint(
                transition_id=transition.id,
                criterion_id=transition.criterion_id,
                kind=kind,
                basis=basis,  # type: ignore[arg-type]
                table=transition.table,
                field=transition.field,
                subject_id=transition.subject_id,
                crediting_source_ids=crediting,
                attributed_round=min(
                    first_accepted.get(source, round_index) for source in crediting
                ),
                realized_round=int(round_index),
            )
        )
        newly_credited.add(transition.criterion_id)
        newly_harvested.update(crediting)

    resolved_cost = cost if cost is not None else aggregate_round_cost(cost_records, round_index)

    return RewardReport(
        reward_version=REWARD_VERSION,
        criteria_projection_version=CRITERIA_PROJECTION_VERSION,
        round_index=int(round_index),
        before_snapshot_id=before.id if before is not None else "",
        after_snapshot_id=after.id if after is not None else "",
        datapoints=tuple(credited),
        cost=resolved_cost,
        ledger=CreditLedger(
            credited_criterion_ids=ledger.credited_criterion_ids | newly_credited,
            harvested_source_ids=ledger.harvested_source_ids | newly_harvested,
        ),
        uncredited=dict(sorted(uncredited.items())),
        uncredited_instances={
            key: tuple(values) for key, values in sorted(uncredited_instances.items())
        },
    )


def _crediting_sources(
    transition: CriterionTransition,
    *,
    round_index: int,
    first_accepted: Mapping[str, int],
    harvested: frozenset[str],
) -> tuple[str, ...]:
    """The sources whose first harvest this transition is, if any.

    A source qualifies when it was first accepted at or before this round, has
    not yet credited anything, and this transition's criterion gained it. The
    "at or before" is what carries delayed credit; the "has not yet credited
    anything" is what stops re-traversal from being paid for. A source with no
    recorded acceptance round is not creditable -- an unknown acquisition cannot
    be the acquisition that bought this.
    """

    return tuple(
        sorted(
            source
            for source in transition.gained_source_ids
            if source in first_accepted
            and first_accepted[source] <= int(round_index)
            and source not in harvested
        )
    )


def _basis(value: str) -> EvidenceBasis | None:
    try:
        return EvidenceBasis(str(value or ""))
    except ValueError:
        return None


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
        for json_path in sorted(directory.glob("round_*_best_guess_context.json")):
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


# ``BASIS_STRENGTH`` is imported for one purpose: to assert at import time that
# nothing creditable sits below the field-scoped accepted rung. If a future edit
# adds a member to CREDITABLE_EVIDENCE_BASES that a blind reader could not
# distinguish from no support, this fails loudly here rather than quietly
# inflating every yield number in the build.
_FLOOR = BASIS_STRENGTH[EvidenceBasis.FIELD_REF_ACCEPTED]
for _basis_member in CREDITABLE_EVIDENCE_BASES:
    if BASIS_STRENGTH[_basis_member] < _FLOOR:
        raise AssertionError(
            f"{_basis_member.value} is below the field-scoped accepted floor; "
            "row-scoped co-location is not verified support"
        )
del _basis_member
