"""Deterministic path scoring for traversal routes (phase 2A).

A depth-3 or depth-4 walk can leave a useful sourced measurement, cross a broad
connector -- a shared paper, method, or coarse context -- and arrive at a
different estimate.  The record that comes back is not malformed: real
neighbour, real edge, real ``source_refs``, deterministic IDs.  It is simply
weak context for the criterion it was walked for, and the engine discovers that
only after an expensive normalisation call has written an ``evidence_gap``.

This module makes that judgement cheap.  It is a **pure function** over
candidate rows and a scoring context: no pipeline import, no graph adapter, no
LLM, no I/O, no clock, no randomness.  Identical rows produce byte-identical
output across interpreter runs.

*It scores.  It does not drop anything.*  Selecting, demoting, and excluding
are the gate's decisions (phase 2B); this module ranks routes and says why.

Three boundaries are deliberate and worth stating, because each one is a place
where a second, quietly divergent definition could grow:

**Criterion state is imported, never re-derived.**  Whether a criterion is
supported comes from :mod:`question_pipeline.criteria` and from nowhere else.
This module reads a :class:`~question_pipeline.criteria.CriteriaSnapshot`; it
never decides what "supported" means.  Two definitions of that in one build
make every downstream comparison meaningless.

**Subject identity comes from declared key columns only.**  With no declared
``key_columns`` the projection's canonical fallback can reduce to a content
hash, which moves the moment a field fills.  That is nominal identity, not
identity, so :func:`question_pipeline.criteria.subject_key` returns ``None``
for an unbound subject and :data:`FEATURE_ANCHOR_CONSISTENCY` degrades to its
declared *unavailable* level rather than pretending to know that two endpoints
are the same subject.  **The key itself is built by ``criteria.py``, never
here** -- a second spelling of that normalisation fails the join silently, since
a miss looks like a subject nobody has seen rather than like an error.

**Row provenance parsing is row-scoped and lives here.**  ``criteria.py`` also
reads ``source_refs``/``source_chunks``, but it does so to establish a
criterion's *evidence basis* -- a claim about what was joined.  This module
reads the same slots to rank a route, which is not a claim about evidence at
all.  The two are kept separate on purpose: a ranking must never be able to
promote itself into a support claim.  A path score is not evidence support and
cannot close a criterion.

Every constant that can move a score is named at module level and carried on
:class:`PathScoreWeights` or :class:`PathFeatureCalibration`, so tuning is a
different argument rather than a different record schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Sequence

from .control import (
    PathExclusionReason,
    PathSelectionReason,
    RouteStep,
    TargetRef,
    TerminalRef,
)
from .criteria import (
    CriteriaSnapshot,
    CriterionState,
    normalize_key_value,
    subject_key,
)

__all__ = [
    "PATH_FEATURES_VERSION",
    "FEATURE_NAMES",
    "FEATURE_SOURCE_OVERLAP",
    "FEATURE_PATH_DEPTH",
    "FEATURE_RELATION_SEQUENCE",
    "FEATURE_TERMINAL_TYPE",
    "FEATURE_ANCHOR_CONSISTENCY",
    "FEATURE_HUB_DEGREE",
    "PathSelectionReason",
    "PathExclusionReason",
    "PathScoreWeights",
    "PathFeatureCalibration",
    "DEFAULT_WEIGHTS",
    "DEFAULT_CALIBRATION",
    "PathRow",
    "PathScore",
    "PathScoringContext",
    "build_context",
    "node_degrees",
    "score_row",
    "score_rows",
]


#: Bumped when a change would move an existing route's score.  A consumer that
#: compares scores across versions is comparing two different measurements, and
#: the version is carried on every scored record so that shows up as a mismatch
#: rather than as a difference in route quality.
#:
#: ``v1`` -> ``v2``: the subject key was re-derived locally instead of imported
#: from :mod:`question_pipeline.criteria`, and the two spellings diverged on
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
#: :func:`question_pipeline.criteria.normalize_key_value`, which is *not* a join
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
# :mod:`question_pipeline.control` and re-exported here.  They are this
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
    :func:`question_pipeline.criteria.normalize_key_value`, which that module
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
