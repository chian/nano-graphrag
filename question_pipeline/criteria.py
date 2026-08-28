"""Projection from table rows to per-criterion state, and snapshots over it.

This module is the **only** boundary in the codebase that reads table rows as
task progress.  Goal, reward, policy, and attribution code consumes the
projection below instead of parsing row fields for itself.  If another module
is inspecting a row to decide whether something is supported, that logic
belongs here.

It is deliberately pure.  Nothing here imports the pipeline, a graph adapter, a
search provider, an LLM client, a table-spec loader, or any persistence layer,
and nothing here performs I/O.  Rows are plain mappings and specs are plain
mappings (or any object exposing the same attributes), so every type in this
file can be constructed by hand and exercised in isolation.

What a criterion is
-------------------

One criterion is one *(table, semantic subject, field)* triple: "for this
subject in this table, is this field established?"  The identifier is derived
through :func:`question_pipeline.control.stable_id` from exactly those three
things, so the same logical criterion carries the same ID across rounds and
across separate runs.

Two exclusions from the ID are load-bearing, mirroring the discipline in 1A
where an action ID excludes the mutable score:

* **No spec identifier.**  Observed table specs grow columns as rows arrive.
  Folding a spec digest into the criterion ID would renumber every criterion
  the moment a new column appeared, and every cross-round join would break
  silently.
* **No values, no round index, no counts.**  A criterion is the *question*, not
  the answer to it.  Its state is what changes between snapshots.

The subject's own identity fields never become criteria of that subject.  A
criterion over the very field that identifies the subject is supported by
construction, and counting it would inflate every yield number downstream.

Be honest about the evidence basis
----------------------------------

The five-link assertion chain -- field assertion, source-local observation,
evidence item, source version, source document -- does not exist in this tree.
There is no evidence registry.  What a row actually offers is a value and, at
best, some provenance references.

So every :class:`CriterionState` records **which basis was used**, as a typed
:class:`EvidenceBasis`, and the names say what was really joined:

* a *field*-scoped reference (``<field>_source_refs`` and friends) is provenance
  the producer attached to that field;
* a *row*-scoped reference (``source_refs`` and friends) is provenance attached
  to the whole row -- co-location, not a field-level join;
* ``ACCEPTED`` means the reference resolved into a caller-supplied set of
  accepted source IDs, ``UNMATCHED`` means it did not, and ``UNCHECKED`` means
  no accepted-source set was supplied and the projection did not check.

:attr:`EvidenceBasis.RESOLVED_ASSERTION_CHAIN` is declared and is never emitted
here; it is the slot the registry will fill.  :data:`PRODUCIBLE_EVIDENCE_BASES`
enumerates what this version can actually produce, so a later reward can demand
a stronger basis without silently redefining what ``supported`` meant in
historical traces.

The second kind of datapoint (v2)
---------------------------------

``criteria_projection_v2`` adds the ``judged_best_guess_*`` bases.  A row cell
can be established two ways: a source *states* it, or an operator *derives* it
and says from which source and why.  v1 could only see the first, so a run
whose extraction never populates a column had no way to record that the value
was recovered, judged, and sourced -- it projected ``unresolved`` and the
recovery was invisible to everything downstream.

A judged best guess is admitted only as the whole package: the derived value,
the operator that produced it, the acceptance decision, and the source IDs that
operator selected *for that column*.  Without the judgment and the sources it is
a candidate, not a datapoint, and :func:`project_rows` will not take it.  Two
guards keep it from becoming a laundering route for row-level co-location:

* it applies **only** where no row of the subject supplies the field, so it can
  never overwrite or upgrade a stated value; and
* its ``source_ids`` come from the resolution, not from the row.  On real
  recorded runs those are a strict subset of the row's own sources in 425 of
  452 cases -- the operator names which of the row's sources supports *this*
  column, which is the field-scoped join v1's row-scoped bases could not make.

**This is a version bump, and the bump is the point.**
:data:`CRITERIA_PROJECTION_VERSION` is folded into every criterion and subject
ID, so no v1 ID joins to a v2 ID.  ``supported`` means something different in
v2 -- it now includes derived values -- and a v1 trace compared against a v2
trace would silently compare two different quantities.  A failed join is the
honest form of that incomparability.

What this module refuses to do
------------------------------

*It does not read the pipeline's own verdict about a row.*  Fields such as
``completeness`` and ``evidence_gap`` are the producer grading itself; treating
them as evidence would make the projection a mirror rather than a measurement.
They are excluded from the criteria set and never consulted for status.

*It does not infer status from counts.*  A criterion's status comes from its
own evidence.  Two inputs with identical row and source counts and different
evidence project differently, and no status anywhere is a function of how many
rows or sources exist.

*It does not report ``conflicting``.*  Multiple distinct values for one
criterion is deterministically observable and is recorded in
:attr:`CriterionState.values`, but the rows cannot distinguish a genuine
contradiction from a legitimately multi-valued measurement.  Naming that
``conflicting`` would assert a semantics the input does not carry, so the
distinction is left as data for a later phase that can resolve it.

*It does not score, rank, gate, or decide completion.*  It projects.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .control import canonical_subject_identity, stable_id
from .provenance import is_provenance_name

__all__ = [
    "CRITERIA_PROJECTION_VERSION",
    "CRITERIA_SNAPSHOT_VERSION",
    "CRITERIA_TRANSITION_VERSION",
    "BASIS_STRENGTH",
    "DATAPOINT_EXCLUSION_CLASSES",
    "PRODUCIBLE_EVIDENCE_BASES",
    "datapoint_exclusion_class",
    "CriterionStatus",
    "EvidenceBasis",
    "TransitionKind",
    "CriterionRef",
    "CriterionState",
    "CriteriaSnapshot",
    "CriterionTransition",
    "project_rows",
    "admits_judged_best_guess",
    "datapoint_fields",
    "diff_snapshots",
    "empty_snapshot",
    "is_datapoint_field",
    "is_missing_value",
    "missing_tokens",
    "subject_key",
    "normalize_key_value",
    "row_subject_ids",
]


#: v3: the criterion field set changed (canonical graph keys and provenance
#: columns are no longer datapoints) and `FIELD_REF_ACCEPTED`'s producing
#: condition changed (field-scoped provenance is now derived and reachable,
#: where it was previously unreachable and identically zero). Counts before and
#: after are not comparable, and the version is folded into criterion ids so a
#: v2/v3 join fails visibly rather than silently comparing different things.
#: v4: engine-minted structural columns (`occurrence_count`, `items`,
#: `item_ids`, `row_count`, `contributing_rows`) stopped projecting as
#: criteria. Excluding columns changes WHICH criteria exist, hence criterion
#: ids, hence every downstream join -- so this is a projection-version change
#: even though no reward formula moved. `reward.py` records that criterion ids
#: do not join across projection versions; that is exactly what this protects.
#: v5: `_MISSING_STRINGS` gained "not specified in current evidence" -- the
#: token `goals`, `pipeline` and this module's own table writer already treat as
#: absence -- so that one module owns what "nothing here" means. This is a
#: PROJECTION-VERSION change, not a cleanup, because `_missing` gates
#: `_subject_key_values` (:861) and `_row_content` (:965) as well as
#: `_project_field` (:1059): a row whose declared key column carries the token
#: stops contributing that pair, `bound` flips, and `_subject_for_row` hashes
#: both into the subject id. So the change moves WHICH SUBJECTS EXIST, hence
#: criterion ids, hence every downstream join. v4 and v5 criterion, subject,
#: snapshot and transition ids DO NOT JOIN. The honest direction is "different
#: criteria, not fewer": for a criterion whose id does not move a cell carrying
#: the token drops from SUPPORTED to UNRESOLVED, but where the token sits in a
#: declared subject-key column the subject is re-keyed and its criteria are
#: removed and re-minted -- and a re-minted criterion is `SUPPORT_GAINED`, which
#: `reward.CreditLedger` cannot suppress because it dedupes by criterion id.
CRITERIA_PROJECTION_VERSION = "criteria_projection_v5"
CRITERIA_SNAPSHOT_VERSION = "criteria_snapshot_v1"
CRITERIA_TRANSITION_VERSION = "criteria_transition_v1"

#: Longest display form retained for one observed value.
MAX_VALUE_LENGTH = 240


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class CriterionStatus(str, Enum):
    """Whether a criterion is established by the rows it was projected from.

    Only two members.  ``conflicting`` is deliberately absent -- see the module
    docstring; multiplicity is carried on :attr:`CriterionState.values` instead
    of being labelled with a semantics the rows do not support.
    """

    SUPPORTED = "supported"
    UNRESOLVED = "unresolved"


class EvidenceBasis(str, Enum):
    """How a criterion's state was established, as an explicit claim.

    The member is a statement about the join that was actually performed.
    Nothing here may be emitted for a join the projection did not do.
    """

    #: Reserved for the evidence registry: field assertion -> source-local
    #: observation -> evidence item -> source version -> source document.
    #: That registry does not exist in this tree and this member is never
    #: produced by :func:`project_rows`.  It is declared so a later reward can
    #: require it by name without rewriting historical traces.
    RESOLVED_ASSERTION_CHAIN = "resolved_assertion_chain"

    #: A provenance reference scoped to this field resolved into the supplied
    #: accepted-source set.
    FIELD_REF_ACCEPTED = "field_ref_accepted"

    #: A field-scoped reference was present, an accepted-source set was
    #: supplied, and no reference matched it.
    FIELD_REF_UNMATCHED = "field_ref_unmatched"

    #: A field-scoped reference was present and no accepted-source set was
    #: supplied.  The projection did not check it.
    FIELD_REF_UNCHECKED = "field_ref_unchecked"

    #: A row-scoped reference resolved into the accepted-source set.  The
    #: reference belongs to the row, not to this field: co-location only.
    ROW_REF_ACCEPTED = "row_ref_accepted"

    #: Row-scoped references present, an accepted-source set was supplied, and
    #: none matched.
    ROW_REF_UNMATCHED = "row_ref_unmatched"

    #: Row-scoped references present and unchecked.
    ROW_REF_UNCHECKED = "row_ref_unchecked"

    #: A value is present and the row carries no provenance reference at all.
    #: The only thing asserting this datapoint is the row itself.
    ROW_VALUE_ONLY = "row_value_only"

    #: An operator derived this value for this field, the run accepted its
    #: decision, and the sources that operator named for *this field* resolved
    #: into the supplied accepted-source set.  The value is derived, not
    #: quoted; the judgment and the sources are part of the datapoint.
    JUDGED_BEST_GUESS_ACCEPTED = "judged_best_guess_accepted"

    #: An accepted judged best guess whose named sources did not resolve into
    #: the accepted-source set.
    JUDGED_BEST_GUESS_UNMATCHED = "judged_best_guess_unmatched"

    #: An accepted judged best guess with no accepted-source set supplied.  The
    #: projection did not check it.
    JUDGED_BEST_GUESS_UNCHECKED = "judged_best_guess_unchecked"

    #: No support.  Carried by every unresolved state.
    NONE = "none"


#: Ordering of evidence bases, weakest first.  A consumer that wants to require
#: a minimum basis compares through this map rather than re-deriving one.
#:
#: **This ladder ranks the join that was performed, not how much the value
#: deserves to be believed.**  It is a threshold predicate and nothing else: it
#: is not a weight, a summand, or an average.  Two facts make any arithmetic on
#: it wrong.  ``ROW_REF_UNCHECKED`` (3) outranks ``ROW_REF_UNMATCHED`` (2) even
#: though the second is the one that actually looked, and ``accepted_source_ids``
#: is optional -- so a strength-weighted score is *raised* by declining to
#: verify.  Only the ACCEPTED rungs (4, 7, 8) name a check that passed.
#:
#: The ``judged_best_guess_*`` bases share the rungs of their ``field_ref_*``
#: counterparts because they name the same *join*: provenance scoped to this
#: field rather than to the row it sat in.  What differs is the kind of value --
#: derived rather than stated -- and that difference is carried by the basis
#: name, which is where a consumer must read it.  Encoding it as a number would
#: invite exactly the arithmetic this ladder forbids.
BASIS_STRENGTH: Mapping[EvidenceBasis, int] = {
    EvidenceBasis.NONE: 0,
    EvidenceBasis.ROW_VALUE_ONLY: 1,
    EvidenceBasis.ROW_REF_UNMATCHED: 2,
    EvidenceBasis.ROW_REF_UNCHECKED: 3,
    EvidenceBasis.ROW_REF_ACCEPTED: 4,
    EvidenceBasis.FIELD_REF_UNMATCHED: 5,
    EvidenceBasis.JUDGED_BEST_GUESS_UNMATCHED: 5,
    EvidenceBasis.FIELD_REF_UNCHECKED: 6,
    EvidenceBasis.JUDGED_BEST_GUESS_UNCHECKED: 6,
    EvidenceBasis.FIELD_REF_ACCEPTED: 7,
    EvidenceBasis.JUDGED_BEST_GUESS_ACCEPTED: 7,
    EvidenceBasis.RESOLVED_ASSERTION_CHAIN: 8,
}

#: The bases this projection version can actually emit.  Anything outside this
#: set appearing on a state produced here is a defect, not a stronger claim.
PRODUCIBLE_EVIDENCE_BASES = frozenset(
    basis for basis in EvidenceBasis if basis is not EvidenceBasis.RESOLVED_ASSERTION_CHAIN
)


class TransitionKind(str, Enum):
    """What changed for one criterion between two snapshots."""

    #: Absent or unresolved before, supported after.  This is the transition
    #: reward is credited against.
    SUPPORT_GAINED = "support_gained"

    #: Supported before, unresolved or absent after.
    SUPPORT_LOST = "support_lost"

    #: Supported on both sides, on a different evidence basis.
    BASIS_CHANGED = "basis_changed"

    #: Same status and basis, different values or sources.
    EVIDENCE_CHANGED = "evidence_changed"

    #: The criterion did not exist before and is unresolved now.
    CRITERION_ADDED = "criterion_added"

    #: The criterion existed unresolved and is gone now.
    CRITERION_REMOVED = "criterion_removed"


# ---------------------------------------------------------------------------
# Refs and state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionRef:
    """One criterion, identified rather than described.

    ``id`` is derived from the table, the semantic subject key, and the field,
    and from nothing else.  ``subject_bound`` says whether the subject was
    addressable through declared key columns or canonical identity slots; an
    unbound subject falls back to row content and its ID is **not** stable
    across rounds by construction, which is why the flag travels with the ref
    rather than being inferred later.
    """

    id: str
    table: str
    field: str
    subject_id: str
    subject_key: tuple[tuple[str, str], ...] = ()
    identity_fields: tuple[str, ...] = ()
    subject_bound: bool = False

    @classmethod
    def create(
        cls,
        *,
        table: str,
        field: str,
        subject_id: str,
        subject_key: Sequence[tuple[str, str]] = (),
        identity_fields: Sequence[str] = (),
        subject_bound: bool = False,
    ) -> "CriterionRef":
        table = _text(table)
        field = _text(field)
        subject_id = _text(subject_id)
        criterion_id = stable_id(
            {
                "version": CRITERIA_PROJECTION_VERSION,
                "table": table,
                "subject_id": subject_id,
                "field": field,
            }
        )
        return cls(
            id=criterion_id,
            table=table,
            field=field,
            subject_id=subject_id,
            subject_key=tuple((str(name), str(value)) for name, value in subject_key),
            identity_fields=tuple(str(name) for name in identity_fields),
            subject_bound=bool(subject_bound),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.id,
            "table": self.table,
            "field": self.field,
            "subject_id": self.subject_id,
            "subject_key": [list(pair) for pair in self.subject_key],
            "identity_fields": list(self.identity_fields),
            "subject_bound": self.subject_bound,
        }


@dataclass(frozen=True)
class CriterionState:
    """One criterion's status, with the basis on which it was established.

    ``source_ids`` is the provenance the basis was derived from.  When the
    basis is row-scoped, those references belong to the row rather than to this
    field, and the basis name is the only thing that says so -- consumers must
    read it rather than assuming a field-level join.

    ``subject_source_ids`` is every source referenced anywhere on the subject's
    rows, including for an unresolved criterion.  It is co-location and nothing
    more; it exists so a verifier can ask "was this field derivable from the
    sources this subject already cites?" without re-reading rows.
    """

    ref: CriterionRef
    status: CriterionStatus
    basis: EvidenceBasis
    values: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    subject_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is CriterionStatus.UNRESOLVED:
            if self.basis is not EvidenceBasis.NONE:
                raise ValueError("an unresolved criterion has no evidence basis")
            if self.values:
                raise ValueError("an unresolved criterion carries no value")
        elif self.basis is EvidenceBasis.NONE:
            raise ValueError("a supported criterion must name its evidence basis")
        if self.basis not in PRODUCIBLE_EVIDENCE_BASES:
            raise ValueError(
                f"{self.basis.value} is not producible by "
                f"{CRITERIA_PROJECTION_VERSION}; a state must never claim a "
                "join the projection did not perform"
            )

    @property
    def criterion_id(self) -> str:
        return self.ref.id

    @property
    def supported(self) -> bool:
        return self.status is CriterionStatus.SUPPORTED

    @property
    def basis_strength(self) -> int:
        return BASIS_STRENGTH[self.basis]

    def identity(self) -> dict[str, Any]:
        """The content that makes this state this state.

        Everything an equal pair of states must agree on, and nothing else.
        Two projections producing the same evidence for the same criteria
        therefore produce one snapshot ID.
        """

        return {
            "criterion_id": self.ref.id,
            "status": self.status.value,
            "basis": self.basis.value,
            "values": list(self.values),
            "source_ids": list(self.source_ids),
            "subject_source_ids": list(self.subject_source_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.ref.to_dict(),
            "status": self.status.value,
            "evidence_basis": self.basis.value,
            "evidence_basis_strength": self.basis_strength,
            "values": list(self.values),
            "source_ids": list(self.source_ids),
            "subject_source_ids": list(self.subject_source_ids),
        }


@dataclass(frozen=True)
class CriteriaSnapshot:
    """Every criterion's state at one point in a run.

    ``id`` is content-addressed over the states alone.  It carries no round
    index and no timestamp, so two rounds whose evidence is identical produce
    one snapshot ID -- which is what makes "nothing changed" observable as an
    identity rather than as an empty diff of two distinct IDs.
    """

    id: str
    version: str
    states: tuple[CriterionState, ...]

    @classmethod
    def create(cls, states: Iterable[CriterionState]) -> "CriteriaSnapshot":
        ordered = tuple(sorted(states, key=lambda state: state.ref.id))
        snapshot_id = stable_id(
            {
                "version": CRITERIA_SNAPSHOT_VERSION,
                "states": [state.identity() for state in ordered],
            }
        )
        return cls(id=snapshot_id, version=CRITERIA_SNAPSHOT_VERSION, states=ordered)

    @property
    def supported(self) -> tuple[CriterionState, ...]:
        return tuple(state for state in self.states if state.supported)

    @property
    def unresolved(self) -> tuple[CriterionState, ...]:
        return tuple(state for state in self.states if not state.supported)

    @property
    def supported_ids(self) -> frozenset[str]:
        return frozenset(state.ref.id for state in self.supported)

    @property
    def unresolved_ids(self) -> frozenset[str]:
        return frozenset(state.ref.id for state in self.unresolved)

    def by_criterion(self) -> dict[str, CriterionState]:
        return {state.ref.id: state for state in self.states}

    def state(self, criterion_id: str) -> CriterionState | None:
        for state in self.states:
            if state.ref.id == criterion_id:
                return state
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_snapshot_id": self.id,
            "criteria_snapshot_version": self.version,
            "criteria_projection_version": CRITERIA_PROJECTION_VERSION,
            "criterion_count": len(self.states),
            "supported_criterion_ids": sorted(self.supported_ids),
            "unresolved_criterion_ids": sorted(self.unresolved_ids),
            "states": [state.to_dict() for state in self.states],
        }


@dataclass(frozen=True)
class CriterionTransition:
    """One criterion's change between two snapshots.

    Carries the criterion ID and **both** snapshot IDs, so a reward credited
    against a transition can be traced back to the exact pair of projections it
    was computed from, and so an attribution join never has to guess which
    snapshot a transition belonged to.
    """

    id: str
    criterion_id: str
    kind: TransitionKind
    before_snapshot_id: str
    after_snapshot_id: str
    table: str = ""
    field: str = ""
    subject_id: str = ""
    before_status: str = ""
    after_status: str = ""
    before_basis: str = ""
    after_basis: str = ""
    gained_source_ids: tuple[str, ...] = ()
    after_source_ids: tuple[str, ...] = ()

    @property
    def is_support_gained(self) -> bool:
        return self.kind is TransitionKind.SUPPORT_GAINED

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria_transition_id": self.id,
            "criteria_transition_version": CRITERIA_TRANSITION_VERSION,
            "criterion_id": self.criterion_id,
            "kind": self.kind.value,
            "before_criteria_snapshot_id": self.before_snapshot_id,
            "after_criteria_snapshot_id": self.after_snapshot_id,
            "table": self.table,
            "field": self.field,
            "subject_id": self.subject_id,
            "before_status": self.before_status,
            "after_status": self.after_status,
            "before_evidence_basis": self.before_basis,
            "after_evidence_basis": self.after_basis,
            "gained_source_ids": list(self.gained_source_ids),
            "after_source_ids": list(self.after_source_ids),
        }


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def empty_snapshot() -> CriteriaSnapshot:
    """The snapshot of a run that has projected nothing yet."""

    return CriteriaSnapshot.create(())


def project_rows(
    rows: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    specs: Any = None,
    *,
    accepted_source_ids: Iterable[str] | None = None,
    best_guess_resolutions: Iterable[Mapping[str, Any]] | None = None,
    deliverable_tables: Iterable[str] | None = None,
) -> CriteriaSnapshot:
    """Project table rows onto per-criterion state.

    ``rows`` maps a table name to its rows.  ``specs`` is anything exposing a
    ``tables`` mapping of table-spec-shaped entries -- a ``TableSpec`` object,
    its ``to_dict()`` payload, or a hand-built dict -- and may be omitted, in
    which case the criteria set is the union of value-bearing columns observed
    on that table's rows and identity falls back to canonical slots.

    ``accepted_source_ids`` is the set of sources the run actually accepted.
    Supplying it is what licenses an ``ACCEPTED`` basis; omitting it yields
    ``UNCHECKED`` bases, never accepted ones, because a check that was not
    performed must not be recorded as one that passed.

    ``deliverable_tables``, when supplied, is the **explicit allowlist** of
    tables that project at all.  The spec guard defaults open -- a table absent
    from ``specs`` is treated as deliverable -- so a caller that must not credit
    working tables has to name what it wants rather than rely on omission.  With
    no spec and no allowlist, a *rejected* best-guess candidate row projects as
    ``supported`` with the value ``"false"``, which is a scoring surface nobody
    intended.  Pass the allowlist.

    ``best_guess_resolutions`` are accepted, judged best guesses, in the shape
    :func:`question_pipeline.best_guess.resolve_candidates` returns: a
    ``target_table``, a ``source_row_index`` into *these same rows*, a
    ``canonical_column``, a ``best_guess_value``, the ``source_ids`` the
    operator named for that column, and the ``operators`` that produced it.  A
    resolution is applied only where no row of the subject supplies the field,
    so it can never overwrite or upgrade a stated value.

    The row-index join is positional and is only sound because the resolutions
    and ``rows`` come from the same artifact write.  A resolution naming an
    index that is out of range, or a column that is not a criterion of its
    table, is dropped rather than guessed at.
    """

    accepted = _accepted_ids(accepted_source_ids)
    checked = accepted is not None
    tables = _spec_tables(specs)
    allowlist = _names(deliverable_tables) if deliverable_tables is not None else None
    guesses = _judged_best_guesses(best_guess_resolutions)

    states: list[CriterionState] = []
    for table in sorted(_row_tables(rows)):
        if allowlist is not None and table not in allowlist:
            continue
        # Positions are kept from the *raw* list, not from the filtered one: a
        # judged best guess names its row by position, and compacting the list
        # first would silently shift every index after a non-mapping entry.
        indexed_rows = [
            (index, row)
            for index, row in enumerate((rows or {}).get(table) or ())
            if isinstance(row, Mapping)
        ]
        table_rows = [row for _, row in indexed_rows]
        spec = tables.get(table)
        if spec is not None and not spec.deliverable:
            continue
        identity_fields = _identity_fields(spec, table_rows)
        fields = _criteria_fields(spec, table_rows, identity_fields)
        if not fields:
            continue
        table_guesses = guesses.get(table, {})
        for subject in _subjects(table, indexed_rows, identity_fields):
            subject_sources = _subject_source_ids(subject.rows)
            for name in fields:
                states.append(
                    _project_field(
                        table=table,
                        field=name,
                        subject=subject,
                        subject_sources=subject_sources,
                        accepted=accepted,
                        checked=checked,
                        guesses=[
                            guess
                            for index in subject.row_indices
                            for guess in table_guesses.get((index, name), ())
                        ],
                    )
                )
    return CriteriaSnapshot.create(states)


def diff_snapshots(
    before: CriteriaSnapshot | None,
    after: CriteriaSnapshot | None,
) -> list[CriterionTransition]:
    """Every criterion that changed between two snapshots.

    A criterion whose state is byte-identical on both sides produces no
    transition; there is nothing to credit and nothing to explain.
    """

    before = before if before is not None else empty_snapshot()
    after = after if after is not None else empty_snapshot()
    before_states = before.by_criterion()
    after_states = after.by_criterion()

    transitions: list[CriterionTransition] = []
    for criterion_id in sorted(set(before_states) | set(after_states)):
        old = before_states.get(criterion_id)
        new = after_states.get(criterion_id)
        kind = _transition_kind(old, new)
        if kind is None:
            continue
        ref = (new or old).ref  # type: ignore[union-attr]
        old_sources = set(old.source_ids) if old is not None else set()
        new_sources = tuple(new.source_ids) if new is not None else ()
        transitions.append(
            CriterionTransition(
                id=stable_id(
                    {
                        "version": CRITERIA_TRANSITION_VERSION,
                        "criterion_id": criterion_id,
                        "before_snapshot_id": before.id,
                        "after_snapshot_id": after.id,
                        "kind": kind.value,
                    }
                ),
                criterion_id=criterion_id,
                kind=kind,
                before_snapshot_id=before.id,
                after_snapshot_id=after.id,
                table=ref.table,
                field=ref.field,
                subject_id=ref.subject_id,
                before_status=old.status.value if old is not None else "",
                after_status=new.status.value if new is not None else "",
                before_basis=old.basis.value if old is not None else "",
                after_basis=new.basis.value if new is not None else "",
                gained_source_ids=tuple(
                    source for source in new_sources if source not in old_sources
                ),
                after_source_ids=new_sources,
            )
        )
    return transitions


def _transition_kind(
    before: CriterionState | None,
    after: CriterionState | None,
) -> TransitionKind | None:
    if before is None and after is None:
        return None
    if after is not None and after.supported:
        if before is None or not before.supported:
            return TransitionKind.SUPPORT_GAINED
        if before.basis is not after.basis:
            return TransitionKind.BASIS_CHANGED
        if before.identity() != after.identity():
            return TransitionKind.EVIDENCE_CHANGED
        return None
    if before is not None and before.supported:
        return TransitionKind.SUPPORT_LOST
    if before is None:
        return TransitionKind.CRITERION_ADDED
    if after is None:
        return TransitionKind.CRITERION_REMOVED
    if before.identity() != after.identity():
        return TransitionKind.EVIDENCE_CHANGED
    return None


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Subject:
    """Internal grouping of the rows that address one semantic subject.

    ``row_indices`` are the positions those rows held in the table as it was
    handed to :func:`project_rows`.  They exist so a judged best guess, which
    names the row it was produced for by position, lands on the subject that
    row belongs to -- without this module re-deriving anyone else's row key.
    """

    id: str
    key: tuple[tuple[str, str], ...]
    identity_fields: tuple[str, ...]
    bound: bool
    rows: tuple[Mapping[str, Any], ...] = ()
    row_indices: tuple[int, ...] = ()


def _subjects(
    table: str,
    indexed_rows: Sequence[tuple[int, Mapping[str, Any]]],
    identity_fields: tuple[str, ...],
) -> list[_Subject]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    indices: dict[str, list[int]] = {}
    refs: dict[str, _Subject] = {}
    for index, row in indexed_rows:
        subject = _subject_for_row(table, row, identity_fields)
        grouped.setdefault(subject.id, []).append(row)
        indices.setdefault(subject.id, []).append(index)
        refs.setdefault(subject.id, subject)
    return [
        _Subject(
            id=subject_id,
            key=refs[subject_id].key,
            identity_fields=refs[subject_id].identity_fields,
            bound=refs[subject_id].bound,
            rows=tuple(grouped[subject_id]),
            row_indices=tuple(indices[subject_id]),
        )
        for subject_id in sorted(grouped)
    ]


def _subject_for_row(
    table: str,
    row: Mapping[str, Any],
    identity_fields: tuple[str, ...],
) -> _Subject:
    """Identify the semantic subject one row addresses.

    Identity comes from the declared key columns when there are any, and
    otherwise from canonical slots.  A row that offers neither is *unbound*: it
    is still projected, but its subject ID falls back to the row's own content,
    so it will not join across rounds once a field fills in.  That instability
    is real and is reported rather than hidden -- the fix is a spec that
    declares key columns, not a cleverer guess here.
    """

    present = _subject_key_values(row, identity_fields)
    bound = bool(identity_fields) and len(present) == len(identity_fields)
    if identity_fields:
        payload: Any = {"key_values": [list(pair) for pair in present], "bound": bound}
    else:
        present = ()
        payload = {"row_content": _row_content(row)}
    subject_id = stable_id(
        {
            "version": CRITERIA_PROJECTION_VERSION,
            "table": _text(table),
            "identity_fields": list(identity_fields),
            **payload,
        }
    )
    return _Subject(
        id=subject_id,
        key=present,
        identity_fields=identity_fields,
        bound=bound,
    )


def _subject_key_values(
    row: Mapping[str, Any],
    key_columns: Sequence[str],
) -> tuple[tuple[str, str], ...]:
    """Every declared key column this row populates, in the projection's own form.

    The single owner of how a subject key is *spelled*.  Values go through
    :func:`_normalize_value`, which JSON-encodes mappings and sequences,
    renders bools as ``true``/``false``, collapses whitespace, casefolds, and
    truncates at :data:`MAX_VALUE_LENGTH` -- so a list-valued or very long key
    column has exactly one spelling anywhere in this build.

    **Private, and it stays private.**  The result may be *partial*: a row
    populating some declared key columns and not others returns only the ones it
    populates, which is what makes the unbound case observable to the projection
    itself.  A partial key is the one shape that must never be used to join --
    it matches on a prefix and so can land on the wrong subject.  Callers get
    :func:`subject_key`, which is bound-or-nothing; publishing this one would put
    the unguarded form in the public API and leave the safe wrapper as something
    a future caller has to know to prefer.
    """

    return tuple(
        (str(name), _normalize_value(_nested(row, str(name))))
        for name in key_columns
        if not _missing(_nested(row, str(name)))
    )


def subject_key(
    row: Mapping[str, Any],
    key_columns: Sequence[str],
) -> tuple[tuple[str, str], ...] | None:
    """The row's subject key, or ``None`` when the subject is unbound.

    ``None`` means the row does not populate every declared key column, or that
    no key columns were declared at all.  An unbound subject joins to nothing by
    construction -- its projected ID falls back to row content, which moves as
    soon as a field fills -- so returning ``None`` is the honest answer rather
    than a partial key that would match the wrong subject.
    """

    columns = tuple(key_columns)
    if not columns:
        return None
    values = _subject_key_values(row, columns)
    return values if len(values) == len(columns) else None


def row_subject_ids(
    table: str,
    rows: Sequence[Mapping[str, Any]],
    specs: Any = None,
) -> tuple[str, ...]:
    """The subject id :func:`project_rows` would group each row under.

    One entry per input row, in input order; ``""`` for anything that is not a
    mapping, which the projection also skips.

    Exported because a consumer that wants to reason about a *row's* subject --
    "does this row belong to a subject that already has support?" -- must ask
    the same question the projection will answer, and the answer depends on
    which identity fields the projection chose: declared key columns when a
    spec supplies them, the canonical fallback otherwise, and that choice is
    made from the whole table's rows rather than from any one of them.
    :func:`subject_key` cannot answer it, because it returns ``None`` for every
    row whenever no key columns are declared -- which is most of this corpus.

    Re-deriving the grouping instead is the failure mode ``path_features_v1``
    already hit once: a second spelling of an identity rule fails *silently*,
    because a row that lands in the wrong group looks like a subject nobody has
    seen rather than like an error.
    """

    mapping_rows = [row for row in rows if isinstance(row, Mapping)]
    spec = _spec_tables(specs).get(_text(table))
    identity_fields = _identity_fields(spec, mapping_rows)
    return tuple(
        _subject_for_row(_text(table), row, identity_fields).id
        if isinstance(row, Mapping)
        else ""
        for row in rows
    )


def normalize_key_value(value: Any) -> str:
    """The projection's comparison form for a single value.

    Exported for the same reason as :func:`subject_key`: a consumer that
    compares its own value against one already inside a snapshot must spell it
    the way the snapshot does.  Re-deriving "casefold and collapse whitespace"
    looks equivalent and is not -- it diverges on sequences, mappings, bools,
    and anything longer than :data:`MAX_VALUE_LENGTH`.
    """

    return _normalize_value(value)


def _identity_fields(
    spec: "_TableSpecView | None",
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Declared key columns, else canonical identity slots present in the rows.

    The canonical fallback uses only the slots the runtime invariants declare
    generic -- ``id``, ``name``, ``entity_type``, ``relation_type``, ``source``,
    ``target``, ``src_id``, ``tgt_id``.  No table, domain, or question name
    appears here or anywhere else in this module.
    """

    if spec is not None and spec.key_columns:
        return spec.key_columns

    # No declaration. The fallback resolves the same canonical vocabulary the
    # declaration owner uses -- one spelling of the rule, imported rather than
    # restated, because a second spelling of an identity rule fails silently: a
    # row landing in the wrong group looks like a subject nobody has seen.
    columns: set[str] = set()
    for row in rows:
        columns.update(str(key) for key in row)
    return canonical_subject_identity(columns)


def _row_content(row: Mapping[str, Any]) -> list[list[str]]:
    """A row's value-bearing content, for identifying an unbound subject."""

    return [
        [str(key), _normalize_value(value)]
        for key, value in sorted(row.items(), key=lambda item: str(item[0]))
        if _is_value_field(str(key)) and not _missing(value)
    ]


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------


def datapoint_fields(
    table: str,
    rows: Sequence[Mapping[str, Any]] | None,
    specs: Any = None,
) -> tuple[str, ...]:
    """The columns of ``table`` that project as criteria, and nothing else.

    This is the same resolution :func:`project_rows` performs internally, made
    public so that a caller which must act on "is this cell a datapoint" -- a
    provenance deriver, for instance -- asks this module rather than keeping a
    second, drifting opinion.  Provenance, control, and identity columns are
    excluded: an identity column is supported by construction of the row, so
    finding its text in a chunk says nothing about whether the row is evidenced.
    """

    table_rows = [row for row in (rows or ()) if isinstance(row, Mapping)]
    spec = _spec_tables(specs).get(table)
    return _criteria_fields(spec, table_rows, _identity_fields(spec, table_rows))


def _criteria_fields(
    spec: "_TableSpecView | None",
    rows: Sequence[Mapping[str, Any]],
    identity_fields: tuple[str, ...],
) -> tuple[str, ...]:
    """Which columns of a table become criteria.

    Declared columns when a spec supplies them -- so a column nobody has filled
    yet still projects as unresolved -- and otherwise the columns observed
    anywhere on the table's rows.  Without a spec, a field that appears on no
    row is invisible, and unresolved detection is limited accordingly.

    Provenance, control, and identity columns are excluded.  Provenance is not
    a datapoint; the producer's own ``completeness``/``evidence_gap`` verdict is
    not evidence; and the subject's identity fields are supported by
    construction.
    """

    declared: list[str] = []
    if spec is not None:
        declared.extend(spec.columns)
    if not declared:
        seen: set[str] = set()
        for row in rows:
            for key in row:
                name = str(key)
                if name not in seen:
                    seen.add(name)
                    declared.append(name)

    excluded = set(identity_fields)
    fields: list[str] = []
    for name in declared:
        if name in excluded or name in fields:
            continue
        if not _is_value_field(name):
            continue
        fields.append(name)
    return tuple(sorted(fields))


def _project_field(
    *,
    table: str,
    field: str,
    subject: _Subject,
    subject_sources: tuple[str, ...],
    accepted: frozenset[str] | None,
    checked: bool,
    guesses: Sequence["_JudgedBestGuess"] = (),
) -> CriterionState:
    ref = CriterionRef.create(
        table=table,
        field=field,
        subject_id=subject.id,
        subject_key=subject.key,
        identity_fields=subject.identity_fields,
        subject_bound=subject.bound,
    )

    display: dict[str, str] = {}
    field_refs: set[str] = set()
    row_refs: set[str] = set()
    for row in subject.rows:
        value = _nested(row, field)
        if _missing(value):
            continue
        normalized = _normalize_value(value)
        shown = _display_value(value)
        if normalized not in display or shown < display[normalized]:
            display[normalized] = shown
        field_refs.update(_field_source_ids(row, field))
        row_refs.update(_row_source_ids(row))

    if display:
        basis, source_ids = _basis_for(field_refs, row_refs, accepted, checked)
        return CriterionState(
            ref=ref,
            status=CriterionStatus.SUPPORTED,
            basis=basis,
            values=tuple(display[key] for key in sorted(display)),
            source_ids=source_ids,
            subject_source_ids=subject_sources,
        )

    # No row of this subject states the field.  A judged best guess may still
    # have derived it -- and only here, where there is nothing to overwrite.
    if guesses:
        return _project_judged_best_guess(
            ref=ref,
            guesses=guesses,
            subject_sources=subject_sources,
            accepted=accepted,
            checked=checked,
        )

    return CriterionState(
        ref=ref,
        status=CriterionStatus.UNRESOLVED,
        basis=EvidenceBasis.NONE,
        subject_source_ids=subject_sources,
    )


def _project_judged_best_guess(
    *,
    ref: CriterionRef,
    guesses: Sequence["_JudgedBestGuess"],
    subject_sources: tuple[str, ...],
    accepted: frozenset[str] | None,
    checked: bool,
) -> CriterionState:
    """State for a field only a judged best guess establishes.

    The datapoint is the whole package: the derived value, the decision that
    accepted it, and the sources the operator named for this field.  The
    decision is carried by the **basis member**, which is typed and closed --
    ``judged_best_guess_accepted`` says both "derived, not quoted" and "the
    named sources resolved".  It is deliberately not spelled into ``values``:
    values fold into the snapshot ID, so an operator rename would surface as a
    spurious ``EVIDENCE_CHANGED`` and rewording would become yield.

    The operator names themselves stay on the resolution the caller holds.  A
    consumer wanting them joins on the criterion ID rather than reading them
    out of a state that must stay prose-free.
    """

    display: dict[str, str] = {}
    named: set[str] = set()
    for guess in guesses:
        shown = _display_value(guess.value)
        normalized = _normalize_value(guess.value)
        if normalized not in display or shown < display[normalized]:
            display[normalized] = shown
        named.update(guess.source_ids)

    if not display:
        return CriterionState(
            ref=ref,
            status=CriterionStatus.UNRESOLVED,
            basis=EvidenceBasis.NONE,
            subject_source_ids=subject_sources,
        )

    if not checked:
        basis = EvidenceBasis.JUDGED_BEST_GUESS_UNCHECKED
        source_ids = tuple(sorted(named))
    else:
        matched = tuple(sorted(named & (accepted or frozenset())))
        if matched:
            basis = EvidenceBasis.JUDGED_BEST_GUESS_ACCEPTED
            source_ids = matched
        else:
            basis = EvidenceBasis.JUDGED_BEST_GUESS_UNMATCHED
            source_ids = tuple(sorted(named))

    return CriterionState(
        ref=ref,
        status=CriterionStatus.SUPPORTED,
        basis=basis,
        values=tuple(display[key] for key in sorted(display)),
        source_ids=source_ids,
        subject_source_ids=tuple(sorted(set(subject_sources) | named)),
    )


def admits_judged_best_guess(resolution: Any) -> bool:
    """Whether one best-guess resolution is admissible as a datapoint.

    THE WHOLE PACKAGE OR NOTHING: not explicitly rejected, a table, a column, an
    integer row index, a non-missing value, and at least one source id the
    operator named FOR THAT COLUMN.  Without the judgment and the sources it is
    a candidate, not a datapoint, and admitting it would put an unevidenced
    guess on the same footing as an evidenced one.

    Extracted from :func:`_judged_best_guesses`, which calls it, so the rule has
    one expression rather than two inside one module.  Exported so a consumer
    that must decide "would the projection take this guess" asks this module
    instead of keeping a second, looser opinion.

    **What this predicate does NOT carry, stated because assuming it would be a
    silent loosening.**  The projection's other guard -- that a guess applies
    only where no row of the subject supplies the field
    (:func:`_project_field`) -- is applied against a *row*, not against a
    resolution, so it is not inherited by any caller of this function.  A caller
    working at a different grain owns the equivalent guard itself.
    """

    if not isinstance(resolution, Mapping):
        return False
    if resolution.get("accepted") is False:
        return False
    if not _text(resolution.get("target_table")):
        return False
    if not _text(resolution.get("canonical_column")):
        return False
    if _missing(resolution.get("best_guess_value")):
        return False
    raw_index = resolution.get("source_row_index")
    if isinstance(raw_index, bool) or not isinstance(raw_index, int):
        return False
    if raw_index < 0:
        return False
    return bool(_source_ids(resolution.get("source_ids")))


@dataclass(frozen=True)
class _JudgedBestGuess:
    """One accepted, judged best guess, read from the caller's resolution."""

    table: str
    row_index: int
    field: str
    value: str
    source_ids: frozenset[str]


def _judged_best_guesses(
    resolutions: Iterable[Mapping[str, Any]] | None,
) -> dict[str, dict[tuple[int, str], tuple[_JudgedBestGuess, ...]]]:
    """Index resolutions by table, row position, and column.

    Anything without all four of a table, an integer row index, a column, and a
    non-missing value is dropped.  A resolution carrying no ``source_ids`` is
    dropped too: a derived value with no source basis is a candidate, not a
    datapoint, and admitting it would put an unevidenced guess on the same
    footing as an evidenced one.

    An explicit ``accepted`` of ``False`` is honoured where the caller supplies
    it.  Its absence is not read as acceptance of an unjudged candidate -- the
    resolution shape this reads is already the accepted set -- but a caller
    passing raw candidates gets the rejected ones dropped rather than scored.
    """

    out: dict[str, dict[tuple[int, str], list[_JudgedBestGuess]]] = {}
    for resolution in resolutions or ():
        if not admits_judged_best_guess(resolution):
            continue
        table = _text(resolution.get("target_table"))
        field = _text(resolution.get("canonical_column"))
        raw_index = resolution.get("source_row_index")
        value = resolution.get("best_guess_value")
        sources = _source_ids(resolution.get("source_ids"))
        out.setdefault(table, {}).setdefault((raw_index, field), []).append(
            _JudgedBestGuess(
                table=table,
                row_index=raw_index,
                field=field,
                value=_display_value(value),
                source_ids=frozenset(sources),
            )
        )
    return {
        table: {key: tuple(items) for key, items in sorted(by_key.items())}
        for table, by_key in out.items()
    }


def _basis_for(
    field_refs: set[str],
    row_refs: set[str],
    accepted: frozenset[str] | None,
    checked: bool,
) -> tuple[EvidenceBasis, tuple[str, ...]]:
    """Name the strongest join actually performed, and nothing stronger.

    Field-scoped provenance outranks row-scoped provenance because it is the
    stronger claim: the producer attached it to this field rather than to the
    row it happened to sit in.  Neither is a resolved assertion chain, and
    neither may be reported as one.
    """

    if field_refs:
        if not checked:
            return EvidenceBasis.FIELD_REF_UNCHECKED, tuple(sorted(field_refs))
        matched = tuple(sorted(field_refs & (accepted or frozenset())))
        if matched:
            return EvidenceBasis.FIELD_REF_ACCEPTED, matched
        return EvidenceBasis.FIELD_REF_UNMATCHED, tuple(sorted(field_refs))
    if row_refs:
        if not checked:
            return EvidenceBasis.ROW_REF_UNCHECKED, tuple(sorted(row_refs))
        matched = tuple(sorted(row_refs & (accepted or frozenset())))
        if matched:
            return EvidenceBasis.ROW_REF_ACCEPTED, matched
        return EvidenceBasis.ROW_REF_UNMATCHED, tuple(sorted(row_refs))
    return EvidenceBasis.ROW_VALUE_ONLY, ()


# ---------------------------------------------------------------------------
# Provenance conventions
# ---------------------------------------------------------------------------

#: Row keys that carry provenance or the producer's own verdict rather than a
#: datapoint.  ``source``/``target``/``src_id``/``tgt_id`` are deliberately
#: absent: those are canonical graph slots holding real content, and only the
#: chunk/document senses of "source" are provenance.
_NON_VALUE_FIELDS = frozenset(
    {
        "chunk_id",
        "chunk_ids",
        "completeness",
        "dedup_key",
        "deduplication_key",
        "evidence",
        "evidence_gap",
        "evidence_text",
        "group_key",
        # ENGINE-MINTED STRUCTURAL COLUMNS. A traversal's COLLAPSE and AGGREGATE
        # mint these to describe the GROUPING, not the subject: how many rows
        # merged, which row ids went in. They are operational volume, and
        # `reward` exists to count datapoints rather than volume, so a criterion
        # minted from one is a criterion that can be satisfied by doing more
        # work rather than by learning more.
        #
        # This matters because two fallbacks compose. `_criteria_fields` mints a
        # criterion per observed column when a table has no spec, and
        # `pipeline._deliverable_tables` falls back to every table handed in
        # when a run declares none -- and a traversal hands in its intermediate
        # variables. With both open, `occurrence_count: 12` projects as a
        # datapoint with the value "12" and is eligible for credit.
        #
        # LATENT, MEASURED, AND NOT EXOTIC. No credited datapoint in 88 recorded
        # reward reports carries these fields, and the two runs that exercise
        # the reward path carry neither column. But a sweep of every recorded
        # exported table found `occurrence_count` and `items` as real columns in
        # more than forty runs -- 2,848 and 804 rows in one -- so the column is
        # common and only the projection has not yet met it.
        #
        # INTERIM, AND DO NOT EXTEND THIS LIST TO CLOSE THE CLASS.
        #
        # These five names are a denylist, and a denylist only excludes what its
        # author thought of -- the reason this file's sibling `provenance.py`
        # argues for allowlists. The class-closing fix is landing in `gasl/` as
        # `engine_columns` on the emitted contract: each command declares, at
        # the construction site, which columns it authored rather than which
        # carry data-derived values. A `_`-prefix convention was considered and
        # REJECTED, on the grounds that it would let this file's parser dictate
        # the engine's output vocabulary and would add a ninth name-based
        # classifier to close the leak from an eighth.
        #
        # So when `engine_columns` arrives, the correct change is to consume it
        # and let these five retire to covering NON-GASL producers only -- not
        # to add a sixth, seventh and eighth name here. Extending the list is
        # the move this note exists to prevent.
        #
        # `count` and `result` are minted by the same engine code and are
        # deliberately NOT here: both are plausible domain column names (a count
        # of deaths, a study's result), and excluding them would silently drop
        # real datapoints to close a latent exposure. A denylist that starts
        # eating real fields is worse than the hole it plugs.
        "contributing_rows",
        "item_ids",
        "items",
        "occurrence_count",
        "row_count",
        "path_depth",
        "quote",
        "quotes",
        "row_context",
        "row_id",
        "source_chunk",
        "source_chunks",
        "source_id",
        "source_ids",
        "source_ref",
        "source_refs",
        "source_row_index",
        "source_row_key",
        "table_name",
    }
)

_NON_VALUE_SUFFIXES = (
    "_chunk_id",
    "_chunk_ids",
    "_dedup_key",
    "_evidence",
    "_evidence_text",
    "_quote",
    "_quotes",
    "_row_id",
    "_source_chunk",
    "_source_chunks",
    "_source_id",
    "_source_ids",
    "_source_ref",
    "_source_refs",
)

_ROW_SOURCE_FIELDS = (
    "source_refs",
    "source_ref",
    "source_ids",
    "source_id",
    "source_chunks",
    "source_chunk",
    "chunk_ids",
    "chunk_id",
)

#: The provenance naming convention lives in `provenance`, which owns it and
#: is a pure leaf. `goals` reads the same predicate, so what this module
#: refuses to credit and what that module refuses to search for cannot drift.
_is_provenance_name = is_provenance_name


#: Retained only to build `<field>` + suffix lookups when reading a specific
#: field's provenance; membership tests go through `_is_provenance_name`.
_FIELD_SOURCE_SUFFIXES = (
    "_source_refs",
    "_source_ref",
    "_source_ids",
    "_source_id",
    "_source_chunks",
    "_source_chunk",
)

_CHUNK_SUFFIX_RE = re.compile(r"^(?P<source_id>.+)_chunk_\d+$")

_SOURCE_SPLIT_RE = re.compile(r"[,;\s]+")


#: The engine's canonical graph abstraction, quoted from
#: `docs/RUNTIME_INVARIANTS.md` -- "allowed as code literals in generic runtime
#: code because they are part of the engine's canonical graph abstraction
#: rather than domain- or source-specific schema".
#:
#: They are therefore, by that same definition, **not domain data**. A row
#: materialised from a graph edge carries them (`src_id = "COVID-19"` names the
#: edge's source entity), and counting them as datapoints inflates every
#: downstream measure with plumbing: measured at 104 of 676 criteria -- 15.4%
#: -- on 30 real rows, with `id` and `entity_name` holding the same string, so
#: one non-datapoint counted twice.
#:
#: This is not a denylist of fields somebody guessed should not count. It is
#: the project's own declared vocabulary, cited rather than invented, which is
#: why it can be trusted to stay correct as schemas change.
_CANONICAL_GRAPH_KEYS = frozenset(
    {
        "id",
        "name",
        "entity_type",
        "relation_type",
        "source",
        "target",
        "src_id",
        "tgt_id",
        # `RUNTIME_INVARIANTS.md` declares `name`; the implementation emits
        # `entity_name` for the same concept -- in real rows the node `id` and
        # `entity_name` hold the identical string. `group_name` is the grouping
        # key's label. Reconciling the doc's vocabulary with the code's
        # spelling, not inventing new exclusions.
        #
        # These matter more than the rest: an entity name matches its chunk
        # verbatim *because extraction copied it out of that chunk*, so
        # grounding it is circular. Left in, 713 of 5,545 grounded cells were
        # these two, crossing from uncreditable ROW_REF_ACCEPTED to creditable
        # FIELD_REF_ACCEPTED.
        "entity_name",
        "group_name",
    }
)


#: The closed set of reasons a column name is not a datapoint. Class labels, in
#: the order :func:`_is_value_field` tests them; ``""`` means it is one.
DATAPOINT_EXCLUSION_CLASSES = (
    "underscore_prefixed",
    "non_value_field",
    "canonical_graph_key",
    "provenance",
    "non_value_suffix",
)


def datapoint_exclusion_class(name: Any) -> str:
    """Why :func:`is_datapoint_field` refuses a column, as a class label.

    ``""`` when it does not refuse it. Exported beside the predicate so a
    consumer disclosing *what it excluded and why* names the class this module
    excluded on rather than re-deriving a classification from its own reading of
    the name -- which would be a second owner of the rule, differing exactly
    where it matters and silently.
    """

    text = _text(name)
    if not text or text.startswith("_"):
        return "underscore_prefixed"
    if text in _NON_VALUE_FIELDS:
        return "non_value_field"
    if text in _CANONICAL_GRAPH_KEYS:
        return "canonical_graph_key"
    if _is_provenance_name(text):
        return "provenance"
    if text.endswith(_NON_VALUE_SUFFIXES):
        return "non_value_suffix"
    return ""


def _is_value_field(name: str) -> bool:
    if not name or name.startswith("_"):
        return False
    if name in _NON_VALUE_FIELDS or name in _CANONICAL_GRAPH_KEYS:
        return False
    if _is_provenance_name(name):
        return False
    return not name.endswith(_NON_VALUE_SUFFIXES)


def _field_source_ids(row: Mapping[str, Any], field: str) -> set[str]:
    ids: set[str] = set()
    for suffix in _FIELD_SOURCE_SUFFIXES:
        ids.update(_source_ids(row.get(f"{field}{suffix}")))
    return ids


def _row_source_ids(row: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for name in _ROW_SOURCE_FIELDS:
        ids.update(_source_ids(row.get(name)))
    return ids


def _subject_source_ids(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    ids: set[str] = set()
    for row in rows:
        ids.update(_row_source_ids(row))
        for key in row:
            name = str(key)
            if name.endswith(_FIELD_SOURCE_SUFFIXES):
                ids.update(_source_ids(row.get(key)))
    return tuple(sorted(ids))


def _source_ids(value: Any) -> set[str]:
    """Canonical source-document IDs from a provenance field.

    A chunk reference is reduced to the document it came from, so a chunk-level
    and a document-level reference to the same source match each other and the
    accepted-source set.
    """

    ids: set[str] = set()
    for item in _iter_scalars(value):
        for part in _SOURCE_SPLIT_RE.split(str(item)):
            text = part.strip()
            if not text or text.lower() in _MISSING_STRINGS:
                continue
            match = _CHUNK_SUFFIX_RE.match(text)
            ids.add(match.group("source_id") if match is not None else text)
    return ids


def _accepted_ids(values: Iterable[str] | None) -> frozenset[str] | None:
    if values is None:
        return None
    accepted: set[str] = set()
    for value in values:
        accepted.update(_source_ids(value))
    return frozenset(accepted)


# ---------------------------------------------------------------------------
# Spec view
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TableSpecView:
    """One table's contract, read from whatever shape the caller supplied."""

    key_columns: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    deliverable: bool = True


def _spec_tables(specs: Any) -> dict[str, _TableSpecView]:
    """Read table contracts from an object or a plain payload.

    Duck-typed on purpose.  Importing the spec loader would drag a YAML
    dependency and file I/O into a module whose whole value is that it can be
    exercised with constructed inputs alone.
    """

    if specs is None:
        return {}
    tables = specs.get("tables") if isinstance(specs, Mapping) else getattr(specs, "tables", None)
    if not isinstance(tables, Mapping):
        return {}

    out: dict[str, _TableSpecView] = {}
    for name, table in tables.items():
        key = _text(name)
        if not key or table is None:
            continue
        out[key] = _TableSpecView(
            # `subject_key_columns` is the identity declaration; `key_columns`
            # is the completeness contract and is only a fallback for specs
            # written before the two were separated.
            key_columns=(
                _names(_spec_attr(table, "subject_key_columns"))
                or _names(_spec_attr(table, "key_columns"))
            ),
            columns=_spec_columns(table),
            deliverable=bool(_spec_attr(table, "deliverable", True)),
        )
    return out


def _spec_columns(table: Any) -> tuple[str, ...]:
    columns = _spec_attr(table, "columns")
    if callable(getattr(table, "all_columns", None)):
        columns = table.all_columns()
    if isinstance(columns, Mapping):
        return _names(columns.keys())
    if isinstance(columns, (list, tuple)):
        names: list[str] = []
        for item in columns:
            if isinstance(item, Mapping):
                names.append(_text(item.get("name")))
            elif isinstance(item, str):
                names.append(_text(item))
            else:
                names.append(_text(getattr(item, "name", "")))
        return _names(names)
    return ()


def _spec_attr(table: Any, name: str, default: Any = None) -> Any:
    if isinstance(table, Mapping):
        return table.get(name, default)
    return getattr(table, name, default)


def _names(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set, frozenset)) and not hasattr(values, "__iter__"):
        return ()
    out: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _row_tables(rows: Mapping[str, Sequence[Mapping[str, Any]]] | None) -> list[str]:
    if not isinstance(rows, Mapping):
        return []
    return [_text(name) for name in rows if _text(name)]


# ---------------------------------------------------------------------------
# Value normalization
# ---------------------------------------------------------------------------

#: Strings a producer writes to mean "nothing here".  A normalization
#: convention, not domain vocabulary.
#:
#: THE UNION OF WHAT FIVE PRODUCERS MEANT BY ABSENCE, AND THIS MODULE IS THE ONE
#: OWNER OF IT.  `acquisition`, `best_guess`, `goals` and `pipeline` each kept
#: their own set (8, 11, 9 and 8 entries); they disagreed on `--`, `[null]`,
#: `not reported`, `not specified` and five more, so the same cell was absence to
#: one consumer and a value to another.  The union rather than the intersection
#: or this module's own former 17, because every one of the 18 is a producer
#: writing "nothing here", which is the set's declared subject: a token that
#: means absence to one producer means absence to all of them, and the
#: divergence was an accident of five authors rather than a disagreement about
#: meaning.  `"not specified in current evidence"` came from `goals` alone and is
#: the entry that makes this a v5 projection bump -- see
#: :data:`CRITERIA_PROJECTION_VERSION`.
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
        "not specified in current evidence",
        "not stated",
        "null",
        "unknown",
    }
)


def missing_tokens() -> tuple[str, ...]:
    """The owned missing-token vocabulary, for a run to record which set it ran.

    A run that emits ``{"module": "criteria", "tokens": 18}`` lets a later
    reader see which convention produced its trace, rather than inferring it
    from the version.
    """

    return tuple(sorted(_MISSING_STRINGS))


def is_missing_value(value: Any) -> bool:
    """Whether a value means "nothing here" rather than being a value.

    Exported additively over :func:`_missing` -- same function, public name, no
    behaviour change -- for the same reason as :func:`normalize_key_value`: a
    consumer deciding whether a cell carries anything must ask this module
    rather than keep a second, drifting opinion.  A credit, a deficit, or a
    best-guess task minted from one of these tokens counts absence as yield.
    """

    return _missing(value)


def is_datapoint_field(name: Any) -> bool:
    """Whether a column name denotes a measured value.

    False for provenance, for the producer's own verdict about a row
    (``completeness``, ``evidence_gap``), for engine-minted structural columns,
    for canonical graph slots, and for anything ``_``-prefixed.  Exported for
    the same reason as :func:`normalize_key_value` and :func:`datapoint_fields`:
    a consumer deciding what counts must ask this module rather than keep a
    second, weaker opinion.  A delegation, not a copy -- the next producer
    self-verdict column added to :data:`_NON_VALUE_FIELDS` leaves every caller's
    basis on the same day, with no second edit.
    """

    return _is_value_field(_text(name))


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return " ".join(value.split()).lower() in _MISSING_STRINGS
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _normalize_value(value: Any) -> str:
    """The comparison form of a value: case- and whitespace-insensitive."""

    return _display_value(value).casefold()


def _display_value(value: Any) -> str:
    if isinstance(value, Mapping):
        text = json.dumps(
            {str(key): _display_value(item) for key, item in sorted(value.items())},
            sort_keys=True,
            separators=(",", ":"),
        )
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = [_display_value(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items = sorted(items)
        text = json.dumps(items, separators=(",", ":"))
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    text = " ".join(text.split())
    return text[:MAX_VALUE_LENGTH]


def _iter_scalars(value: Any) -> Iterable[Any]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        out: list[Any] = []
        for item in value:
            out.extend(_iter_scalars(item))
        return tuple(out)
    return (value,)


def _nested(row: Mapping[str, Any], field: str) -> Any:
    """Read a field, following dotted paths into nested mappings."""

    if field in row:
        return row[field]
    current: Any = row
    for part in str(field).split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _text(value: Any) -> str:
    return str(value or "").strip()
