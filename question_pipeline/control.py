"""Policy-facing control vocabulary for the question pipeline.

This module owns the nouns the control layer is written in: the decision
surfaces, the identifier refs that carry provenance, the candidate actions a
planner proposes, the decision records a policy returns, and the stop contract
orchestration enforces.

It is deliberately pure.  Nothing here imports the pipeline, a graph adapter, a
search provider, an LLM client, or any persistence layer, and nothing here
performs I/O.  Every type in this file can be constructed by hand and exercised
in isolation, which is the property that lets orchestration and policy evolve
without either side importing the other's implementation details.

Three design commitments are load-bearing:

*Surface-agnostic base.*  :class:`ActionCandidate` carries only the fields every
control surface has.  A query lives on :class:`SearchCandidate`; a route lives
on :class:`PathCandidate`.  A base type that assumed a query would force every
later surface to invent one.

*Provenance by identifier.*  Operator, target, attempt, and prompt-arm
provenance travels as frozen refs with stable IDs and an explicit
``to_metadata()`` projection.  No consumer should ever recover provenance by
parsing prose.

*Immutable records.*  Every record is a frozen dataclass with ``to_dict()``.
An append-only ledger built over immutable records is append-only by
construction rather than by the discipline of whoever writes to it.  The two
``Mapping`` fields -- ``TargetRef.anchor_values`` and
``PathCandidate.path_score_features`` -- are copied at construction and are not
to be mutated afterwards; they stay plain dicts because ``MappingProxyType``
cannot be deep-copied, and round records are deep-copied on their way to disk.

Determinism is a hard requirement.  Identical inputs must produce identical IDs
and identical rankings across processes and across runs, because every join the
control layer performs later -- ledger reconstruction, cross-round outcome
attribution, reward credit -- is a join on those IDs.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, is_dataclass
from enum import Enum
from typing import AbstractSet, Any, Mapping, Protocol, Sequence

__all__ = [
    "CONTROL_VOCABULARY_VERSION",
    "POLICY_STATE_VERSION",
    "STOP_CONTEXT_VERSION",
    "STOP_POLICY_STATE_VERSION",
    "MIN_QUERY_LENGTH",
    "ControlSurface",
    "ActionOrigin",
    "StopReason",
    "PathSelectionReason",
    "PathExclusionReason",
    "OperatorRef",
    "TargetRef",
    "AttemptRef",
    "PromptArmRef",
    "ExecutionErrorRef",
    "RouteStep",
    "TerminalRef",
    "ActionCandidate",
    "SearchCandidate",
    "PathCandidate",
    "DecisionContext",
    "PolicyStateManifest",
    "PolicyDecision",
    "StopContext",
    "StopDecision",
    "TableFillControlPolicy",
    "StaticTableFillPolicy",
    "execution_error_stop_decision",
    "terminal_no_action_stop_decision",
    "orchestration_stop_override",
    "resolve_stop_decision",
    "normalize_query",
    "select_first_clearing",
    "stable_id",
    "CANONICAL_IDENTITY_SLOTS",
    "canonical_subject_identity",
]


#: The canonical identity slots, cited from `docs/RUNTIME_INVARIANTS.md` --
#: "allowed as code literals in generic runtime code because they are part of
#: the engine's canonical graph abstraction rather than domain- or
#: source-specific schema". The project's own declared vocabulary, cited rather
#: than invented, which is why a declaration minted from it cannot drift with a
#: planner's wording.
CANONICAL_IDENTITY_SLOTS = (
    "id", "name", "entity_type", "relation_type",
    "source", "target", "src_id", "tgt_id",
)


def canonical_subject_identity(columns) -> tuple[str, ...]:
    """The canonical identity a table's own column vocabulary supports.

    A pure function of the column names and of nothing else: no counter, no
    state, no model-emitted text. Identical column vocabularies resolve to
    byte-identical declarations in every round of every run.

    Returns ``()`` when the table carries no canonical slot. A refusal, not a
    gap to fill: inventing an identity for a table that cannot support one
    leaves every row unbound under one shared empty key and collapses the table
    into a single enormous cell, which reads downstream as spectacular evidence
    accumulation and is a defect.

    This module defines the function and owns no value. The owner of a table's
    declaration mints it -- see `table_specs` -- so there is one declaration
    rather than one per consumer.
    """

    present = {str(name) for name in (columns or ())}
    edge_source = "src_id" if "src_id" in present else ("source" if "source" in present else "")
    edge_target = "tgt_id" if "tgt_id" in present else ("target" if "target" in present else "")
    if edge_source and edge_target:
        relation = ("relation_type",) if "relation_type" in present else ()
        return (edge_source, edge_target, *relation)
    if "id" in present:
        return ("id",)
    if "name" in present:
        return ("name", "entity_type") if "entity_type" in present else ("name",)
    return ()


#: ``v1`` -> ``v2``: the round vocabulary is gone. Candidates, decision
#: contexts, and stop contexts carry ``episode_id`` -- the Episode whose
#: planning pass minted or consulted them -- where ``round_index`` used to sit,
#: and the round-budget stop concept (``ROUND_BUDGET_EXHAUSTED``,
#: ``round_budget_available``) is deleted rather than renamed: there is no
#: round budget, only the Episode compositions' own verdicts and the declared
#: unit bound. Every stable ID minted under ``v1`` is incomparable with a
#: ``v2`` ID, which is the intended way a cross-version join fails.
CONTROL_VOCABULARY_VERSION = "control_v2"
POLICY_STATE_VERSION = "policy_state_v2"
STOP_CONTEXT_VERSION = "stop_context_v2"
STOP_POLICY_STATE_VERSION = "stop_policy_state_v2"

#: Length of the hex prefix :func:`_stable_id` returns.
STABLE_ID_LENGTH = 16

#: Shortest normalized query a search candidate may carry.
MIN_QUERY_LENGTH = 4


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class ControlSurface(str, Enum):
    """A place in the loop where a policy is consulted.

    These name *surfaces*, never subjects.  A surface is a decision point in
    orchestration; what the decision is about comes from the criteria snapshot
    and the table contracts at runtime, never from a name baked in here.
    """

    CATALOG_SEARCH = "catalog_search"
    TARGET_SEARCH = "target_search"
    PATH_SELECTION = "path_selection"
    STOP = "stop"


class ActionOrigin(str, Enum):
    """Where a candidate proposal came from, as a typed label."""

    LLM = "llm"
    FALLBACK = "fallback"
    MEMORY = "memory"
    DERIVED = "derived"
    TRAVERSAL = "traversal"


class StopReason(str, Enum):
    """The closed set of reasons run continuation continues or halts."""

    CONTINUE = "continue"
    GOAL_FULFILLED = "task_goal_fulfilled"

    SOURCE_BUDGET_EXHAUSTED = "source_budget_exhausted"
    FRONTIER_EXHAUSTED = "search_frontier_exhausted"
    EXECUTION_ERROR = "execution_error"


class PathSelectionReason(str, Enum):
    """Why a route scored the way it did, as a class label.

    Lives here rather than beside the scorer because ``PathCandidate`` carries
    it as a typed field and this module may not import the module that computes
    it -- the dependency runs the other way, and a vocabulary owned by its
    consumer is a vocabulary its producer can silently widen.  The scorer
    re-exports these names, so the producing side is unchanged.

    Deliberately closed, and deliberately not prose: a downstream stage groups
    by an identifier instead of matching on a sentence, and no generated text
    can steer another module's behaviour.
    """

    #: The route's evidence includes a chunk of the source accepted this round.
    CURRENT_CHUNK_EVIDENCE = "current_chunk_evidence"
    #: The route cites a source accepted this round, but not the same chunk.
    CURRENT_SOURCE_EVIDENCE = "current_source_evidence"
    #: The route cites an accepted source from an earlier round.
    ACCEPTED_SOURCE_EVIDENCE = "accepted_source_evidence"
    #: The route starts and ends on the same criterion subject.
    ANCHOR_PRESERVED = "anchor_preserved"
    #: Nothing distinguishes this route either way at this context's resolution.
    NEUTRAL_CONTEXT = "neutral_context"
    #: The route begins on one criterion subject and ends on a different one.
    ANCHOR_CROSSED_SUBJECT = "anchor_crossed_subject"
    #: A node on the route connects an outsized share of the candidate set.
    HIGH_DEGREE_CONNECTOR = "high_degree_connector"
    #: The route is longer than the anchored depth this context allows for free.
    EXTENDED_ROUTE = "extended_route"
    #: The route carries provenance, none of which is an accepted source.
    UNACCEPTED_PROVENANCE = "unaccepted_provenance"
    #: The route carries no provenance reference at all.
    NO_PROVENANCE = "no_provenance"
    #: There was nothing to score.  Pairs with a :class:`PathExclusionReason`.
    UNSCORED = "unscored"


class PathExclusionReason(str, Enum):
    """Why a candidate could not be *scored*, as a class label.

    Scoring excludes only what it cannot measure.  **Nothing here is a policy
    decision** -- a route that scores badly is scored badly and carried on with
    its reason; whether a low score is dropped, demoted, or kept for recall
    belongs to the gate, and the gate's own dispositions are its own vocabulary.
    """

    #: No route, no terminal, no endpoint slots: nothing identifies a path.
    NO_ROUTE_EVIDENCE = "no_route_evidence"


_EXECUTION_STATUS = {
    StopReason.GOAL_FULFILLED: "finished",
    StopReason.SOURCE_BUDGET_EXHAUSTED: "halted_source_budget",
    StopReason.FRONTIER_EXHAUSTED: "halted_frontier",
    StopReason.EXECUTION_ERROR: "halted_execution_error",
}


# ---------------------------------------------------------------------------
# Provenance refs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OperatorRef:
    """The operator that proposed an action, plus its attempt context."""

    name: str = ""
    source_family: str = ""
    attempt_index: int | None = None
    context_tags: tuple[str, ...] = ()
    last_failure_class: str = ""
    exhausted_operators: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "OperatorRef":
        value = value or {}
        return cls(
            name=_text(value.get("operator") or value.get("strategy_operator")),
            source_family=_text(value.get("source_family")),
            attempt_index=_optional_int(value.get("attempt_index")),
            context_tags=_strings(value.get("context_tags")),
            last_failure_class=_text(value.get("last_failure_class")),
            exhausted_operators=_strings(value.get("exhausted_operators")),
        )

    def to_metadata(self) -> dict[str, Any]:
        """Project onto the metadata keys durable memory already reads."""

        return {
            "strategy_operator": self.name,
            "strategy_family": self.name,
            "source_family": self.source_family,
            "operator_attempt": self.attempt_index,
            "operator_context_tags": list(self.context_tags),
            "operator_last_failure_class": self.last_failure_class,
            "operator_exhausted": list(self.exhausted_operators),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_metadata()


@dataclass(frozen=True)
class TargetRef:
    """The deficit an action is meant to reduce, by identifier.

    ``criteria_snapshot_id`` and ``criterion_ids`` are the join keys into the
    criteria projection.  This module never derives them; it carries them so
    that a decision, the criteria it was made against, and the outcomes it
    later produced can be joined without re-reading rows.
    """

    deficit_id: str = ""
    target_id: str = ""
    name: str = ""
    table: str = ""
    deficit_type: str = ""
    criteria_snapshot_id: str = ""
    criterion_ids: tuple[str, ...] = ()
    subject_ids: tuple[str, ...] = ()
    key_columns: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    anchor_values: Mapping[str, Any] = field(default_factory=dict)
    expected_minimum_count: int = 0
    supported_count: int = 0
    deficit_count: int = 0

    @property
    def key(self) -> str:
        """The identifier used when grouping actions by target."""

        return self.deficit_id or self.target_id

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "TargetRef":
        value = value or {}
        deficit_id = _text(value.get("id") or value.get("fill_deficit_id"))
        anchors = value.get("anchor_values")
        return cls(
            deficit_id=deficit_id,
            target_id=_text(value.get("target_id")) or deficit_id,
            name=_text(value.get("target_name") or value.get("name")),
            table=_text(value.get("target_table")),
            deficit_type=_text(value.get("deficit_type")),
            criteria_snapshot_id=_text(
                value.get("criteria_snapshot_id")
                or value.get("target_basis_snapshot_id")
            ),
            criterion_ids=_strings(value.get("criterion_ids")),
            subject_ids=_strings(value.get("subject_ids")),
            key_columns=_strings(value.get("key_columns")),
            missing_fields=_strings(value.get("missing_fields")),
            anchor_values=dict(anchors) if isinstance(anchors, Mapping) else {},
            expected_minimum_count=_int(value.get("expected_minimum_count")),
            supported_count=_int(value.get("supported_count")),
            deficit_count=_int(value.get("deficit_count")),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "fill_deficit_id": self.deficit_id,
            "fill_deficit_type": self.deficit_type,
            "target_id": self.target_id,
            "target_name": self.name,
            "target_table": self.table,
            "criteria_snapshot_id": self.criteria_snapshot_id,
            "criterion_ids": list(self.criterion_ids),
            "subject_ids": list(self.subject_ids),
            "key_columns": list(self.key_columns),
            "missing_fields": list(self.missing_fields),
            "anchor_values": dict(self.anchor_values),
            "expected_minimum_count": self.expected_minimum_count,
            "supported_count": self.supported_count,
            "deficit_count": self.deficit_count,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_metadata()


@dataclass(frozen=True)
class AttemptRef:
    """One strategy attempt, identified rather than described."""

    id: str = ""
    evolution_index: int = 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "AttemptRef":
        value = value or {}
        return cls(
            id=_text(value.get("id") or value.get("strategy_attempt_id")),
            evolution_index=_int(value.get("evolution_index")),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "strategy_attempt_id": self.id,
            "evolution_index": self.evolution_index,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_metadata()


@dataclass(frozen=True)
class PromptArmRef:
    """A replayable prompt mutation applied to one attempt.

    The delta and hypothesis are recorded so a trace can be read, never so that
    another module can branch on their wording.  Routing joins on ``id``.
    """

    id: str = ""
    name: str = ""
    index: int = 0
    prompt_delta: str = ""
    hypothesis: str = ""
    expected_source_shape: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PromptArmRef":
        value = value or {}
        return cls(
            id=_text(value.get("prompt_arm_id") or value.get("id")),
            name=_text(value.get("prompt_arm_name") or value.get("name")),
            index=_int(value.get("prompt_arm_index") or value.get("index")),
            prompt_delta=_text(value.get("prompt_delta")),
            hypothesis=_text(
                value.get("prompt_hypothesis") or value.get("hypothesis")
            ),
            expected_source_shape=_text(value.get("expected_source_shape")),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "prompt_arm_id": self.id,
            "prompt_arm_name": self.name,
            "prompt_arm_index": self.index,
            "prompt_delta": self.prompt_delta,
            "prompt_hypothesis": self.hypothesis,
            "expected_source_shape": self.expected_source_shape,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_metadata()


@dataclass(frozen=True)
class ExecutionErrorRef:
    """A validated runtime failure, carried by identifier.

    ``reason`` and ``source`` are class labels from the raising subsystem, not
    prose for a human.  ``owner_kind``/``owner_id`` identify the exact artifact
    that failed; ``detail_ids`` carries any further identifiers that subsystem
    wants preserved, opaque to this module.  Keeping it opaque is deliberate:
    the control vocabulary must not grow a field per failing subsystem.
    """

    reason: str = ""
    source: str = ""
    owner_kind: str = ""
    owner_id: str = ""
    contract_version: str = ""
    detail_ids: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (self.reason and self.source and self.owner_kind and self.owner_id):
            raise ValueError(
                "an execution error must identify a reason class, a source, "
                "and the owner that failed"
            )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "execution_error_reason": self.reason,
            "execution_error_source": self.source,
            "execution_error_owner_kind": self.owner_kind,
            "execution_error_owner_id": self.owner_id,
            "execution_error_contract_version": self.contract_version,
            "execution_error_detail_ids": {
                str(key): str(value)
                for key, value in sorted(self.detail_ids.items())
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_metadata()


# ---------------------------------------------------------------------------
# Route vocabulary (path surface)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteStep:
    """One hop of a traversal route, in canonical slots only."""

    src_id: str = ""
    tgt_id: str = ""
    source: str = ""
    target: str = ""
    relation_type: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RouteStep":
        value = value or {}
        return cls(
            src_id=_text(value.get("src_id")),
            tgt_id=_text(value.get("tgt_id")),
            source=_text(value.get("source")),
            target=_text(value.get("target")),
            relation_type=_text(value.get("relation_type")),
        )

    @property
    def identity(self) -> tuple[str, str, str]:
        """The part of a hop that makes the route this route.

        Falls back to endpoint names when a graph carries no node IDs, so a
        route identity is stable for either shape of adapter output.
        """

        return (
            self.src_id or self.source,
            self.tgt_id or self.target,
            self.relation_type,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "src_id": self.src_id,
            "tgt_id": self.tgt_id,
            "source": self.source,
            "target": self.target,
            "relation_type": self.relation_type,
        }


@dataclass(frozen=True)
class TerminalRef:
    """The endpoint a route arrives at, in canonical slots only."""

    id: str = ""
    name: str = ""
    entity_type: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "TerminalRef":
        value = value or {}
        return cls(
            id=_text(value.get("id")),
            name=_text(value.get("name")),
            entity_type=_text(value.get("entity_type")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "entity_type": self.entity_type}


# ---------------------------------------------------------------------------
# Candidate actions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionCandidate:
    """A proposed action, before a policy has ranked it.

    The base carries only what every surface has.  Anything a specific surface
    needs -- a query, a route, a score -- belongs on a subtype, and subtypes
    extend behaviour through three hooks rather than through ``isinstance``
    checks in the policy:

    ``identity_payload``
        the surface-specific fields that participate in the stable action ID.
    ``dedupe_key``
        the key under which two proposals are the same action.
    ``is_valid``
        whether the proposal is well formed enough to rank.
    """

    id: str
    surface: ControlSurface
    #: The Episode whose planning pass minted this candidate ("" at bootstrap,
    #: before any Episode has opened). Attribution, never an ordinal.
    episode_id: str
    operator: OperatorRef = field(default_factory=OperatorRef)
    attempt: AttemptRef = field(default_factory=AttemptRef)
    prompt_arm: PromptArmRef = field(default_factory=PromptArmRef)
    rationale: str = ""
    origin: ActionOrigin = ActionOrigin.LLM

    # -- surface hooks ------------------------------------------------------

    @property
    def target_key(self) -> str:
        """Grouping key for surfaces that bind an action to a target."""

        return ""

    def identity_payload(self) -> dict[str, Any]:
        """Surface-specific contribution to the stable action ID."""

        return {}

    def dedupe_key(self) -> tuple[Any, ...]:
        return (self.surface.value, self.target_key)

    def is_valid(self) -> bool:
        return True

    # -- shared behaviour ---------------------------------------------------

    def to_metadata(self) -> dict[str, Any]:
        """Every ref this action carries, flattened onto its metadata keys."""

        return {
            "control_action_id": self.id,
            "control_surface": self.surface.value,
            "episode_id": self.episode_id,
            "action_origin": self.origin.value,
            **self.operator.to_metadata(),
            **self.attempt.to_metadata(),
            **self.prompt_arm.to_metadata(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "surface": self.surface.value,
            "episode_id": self.episode_id,
            "operator": self.operator.to_dict(),
            "attempt": self.attempt.to_dict(),
            "prompt_arm": self.prompt_arm.to_dict(),
            "rationale": self.rationale,
            "origin": self.origin.value,
        }


@dataclass(frozen=True)
class SearchCandidate(ActionCandidate):
    """A validated query proposal, before it becomes an executable task."""

    query: str = ""
    query_index: int = 0
    target: TargetRef | None = None

    @classmethod
    def create(
        cls,
        *,
        surface: ControlSurface,
        query: str,
        episode_id: str = "",
        operator: OperatorRef | None = None,
        attempt: AttemptRef | None = None,
        prompt_arm: PromptArmRef | None = None,
        query_index: int = 0,
        rationale: str = "",
        origin: ActionOrigin | str = ActionOrigin.LLM,
        target: TargetRef | None = None,
    ) -> "SearchCandidate":
        operator = operator or OperatorRef()
        attempt = attempt or AttemptRef()
        prompt_arm = prompt_arm or PromptArmRef()
        collapsed = " ".join(str(query or "").split())
        identity = {
            **_base_identity(surface, episode_id, operator, attempt, prompt_arm),
            "query": normalize_query(collapsed),
            "target": target.key if target is not None else "",
        }
        return cls(
            id=_stable_id(identity),
            surface=surface,
            episode_id=_text(episode_id),
            operator=operator,
            attempt=attempt,
            prompt_arm=prompt_arm,
            rationale=str(rationale or "").strip(),
            origin=ActionOrigin(origin),
            query=collapsed,
            query_index=_int(query_index),
            target=target,
        )

    @property
    def target_key(self) -> str:
        return self.target.key if self.target is not None else ""

    def identity_payload(self) -> dict[str, Any]:
        return {"query": normalize_query(self.query), "target": self.target_key}

    def dedupe_key(self) -> tuple[Any, ...]:
        # ``prompt_arm.id`` participates here so two arms proposing the same
        # query text for the same target are *not* collapsed into one
        # candidate.  Without it, ``_admissible`` kept only the first-seen
        # arm and every outcome the shared query produced was attributed to
        # that arm alone -- an order-dependent credit assignment that is
        # exactly the kind of artifact 3B's contrast must not manufacture.
        # See ``docs/CONTROL_LAYER_BUILD.md`` "From 1A review -- for 3B and
        # `prompt-mutation-steward`": the test that matters is that two arms
        # emitting identical query text still get attributed separately.
        return (
            self.surface.value,
            self.target_key,
            normalize_query(self.query),
            self.prompt_arm.id,
        )

    def is_valid(self) -> bool:
        return len(normalize_query(self.query)) >= MIN_QUERY_LENGTH

    def to_metadata(self) -> dict[str, Any]:
        metadata = super().to_metadata()
        metadata["query_index"] = self.query_index
        if self.target is not None:
            metadata.update(self.target.to_metadata())
        return metadata

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload.update(
            {
                "query": self.query,
                "query_index": self.query_index,
                "target": self.target.to_dict() if self.target else None,
            }
        )
        return payload


@dataclass(frozen=True)
class PathCandidate(ActionCandidate):
    """A traversal route proposed as support for a target.

    Deliberately has no query.  A route is identified by its hops and its
    terminal; the score is carried, not computed -- scoring belongs to the
    module that owns the features, and the ID must not move when a route is
    rescored or an outcome would stop joining to the decision that produced it.
    """

    route: tuple[RouteStep, ...] = ()
    terminal: TerminalRef | None = None
    target: TargetRef | None = None
    row_id: str = ""
    path_score: float = 0.0
    path_score_features: Mapping[str, float] = field(default_factory=dict)
    #: Closed vocabularies, not prose.  ``None`` is "not stated"; there is no
    #: empty-string member, so a reader never has to decide whether "" meant
    #: absent or meant a reason nobody bothered to name.  Neither field is in
    #: :meth:`create`'s identity payload, so relabelling a route never moves
    #: its ID -- an outcome recorded against a candidate must keep joining to
    #: it after the reason is refined.
    path_selection_reason: PathSelectionReason | None = None
    path_exclusion_reason: PathExclusionReason | None = None

    @classmethod
    def create(
        cls,
        *,
        episode_id: str = "",
        route: Sequence[RouteStep] = (),
        terminal: TerminalRef | None = None,
        target: TargetRef | None = None,
        row_id: str = "",
        operator: OperatorRef | None = None,
        attempt: AttemptRef | None = None,
        prompt_arm: PromptArmRef | None = None,
        path_score: float = 0.0,
        path_score_features: Mapping[str, float] | None = None,
        path_selection_reason: PathSelectionReason | str | None = None,
        path_exclusion_reason: PathExclusionReason | str | None = None,
        rationale: str = "",
        origin: ActionOrigin | str = ActionOrigin.TRAVERSAL,
        surface: ControlSurface = ControlSurface.PATH_SELECTION,
    ) -> "PathCandidate":
        operator = operator or OperatorRef()
        attempt = attempt or AttemptRef()
        prompt_arm = prompt_arm or PromptArmRef()
        steps = tuple(route)
        identity = {
            **_base_identity(surface, episode_id, operator, attempt, prompt_arm),
            "route": [list(step.identity) for step in steps],
            "terminal": (terminal.id or terminal.name) if terminal else "",
            "target": target.key if target is not None else "",
            "row_id": str(row_id or ""),
        }
        return cls(
            id=_stable_id(identity),
            surface=surface,
            episode_id=_text(episode_id),
            operator=operator,
            attempt=attempt,
            prompt_arm=prompt_arm,
            rationale=str(rationale or "").strip(),
            origin=ActionOrigin(origin),
            route=steps,
            terminal=terminal,
            target=target,
            row_id=str(row_id or ""),
            path_score=_float(path_score),
            path_score_features={
                str(key): _float(value)
                for key, value in dict(path_score_features or {}).items()
            },
            path_selection_reason=_enum_or_none(
                PathSelectionReason, path_selection_reason
            ),
            path_exclusion_reason=_enum_or_none(
                PathExclusionReason, path_exclusion_reason
            ),
        )

    @property
    def target_key(self) -> str:
        return self.target.key if self.target is not None else ""

    @property
    def route_identity(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(step.identity for step in self.route)

    @property
    def depth(self) -> int:
        return len(self.route)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "route": [list(step) for step in self.route_identity],
            "target": self.target_key,
            "row_id": self.row_id,
        }

    def dedupe_key(self) -> tuple[Any, ...]:
        return (
            self.surface.value,
            self.target_key,
            self.row_id,
            self.route_identity,
        )

    def is_valid(self) -> bool:
        return bool(self.route) or bool(self.row_id)

    def to_metadata(self) -> dict[str, Any]:
        metadata = super().to_metadata()
        metadata.update(
            {
                "path_row_id": self.row_id,
                "path_depth": self.depth,
                "path_score": self.path_score,
            }
        )
        if self.target is not None:
            metadata.update(self.target.to_metadata())
        return metadata

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload.update(
            {
                "route": [step.to_dict() for step in self.route],
                "terminal": self.terminal.to_dict() if self.terminal else None,
                "target": self.target.to_dict() if self.target else None,
                "row_id": self.row_id,
                "path_depth": self.depth,
                "path_score": self.path_score,
                "path_score_features": dict(self.path_score_features),
                "path_selection_reason": (
                    self.path_selection_reason.value
                    if self.path_selection_reason is not None
                    else ""
                ),
                "path_exclusion_reason": (
                    self.path_exclusion_reason.value
                    if self.path_exclusion_reason is not None
                    else ""
                ),
            }
        )
        return payload


# ---------------------------------------------------------------------------
# Decision records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionContext:
    """Everything a ranking policy is allowed to see at one surface."""

    surface: ControlSurface
    #: The Episode whose planning pass this decision belongs to ("" at
    #: bootstrap). Attribution, never an ordinal.
    episode_id: str
    max_actions: int
    pending_actions: int = 0
    #: Source units the run may still pull. ``-1`` means the run declared no
    #: unit bound at all -- unbounded is stated, never spelled as zero.
    remaining_source_budget: int = 0
    criteria_snapshot_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface.value,
            "episode_id": self.episode_id,
            "max_actions": self.max_actions,
            "pending_actions": self.pending_actions,
            "remaining_source_budget": self.remaining_source_budget,
            "criteria_snapshot_id": self.criteria_snapshot_id,
        }


@dataclass(frozen=True)
class PolicyStateManifest:
    """The versioned, immutable state presented to one policy decision."""

    id: str
    version: str
    context: DecisionContext
    candidate_action_ids: tuple[str, ...]

    @classmethod
    def create(
        cls,
        context: DecisionContext,
        candidate_action_ids: Sequence[str],
    ) -> "PolicyStateManifest":
        candidate_ids = tuple(candidate_action_ids)
        payload = {
            "version": POLICY_STATE_VERSION,
            "context": context.to_dict(),
            "candidate_action_ids": list(candidate_ids),
        }
        return cls(
            id=_stable_id(payload),
            version=POLICY_STATE_VERSION,
            context=context,
            candidate_action_ids=candidate_ids,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_state_id": self.id,
            "policy_state_version": self.version,
            **self.context.to_dict(),
            "candidate_action_ids": list(self.candidate_action_ids),
        }


@dataclass(frozen=True)
class PolicyDecision:
    """One ranking decision, with the alternatives it rejected.

    ``candidate_action_ids`` matters as much as ``ranked_action_ids``.  A trace
    that records only what was chosen cannot answer what was passed over, and
    that is the first question any later analysis asks.
    """

    id: str
    policy_name: str
    context: DecisionContext
    state: PolicyStateManifest
    candidate_action_ids: tuple[str, ...]
    ranked_action_ids: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        policy_name: str,
        context: DecisionContext,
        candidate_action_ids: Sequence[str],
        ranked_action_ids: Sequence[str],
    ) -> "PolicyDecision":
        candidate_ids = tuple(candidate_action_ids)
        ranked_ids = tuple(ranked_action_ids)
        state = PolicyStateManifest.create(context, candidate_ids)
        decision_id = _stable_id(
            {
                "policy": policy_name,
                "policy_state_id": state.id,
                "ranked_action_ids": list(ranked_ids),
            }
        )
        return cls(
            id=decision_id,
            policy_name=policy_name,
            context=context,
            state=state,
            candidate_action_ids=candidate_ids,
            ranked_action_ids=ranked_ids,
        )

    @property
    def selected_action_ids(self) -> tuple[str, ...]:
        """The prefix of the ranking the budget actually admits."""

        return self.ranked_action_ids[: max(0, self.context.max_actions)]

    @property
    def rejected_action_ids(self) -> tuple[str, ...]:
        selected = set(self.selected_action_ids)
        return tuple(
            action_id
            for action_id in self.candidate_action_ids
            if action_id not in selected
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.id,
            "policy_name": self.policy_name,
            "control_vocabulary_version": CONTROL_VOCABULARY_VERSION,
            **self.context.to_dict(),
            "policy_state_id": self.state.id,
            "policy_state_version": self.state.version,
            "policy_state": self.state.to_dict(),
            "candidate_action_ids": list(self.candidate_action_ids),
            "ranked_action_ids": list(self.ranked_action_ids),
            "selected_action_ids": list(self.selected_action_ids),
        }


# ---------------------------------------------------------------------------
# Stop contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StopContext:
    """The inputs a stop decision is entitled to read."""

    #: The Episode whose completion this stop decision follows ("" when the
    #: run stops before any Episode opened).
    episode_id: str = ""
    goal_mode: bool = False
    goal_fulfilled: bool = False
    source_budget_available: bool = True
    frontier_pending: int = 0
    frontier_required: bool = False
    criteria_snapshot_id: str = ""
    criteria_transition_id: str = ""
    required_unresolved_criterion_ids: tuple[str, ...] = ()
    goal_check_results: tuple[tuple[str, bool], ...] = ()
    execution_error: ExecutionErrorRef | None = None

    def __post_init__(self) -> None:
        if self.execution_error is not None and self.goal_mode and self.goal_fulfilled:
            raise ValueError(
                "an execution-error stop context cannot also report a "
                "fulfilled goal"
            )

    @property
    def has_execution_error(self) -> bool:
        return self.execution_error is not None

    @property
    def is_terminal(self) -> bool:
        """True when no further action is physically available.

        Terminal is about exhausted inputs, not about satisfaction.  A
        fulfilled goal is a policy judgement; an empty budget is not.
        """

        if not self.source_budget_available:
            return True
        if self.frontier_required and self.frontier_pending <= 0:
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stop_context_version": STOP_CONTEXT_VERSION,
            "episode_id": self.episode_id,
            "goal_mode": self.goal_mode,
            "goal_fulfilled": self.goal_fulfilled,

            "source_budget_available": self.source_budget_available,
            "frontier_pending": self.frontier_pending,
            "frontier_required": self.frontier_required,
            "criteria_snapshot_id": self.criteria_snapshot_id,
            "criteria_transition_id": self.criteria_transition_id,
            "required_unresolved_criterion_ids": list(
                self.required_unresolved_criterion_ids
            ),
            "goal_check_results": [
                {"name": name, "satisfied": satisfied}
                for name, satisfied in self.goal_check_results
            ],
            "execution_error": self.has_execution_error,
        }
        if self.execution_error is not None:
            payload.update(self.execution_error.to_metadata())
        return payload


@dataclass(frozen=True)
class StopDecision:
    """Whether the loop continues, and on whose authority."""

    stop: bool
    reason: StopReason = StopReason.CONTINUE
    id: str = ""
    policy_name: str = ""
    policy_state_id: str = ""
    policy_state_version: str = STOP_POLICY_STATE_VERSION
    context: StopContext | None = None
    orchestration_owned: bool = False

    @property
    def execution_status(self) -> str:
        if not self.stop:
            return "running"
        return _EXECUTION_STATUS.get(self.reason, "halted")

    @property
    def goal_status(self) -> str:
        if self.context is None or not self.context.goal_mode:
            return "not_applicable"
        if self.context.has_execution_error:
            return "incomplete"
        return "fulfilled" if self.context.goal_fulfilled else "incomplete"

    def to_dict(self) -> dict[str, Any]:
        context = self.context.to_dict() if self.context is not None else {}
        return {
            "decision_id": self.id,
            "policy_name": self.policy_name,
            "surface": ControlSurface.STOP.value,
            "control_vocabulary_version": CONTROL_VOCABULARY_VERSION,
            "policy_state_id": self.policy_state_id,
            "policy_state_version": self.policy_state_version,
            "stop": self.stop,
            "reason": self.reason.value,
            "execution_status": self.execution_status,
            "goal_status": self.goal_status,
            "orchestration_owned": self.orchestration_owned,
            **context,
        }


def _stop_decision(
    context: StopContext,
    *,
    stop: bool,
    reason: StopReason,
    policy_name: str,
    orchestration_owned: bool,
) -> StopDecision:
    state_id = _stable_id(
        {"version": STOP_POLICY_STATE_VERSION, "context": context.to_dict()}
    )
    decision_id = _stable_id(
        {
            "policy": policy_name,
            "policy_state_id": state_id,
            "stop": stop,
            "reason": reason.value,
        }
    )
    return StopDecision(
        stop=stop,
        reason=reason,
        id=decision_id,
        policy_name=policy_name,
        policy_state_id=state_id,
        policy_state_version=STOP_POLICY_STATE_VERSION,
        context=context,
        orchestration_owned=orchestration_owned,
    )


def execution_error_stop_decision(context: StopContext) -> StopDecision:
    """Orchestration-owned stop for a validated runtime failure."""

    if not context.has_execution_error:
        raise ValueError("the execution-error stop guard requires an error ref")
    return _stop_decision(
        context,
        stop=True,
        reason=StopReason.EXECUTION_ERROR,
        policy_name="execution_error_guard_v1",
        orchestration_owned=True,
    )


def terminal_no_action_stop_decision(context: StopContext) -> StopDecision:
    """Orchestration-owned stop when no further action is available."""

    if context.has_execution_error or not context.is_terminal:
        raise ValueError(
            "the no-action stop guard requires an exhausted, error-free "
            "execution input"
        )
    if context.goal_mode and context.goal_fulfilled:
        reason = StopReason.GOAL_FULFILLED
    elif not context.source_budget_available:
        reason = StopReason.SOURCE_BUDGET_EXHAUSTED
    elif context.frontier_required and context.frontier_pending <= 0:
        reason = StopReason.FRONTIER_EXHAUSTED
    else:
        # ``is_terminal`` is defined by exactly the two conditions above, so
        # reaching here means the context lied about being terminal.  Loud,
        # never a default reason.
        raise ValueError("terminal stop context carries no terminal condition")
    return _stop_decision(
        context,
        stop=True,
        reason=reason,
        policy_name="terminal_execution_guard_v1",
        orchestration_owned=True,
    )


def orchestration_stop_override(context: StopContext) -> StopDecision | None:
    """The stop orchestration takes regardless of what a policy returns."""

    if context.has_execution_error:
        return execution_error_stop_decision(context)
    if context.is_terminal:
        return terminal_no_action_stop_decision(context)
    return None


def resolve_stop_decision(
    context: StopContext,
    policy: "TableFillControlPolicy",
) -> StopDecision:
    """Resolve run continuation after one completed Episode, guards first.

    This is the only entry point orchestration should call.  Calling
    ``policy.decide_stop`` directly would let a custom policy record
    ``continue`` on a run the composition is about to exit, which makes the ledger
    disagree with what happened -- and a ledger that disagrees with the run is
    worse than no ledger.
    """

    override = orchestration_stop_override(context)
    if override is not None:
        return override
    decision = policy.decide_stop(context)
    if not isinstance(decision, StopDecision):
        raise TypeError("decide_stop must return a StopDecision")
    if decision.context is not context:
        # Rebind so the ledger records the context the loop actually saw.
        return _stop_decision(
            context,
            stop=decision.stop,
            reason=decision.reason,
            policy_name=decision.policy_name or getattr(policy, "name", ""),
            orchestration_owned=False,
        )
    return decision


# ---------------------------------------------------------------------------
# Policy surface
# ---------------------------------------------------------------------------


class TableFillControlPolicy(Protocol):
    """The complete policy surface orchestration exposes.

    Two methods, no more.  Every surface that becomes policy-controlled later
    arrives as a new :class:`ControlSurface` and a new candidate subtype, not
    as a new method here -- otherwise a replay or learned policy has to
    implement a method per surface before it can run at all.
    """

    name: str

    def rank_actions(
        self,
        context: DecisionContext,
        candidates: Sequence[ActionCandidate],
    ) -> PolicyDecision:
        ...

    def decide_stop(self, context: StopContext) -> StopDecision:
        ...


class StaticTableFillPolicy:
    """Deterministic ranking and stop logic; the default policy."""

    name = "static_v1"

    def rank_actions(
        self,
        context: DecisionContext,
        candidates: Sequence[ActionCandidate],
    ) -> PolicyDecision:
        if context.surface == ControlSurface.STOP:
            raise ValueError("the stop surface is decided by decide_stop")
        valid = _admissible(context.surface, candidates)
        ranked = self._rank(context.surface, valid)
        return PolicyDecision.create(
            policy_name=self.name,
            context=context,
            candidate_action_ids=[candidate.id for candidate in valid],
            ranked_action_ids=[candidate.id for candidate in ranked],
        )

    def _rank(
        self,
        surface: ControlSurface,
        candidates: Sequence[ActionCandidate],
    ) -> list[ActionCandidate]:
        if surface == ControlSurface.TARGET_SEARCH:
            return _target_coverage_first(candidates)
        if surface == ControlSurface.PATH_SELECTION:
            # Stable sort: ties keep proposal order, so the ranking is a
            # function of the input alone.  The score is supplied by the
            # module that owns path features; this policy only orders by it.
            return sorted(
                candidates,
                key=lambda candidate: -getattr(candidate, "path_score", 0.0),
            )
        return list(candidates)

    def decide_stop(self, context: StopContext) -> StopDecision:
        override = orchestration_stop_override(context)
        if override is not None:
            return override
        if context.goal_mode and context.goal_fulfilled:
            return self._decision(context, True, StopReason.GOAL_FULFILLED)

        # THE DECISION IS A CALCULATION, AND IT IS DELIBERATELY NARROW.
        #
        # What it replaced gated on `answer_sufficient` and `answer_confidence`
        # -- both emitted by a model at `strategy.assess_answer` -- against
        # `target_confidence = 0.75`, a threshold with no measurement behind
        # it. Every term below is instead a count the engine already keeps.
        #
        # WHAT IT REPLACED. `answer_sufficient` and `answer_confidence` are
        # produced by a model; `target_confidence = 0.75` was a constant with
        # no measurement behind it. `strategy.py` never states confidence in
        # WHAT, so the number was not anchored to a quantity even in principle.
        # That is a defect readable from the code, and it is the whole reason
        # the pair is gone.
        #
        # WHAT IS NOT HERE, AND WHY. A "round credited nothing" condition was
        # specified and then withdrawn: credit depends on grounding, and a
        # grounding failure would make this halt fire while the run still had
        # unresolved criteria outstanding. No SEARCH policy can repair a
        # GROUNDING failure, so reading credit here would re-import the class
        # of failure this redesign removes. An accepted-to-extracted ratio was
        # considered and rejected on the same footing.
        #
        # So the rule is narrower than the one it replaces and says so. A
        # calculated rule that admits its reach beats an asked one whose
        # threshold was never anchored. No constant appears: every comparison is against zero, which
        # is the boundary between "some" and "none" rather than a tuned value.
        if (
            context.frontier_required
            and context.frontier_pending == 0
            and not context.source_budget_available
        ):
            return self._decision(context, True, StopReason.FRONTIER_EXHAUSTED)

        return self._decision(context, False, StopReason.CONTINUE)

    def _decision(
        self,
        context: StopContext,
        stop: bool,
        reason: StopReason,
    ) -> StopDecision:
        return _stop_decision(
            context,
            stop=stop,
            reason=reason,
            policy_name=self.name,
            orchestration_owned=False,
        )


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------


def _admissible(
    surface: ControlSurface,
    candidates: Sequence[ActionCandidate],
) -> list[ActionCandidate]:
    """Drop off-surface, malformed, and duplicate proposals, in input order."""

    admitted: list[ActionCandidate] = []
    seen: set[tuple[Any, ...]] = set()
    for candidate in candidates:
        if candidate.surface != surface or not candidate.is_valid():
            continue
        key = candidate.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        admitted.append(candidate)
    return admitted


def _target_coverage_first(
    candidates: Sequence[ActionCandidate],
) -> list[ActionCandidate]:
    """One action per target before any target gets a second."""

    first: list[ActionCandidate] = []
    rest: list[ActionCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.target_key
        if key and key not in seen:
            seen.add(key)
            first.append(candidate)
        else:
            rest.append(candidate)
    return [*first, *rest]


# ---------------------------------------------------------------------------
# Stable identity
# ---------------------------------------------------------------------------


def normalize_query(value: str) -> str:
    """Case- and whitespace-insensitive query form used for identity."""

    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _base_identity(
    surface: ControlSurface,
    episode_id: str,
    operator: OperatorRef,
    attempt: AttemptRef,
    prompt_arm: PromptArmRef,
) -> dict[str, Any]:
    """The identity every candidate shares, whatever its surface."""

    return {
        "surface": surface.value,
        "episode_id": _text(episode_id),
        "operator": operator.name,
        "attempt": attempt.id,
        "prompt_arm": prompt_arm.id,
    }


def _canonical(value: Any) -> Any:
    """Reduce a payload to JSON primitives, refusing anything ambiguous.

    ``json.dumps(default=str)`` would silently accept an object whose ``repr``
    contains its memory address, producing an ID that changes between
    processes.  Every join in this build is on those IDs, so an unknown type is
    an error rather than a coercion.
    """

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("a stable id cannot contain a non-finite float")
        return value
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_canonical(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, default=None),
        )
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if is_dataclass(value) and hasattr(value, "to_dict"):
        return _canonical(value.to_dict())
    raise TypeError(f"{type(value).__name__} has no stable serialization")


def _stable_id(payload: Mapping[str, Any]) -> str:
    """A deterministic ID for a payload: sorted JSON, SHA1, hex prefix.

    Identical inputs yield identical IDs in every process and every run, which
    is what makes replay joins hold across a resumed or re-run pipeline.
    """

    raw = json.dumps(
        _canonical(payload),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:STABLE_ID_LENGTH]


#: Public alias.  Consumers outside this module should import this name.
stable_id = _stable_id


# ---------------------------------------------------------------------------
# The switch edge's accept rule
# ---------------------------------------------------------------------------


def select_first_clearing(
    candidates: Sequence[tuple[str, float]],
    *,
    floor: float,
    opened: AbstractSet[str],
) -> int | None:
    """Index of the first candidate clearing ``floor`` whose key is untried.

    Pure, and deliberately free of provider vocabulary: it takes ``(content
    key, reported distance)`` pairs and a set of already-opened content keys, so
    a second acquisition surface can call the same rule, and route 2 can
    recompute the accept decision offline from ``strategy_proposals.jsonl``
    without instantiating a provider source.

    Both conjuncts matter and neither is a model's judgement.  ``distance`` is a
    number a model *reported* and this comparison is what decides "far enough";
    ``opened`` holds keys minted in code from declared inputs, which is what
    makes the second conjunct model-independent.  A non-finite or unparseable
    distance never clears -- an instrument that did not answer is not evidence
    that a candidate is distant.
    """

    for index, (key, distance) in enumerate(candidates):
        try:
            value = float(distance)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < float(floor):
            continue
        if str(key) in opened:
            continue
        return index
    return None


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    return str(value or "").strip()


def _enum_or_none(enum_cls: type[Enum], value: Any) -> Any:
    """Coerce to a member of a closed vocabulary, or refuse.

    ``None`` and ``""`` mean "not stated" and pass through as ``None``.
    Anything else must name a member: an unknown label raises rather than
    being stored, which is the whole difference between a typed field and a
    ``str`` field with a convention attached to it.
    """

    if value is None:
        return None
    if isinstance(value, enum_cls):
        return value
    label = str(value).strip()
    if not label:
        return None
    return enum_cls(label)


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(item).strip() for item in value if str(item or "").strip())


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0
