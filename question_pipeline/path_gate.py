"""The path-selection gate: routes become table candidates here (phase 2B).

Traversal produces routes.  Operational table formation consumes records.  This
module is the boundary between the two, and it exists so that boundary is a
**recorded policy decision** rather than a silent filter: every route considered
and every route taken survives in the trace, with a class label saying why.

What this module is not
-----------------------

*It does not score.*  Scoring is :mod:`question_pipeline.path_features`, and its
weights, calibration, and reason vocabulary are that module's.  This module
applies a score and records what it did with it.

*It does not rank.*  Ranking is :class:`~question_pipeline.control.
StaticTableFillPolicy` at :attr:`~question_pipeline.control.ControlSurface.
PATH_SELECTION`.  A surface is added here; no policy is.

*It does not decide what "supported" means.*  That is
:mod:`question_pipeline.criteria`.  This module reads a projection and joins to
it by the projection's own subject id.

The line this module must not cross
-----------------------------------

**A record that reports a real gap is a true finding about the literature, and
deleting it makes the system look more complete than it is.**  So the gate
demotes *routes*; it never deletes *records* that express missing evidence.

That is enforced structurally rather than hoped for, and the construction is
worth spelling out because it is the whole design:

1. A criterion is ``SUPPORTED`` exactly when some row of its subject carries a
   non-missing value for that field (``criteria._project_field``).  So removing
   a row can remove support, and a per-row rule cannot be safe.
2. Therefore the gate demotes at **subject** granularity, using the
   projection's own subject id: a subject is demoted only when *every* one of
   its rows is demotable.  A retained subject keeps all of its rows, so its
   criteria are unchanged -- not "probably unchanged", identical inputs.
3. A subject with **any** supported criterion is exempt outright.  So a record
   whose independently sourced fields are supported stays, with its other
   criteria unresolved, which is the registered non-goal control.
4. A demoted subject therefore has no supported criterion, meaning no row of it
   carries a value in any criteria field.  It contributes no supported
   criterion to lose and no *value* to the table's observed column set.

Step 4 leaves exactly one residual, named rather than papered over: without a
declared table spec, ``criteria._criteria_fields`` derives the criteria set
from the *keys present* on rows, not from the values.  A demoted subject that
was the only carrier of some column key would remove that column -- and hence
one unresolved criterion -- from every other subject.  That cannot remove
support and cannot invent it, but a subject whose *only* unresolved criterion
came from such a column would stop counting as partial.  The gate does not
engineer around this; :func:`gate_rows` reports the pre- and post-gate column
sets so it is measured instead of assumed.

Why nothing is dropped by default
---------------------------------

:data:`PathGateSettings.enabled` defaults to ``False`` and the shipped pipeline
admits every row.  Phase 2A's experiment failed on both of its registered
routes: ``path_score`` did not predict the LLM's later verdict, and a blind
reading of the source chunks did not separate top-quintile routes from
bottom-quintile ones.  A gate that deleted rows on a score with no established
validity would be asserting something the measurement does not support.  What
2A *did* establish is that the score's resolution varies enormously -- four of
six features had no inputs on 89% of that corpus -- so
:attr:`PathGateSettings.min_inputs_present` refuses to gate at all on a starved
score, and the record says how many features were actually measured.

The surface is live regardless: the decision, the candidates, and the
dispositions are recorded on every run whether or not anything is demoted.
Recording what was considered is the deliverable; dropping is a configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .control import (
    ControlSurface,
    DecisionContext,
    PathCandidate,
    PolicyDecision,
    TableFillControlPolicy,
    TargetRef,
)
from .criteria import CriteriaSnapshot, row_subject_ids
from .path_features import (
    FEATURE_NAMES,
    PathRow,
    PathScore,
    PathScoringContext,
    score_rows,
)

__all__ = [
    "PATH_GATE_VERSION",
    "PathGateDisposition",
    "PathGateReason",
    "PathGateSettings",
    "GatedRow",
    "PathGateResult",
    "gate_rows",
]


#: Bumped when a change would move which rows this gate admits for an unchanged
#: input.  Carried on every result, so a consumer comparing two runs' admitted
#: sets across a version change sees a mismatch rather than a difference it
#: attributes to the data.
#:
#: ``v1`` -> ``v2``: a row the scorer could not score at all -- no route, no
#: terminal, no endpoint, reported as
#: :attr:`~question_pipeline.control.PathExclusionReason.NO_ROUTE_EVIDENCE` --
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
