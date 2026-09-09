"""The provider binding of the composed ``method_loop.Episode`` method.

Chartered in ``docs/ACQUISITION_LOOP.md``; designed in
``experiments/log/4E-c-provider-composition.md``. This is the ONE file that
owns the provider surface's binding; the generic kernel stays in
``method_loop/`` and provider/search mechanics stay injected collaborators.

    run Episode  (unit: one completed strategy Episode)
      |
      +-- strategy Episode  (unit: one completed search Episode)
            |
            +-- search Episode  (unit: one fetched page/document)
                  |
                  +-- page Episode  (unit: one lexical-probe Episode)
                        |
                        +-- lexical-probe Episode  (unit: one chunk)
                              |
                              +-- chunk Leaf
                                    extract -> accept evidence -> credit

    fan-up: chunk -> lexical probe -> page -> search -> strategy -> run

The run is driven by **one** ``Episode.run_async`` call. Nothing in this package
contains a ``for`` or ``while`` that pulls a unit, calls ``scoped.observe``,
reads a verdict, or keeps a per-scope list. The loop body is the kernel's, once,
in ``method_loop.episode.Episode``.

What this module owns
---------------------

1. **The five grains**, each declared once with its unit and credit sentences.
   The run-start ``TableCreditAssigner`` supplies their one frozen generic channel
   schema before any scope opens. Their numerical controls are declared once
   and consume the same role-based estimate contract.
2. **The credit assigner**: accepted evidence is first written into typed table
   state; one deterministic assignment then projects the resulting supported
   logical value slots. Row completion is a diagnostic of that same projection.
   It reads no curve and calls no model.
3. **The fate rule**: what a page's outcome means for ``(active,
   counts_toward_verdict)``, implemented once here and *called* by the
   surface's ``extract`` -- never re-derived by a second module.
4. **The sources**, one per grain, and the typed objects they read before a
   pull (a page budget, provider health, the run's terminal state).
5. **The binding**: ``ProviderBinding`` builds the five Episode declarations,
   binds the chunk leaf, hooks, source callbacks, and record writers through
   injected collaborators. ``AcquisitionController`` owns the context and the
   single kernel call. Neither consults anything between units.

An acquisition credit is a table-supported logical value-slot identity. The source version,
exact chunk and span, direct assertion candidate, and deterministic acceptance
must already be durable in ``evidence_registry`` and the accepted value must be
materialized in typed table state before this surface can emit that identity.
The same post-storage projection reports row completion without creating a
second credit identity or channel.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import (
    Any,
    AbstractSet,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
    Optional,
    Sequence,
)

from method_loop import (
    END_BOUND_HIT,
    END_EXHAUSTED,
    END_SOURCE_FAILED,
    END_YIELD_STOP,
    Context,
    CreditResult,
    Episode,
    EpisodeRecord,
    EpisodeView,
    Grain,
    Leaf,
    ResumeUnit,
    ScopedYield,
    SourceEnd,
)
from rarefaction import ChannelSchema, ControllerConfig, IncidenceReport

from . import criteria
from .control import select_first_clearing, stable_id
from .costs import CostErrorClass, ObservationKind, classify_error
from .evidence_registry import (
    AcceptedBestGuessCell,
    BestGuessAssertionCandidate,
    DirectAssertionCandidate,
    EvidenceCommit,
    SourceChunk,
    SourceDocument,
    SourceVersion,
    TextSpan,
)
from .evidence_acceptance import EvidenceAcceptor
from .table_specs import ColumnEvidenceRole
from .tables import (
    ResultContract,
    ResultColumn,
    TableMutation,
    TypedTableStore,
    result_contract,
)
from .search import (
    SearchFrontier,
    SearchHarvester,
    SearchOutcome,
    SearchTask,
    is_fatal_search_error,
    search_result_observation,
    summarize_prompt_arms,
)

__all__ = [
    "ACQUISITION_POLICY_NAME",
    "CREDIT_SEMANTICS",
    "DEFAULT_CHUNK_CONTROL",
    "DEFAULT_ITEM_CONTROL",
    "DEFAULT_PAGE_CONTROL",
    "DEFAULT_RUN_CONTROL",
    "DEFAULT_STRATEGY_CONTROL",
    "LEXICAL_PROBE_GRAIN",
    "LEXICAL_EMPTY_PREFIX_GAMMA",
    "MAX_PROPOSAL_SAMPLES",
    "PAGE_CREDIT_WINDOW",
    "REJECT_OPERATOR_NOT_IN_CATALOG",
    "RUN_GRAIN",
    "SEARCH_GRAIN",
    "STRATEGY_DISTANCE_FLOOR",
    "STRATEGY_GRAIN",
    "AcquisitionController",
    "AcquisitionDecision",
    "TableCreditAssigner",
    "CreditAttribution",
    "CreditColumn",
    "PageCredit",
    "PAGE_GRAIN",
    "PageMaterial",
    "PageSource",
    "PageUnit",
    "ProviderHealth",
    "ProviderBinding",
    "RunTermination",
    "SourceBudget",
    "StrategyProposer",
    "StrategySearches",
    "declared_credit_columns",
    "join_costs",
    "lexical_threshold_adapter",
    "page_fate",
    "window_episode_record",
]

ACQUISITION_POLICY_NAME = "acquisition_yield_v2"

#: Stamped on every emitted acquisition record. The module docstring's
#: separation, in the artifact a later reader actually opens.
CREDIT_SEMANTICS = "single_post_table_logical_slot_credit_v2"


# ==========================================================================
# The five grains -- the one place a policy is declared (charter rule 4)
# ==========================================================================

#: Per-search item policy. Firecrawl may return a provider-sized batch, but the
#: batch is only a buffer. After each one-page pull, the paired numerical
#: component predicts the next page's marginal hypervolume credit. Its upper
#: band must be zero for the declared streak before this policy stops.
DEFAULT_ITEM_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=4
)

#: Chunk policy inside one lexical probe. Its base threshold remains
#: conservative; the binding adapter below relaxes it only for an initial
#: successfully evaluated prefix that has produced no accepted identity.
DEFAULT_CHUNK_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=4
)

LEXICAL_EMPTY_PREFIX_GAMMA = 0.06

#: Lexical-probe policy inside one page.  Its unit is a completed ranking, so
#: it can be calibrated independently from both chunks and Firecrawl pages.
DEFAULT_PAGE_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=4
)

#: Strategy-grain policy (unit = one completed search). Its scalar threshold is
#: fixed before the run and applies to predicted next-search hypervolume.
DEFAULT_STRATEGY_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=8
)

#: Run-grain policy (unit = one completed strategy). Its scalar threshold is
#: fixed before the run and applies to predicted next-strategy hypervolume.
DEFAULT_RUN_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=8
)

SEARCH_GRAIN = Grain(
    name="search",
    unit=(
        "one fetched page or document from this search's result list: the page "
        "is acquired and extracted before the next one is pulled"
    ),
    credit=(
        "one non-trivial logical value slot for a declared, deliverable, "
        "non-key contract column"
    ),
    control=DEFAULT_ITEM_CONTROL,
)

PAGE_GRAIN = Grain(
    name="page",
    unit="one completed lexical-probe episode over this page's remaining chunks",
    credit=(
        "one accepted finding that the probe contributed to this page, counted "
        "once however many chunks in that probe carried it"
    ),
    control=DEFAULT_PAGE_CONTROL,
)

LEXICAL_PROBE_GRAIN = Grain(
    name="lexical_probe",
    unit=(
        "one previously unprocessed chunk from this probe's lexical ranking; "
        "the same chunk identity is never pulled twice on one page"
    ),
    credit=(
        "one accepted finding carried by that chunk; recurrence in another "
        "chunk is incidence but not a new distinct finding"
    ),
    control=DEFAULT_CHUNK_CONTROL,
)


def lexical_threshold_adapter(
    report: IncidenceReport,
    current: Mapping[str, object],
) -> Mapping[str, object]:
    """Relax lexical stopping only while its accepted prefix is empty."""

    if report.primary.scope_path[-1][0] != LEXICAL_PROBE_GRAIN.name:
        return current
    rho = current.get("rho")
    if not isinstance(rho, Mapping):
        raise TypeError("lexical threshold adapter requires channel rho values")
    return {
        "gamma": (
            LEXICAL_EMPTY_PREFIX_GAMMA
            if report.primary.observed_results.value == 0.0
            else DEFAULT_CHUNK_CONTROL.gamma
        ),
        "rho": dict(rho),
    }

STRATEGY_GRAIN = Grain(
    name="strategy",
    unit="one completed search episode of this strategy",
    credit=(
        "one credit identity that a search contributed to this strategy, "
        "counted once however many of its pages carried it"
    ),
    control=DEFAULT_STRATEGY_CONTROL,
)

RUN_GRAIN = Grain(
    name="run",
    unit="one completed strategy episode",
    credit=(
        "one credit identity that a strategy contributed to the run, counted "
        "once however many of its searches carried it"
    ),
    control=DEFAULT_RUN_CONTROL,
)

#: The declared grain order of this composition, handed to ``Context`` so a
#: mis-nested episode fails by name instead of opening a scope nobody meant.
GRAIN_ORDER = (
    RUN_GRAIN,
    STRATEGY_GRAIN,
    SEARCH_GRAIN,
    PAGE_GRAIN,
    LEXICAL_PROBE_GRAIN,
)


def grain_disclosure(grain: Grain) -> dict[str, Any]:
    """One grain's numerical declaration for the durable record."""

    return {
        "name": grain.name,
        "unit": grain.unit,
        "credit": grain.credit,
        "controller": grain.control.as_record(),
    }


# ==========================================================================
# End vocabulary -- class labels, never prose; nothing branches on them
# ==========================================================================

FATAL_SEARCH_ERROR = "fatal_search_error"
SEARCH_ERROR = "search_error"
BOUND_KIND_RUN_SOURCE_BUDGET = "run_source_budget"
BOUND_KIND_EPISODE_UNIT_SAFETY_CAP = "episode_unit_safety_cap"
#: A spent sampling budget is a CUT, not exhaustion. ``None`` stays reserved for
#: the honest end -- the declared catalog is drained and the sampler returned
#: nothing at all -- because "the mutation mechanism gave up" and "the search
#: space ran out" license opposite conclusions about a run's low yield.
BOUND_KIND_PROPOSAL_SAMPLES = "proposal_samples"
RUN_END_GOAL_FULFILLED = "run_goal_fulfilled"
RUN_END_EXECUTION_ERROR = "run_execution_error"

#: ``control.StopReason`` -> (end kind, end reason). A written table, not an
#: inference. ``GOAL_FULFILLED`` is a ``bound_hit`` deliberately: it is a
#: satisfaction condition, not a yield verdict, and presenting it as a
#: ``yield_stop`` would let a policy judgement wear the stop rule's clothes.
#: ``FRONTIER_EXHAUSTED`` is the one genuine exhaustion, and is signalled by the
#: source returning ``None`` rather than a ``SourceEnd``.
STOP_REASON_ENDS: dict[str, tuple[str, str]] = {
    "task_goal_fulfilled": (END_BOUND_HIT, RUN_END_GOAL_FULFILLED),
    "source_budget_exhausted": (END_BOUND_HIT, BOUND_KIND_RUN_SOURCE_BUDGET),
    "episode_unit_safety_cap": (
        END_BOUND_HIT,
        BOUND_KIND_EPISODE_UNIT_SAFETY_CAP,
    ),
    "execution_error": (END_SOURCE_FAILED, RUN_END_EXECUTION_ERROR),
}
STOP_REASON_FRONTIER_EXHAUSTED = "search_frontier_exhausted"


# ==========================================================================
# The declared typed objects a source reads before a pull (charter rule 7)
# ==========================================================================


@dataclass
class SourceBudget:
    """Pages this run may still pull.

    Written by the page hook, read by the sources before a pull, and read by
    ``extract`` never at all -- which is the clause rule 7 is about. It charges
    every **pulled** page, not every accepted one: mechanically unusable and
    extraction-failed pages still cost acquisition work and remain explicit
    units even though they do not enter the estimator's judged history.
    """

    limit: int
    spent: int = 0

    @property
    def exhausted(self) -> bool:
        return self.limit > 0 and self.spent >= self.limit

    def charge(self, pages: int = 1) -> None:
        self.spent += max(0, int(pages))

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "pages_pulled": self.spent,
        }


@dataclass
class ProviderHealth:
    """Whether the provider has refused this run. A class label, never prose."""

    fatal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"fatal": self.fatal}


@dataclass
class RunTermination:
    """The run-level terminal state the run source reads before every pull.

    Written by the ``on_strategy`` hook from ``control.resolve_stop_decision``,
    which is the one entry point for that question, and carrying the typed
    ``StopReason`` member and the decision id -- never prose. Read by
    :meth:`StrategyProposer.next`; ``extract`` reads it not at all.

    Without this the composition would have one decision edge -- "does this run
    continue" -- with no rule at all: ``orchestration_stop_override`` is a pure
    function that raises nothing, and the round loop that used to read it is
    deleted.
    """

    stopped: bool = False
    reason: str = ""
    decision_id: str = ""

    def source_end(self) -> Optional[SourceEnd]:
        """The named end this termination becomes, or ``None``.

        ``None`` here means "this reason ends the run by exhaustion" and is only
        reachable when :attr:`stopped` is already True -- the caller branches on
        ``stopped`` first, so "no termination" and ``FRONTIER_EXHAUSTED`` are
        never conflated.
        """

        if not self.stopped:
            return None
        end = STOP_REASON_ENDS.get(self.reason)
        if end is None:
            return None
        return SourceEnd(end[0], end[1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "stopped": self.stopped,
            "reason": self.reason,
            "decision_id": self.decision_id,
        }


# ==========================================================================
# The fate table -- a PAIR of axes, so it partitions
# ==========================================================================

#: Mechanical outcomes reached before extraction. First match in this order wins,
#: and every one of them is an announced NON-JUDGEMENT: the page is in the curve
#: with its disclosure count and out of the stop history, because a fact about a
#: URL is not evidence about whether the result list is still yielding.
FATE_DUPLICATE_URL = "duplicate_url"
FATE_FETCH_FAILED = "fetch_failed"
FATE_BLOCKED_PAGE = "blocked_page"
FATE_TOO_SHORT = "too_short"
FATE_TOO_LARGE = "too_large"
FATE_NO_EXTRACTOR = "no_extractor"
FATE_NO_CREDIT_COLUMNS = "no_credit_columns"

PRE_EXTRACTION_FATES = (
    FATE_DUPLICATE_URL,
    FATE_FETCH_FAILED,
    FATE_BLOCKED_PAGE,
    FATE_TOO_SHORT,
    FATE_TOO_LARGE,
    FATE_NO_EXTRACTOR,
    FATE_NO_CREDIT_COLUMNS,
)

#: Extraction outcomes. ``EXTRACT_ALL_CHUNKS_FAILED`` exists because
#: ``extraction.extract_from_text`` converts a per-chunk timeout or exception
#: into an empty result: without it a page whose every chunk failed would reach
#: the "extracted" row, enter the stop history as a barren judged unit, and a
#: stream of them would read as a result list that had stopped yielding. That is
#: the silent-failure class this build bans, with a mechanical cause instead of
#: a model one.
EXTRACT_OK = "extracted"
EXTRACT_RAISED = "extract_raised"
EXTRACT_ALL_CHUNKS_FAILED = "extract_all_chunks_failed"
EXTRACT_NOT_RUN = "not_run"


@dataclass(frozen=True)
class PageFate:
    """One page's mechanical and extraction outcome."""

    #: One of :data:`PRE_EXTRACTION_FATES`, or ``""`` when extraction was attempted.
    mechanical: str = ""
    #: One of the ``EXTRACT_*`` labels, or ``""`` likewise.
    extraction: str = ""
    #: The classified error, for the two classified mechanical rows and for a
    #: raised extraction. A class label from `costs.classify_error`, never prose.
    error_class: str = ""

    @property
    def credit_note(self) -> str:
        """The counted class label. Composed from both axes, never prose."""

        if self.mechanical:
            if self.error_class:
                return f"not_judged:{self.mechanical}:{self.error_class}"
            return f"not_judged:{self.mechanical}"
        extraction = self.extraction or EXTRACT_NOT_RUN
        if extraction == EXTRACT_RAISED and self.error_class:
            extraction = f"{extraction}:{self.error_class}"
        return f"extract:{extraction}"

    @property
    def judged(self) -> bool:
        """Whether this page is evidence about the search's yield.

        A mechanical skip is a fact about a URL and stays out. An extraction
        that raised, or one whose every chunk failed, is an instrument failure
        and stays out. Every successfully extracted page is a judged unit,
        including pages that produce no new accepted evidence.
        """

        if self.mechanical:
            return False
        if self.extraction in (EXTRACT_RAISED, EXTRACT_ALL_CHUNKS_FAILED):
            return False
        return True

    @property
    def disclosure(self) -> str:
        """Why this page could not be judged. Empty when it was."""

        if self.judged:
            return ""
        if self.mechanical == FATE_NO_EXTRACTOR:
            return (
                "no extractor is built yet: the schema is synthesized from "
                "these pages, so zero credits here means 'could not judge'"
            )
        if self.mechanical == FATE_NO_CREDIT_COLUMNS:
            return (
                "no declared, deliverable, non-key credit columns exist; zero "
                "credits here means 'could not judge', not 'barren page'"
            )
        if self.mechanical:
            return (
                f"the page was not judged: {self.credit_note}; a fact about "
                f"this URL, not evidence about this search's yield"
            )
        return (
            f"extraction did not deliver a readable result: {self.credit_note}; "
            f"an instrument failure, not a page that carried nothing"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mechanical": self.mechanical,
            "extraction": self.extraction,
            "error_class": self.error_class,
            "credit_note": self.credit_note,
            "judged": self.judged,
        }


#: Fate -> the reason a page contributes to ``SearchOutcome.skipped_by_reason``.
#: DECLARED ONCE, HERE, beside the fate rule, under the same single-owner clause
#: as the fate mapping itself: no consumer re-derives it by matching class-label
#: strings, because arm penalties and arm provenance are read from declared
#: fields and never reconstructed from wording.
#:
FATE_SKIP_REASONS: dict[str, str] = {
    FATE_DUPLICATE_URL: "duplicate_url",
    FATE_FETCH_FAILED: "fetch_failed",
    FATE_BLOCKED_PAGE: "blocked_page",
    FATE_TOO_SHORT: "too_short",
    FATE_TOO_LARGE: "too_large",
    FATE_NO_EXTRACTOR: "no_extractor",
    FATE_NO_CREDIT_COLUMNS: "no_credit_columns",
    EXTRACT_RAISED: "extract_failed",
    EXTRACT_ALL_CHUNKS_FAILED: "extract_all_chunks_failed",
}


def fate_skip_reason(fate: PageFate) -> str:
    """What this page adds to ``SearchOutcome.skipped_by_reason``, or ``""``."""

    if fate.mechanical:
        return FATE_SKIP_REASONS.get(fate.mechanical, "")
    return FATE_SKIP_REASONS.get(fate.extraction, "")


def page_fate(
    *,
    mechanical: str = "",
    extraction: str = "",
    error_class: str = "",
) -> PageFate:
    """Mint one page's fate. The only constructor callers use.

    ``pipeline`` returns ``PageMaterial`` facts and mints no fate: two modules
    holding opinions about what a fate means is how a model's boolean ended up
    on ``CreditResult.active`` in the first place.
    """

    if mechanical and mechanical not in PRE_EXTRACTION_FATES:
        raise ValueError(f"{mechanical!r} is not a declared pre-extraction fate")
    return PageFate(
        mechanical=mechanical,
        extraction=extraction,
        error_class=error_class,
    )


# ==========================================================================
# The leaf's unit and material
# ==========================================================================


@dataclass
class PageUnit:
    """One pulled page. The Leaf's unit -- NOT an ``Acquirable``.

    Constructed fresh on every pull and never reused across leaves, which is
    what makes :attr:`credit_detail`'s raise-on-second-write a guard rather than
    a latent crash.
    """

    task: Any
    result: Mapping[str, Any]
    rank: int
    episode_id: str
    episode_path: tuple[tuple[str, str], ...]
    #: The PULL-TIME identity: ``f"{task.id}#{rank}"``. Every page has one,
    #: accepted or not, before any I/O -- which is what a source id could never
    #: be, because it is minted inside ``extract`` while ``Leaf`` is frozen
    #: before ``extract`` runs. It is the leaf label, hence the page
    #: ``UnitRecord.unit_label``, and it is the SOURCE cost record's
    #: ``observation_id``, so every page including the ones refused before a
    #: source id exists has one joinable cost record.
    label: str = ""
    #: Written exactly once by the crediter and read by the hook. ``extract``
    #: neither reads nor writes it, and nothing anywhere branches on its
    #: contents: the rule labels it carries are counted and recorded, never
    #: compared to steer anything.
    credit_detail: Optional["PageCredit"] = None

    def attach_credit(self, detail: "PageCredit") -> None:
        if self.credit_detail is not None:
            raise ValueError(
                f"credit detail already attached to page {self.label!r}; a "
                f"PageUnit is constructed fresh per pull and credited once"
            )
        object.__setattr__(self, "credit_detail", detail)


@dataclass(frozen=True)
class ChunkUnit:
    """One exact chunk selected once inside one page's lexical probes."""

    page: PageUnit
    span: Any
    source_record: Mapping[str, Any]
    episode_id: str
    episode_path: tuple[tuple[str, str], ...]
    probe_key: str
    label: str
    credit_detail: Optional["PageCredit"] = None

    def attach_credit(self, detail: "PageCredit") -> None:
        if self.credit_detail is not None:
            raise ValueError(
                f"credit detail already attached to chunk {self.label!r}"
            )
        object.__setattr__(self, "credit_detail", detail)


@dataclass
class PageRunState:
    """Binding-local state shared by successive probes of one page."""

    unit: PageUnit
    source_record: Mapping[str, Any]
    ingestion: dict[str, Any]
    reduction: Mapping[str, Any]
    chunks: tuple[Any, ...]
    outline: Mapping[str, Any]
    processed_chunk_ids: set[str] = field(default_factory=set)
    seen_finding_ids: set[str] = field(default_factory=set)
    probe_proposals: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    probe_history: list[dict[str, Any]] = field(default_factory=list)
    chunk_units: list[ChunkUnit] = field(default_factory=list)
    materials: list["PageMaterial"] = field(default_factory=list)

    def chunk_id(self, span: Any) -> str:
        return f"{self.source_record.get('id', '')}_chunk_{span.index}"

    def remaining_chunks(self) -> tuple[Any, ...]:
        return tuple(
            span
            for span in self.chunks
            if self.chunk_id(span) not in self.processed_chunk_ids
        )


@dataclass(frozen=True)
class PageMaterial:
    """What ``extract`` returns. Facts only -- no ``active`` flag, no fate.

    ``records`` are the extracted records the assertion-candidate builder iterates, each
    ``{"table", "index", "values", "source_chunks"}``: kind-2 credits are a
    property of ONE extracted record, and a stream that flattens every entity's
    attributes together cannot say whether one subject carried six columns or
    six subjects carried one each.
    """

    source_id: str = ""
    fate: PageFate = field(default_factory=PageFate)
    entities: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    relationships: Sequence[Mapping[str, Any]] = ()
    records: Sequence[Mapping[str, Any]] = ()
    guesses: Sequence[Mapping[str, Any]] = ()
    #: The accepted source unit's persisted record, or ``None`` when the page
    #: was refused before one was written. Generic unit vocabulary on purpose:
    #: the unit is one fetched page or document, whatever the medium.
    source_record: Optional[Mapping[str, Any]] = None
    ingestion: Mapping[str, Any] = field(default_factory=dict)
    reduction: Mapping[str, Any] = field(default_factory=dict)
    #: Per-chunk encounters, including whether each chunk's extraction FAILED --
    #: so a chunk-grain replay cannot read an instrument failure as barrenness.
    chunks: Sequence[Mapping[str, Any]] = ()
    #: Model calls and their cost belong to the SOURCE scope this ran inside.
    text_chars: int = 0
    evidence_commit: Optional[EvidenceCommit] = None
    evidence_commits: Sequence[EvidenceCommit] = ()
    probe_history: Sequence[Mapping[str, Any]] = ()


# ==========================================================================
# The credit basis -- one owner, and the exclusion is disclosed by class
# ==========================================================================

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NAME_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_REPORTED_NUMBER_RE = re.compile(
    r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?"
)

RULE_DECLARED_NAME = "declared_name"
RULE_DECLARED_ALIAS = "declared_alias"
RULE_TOKEN_OVERLAP = "token_overlap"

SOURCE_KIND_VERBATIM = "verbatim"


def _reported_number(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool):
        return None
    match = _REPORTED_NUMBER_RE.fullmatch(str(value).strip())
    if match is None:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def _locate_reported_value(
    value: Any,
    chunks: Sequence[SourceChunk],
) -> Optional[tuple[SourceChunk, int, int, str]]:
    """Find a literal value, allowing only numeric-format normalization."""

    literal = str(value)
    for chunk in chunks:
        offset = chunk.text.find(literal)
        if offset >= 0:
            return chunk, offset, offset + len(literal), "exact_text"
    numeric = _reported_number(value)
    if numeric is None:
        return None
    for chunk in chunks:
        for match in _REPORTED_NUMBER_RE.finditer(chunk.text):
            if _reported_number(match.group(0)) == numeric:
                return (
                    chunk,
                    match.start(),
                    match.end(),
                    "numeric_format",
                )
    return None


def _tokens(name: Any) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(str(name or "").lower()))


def _normalize_name(name: Any) -> str:
    return _NAME_NORMALIZE_RE.sub("_", str(name or "").lower()).strip("_")


@dataclass(frozen=True)
class CreditColumn:
    """One declared target column, with everything a consumer needs of it.

    Carries the declared fields as well as the matching keys so the ONE
    selection of columns lives here, so acceptance and incidence cannot drift
    onto independently selected contracts.
    """

    table: str
    column: str
    table_id: str
    column_id: str
    value_slot: str
    slot_id: str
    required: bool
    role: ColumnEvidenceRole
    token_keys: tuple[frozenset[str], ...]
    normalized_names: tuple[str, ...] = ()
    normalized_aliases: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    description: str = ""
    value_type: str = ""
    unit: str = ""


@dataclass(frozen=True)
class ExcludedColumn:
    """A declared column the basis refuses, and the class it refused it on."""

    table: str
    column: str
    exclusion_class: str


@dataclass(frozen=True)
class CreditBasis:
    """The declared ordinary columns, exclusions, and subject keys."""

    columns: tuple[CreditColumn, ...]
    excluded: tuple[ExcludedColumn, ...]
    subject_key_columns: Mapping[str, tuple[str, ...]]
    tables: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": [
                {
                    "table": column.table,
                    "table_id": column.table_id,
                    "column": column.column,
                    "column_id": column.column_id,
                    "value_slot": column.value_slot,
                    "slot_id": column.slot_id,
                    "required": column.required,
                    "role": column.role.value,
                    "value_type": column.value_type,
                    "unit": column.unit,
                }
                for column in self.columns
            ],
            "excluded_columns": [
                {
                    "table": item.table,
                    "column": item.column,
                    "class": item.exclusion_class,
                }
                for item in self.excluded
            ],
            "subject_key_columns": {
                table: list(columns)
                for table, columns in self.subject_key_columns.items()
            },
            "typed_column_count": sum(
                1 for column in self.columns if column.value_type or column.unit
            ),
        }


def declared_credit_columns(table_spec: Any) -> tuple[CreditColumn, ...]:
    """The columns whose values count as acquisition credits.

    Kept as the package's public name for the basis; :func:`credit_basis`
    returns the same computation with its exclusions attached.
    """

    return credit_basis(table_spec).columns


def credit_basis(table_spec: Any) -> CreditBasis:
    """Add extraction matching keys to the store-owned result contract.

    ``tables.result_contract`` is the one owner of column selection and
    logical-slot grouping. This surface adds only the lexical names needed to
    map extracted fields onto those already-selected physical columns.

    **THE BASIS HAS ONE OWNER AND IT IS ``criteria``.** This used to keep a
    second, weaker opinion -- key membership plus the provenance name shape --
    which admitted ``evidence_gap``: the producer's own verdict about its
    output, minting a credit, in the numerator of the rule that decides whether
    to keep fetching. The loop was deciding whether to keep acquiring partly on
    the strength of what the extractor said about its own output. Routing the
    basis through ``criteria.is_datapoint_field`` closes the *class* rather than
    the instance: the next producer self-verdict column added to that module's
    list leaves this basis on the same day, with no second edit here.

    The over-exclusion risk is named rather than hidden: ``criteria``'s
    canonical graph keys include ``name``, ``source`` and ``target``, and a
    different domain could declare a real column so named. Such a column would
    stop crediting -- which is the aligned direction, because ``criteria``
    already refuses to make it a criterion, so a value there can never become a
    datapoint, and crediting acquisition for a column that can never become a
    datapoint is operational volume with an identity attached. Every exclusion
    is emitted with its class, so an unintended one is legible on the first run.
    """

    return _credit_basis_from_contract(result_contract(table_spec))


def _credit_basis_from_contract(contract: ResultContract) -> CreditBasis:
    return CreditBasis(
        columns=tuple(_credit_column(column) for column in contract.columns),
        excluded=tuple(
            ExcludedColumn(item.table, item.column, item.exclusion_class)
            for item in contract.excluded
        ),
        subject_key_columns=contract.subject_key_columns,
        tables=contract.tables,
    )


def _credit_column(column: ResultColumn) -> CreditColumn:
    name = column.column
    aliases = column.aliases
    names = [name, *aliases]
    token_keys = tuple(dict.fromkeys(_tokens(item) for item in names if _tokens(item)))
    return CreditColumn(
        table=column.table,
        column=name,
        table_id=column.table_id,
        column_id=column.column_id,
        value_slot=column.value_slot,
        slot_id=column.slot_id,
        required=column.required,
        role=column.role,
        token_keys=token_keys,
        normalized_names=(_normalize_name(name),),
        normalized_aliases=tuple(
            dict.fromkeys(_normalize_name(alias) for alias in aliases if alias)
        ),
        aliases=aliases,
        description=column.description,
        value_type=column.value_type,
        unit=column.unit,
    )


# ==========================================================================
# The crediter
# ==========================================================================


@dataclass(frozen=True)
class CreditAttribution:
    """One post-storage credit assignment for one logical value slot."""

    identity: str
    assignment_id: str
    criterion_id: str
    subject_id: str
    source_id: str
    table: str
    column: str
    value_slot: str
    slot_id: str
    field: str
    rule: str
    triviality_rule: str
    source_kind: str
    new_to_table: bool
    before_table_state_id: str
    after_table_state_id: str
    strategy_key: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "assignment_id": self.assignment_id,
            "criterion_id": self.criterion_id,
            "subject_id": self.subject_id,
            "source_id": self.source_id,
            "table": self.table,
            "column": self.column,
            "value_slot": self.value_slot,
            "slot_id": self.slot_id,
            "field": self.field,
            "rule": self.rule,
            "triviality_rule": self.triviality_rule,
            "source_kind": self.source_kind,
            "new_to_table": self.new_to_table,
            "before_table_state_id": self.before_table_state_id,
            "after_table_state_id": self.after_table_state_id,
            "strategy_key": self.strategy_key,
        }


@dataclass(frozen=True)
class RowCompletionDetail:
    """Diagnostic for a first transition to all required logical slots."""

    identity: str
    table: str
    subject_id: str
    accepted_slot_ids: tuple[str, ...]
    declared_total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "table": self.table,
            "subject_id": self.subject_id,
            "accepted_slot_ids": list(self.accepted_slot_ids),
            "declared_total": self.declared_total,
        }


@dataclass(frozen=True)
class _AcceptedProjection:
    """Post-storage logical-slot incidence and row diagnostics."""

    attributions: tuple[CreditAttribution, ...] = ()
    row_completions: tuple[RowCompletionDetail, ...] = ()


@dataclass(frozen=True)
class PageCredit:
    """The typed breakdown the crediter writes onto the unit it was handed.

    It travels on the unit rather than on ``CreditResult`` because a credit
    identity is a dedupe key -- appending the rule that matched it would make
    one value matched two ways two identities -- and because adding an opaque
    payload to a kernel type that was deliberately kept minimal is worse than a
    declared object on this surface's own unit. Written once by the crediter,
    read by the hook, ordered by the kernel's fixed credit -> observe -> hook
    step rather than by a convention.
    """

    attributions: tuple[CreditAttribution, ...]
    row_completions: tuple[RowCompletionDetail, ...]
    row_completion_unavailable: Mapping[str, str]
    declared_facets: tuple[str, ...]
    chunk_encounters: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributions": [item.to_dict() for item in self.attributions],
            "row_completions": [item.to_dict() for item in self.row_completions],
            "row_completion_unavailable": dict(self.row_completion_unavailable),
            "declared_facets": list(self.declared_facets),
            "chunk_encounters": [dict(item) for item in self.chunk_encounters],
        }


class TableCreditAssigner:
    """The single what-counts rule: typed table state -> incidence channels.

    Evidence acceptance is necessary but not sufficient. The accepted cells
    are first materialized by ``TypedTableStore``; only cells present in the
    resulting typed table state receive an assignment. These exact
    assignments feed Episode incidence and later yield reporting.

    CONSTRUCTED ONCE PER RUN, with two consequences stated rather than left to a
    run to discover: a column the planner adds to the observed spec mid-run
    never credits, and the declared facet set is fixed at run start. The digest
    of the spec it was built from is emitted on every record, so a mid-run spec
    rewrite is legible against a denominator that did not move.
    """

    def __init__(self, table_spec: Any, table_store: TypedTableStore) -> None:
        self._table_spec = table_spec
        if not isinstance(table_store, TypedTableStore):
            raise TypeError("TableCreditAssigner requires a TypedTableStore")
        if table_spec != table_store.table_spec:
            raise ValueError(
                "TableCreditAssigner and TypedTableStore must share one table contract"
            )
        self._table_store = table_store
        self._assignments: list[CreditAttribution] = []
        self._basis = _credit_basis_from_contract(table_store.result_contract)
        self._by_table: dict[str, list[CreditColumn]] = {}
        self._column_by_id: dict[str, CreditColumn] = {}
        self._column_by_field: dict[tuple[str, str], CreditColumn] = {}
        for column in self._basis.columns:
            self._by_table.setdefault(column.table, []).append(column)
            self._column_by_id[column.column_id] = column
            self._column_by_field[(column.table, column.column)] = column
        self._row_completion_unavailable: dict[str, str] = {}
        for table in self._basis.tables:
            if not self._basis.subject_key_columns.get(table):
                self._row_completion_unavailable[table] = (
                    "table declares no subject_key_columns, so logical row "
                    "completion cannot be measured"
                )
            elif not self._by_table.get(table):
                self._row_completion_unavailable[table] = (
                    "table declares no non-key result slots, so logical row "
                    "completion cannot be measured"
                )
        ordinary = tuple(
            f"column:{slot.slot_id}"
            for slot in table_store.result_contract.slots
        )
        self._declared_facets = ordinary
        self._facet_labels = {
            f"column:{slot.slot_id}": f"{slot.table}.{slot.value_slot}"
            for slot in table_store.result_contract.slots
        }
        required = tuple(
            f"column:{slot.slot_id}"
            for slot in table_store.result_contract.slots
            if slot.required
        )
        self._channel_schema = (
            ChannelSchema.partition(
                self._declared_facets,
                union_members=ordinary,
                controller_channels=required or ordinary,
            )
            if ordinary
            else ChannelSchema.single()
        )
        self._spec_digest = stable_id(self._basis.to_dict())

    # ------------------------------------------------------------------ #
    # declarations
    # ------------------------------------------------------------------ #
    @property
    def basis(self) -> CreditBasis:
        return self._basis

    @property
    def declared_facets(self) -> tuple[str, ...]:
        return self._declared_facets

    @property
    def facet_labels(self) -> Mapping[str, str]:
        return dict(self._facet_labels)

    @property
    def channel_schema(self) -> ChannelSchema:
        return self._channel_schema

    @property
    def spec_digest(self) -> str:
        return self._spec_digest

    @property
    def row_completion_unavailable(self) -> Mapping[str, str]:
        return dict(self._row_completion_unavailable)

    @property
    def rows_by_name(self) -> dict[str, list[dict[str, Any]]]:
        return self._table_store.rows_by_name

    def assignments_for_strategy(self, strategy_key: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            item.to_dict()
            for item in self._assignments
            if item.strategy_key == str(strategy_key)
        )

    def checkpoint_assignments(self) -> tuple[dict[str, Any], ...]:
        return tuple(item.to_dict() for item in self._assignments)

    def restore_assignments(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self._assignments = [
            CreditAttribution(**dict(row))
            for row in rows
            if isinstance(row, Mapping)
        ]

    def columns_by_table(self) -> dict[str, list[str]]:
        return {
            table: [column.column for column in columns]
            for table, columns in self._by_table.items()
        }

    def best_guess_columns_by_table(self) -> dict[str, list[str]]:
        return {
            table: [
                column.column
                for column in columns
                if column.role is ColumnEvidenceRole.BEST_GUESS
            ]
            for table, columns in self._by_table.items()
        }

    def best_guess_routes_by_table(self) -> dict[str, dict[str, list[str]]]:
        routes: dict[str, dict[str, list[str]]] = {}
        for table, columns in self._by_table.items():
            reported_by_slot: dict[str, list[str]] = {}
            for column in columns:
                if column.role is ColumnEvidenceRole.REPORTED:
                    reported_by_slot.setdefault(column.value_slot, []).append(
                        column.column
                    )
            routes[table] = {
                column.column: list(reported_by_slot.get(column.value_slot, ()))
                for column in columns
                if column.role is ColumnEvidenceRole.BEST_GUESS
            }
        return routes

    def assertion_candidates(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        document: SourceDocument,
        version: SourceVersion,
        chunks: Sequence[SourceChunk],
    ) -> tuple[tuple[TextSpan, ...], tuple[DirectAssertionCandidate, ...]]:
        """Anchor direct scalar extractions to exact source-version spans."""

        spans: dict[str, TextSpan] = {}
        candidates: list[DirectAssertionCandidate] = []
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        for position, record in enumerate(records):
            if not isinstance(record, Mapping):
                continue
            table = str(record.get("table") or "")
            values = record.get("values")
            if not isinstance(values, Mapping):
                continue
            subject_refs = criteria.row_subject_refs(
                table, [values], self._table_spec
            )
            subject = subject_refs[0] if subject_refs else None
            if subject is None:
                continue
            record_chunks = tuple(
                chunks_by_id[chunk_id]
                for chunk_id in (
                    str(item) for item in record.get("source_chunks") or ()
                )
                if chunk_id in chunks_by_id
            )
            if not record_chunks:
                continue
            for field_name, value in _iter_fields(values):
                match = self._match(
                    field_name,
                    [
                        column
                        for column in self._by_table.get(table) or ()
                        if column.role is ColumnEvidenceRole.REPORTED
                    ],
                )
                if match is None or isinstance(value, (Mapping, list, tuple, set, bool)):
                    continue
                column, match_rule = match
                admitted = self._non_trivial(value, column)
                if admitted is None:
                    continue
                located = _locate_reported_value(value, record_chunks)
                if located is None:
                    continue
                chunk, offset, end, source_match_rule = located
                span = TextSpan.create(chunk, offset, end)
                spans.setdefault(span.id, span)
                ref = criteria.CriterionRef.create(
                    table=table,
                    field=column.column,
                    subject_id=subject.id,
                    subject_key=subject.key,
                    identity_fields=subject.identity_fields,
                    subject_bound=subject.bound,
                )
                candidates.append(
                    DirectAssertionCandidate.create(
                        table_id=column.table_id,
                        table=table,
                        column_id=column.column_id,
                        column=column.column,
                        subject_id=subject.id,
                        subject_bound=subject.bound,
                        criterion_id=ref.id,
                        source_id=document.source_id,
                        source_document_id=document.id,
                        source_version_id=version.id,
                        chunk_id=chunk.id,
                        span_id=span.id,
                        verbatim_text=span.text,
                        value_json=json.dumps(value, ensure_ascii=False),
                        normalized_value=admitted[0],
                        value_type=column.value_type,
                        unit=column.unit,
                        field_name=str(field_name),
                        match_rule=match_rule,
                        column_role=column.role.value,
                        source_match_rule=source_match_rule,
                    )
                )
        return tuple(spans.values()), tuple(candidates)

    def best_guess_candidates(
        self,
        records: Sequence[Mapping[str, Any]],
        resolutions: Sequence[Mapping[str, Any]],
        *,
        document: SourceDocument,
        version: SourceVersion,
        chunks: Sequence[SourceChunk],
    ) -> tuple[BestGuessAssertionCandidate, ...]:
        """Convert accepted-shape LLM resolutions into typed candidates."""

        rows: dict[str, list[Mapping[str, Any]]] = {}
        for record in records:
            if not isinstance(record, Mapping):
                continue
            table = str(record.get("table") or "")
            values = record.get("values")
            if table and isinstance(values, Mapping):
                rows.setdefault(table, []).append(values)
        chunk_ids = {chunk.id for chunk in chunks}
        out: list[BestGuessAssertionCandidate] = []
        for resolution in resolutions:
            if not isinstance(resolution, Mapping):
                continue
            table = str(resolution.get("target_table") or "")
            column_name = str(resolution.get("canonical_column") or "")
            table_rows = rows.get(table) or []
            try:
                values = table_rows[int(resolution.get("source_row_index"))]
            except (IndexError, TypeError, ValueError):
                continue
            column = next(
                (
                    item
                    for item in self._by_table.get(table) or ()
                    if item.column == column_name
                    and item.role is ColumnEvidenceRole.BEST_GUESS
                ),
                None,
            )
            if column is None:
                continue
            subject_refs = criteria.row_subject_refs(table, [values], self._table_spec)
            subject = subject_refs[0] if subject_refs else None
            if subject is None or not subject.bound:
                continue
            value = resolution.get("best_guess_value")
            admitted = self._non_trivial(value, column)
            if admitted is None:
                continue
            cited = tuple(
                chunk_id
                for chunk_id in (
                    str(item) for item in resolution.get("source_chunks") or ()
                )
                if chunk_id in chunk_ids
            )
            if not cited:
                continue
            operators = tuple(
                str(item) for item in resolution.get("operators") or ()
            )
            if "source_chunk_extract" not in operators:
                continue
            ref = criteria.CriterionRef.create(
                table=table,
                field=column.column,
                subject_id=subject.id,
                subject_key=subject.key,
                identity_fields=subject.identity_fields,
                subject_bound=subject.bound,
            )
            out.append(
                BestGuessAssertionCandidate.create(
                    table_id=column.table_id,
                    table=table,
                    column_id=column.column_id,
                    column=column.column,
                    subject_id=subject.id,
                    subject_bound=subject.bound,
                    criterion_id=ref.id,
                    source_id=document.source_id,
                    source_document_id=document.id,
                    source_version_id=version.id,
                    supporting_chunk_ids=cited,
                    value_json=json.dumps(value, ensure_ascii=False),
                    normalized_value=admitted[0],
                    value_type=column.value_type,
                    unit=column.unit,
                    reasoning_basis=str(resolution.get("basis") or ""),
                    confidence=float(resolution.get("confidence") or 0.0),
                    reasoning_operator="source_chunk_extract",
                    column_role=column.role.value,
                )
            )
        return tuple(out)

    def __call__(self, unit: PageUnit, material: PageMaterial) -> CreditResult:
        """The Leaf's ``credit`` slot. Writes the breakdown onto the unit once."""

        fate = material.fate
        commit = material.evidence_commit if fate.judged else None
        mutation = (
            self._table_store.apply(material.records, commit)
            if commit is not None
            else None
        )
        projected = self._accepted_identities(unit, commit, mutation)
        self._assignments.extend(projected.attributions)
        detail = PageCredit(
            attributions=projected.attributions,
            row_completions=projected.row_completions,
            row_completion_unavailable=self.row_completion_unavailable,
            declared_facets=self._declared_facets,
            chunk_encounters=tuple(dict(item) for item in material.chunks),
        )
        unit.attach_credit(detail)

        if not self._basis.columns and not self._basis.tables:
            return CreditResult.disabled(
                "no declared, deliverable contract columns exist; zero credits "
                "here means 'could not judge', not 'barren page'"
            )
        if not fate.judged:
            return CreditResult.disabled(fate.disclosure)

        identities = tuple(
            dict.fromkeys(item.identity for item in projected.attributions)
        )
        facets = self._facets(projected)
        return CreditResult(credits=identities, facets=facets)

    def _accepted_identities(
        self,
        unit: PageUnit | ChunkUnit,
        commit: Optional[EvidenceCommit],
        mutation: Optional[TableMutation],
    ) -> _AcceptedProjection:
        if commit is None or mutation is None:
            return _AcceptedProjection()
        admitted = mutation.admitted_cell_ids
        cells = [
            *commit.accepted_cells,
            *commit.accepted_best_guess_cells,
        ]
        before_slots = mutation.before_projection.identities
        logical_value_by_cell_id = {
            cell_id: value
            for value in mutation.after_projection.slot_values
            for cell_id in value.accepted_cell_ids
        }
        candidates: dict[str, tuple[Any, CreditColumn]] = {}
        for cell in cells:
            if cell.id not in admitted:
                continue
            column = self._column_by_id.get(cell.column_id)
            if column is None:
                continue
            logical_value = logical_value_by_cell_id.get(cell.id)
            if logical_value is None:
                continue
            identity = logical_value.identity
            prior = candidates.get(identity)
            if prior is not None:
                prior_cell, _ = prior
                if not isinstance(prior_cell, AcceptedBestGuessCell):
                    continue
                if isinstance(cell, AcceptedBestGuessCell):
                    continue
            candidates[identity] = (cell, column)

        strategy_key = (
            str(unit.episode_path[1][1])
            if len(unit.episode_path) > 1
            and unit.episode_path[1][0] == STRATEGY_GRAIN.name
            else ""
        )
        attributions: list[CreditAttribution] = []
        for identity, (cell, column) in candidates.items():
            attributions.append(
                CreditAttribution(
                    identity=identity,
                    assignment_id=stable_id(
                        {
                            "version": "post_table_credit_assignment_v1",
                            "credit_identity": identity,
                            "evidence_cell_id": cell.id,
                            "unit_label": unit.label,
                        }
                    ),
                    criterion_id=cell.criterion_id,
                    subject_id=cell.subject_id,
                    source_id=cell.source_id,
                    table=cell.table,
                    column=cell.column,
                    value_slot=column.value_slot,
                    slot_id=column.slot_id,
                    field=cell.column,
                    rule=cell.acceptance_rule_version,
                    triviality_rule="accepted_registry_chain",
                    source_kind=(
                        "best_guess"
                        if isinstance(cell, AcceptedBestGuessCell)
                        else SOURCE_KIND_VERBATIM
                    ),
                    new_to_table=identity not in before_slots,
                    before_table_state_id=mutation.before_state_id,
                    after_table_state_id=mutation.after_state_id,
                    strategy_key=strategy_key,
                )
            )
        before_rows = mutation.before_projection.completed_subjects
        after_rows = mutation.after_projection.completed_subjects
        after_row_states = {
            (row.table_id, row.table, row.subject_id): row
            for row in mutation.after_projection.rows
        }
        rows = tuple(
            RowCompletionDetail(
                identity=after_row_states[
                    (table_id, table, subject_id)
                ].identity,
                table=table,
                subject_id=subject_id,
                accepted_slot_ids=tuple(
                    after_row_states[(table_id, table, subject_id)].required_slot_ids
                ),
                declared_total=len(
                    after_row_states[(table_id, table, subject_id)].required_slot_ids
                ),
            )
            for table_id, table, subject_id in sorted(after_rows - before_rows)
        )
        return _AcceptedProjection(
            attributions=tuple(attributions), row_completions=rows
        )

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _facets(self, projected: _AcceptedProjection) -> dict[str, tuple[str, ...]]:
        """EVERY declared facet on EVERY active result, empty where uncredited.

        The declared set is a property of the table spec, not of which page
        arrived first. With the alternative shape a scope where no page ever
        credits anything emits no facets at all -- indistinguishable from a
        crediter that has no facets, and "every declared column has a curve and
        all of them are flat" and "no column curve exists" are opposite facts.
        Fan-up needs it too: a parent derives its facet names from its children's
        unit records, so a search whose facet set depended on which page arrived
        would give its strategy a facet set depending on which search arrived.

        The groups partition base-channel membership. Logical-slot identities
        also form the kernel-derived pooled union. Row completion is diagnostic
        state from the same projection and is not a second credit channel.
        """

        groups: dict[str, list[str]] = {name: [] for name in self._declared_facets}
        seen: set[str] = set()
        for attribution in projected.attributions:
            if attribution.identity in seen:
                continue
            seen.add(attribution.identity)
            groups[f"column:{attribution.slot_id}"].append(
                attribution.identity
            )
        return {name: tuple(members) for name, members in groups.items()}


    def _match(
        self,
        field_name: Any,
        columns: Sequence[CreditColumn],
    ) -> Optional[tuple[CreditColumn, str]]:
        """Field -> at most ONE column, first hit wins across three rules.

        4C credited *every* column whose token key matched a field, so one field
        could credit several columns. Under first-hit-wins a field credits at
        most one, which is strictly fewer credits and never more.

        ``token_overlap`` is a disclosed fallback: it fires only when neither
        declared rule matched, and every credit it mints carries its rule label
        so a run can count how often it fired and what it credited.
        """

        normalized = _normalize_name(field_name)
        if normalized:
            for column in columns:
                if normalized in column.normalized_names:
                    return column, RULE_DECLARED_NAME
            for column in columns:
                if normalized in column.normalized_aliases:
                    return column, RULE_DECLARED_ALIAS
        field_tokens = _tokens(field_name)
        if not field_tokens:
            return None
        for column in columns:
            # A field credits a column when it carries at least the column's
            # tokens (specific field, general column), or when the field is a
            # multi-token subset of the column (abbreviated field). A
            # single-token field may only exact-match: without this, a bare
            # `year` or `basis` fans out into every multi-token column that
            # contains the token.
            for key in column.token_keys:
                if key <= field_tokens or (
                    len(field_tokens) >= 2 and field_tokens <= key
                ):
                    return column, RULE_TOKEN_OVERLAP
        return None

    def _non_trivial(
        self,
        value: Any,
        column: CreditColumn,
    ) -> Optional[tuple[str, str]]:
        """The normalized value and the clause that admitted it, or ``None``.

        Three clauses must hold: the value normalizes to something non-empty;
        ``criteria`` does not call it missing; and it parses as the column's
        declared ``value_type`` where one is declared. ``unit`` is typed column
        metadata, not text that the scalar must repeat: a reported value of
        ``1,000`` in a deaths column is still a value in people.

        THE MISSING-TOKEN SET AND THE NORMALIZED FORM HAVE ONE OWNER, and it is
        ``criteria``. This module kept its own eight-token set and its own
        normalizer; they disagreed on nine tokens, so a page saying "deaths: not
        reported" minted a credit -- absence counted as yield, at the exact grain
        that decides whether to keep fetching -- and they disagreed on sequences,
        mappings, bools and long strings, so the acquisition curve and the
        criteria snapshot spelled the same value two ways.

        Clauses three and four are STRUCTURALLY INERT on every spec in this tree
        today: no column declares a ``value_type`` or a ``unit``, so the rule
        reduces to clauses one and two and no existing credit changes. That is
        emitted rather than assumed, so a run cannot report the typed clause as
        exercised when it was not.
        """

        if criteria.is_missing_value(value):
            return None
        normalized = criteria.normalize_key_value(value)
        if not normalized:
            return None
        if not column.value_type:
            return normalized, ("untyped" if not column.unit else f"unit:{column.unit}")
        if not _parses_as(normalized, column.value_type, column.unit):
            return None
        return normalized, column.value_type





def _iter_fields(values: Mapping[str, Any]) -> Iterable[tuple[str, Any]]:
    for key, value in values.items():
        if value is None:
            continue
        yield str(key), value


_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?")
_RANGE_SPLIT_RE = re.compile(r"\s*(?:-|–|—|to)\s*", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
_YEAR_RE = re.compile(r"^\d{4}$")


def _strip_unit(text: str, unit: str) -> str:
    if not unit:
        return text
    return re.sub(re.escape(unit), " ", text, flags=re.IGNORECASE).strip()


def _parses_as(text: str, value_type: str, unit: str) -> bool:
    """Deterministic checker per declared type member. No model, no heuristic."""

    body = _strip_unit(text, unit)
    if value_type == "number":
        match = _NUMBER_RE.fullmatch(body.replace(" ", ""))
        return match is not None
    if value_type == "integer":
        stripped = body.replace(",", "").replace(" ", "")
        return bool(stripped) and (
            stripped.lstrip("+-").isdigit() and stripped.lstrip("+-") != ""
        )
    if value_type == "range":
        parts = [part for part in _RANGE_SPLIT_RE.split(body) if part.strip()]
        return len(parts) == 2 and all(
            _NUMBER_RE.fullmatch(part.replace(" ", "").replace(",", ""))
            for part in parts
        )
    if value_type == "date":
        return bool(_ISO_DATE_RE.match(body.strip()))
    if value_type == "year":
        return bool(_YEAR_RE.match(body.strip())) and 1000 <= int(body.strip()) <= 2999
    if value_type in ("category", "text"):
        return bool(body.strip())
    return False


# ==========================================================================
# The sources -- one per grain
# ==========================================================================

SearchFn = Callable[[str, Optional[int]], Sequence[Mapping[str, Any]]]
PageFactory = Callable[[Any, Mapping[str, Any], int], Any]


class RankedChunkSource:
    """One lexical ranking over chunks that were unprocessed when it opened."""

    def __init__(
        self,
        *,
        state: PageRunState,
        ranked_chunks: Sequence[Any],
        make_leaf: Callable[[Any], Leaf],
    ) -> None:
        self._state = state
        self._ranked_chunks = tuple(ranked_chunks)
        self._make_leaf = make_leaf
        self._next_index = 0

    def next(self, view: EpisodeView) -> Leaf | None:
        while self._next_index < len(self._ranked_chunks):
            span = self._ranked_chunks[self._next_index]
            self._next_index += 1
            if self._state.chunk_id(span) in self._state.processed_chunk_ids:
                continue
            return self._make_leaf(span)
        return None


class LexicalProbeSource:
    """Propose one query per pull, after observing every prior probe."""

    def __init__(
        self,
        *,
        state: PageRunState,
        propose: Callable[..., Awaitable[Any]],
        rank: Callable[[Sequence[Any], str], Sequence[Any]],
        make_probe: Callable[[str, Any, Sequence[Any]], Episode],
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        open_prompt_scope: Callable[
            [str, tuple[tuple[str, str], ...]], Any
        ],
    ) -> None:
        self._state = state
        self._propose = propose
        self._rank = rank
        self._make_probe = make_probe
        self._open_cost_scope = open_cost_scope
        self._open_prompt_scope = open_prompt_scope

    async def next(self, view: EpisodeView) -> Episode | None:
        remaining = self._state.remaining_chunks()
        # Physical exhaustion is authoritative. No model call and no
        # statistical extrapolation may create a unit beyond the page.
        if not remaining:
            return None

        probe_key = f"probe-{len(self._state.probe_history) + 1:04d}"
        observation_id = f"{self._state.unit.label}#{probe_key}"
        with self._open_prompt_scope(
            view.episode_ref.episode_id,
            view.path,
        ):
            with self._open_cost_scope(
                ObservationKind.PROBE_SEARCH.value,
                observation_id,
                view.episode_ref.episode_id,
                view.path,
            ):
                proposal = await self._propose(
                    outline=self._state.outline,
                    previous_probes=tuple(self._state.probe_history),
                )
        query = str(
            proposal.get("query")
            if isinstance(proposal, Mapping)
            else getattr(proposal, "query", "")
        ).strip()
        if not query:
            raise ValueError("lexical probe proposer returned an empty query")
        ranked = tuple(self._rank(remaining, query))
        if not ranked:
            return None
        proposal_record = (
            dict(proposal)
            if isinstance(proposal, Mapping)
            else proposal.to_dict()
        )
        self._state.probe_proposals[probe_key] = proposal_record
        return self._make_probe(probe_key, proposal, ranked)


class PageSource:
    """The ``search`` grain's source: one page of one result list per pull.

    THE LIST IS CONSUMED ONE RANK PER PULL, AFTER THE VERDICT. That is the
    property the phase-batched flow structurally lacked -- it computed the
    keep-going signal after the keep-going decisions had passed -- and it is now
    a property of where the pull sits in the kernel's loop body rather than of a
    ``break`` a surface remembered to write.
    """

    def __init__(
        self,
        *,
        task: Any,
        search_fn: SearchFn,
        make_page: PageFactory,
        budget: SourceBudget,
        health: ProviderHealth,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        on_results: Optional[Callable[[Any, Sequence[Mapping[str, Any]]], None]] = None,
        on_error: Optional[Callable[[Any, BaseException, bool], None]] = None,
        is_fatal: Callable[[BaseException], bool] = lambda _exc: False,
    ) -> None:
        self._task = task
        self._search_fn = search_fn
        self._make_page = make_page
        self._budget = budget
        self._health = health
        self._episode_id = str(episode_id)
        self._episode_path = tuple(episode_path)
        self._open_cost_scope = open_cost_scope
        self._on_results = on_results
        self._on_error = on_error
        self._is_fatal = is_fatal
        self._results: list[Mapping[str, Any]] = []
        self._next_rank = 0
        self._issued = False
        #: The provider call's finished meter, for the search's own outcome.
        #: The SEARCH scope now closes when that call returns, so per-page work
        #: no longer nests inside it: a page's SOURCE record carries
        #: ``nested_in=""`` and its own ``fetched_bytes``, where those bytes
        #: used to land on the search's meter.
        self.cost: Optional[Mapping[str, Any]] = None

    @property
    def remaining(self) -> int:
        """Buffered results not processed because the episode ended."""

        return max(0, len(self._results) - self._next_rank)

    @property
    def result_buffer(self) -> dict[str, int]:
        """Provider results split into processed and still-unprocessed counts."""

        return {
            "buffered_results": len(self._results),
            "processed_results": self._next_rank,
            "unprocessed_results": self.remaining,
        }

    def next(self, view: EpisodeView) -> Any:
        if self._health.fatal:
            # The run already knows the provider refused. A search must not pay
            # another round trip to rediscover it.
            return SourceEnd(END_SOURCE_FAILED, FATAL_SEARCH_ERROR)
        if self._budget.exhausted:
            return SourceEnd(END_BOUND_HIT, BOUND_KIND_RUN_SOURCE_BUDGET)
        if not self._issued:
            self._issued = True
            end = self._issue()
            if end is not None:
                return end
        if self._next_rank >= len(self._results):
            return None
        result = self._results[self._next_rank]
        self._next_rank += 1
        return self._make_page(self._task, result, self._next_rank)

    def _issue(self) -> Optional[SourceEnd]:
        """The provider call, inside its own cost scope, on the first pull."""

        end: Optional[SourceEnd] = None
        results: list[Mapping[str, Any]] = []
        with self._open_cost_scope(
            ObservationKind.SEARCH.value,
            str(self._task.id),
            self._episode_id,
            self._episode_path,
        ) as meter:
            try:
                # ``None`` is the acquisition framework's explicit absence of
                # an item cap. The real Firecrawl adapter resolves it to that
                # provider's own default batch size; an injected adapter owns
                # its own interpretation and is never stamped as Firecrawl.
                results = list(self._search_fn(self._task.query, None))
            except Exception as exc:  # noqa: BLE001 - classified once, then named
                fatal = bool(self._is_fatal(exc))
                if meter is not None:
                    error_class = classify_error(exc)
                    if error_class == CostErrorClass.OTHER.value:
                        error_class = CostErrorClass.SEARCH_FAILED.value
                    meter.add_provider_call(error_class=error_class)
                if self._on_error is not None:
                    self._on_error(self._task, exc, fatal)
                if fatal:
                    self._health.fatal = FATAL_SEARCH_ERROR
                    end = SourceEnd(END_SOURCE_FAILED, FATAL_SEARCH_ERROR)
                else:
                    end = SourceEnd(END_SOURCE_FAILED, SEARCH_ERROR)
            else:
                if meter is not None:
                    meter.add_provider_call(returned_hits=len(results))
            if meter is not None:
                self.cost = meter.snapshot().to_dict()
        if end is not None:
            return end
        self._results = results
        if self._on_results is not None:
            self._on_results(self._task, results)
        return None


class StrategySearches:
    """The ``strategy`` grain's source: one search episode per pull.

    The frontier stays the queue; the episode becomes its consumer. A strategy
    that yield-stops leaves its remaining tasks IN the frontier, which is how
    "never deleted, never domain-filtered" survives the deletion of the demotion
    machinery.
    """

    def __init__(
        self,
        *,
        strategy_key: str,
        family: str,
        next_task: Callable[[str], Any],
        make_search: Callable[[Any], Episode],
        budget: SourceBudget,
        health: ProviderHealth,
    ) -> None:
        self._strategy_key = strategy_key
        self._family = family
        self._next_task = next_task
        self._make_search = make_search
        self._budget = budget
        self._health = health

    def next(self, view: EpisodeView) -> Episode | None | SourceEnd:
        if self._health.fatal:
            return SourceEnd(END_SOURCE_FAILED, FATAL_SEARCH_ERROR)
        if self._budget.exhausted:
            return SourceEnd(END_BOUND_HIT, BOUND_KIND_RUN_SOURCE_BUDGET)
        task = self._next_task(self._family)
        if task is None:
            return None
        return self._make_search(task)


#: A proposed strategy is "semantically distant enough" when the model's own
#: reported distance clears this floor. NO MEASUREMENT JUSTIFIES 0.5. It is the
#: midpoint of the [0,1] scale the prompt declares -- chosen because it is the
#: scale's own midpoint rather than fitted to any observation -- and it is
#: registered as an instrument parameter that can move a result, with every
#: candidate's reported distance emitted so a later phase can set it from data.
#: A module constant and NOT a `PipelineConfig` field: a config knob on a
#: threshold invites re-running until the direction flips.
STRATEGY_DISTANCE_FLOOR = 0.5

#: How many samples per pull before the proposer gives up. With the run grain's
#: verdict unreachable below ten completed strategies, this explicit proposal
#: cap and the run Episode's emergency unit boundary are the operative ends
#: THAN THAT. It is a bound, disclosed as a bound and never presented as a
#: decision, and the run record names which end fired.
MAX_PROPOSAL_SAMPLES = 3

#: Why a sampled candidate never reached the accept rule. A class label, never
#: prose, and the ONLY rejection that happens before the rule: everything else a
#: candidate can fail is the rule itself (below the floor, or a content key
#: already opened), which `control.select_first_clearing` decides and the ledger
#: counts separately.
#:
#: IT IS A REJECTION AND NOT A RENAME. The model's `operator` string is the one
#: sampled field that would otherwise become a durable join key -- the strategy
#: episode's key, hence a scope path segment, hence `scope_key`,
#: `strategy_family`, the `_strategy_ends` key, and the argument the frontier
#: resolves by string equality. Coercing an out-of-catalog string onto the
#: nearest catalog member would be generated prose steering the loop with the
#: evidence of it erased; dropping it keeps the model's whole contribution to
#: this edge inside the catalog it was shown.
REJECT_OPERATOR_NOT_IN_CATALOG = "operator_not_in_catalog"


class StrategyProposer:
    """The ``run`` grain's source: the switch edge.

    Pull order, and every step before the model is a typed check:

    1. the run's terminal state (a goal fulfilled, an execution error, a spent
       budget) -> the named ``SourceEnd`` its ``StopReason`` maps to;
    2. provider health;
    3. the page budget, at this grain as well as inside a strategy -- so a spent
       budget ends the run rather than producing a stream of ``bound_hit``
       children the parent's history excludes, which would leave the run's
       observation count at zero forever;
    4. a declared family eligible to open -> build it. **No model call.**
    5. otherwise sample.

    THE MODEL SITS ONLY IN STEP 5, and only in that step's string work. It
    samples candidate strings and reports a number. It does not decide *whether*
    to propose -- that is the run grain's own verdict, read after every unit --
    and it does not decide whether a candidate is distant enough: the comparison
    in :func:`control.select_first_clearing` does, over a key this class mints in
    code from declared inputs.
    """

    def __init__(
        self,
        *,
        declared: Callable[[], Sequence[str]],
        sample: Callable[[Sequence[Mapping[str, Any]]], Awaitable[Sequence[Mapping[str, Any]]]],
        build: Callable[[str, str, Sequence[str]], Episode],
        catalog: AbstractSet[str],
        declared_target_ids: Callable[[], AbstractSet[str]],
        budget: SourceBudget,
        health: ProviderHealth,
        termination: RunTermination,
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        run_key: str,
        record_proposal: Optional[Callable[[Mapping[str, Any]], None]] = None,
        distance_floor: float = STRATEGY_DISTANCE_FLOOR,
        max_samples: int = MAX_PROPOSAL_SAMPLES,
    ) -> None:
        self._declared = declared
        self._sample = sample
        self._build = build
        self._catalog = catalog
        self._declared_target_ids = declared_target_ids
        self._budget = budget
        self._health = health
        self._termination = termination
        self._open_cost_scope = open_cost_scope
        self._episode_id = str(episode_id)
        self._episode_path = tuple(episode_path)
        self._run_key = run_key
        self._record_proposal = record_proposal
        self._floor = float(distance_floor)
        self._max_samples = max(1, int(max_samples))
        self._opened_content: set[str] = set()
        self._opened: list[dict[str, Any]] = []
        self._opened_token_sets: list[frozenset[str]] = []
        self._instances: dict[str, int] = {}
        self._pulls = 0
        self._resume_episode: Optional[Episode] = None
        # The candidate partition, emitted whether or not any cell is zero:
        # `candidates == operator_not_in_catalog + cleared_floor + below_floor`,
        # with `already_opened` a subset of `cleared_floor`. A zero
        # `operator_not_in_catalog` is the finding that the model stayed inside
        # its catalog on this configuration -- never an absent instrument.
        self.ledger: dict[str, Any] = {
            "pulls": 0,
            "samples": 0,
            "candidates": 0,
            REJECT_OPERATOR_NOT_IN_CATALOG: 0,
            "cleared_floor": 0,
            "below_floor": 0,
            "already_opened": 0,
            "accepted": 0,
            "end": "",
            "distance_floor": self._floor,
            "max_proposal_samples": self._max_samples,
        }

    def opened_content_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._opened_content))

    def instances_opened(self) -> dict[str, int]:
        """Instances opened per family -- THE WHOLE MAP, and public.

        C37's observable. It is emitted for every family this run opened, not
        only for the families the frontier still holds work for: a family that
        was opened and drained its queue is exactly the case the re-open bound
        is about, and reporting only the families with pending work would hide
        it. Public because the run record is another module's, and reaching into
        a private attribute to build a disclosure makes that disclosure
        something no one can change here without breaking a caller.
        """

        return dict(self._instances)

    def checkpoint_state(self) -> dict[str, Any]:
        """Return the exact string-policy state needed at the next pull."""

        return {
            "opened_content": sorted(self._opened_content),
            "opened": [dict(item) for item in self._opened],
            "instances": dict(self._instances),
            "pulls": self._pulls,
            "ledger": dict(self.ledger),
        }

    def restore_checkpoint_state(self, state: Mapping[str, Any]) -> None:
        """Restore a state emitted by :meth:`checkpoint_state`."""

        opened = [dict(item) for item in (state.get("opened") or ())]
        self._opened = opened
        self._opened_content = {
            str(value) for value in (state.get("opened_content") or ())
        }
        self._opened_token_sets = [
            _proposal_tokens(
                str(item.get("family") or ""),
                item.get("targets") or (),
                item.get("seeds") or (),
            )
            for item in opened
        ]
        self._instances = {
            str(name): int(value)
            for name, value in dict(state.get("instances") or {}).items()
        }
        self._pulls = int(state.get("pulls") or 0)
        restored_ledger = dict(state.get("ledger") or {})
        if restored_ledger:
            self.ledger.update(restored_ledger)
        self.ledger["pulls"] = self._pulls

    def resume_with(self, episode: Episode) -> None:
        """Return the interrupted child once before proposing new work."""

        if self._resume_episode is not None:
            raise ValueError("a proposer may hold only one resumed child")
        self._resume_episode = episode

    async def next(self, view: EpisodeView) -> Episode | None | SourceEnd:
        if self._resume_episode is not None:
            episode = self._resume_episode
            self._resume_episode = None
            return episode
        if self._termination.stopped:
            end = self._termination.source_end()
            self.ledger["end"] = (
                end.reason if end is not None else STOP_REASON_FRONTIER_EXHAUSTED
            )
            return end
        if self._health.fatal:
            self.ledger["end"] = FATAL_SEARCH_ERROR
            return SourceEnd(END_SOURCE_FAILED, FATAL_SEARCH_ERROR)
        if self._budget.exhausted:
            self.ledger["end"] = BOUND_KIND_RUN_SOURCE_BUDGET
            return SourceEnd(END_BOUND_HIT, BOUND_KIND_RUN_SOURCE_BUDGET)

        self._pulls += 1
        self.ledger["pulls"] = self._pulls
        # THE SCOPE WRAPS THE WHOLE PULL, not just the model sample. The
        # declared-family path at step 4 reaches the same billed arm planner as
        # the sampled path does, so a scope around `sample(...)` alone would
        # bill every declared-family pull's planner spend to the orphan meter --
        # free in the record and expensive in reality, which is the exact bias
        # cost accounting exists to remove. A pull that returns a declared
        # family therefore still writes a record, with `proposal_samples: 0`.
        #
        # `observation_id` is `f"{run_key}#p{n}"` where n counts PULLS, not
        # samples. It joins to the run record by `run_key` and to
        # `strategy_proposals.jsonl` by pull number, so a cost record on this
        # edge joins to something -- which is the defect this scope removes, one
        # level out.
        #
        with self._open_cost_scope(
            ObservationKind.STRATEGY_PROPOSAL.value,
            f"{self._run_key}#p{self._pulls}",
            self._episode_id,
            self._episode_path,
        ):
            episode = await self._pull()
        return episode

    async def _pull(self) -> Episode | None | SourceEnd:
        """The pull itself. IT TAKES NO VIEW, and that is the point.

        Every input is a typed object this class was handed -- the run's
        terminal state, provider health, the page budget, the declared families,
        and the declared target ids. The proposer reads no curve, no verdict and
        no unit count, so there is no second acquisition decision hidden here.
        """

        # Step 4: a declared family eligible to open. NO MODEL CALL. `declared`
        # is the set of families with pending frontier work that the
        # deterministic planner routes and that are ELIGIBLE TO RE-OPEN under
        # the caller's written rule -- it is NOT the whole operator catalog,
        # which would stay deterministic while bypassing the pseudo-gradient
        # entirely.
        #
        # The declared path deliberately does not consult the opened-content
        # set. Eligibility is the caller's rule over the child records this run
        # already holds ("the last instance ended `exhausted` AND the frontier
        # now holds work for it"), and a content key fixed per family would make
        # a family that merely ran out of queued work at the instant it was
        # pulled unreopenable for the rest of the run -- work planned for it
        # would sit in the frontier forever with nothing saying so. The key it
        # records is instance-scoped so a proposal can never collide with it.
        for family in self._declared():
            instance = self._instances.get(family, 0)
            return self._open(
                family,
                self._declared_key(family, instance),
                (),
            )

        declared_targets = set(self._declared_target_ids())
        for sample_index in range(self._max_samples):
            self.ledger["samples"] = int(self.ledger["samples"]) + 1
            candidates = list(await self._sample(list(self._opened)) or ())
            self.ledger["candidates"] = int(self.ledger["candidates"]) + len(candidates)
            if not candidates:
                continue
            # THE INADMISSIBLE CANDIDATE NEVER REACHES THE ACCEPT RULE. It is
            # dropped here, before selection -- not marked and passed on, and
            # never renamed onto a catalog member. `keyed` therefore holds only
            # admissible candidates and `keyed_rows` carries each one's index
            # back into `rows`, so the emitted file still carries every
            # candidate the model returned while the rule only ever sees the
            # ones whose operator the catalog declares.
            keyed: list[tuple[str, float]] = []
            keyed_rows: list[int] = []
            rows: list[dict[str, Any]] = []
            for returned_index, candidate in enumerate(candidates):
                family = str(candidate.get("operator") or "").strip()
                targets = sorted(
                    declared_targets
                    & {str(value) for value in (candidate.get("target_ids") or ())}
                )
                seeds = tuple(
                    dict.fromkeys(
                        _normalize_seed(seed)
                        for seed in (candidate.get("query_seeds") or ())
                        if _normalize_seed(seed)
                    )
                )
                admissible = family in self._catalog
                # `""` for an inadmissible candidate, and it never enters
                # `_opened_content`, because that candidate never opens
                # anything: a sentinel in the opened set would make the second
                # inadmissible candidate of a run "already tried".
                content = (
                    self._content_key(family, targets, seeds) if admissible else ""
                )
                distance = candidate.get("distance")
                rows.append(
                    {
                        "sample_index": sample_index,
                        "returned_index": returned_index,
                        "operator": family,
                        "operator_in_catalog": admissible,
                        "target_ids": targets,
                        "query_seeds": list(seeds),
                        "content_key": content,
                        "distance": distance,
                        "min_deterministic_distance": self._deterministic_distance(
                            family, targets, seeds
                        ),
                        "label": str(candidate.get("label") or ""),
                        "rationale": str(candidate.get("rationale") or ""),
                        "distance_floor": self._floor,
                        "max_proposal_samples": self._max_samples,
                        "opened_content_keys": self.opened_content_keys(),
                        "accepted": False,
                        "rejection_class": (
                            "" if admissible else REJECT_OPERATOR_NOT_IN_CATALOG
                        ),
                    }
                )
                if not admissible:
                    # Counted, because how often the model proposes outside the
                    # catalog it was shown is a property of the switch edge and
                    # is otherwise invisible: a dropped candidate leaves no
                    # episode, no scope and no cost of its own.
                    self.ledger[REJECT_OPERATOR_NOT_IN_CATALOG] = (
                        int(self.ledger[REJECT_OPERATOR_NOT_IN_CATALOG]) + 1
                    )
                    continue
                keyed.append((content, distance))
                keyed_rows.append(len(rows) - 1)
            index = select_first_clearing(
                keyed, floor=self._floor, opened=self._opened_content
            )
            self._count_candidates(keyed)
            if index is not None:
                rows[keyed_rows[index]]["accepted"] = True
            for row in rows:
                if self._record_proposal is not None:
                    self._record_proposal(row)
            if index is None:
                continue
            self.ledger["accepted"] = int(self.ledger["accepted"]) + 1
            chosen = rows[keyed_rows[index]]
            return self._open(
                str(chosen["operator"]),
                str(chosen["content_key"]),
                tuple(chosen["query_seeds"]),
                targets=tuple(chosen["target_ids"]),
                label=str(chosen["label"]),
            )

        if int(self.ledger["candidates"]) == 0:
            # The declared catalog is drained AND the sampler returned nothing at
            # all: the honest exhaustion, and the only thing `None` spells.
            self.ledger["end"] = END_EXHAUSTED
            return None
        # The sampling budget was spent. A CUT, not exhaustion -- a later reader
        # uses the run's end to decide whether low yield was a saturated search
        # space or an instrument that stopped asking, and those license opposite
        # conclusions.
        self.ledger["end"] = BOUND_KIND_PROPOSAL_SAMPLES
        return SourceEnd(END_BOUND_HIT, BOUND_KIND_PROPOSAL_SAMPLES)

    def _count_candidates(self, keyed: Sequence[tuple[str, Any]]) -> None:
        """Tally the ADMISSIBLE candidates against the rule's two conjuncts.

        The inadmissible ones are counted where they are dropped, so the ledger
        partitions what the model returned:
        ``candidates == operator_not_in_catalog + cleared_floor + below_floor``,
        with ``already_opened`` a subset of ``cleared_floor``.
        """

        for content, distance in keyed:
            try:
                value = float(distance)
            except (TypeError, ValueError):
                value = float("-inf")
            if value >= self._floor:
                self.ledger["cleared_floor"] = int(self.ledger["cleared_floor"]) + 1
                if content in self._opened_content:
                    self.ledger["already_opened"] = (
                        int(self.ledger["already_opened"]) + 1
                    )
            else:
                self.ledger["below_floor"] = int(self.ledger["below_floor"]) + 1

    def _open(
        self,
        family: str,
        content: str,
        seeds: Sequence[str],
        targets: Sequence[str] = (),
        label: str = "",
    ) -> Episode:
        """Open one INSTANCE of a family, keyed ``family#instance``.

        The path segment is instance-scoped and the family is carried as a
        field, so every ledger grouping, arm join and curve comparison stays by
        family while the scope path stays unique -- ``open_scope`` raises on a
        re-opened path, and the deterministic planner routes the same family
        again by design.

        NOTHING MODEL-AUTHORED ENTERS THE KEY, and that holds because of where
        the catalog test sits rather than by convention: ``family`` is always a
        member of the injected catalog -- the declared path takes it from
        ``declared()`` and the sampled path only reaches here through
        :meth:`_pull`, which drops an out-of-catalog candidate before selection.
        The key is a durable join -- scope path, ``scope_key``,
        ``strategy_family``, the ``_strategy_ends`` key, and the string the
        frontier resolves by equality -- so a model-worded segment here would be
        generated prose deciding which work a strategy may pull.
        """

        self._opened_content.add(content)
        self._opened.append(
            {
                "family": family,
                "content_key": content,
                "targets": list(targets),
                "seeds": list(seeds),
                "label": label,
            }
        )
        self._opened_token_sets.append(_proposal_tokens(family, targets, seeds))
        instance = self._instances.get(family, 0)
        self._instances[family] = instance + 1
        return self._build(f"{family}#{instance}", family, list(seeds))

    def _content_key(
        self,
        family: str,
        targets: Sequence[str],
        seeds: Sequence[str],
    ) -> str:
        """The key a strategy is joined on, minted in code from declared inputs.

        Content-addressed, so two samples of the same content collapse to one
        key and the untried test compares content rather than wording -- which
        is what stops it being evadable by rewording, and is what keeps the
        model's reported distance the only model-supplied input to the accept
        rule. The model's ``label`` is recorded beside it and never joined on.

        A candidate naming an operator outside the injected catalog never
        reaches this function: :meth:`_pull` drops it before selection, records
        its row with ``accepted: false`` and
        ``rejection_class: operator_not_in_catalog``, and counts it in the
        ledger. Rejected, not renamed -- and the rejection is implemented there
        rather than promised here.
        """

        return stable_id(
            {
                "operator": family,
                "targets": sorted(str(target) for target in targets),
                "seeds": sorted(str(seed) for seed in seeds),
            }
        )

    @staticmethod
    def _declared_key(family: str, instance: int) -> str:
        """The content key a deterministically-routed family instance records.

        Instance-scoped, so re-opening a family whose queue refilled is possible
        and a proposal for the same operator with no targets and no seeds cannot
        collide with an instance the planner already ran.
        """

        return stable_id(
            {"operator": family, "declared": True, "instance": int(instance)}
        )

    def _deterministic_distance(
        self,
        family: str,
        targets: Sequence[str],
        seeds: Sequence[str],
    ) -> float:
        """A model-INDEPENDENT comparator, recorded and never branched on.

        Jaccard distance between this candidate's ``(operator, target ids,
        normalized seed tokens)`` token set and the nearest already-opened
        strategy's. Without a comparator, the later phase that sets the floor
        from data has nothing to calibrate against, and the degenerate case --
        every reported distance above the floor, so the floor never rejects
        anything -- is illegible in the trace.
        """

        tokens = _proposal_tokens(family, targets, seeds)
        best = 1.0
        for opened in self._opened_token_sets:
            union = tokens | opened
            if not union:
                continue
            best = min(best, 1.0 - len(tokens & opened) / len(union))
        return round(best, 4)


def _normalize_seed(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _proposal_tokens(
    family: str,
    targets: Sequence[str],
    seeds: Sequence[str],
) -> frozenset[str]:
    tokens = set(_tokens(family))
    for target in targets:
        tokens |= _tokens(target)
    for seed in seeds:
        tokens |= _tokens(seed)
    return frozenset(tokens)


# ==========================================================================
# Decisions and the cost join
# ==========================================================================

DECISION_SEARCH_ITEM_YIELD = "SEARCH_ITEM_YIELD"
DECISION_STRATEGY_YIELD = "STRATEGY_YIELD"
DECISION_RUN_YIELD = "RUN_YIELD"


@dataclass(frozen=True)
class AcquisitionDecision:
    """One grain's yield verdict, as a ledger record.

    Deliberately NOT a ``control.PolicyDecision``: that type's identity is a
    ranking over candidate action ids, and its ``selected``/``rejected``
    properties have no meaning for a stop verdict. The ledger takes any mapping,
    so a yield verdict is recorded as what it is.
    """

    policy_name: str
    decision_point: str
    scope_path: tuple[tuple[str, str], ...]
    scope_key: str
    family: str
    verdict: Mapping[str, Any]
    curve: Mapping[str, Any]
    facets: Mapping[str, Any]
    controller: Mapping[str, Any]
    ended_by: str
    end_reason: str
    units_consumed: int
    declared_facets: tuple[str, ...]

    @property
    def decision_id(self) -> str:
        # The curve arrays are excluded for the same reason 1A excludes the
        # mutable score from an action id.
        return stable_id(
            {
                "policy": self.policy_name,
                "decision_point": self.decision_point,
                "scope_path": [list(segment) for segment in self.scope_path],
                "flat_streak": self.verdict.get("flat_streak"),
                "done_streak": self.verdict.get("done_streak"),
                "outcome": self.verdict.get("outcome"),
                "ended_by": self.ended_by,
                "end_reason": self.end_reason,
                "units_consumed": self.units_consumed,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "decision_point": self.decision_point,
            "scope_path": [list(segment) for segment in self.scope_path],
            "scope_key": self.scope_key,
            "strategy_family": self.family,
            "verdict": dict(self.verdict),
            "curve": dict(self.curve),
            "facets": dict(self.facets),
            "controller": dict(self.controller),
            "ended_by": self.ended_by,
            "end_reason": self.end_reason,
            "units_consumed": self.units_consumed,
            "declared_facets": list(self.declared_facets),
            "credit_semantics": CREDIT_SEMANTICS,
            "decision_id": self.decision_id,
        }


def decision_from_record(
    record: EpisodeRecord,
    *,
    decision_point: str,
    family: str,
    declared_facets: Sequence[str],
) -> AcquisitionDecision:
    return AcquisitionDecision(
        policy_name=ACQUISITION_POLICY_NAME,
        decision_point=decision_point,
        scope_path=tuple(record.path),
        scope_key=record.scope_key,
        family=family,
        verdict=dict(record.final_verdict),
        curve=dict(record.curve),
        facets=dict(record.facets),
        controller=dict(record.controller),
        ended_by=record.ended_by,
        end_reason=record.end_reason,
        units_consumed=record.units_consumed,
        declared_facets=tuple(declared_facets),
    )


def join_costs(
    record: EpisodeRecord,
    cost_records: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict]]:
    """Cost records for this episode and its units, joined by id.

    A FILTER BY ID, NEVER A SUM: 1B records per action and 3A's attribution
    rules decide which sums are legitimate. The search scope's
    ``observation_id`` is the search episode's ``scope_key`` (the task id) and
    the source scope's is the page's ``unit_label`` (the pull-time identity), so
    both hops are id joins in emitted artifacts and neither is a text match.
    """

    out: dict[str, list[dict]] = {"scope": [], "units": []}
    record_path = [list(segment) for segment in record.path]
    for cost in cost_records:
        if str(cost.get("episode_id") or "") != str(record.episode_id or ""):
            continue
        if list(cost.get("episode_path") or ()) != record_path:
            continue
        observation_id = str(cost.get("observation_id") or "")
        if observation_id == record.scope_key:
            out["scope"].append(dict(cost))
        else:
            out["units"].append(dict(cost))
    return out


# ==========================================================================
# Export: the record written whole, with the one windowed list disclosed
# ==========================================================================

#: Identities per leaf credit list retained in the exported episode tree.
#: NO MEASUREMENT JUSTIFIES 20,000. It is a payload ceiling, not a measured
#: bound: one page can carry many extracted records, so it mints up to
#: ``len(declared_credit_columns) x (distinct values per column)`` identities and
#: the real bound is not computable in advance. Every windowed record names the
#: omitted count, the index range, and what stays recoverable -- every unit's
#: label, ``new``, ``cumulative_distinct``, ``crediting_disabled`` and
#: ``counts_toward_verdict``, so every verdict at every grain still recomputes --
#: and the emitted ``window`` block says whether it bound at all.
PAGE_CREDIT_WINDOW = 20000


def window_episode_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """The emitted record, with only leaf identity lists windowed.

    NO EPISODE RECORD IS EVER OMITTED -- episodes are few (strategies x
    searches), and the nested tree is the only artifact that can carry a
    parent/child relationship. Windowing takes from both ends and names the
    omitted middle; it never truncates by position in silence.
    """

    out = dict(record)
    units = out.get("units")
    if isinstance(units, list):
        out["units"] = [_window_unit(dict(unit)) for unit in units]
    return out


def _window_unit(unit: dict[str, Any]) -> dict[str, Any]:
    child = unit.get("child")
    if isinstance(child, Mapping):
        unit["child"] = window_episode_record(child)
        return unit
    credits = unit.get("credits")
    if not isinstance(credits, list) or len(credits) <= PAGE_CREDIT_WINDOW:
        return unit
    head = PAGE_CREDIT_WINDOW // 2
    tail = PAGE_CREDIT_WINDOW - head
    omitted = len(credits) - PAGE_CREDIT_WINDOW
    unit["credits"] = credits[:head] + credits[-tail:]
    sample = unit.get("incidence_sample")
    if isinstance(sample, list) and len(sample) > PAGE_CREDIT_WINDOW:
        unit["incidence_sample"] = sample[:head] + sample[-tail:]
    unit["window"] = {
        "windowed": True,
        "limit": PAGE_CREDIT_WINDOW,
        "omitted_count": omitted,
        "omitted_index_range": [head, len(credits) - tail - 1],
        "recoverable": [
            "unit_label",
            "new",
            "cumulative_distinct",
            "crediting_disabled",
            "counts_toward_verdict",
        ],
        "not_recoverable": [
            "the identities and incidence membership of the omitted middle, "
            "so Q1/Q2, exact rolling rarefaction, and pairwise variance cannot "
            "be independently recomputed from this window"
        ],
    }
    return unit


# ==========================================================================
# The controller
# ==========================================================================


@dataclass
class AcquisitionController:
    """Builds the composition, runs it once, and writes decisions from records.

    It is NOT a controller the loop consults between units: ``observe_item``,
    ``close_search`` and the parent's own list of a child's identities are gone
    and nothing replaces them. Fan-up is ``Episode._contribution``, and no hook
    accumulates ``record.credits`` per scope.

    It holds NO POLICY of its own -- each grain carries its own, and
    ``Context.enter`` hands it straight to ``open_scope`` -- and no meter: cost
    has one owner and it is ``costs.py``.
    """

    crediter: TableCreditAssigner
    budget: SourceBudget
    health: ProviderHealth = field(default_factory=ProviderHealth)
    termination: RunTermination = field(default_factory=RunTermination)

    def __post_init__(self) -> None:
        schema = self.crediter.channel_schema
        self.context = Context(
            scoped=ScopedYield(threshold_adapter=lexical_threshold_adapter),
            order=GRAIN_ORDER,
            channel_schemas={grain.name: schema for grain in GRAIN_ORDER},
        )
        self.decision_records: list[dict[str, Any]] = []
        self.record: Optional[EpisodeRecord] = None
        self.proposer: Optional[StrategyProposer] = None
        self.stranded: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # the one call that runs the tree
    # ------------------------------------------------------------------ #
    async def run(self, episode: Episode) -> EpisodeRecord:
        """Run the whole composition, once, and record the run's own end.

        The run-ending decision has NO HOOK by construction: the run grain has
        no parent and its own verdict is read after its hook, so the record is
        written here from what ``run_async`` returned. Stated so nobody looks
        for a hook that cannot exist.
        """

        record = await episode.run_async(self.context)
        self.record = record
        self.write_decision(
            record,
            decision_point=DECISION_RUN_YIELD,
            family="",
        )
        return record

    def write_decision(
        self,
        record: EpisodeRecord,
        *,
        decision_point: str,
        family: str,
    ) -> dict[str, Any]:
        payload = decision_from_record(
            record,
            decision_point=decision_point,
            family=family,
            declared_facets=self.crediter.declared_facets,
        ).to_dict()
        self.decision_records.append(payload)
        return payload

    # ------------------------------------------------------------------ #
    # export
    # ------------------------------------------------------------------ #
    def export(self) -> dict[str, Any]:
        """The summary view. A PROJECTION, and it says so.

        The whole record lives in ``acquisition_episodes.json``; this file
        derives from it and names what it drops, so a reader who checks only the
        summary is told, in the summary, that it is one.
        """

        return {
            "policy_name": ACQUISITION_POLICY_NAME,
            "projection_of": "acquisition_episodes.json",
            "keys_not_carried": [
                "units",
                "credits",
                "facets",
                "unit-level yield records",
            ],
            "credit_semantics": CREDIT_SEMANTICS,
            "credit_join": (
                "typed-table-supported logical value-slot identities fan up; "
                "row completion is diagnostic state from the same projection"
            ),
            "facet_gate": "crediting_active",
            "grains": [
                grain_disclosure(grain) for grain in GRAIN_ORDER
            ],
            "credit_basis": self.crediter.basis.to_dict(),
            "spec_digest": self.crediter.spec_digest,
            "declared_facets": list(self.crediter.declared_facets),
            "channel_schema": self.crediter.channel_schema.as_record(),
            "row_completion_rule": ROW_COMPLETION_RULE_DISCLOSURE,
            "budget": self.budget.to_dict(),
            "provider_health": self.health.to_dict(),
            "run_termination": self.termination.to_dict(),
            "proposer": dict(self.proposer.ledger) if self.proposer else {},
            # C37: per-family instance counts for EVERY family opened, not only
            # the ones the frontier still holds work for.
            "strategy_instances_opened": (
                self.proposer.instances_opened() if self.proposer else {}
            ),
            "stranded_frontier_work": list(self.stranded),
            "decisions": list(self.decision_records),
            "run": (
                {
                    "scope_key": self.record.scope_key,
                    "units_consumed": self.record.units_consumed,
                    "ended_by": self.record.ended_by,
                    "end_reason": self.record.end_reason,
                    "final_verdict": dict(self.record.final_verdict),
                    "curve": dict(self.record.curve),
                }
                if self.record is not None
                else {}
            ),
        }


#: The row-completeness diagnostic, in the artifact rather than only in code.
ROW_COMPLETION_RULE_DISCLOSURE = {
    "rule": (
        "the first durable acceptance transition at which one bound subject "
        "has at least one accepted evidence route for every required logical "
        "value slot"
    ),
    "identity": "typed-table-supported stable subject ID",
    "required_value_slots": (
        "frozen slot IDs with their reported/best-guess column alternatives"
    ),
}


class _SingleAcquirableSource:
    """Yield one already-composed Episode/Leaf, then physical exhaustion."""

    def __init__(self, item: Any) -> None:
        self._item = item
        self._yielded = False

    def next(self, view: EpisodeView) -> Any:
        if self._yielded:
            return None
        self._yielded = True
        return self._item


class ProviderBinding:
    """Own the provider surface's Episode wiring behind injected collaborators.

    This class is deliberately a binding, not a second loop and not a provider
    adapter. ``Episode`` still owns every pull/observe/verdict edge;
    ``SearchHarvester`` still owns page preparation and persistence; the
    evidence registry, graph transform, prompt/cost scopes, model string work,
    and the pipeline's downstream post-strategy transformation are injected.
    Moving those collaborations here makes the file boundary coincide with the
    surface boundary without changing any collaborator's behavior.
    """

    def __init__(
        self,
        *,
        controller: AcquisitionController,
        run_key: str,
        episode_unit_safety_cap: int,
        strategy_catalog: AbstractSet[str],
        frontier: SearchFrontier,
        search_fn: SearchFn,
        harvester: SearchHarvester,
        search_provider_batch: Mapping[str, Any],
        answers_dir: Path,
        open_cost_scope: Callable[
            [str, str, str, tuple[tuple[str, str], ...]], Any
        ],
        open_prompt_scope: Callable[
            [str, tuple[tuple[str, str], ...]], Any
        ],
        sample_strategies: Callable[
            [Sequence[Mapping[str, Any]]],
            Awaitable[Sequence[Mapping[str, Any]]],
        ],
        post_strategy: Callable[..., Awaitable[None]],
        get_table_extractor: Callable[[], Any],
        extract_table_text: Callable[..., Awaitable[list[dict[str, Any]]]],
        page_outline: Callable[[str, str], Mapping[str, Any]],
        propose_lexical_probe: Callable[..., Awaitable[Any]],
        rank_chunks: Callable[[Sequence[Any], str], Sequence[Any]],
        get_extractor: Callable[[], Any],
        extract_text: Callable[..., Awaitable[tuple[Any, Any]]],
        chunk_spans: Callable[..., Iterable[Any]],
        page_best_guess_fn: Callable[..., Awaitable[Mapping[str, Any]]],
        infer_best_guess_candidates: Callable[..., Awaitable[Sequence[Mapping[str, Any]]]],
        evidence_acceptor: EvidenceAcceptor,
        evidence_registry: Any,
        get_graph: Callable[[], Any],
        set_graph: Callable[[Any], None],
        enrich_graph_fn: Callable[..., Any],
        similarity_threshold: float,
        auto_merge_entities: bool,
        chunk_size: int,
        chunk_overlap: int,
        extraction_concurrency: int,
        extraction_timeout_sec: Optional[float],
        best_guess_evidence_chars: int,
        best_guess_llm_batch_size: int,
        best_guess_llm_timeout_sec: Optional[float],
        record_goal_discovery_sources: Callable[[list[dict[str, Any]]], None],
        refresh_search_memory: Callable[[], None],
        record_prompt_attempt_counts: Callable[[Sequence[SearchOutcome]], None],
        append_control_decision: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        record_hook_failure: Callable[[str, str, BaseException], None],
        set_active_strategy: Callable[
            [str, tuple[tuple[str, str], ...]], None
        ],
        set_units_pulled: Callable[[int], None],
        set_search_provider_error: Callable[[str], None],
        goal_states: Callable[[], Sequence[Mapping[str, Any]]],
        exported_rows: Callable[[], Mapping[str, Sequence[Mapping[str, Any]]]],
        source_ingestion_ledger: dict[str, dict[str, Any]],
        last_search_outcomes: list[SearchOutcome],
        search_outcomes: list[dict[str, Any]],
        queries_used: list[str],
        orphan_snapshot: Callable[[], Mapping[str, Any]],
        hook_failures: Callable[[], Sequence[Mapping[str, Any]]],
        criteria_projection_version: str,
        missing_tokens: Callable[[], AbstractSet[str]],
        checkpoint_completed_strategy: Optional[
            Callable[[Optional[EpisodeRecord], Any], Any]
        ] = None,
        checkpoint_completed_search: Optional[
            Callable[[Optional[EpisodeRecord], str, str], Any]
        ] = None,
    ) -> None:
        self.controller = controller
        self.crediter = controller.crediter
        self.budget = controller.budget
        self.health = controller.health
        self.termination = controller.termination
        self.run_key = str(run_key)
        self.run_path = ((RUN_GRAIN.name, self.run_key),)
        self.controller.context.bind_run_id(self.run_key)
        self.run_episode_id = Episode.identity(
            self.controller.context,
            RUN_GRAIN,
            self.run_key,
        ).episode_id
        self.episode_unit_safety_cap = int(episode_unit_safety_cap)
        self.strategy_catalog = frozenset(strategy_catalog)
        self.frontier = frontier
        self.search_fn = search_fn
        self.harvester = harvester
        self.search_provider_batch = dict(search_provider_batch)
        self.answers_dir = Path(answers_dir)
        self.open_cost_scope = open_cost_scope
        self.open_prompt_scope = open_prompt_scope
        self.sample_strategies = sample_strategies
        self.post_strategy = post_strategy
        self.get_table_extractor = get_table_extractor
        self.extract_table_text = extract_table_text
        self.page_outline = page_outline
        self.propose_lexical_probe = propose_lexical_probe
        self.rank_chunks = rank_chunks
        self.get_extractor = get_extractor
        self.extract_text = extract_text
        self.chunk_spans = chunk_spans
        self.page_best_guess_fn = page_best_guess_fn
        self.infer_best_guess_candidates = infer_best_guess_candidates
        if not isinstance(evidence_acceptor, EvidenceAcceptor):
            raise TypeError("evidence_acceptor must implement EvidenceAcceptor")
        self.evidence_acceptor = evidence_acceptor
        self.evidence_registry = evidence_registry
        self.get_graph = get_graph
        self.set_graph = set_graph
        self.enrich_graph_fn = enrich_graph_fn
        self.similarity_threshold = float(similarity_threshold)
        self.auto_merge_entities = bool(auto_merge_entities)
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)
        self.extraction_concurrency = int(extraction_concurrency)
        self.extraction_timeout_sec = extraction_timeout_sec
        self.best_guess_evidence_chars = int(best_guess_evidence_chars)
        self.best_guess_llm_batch_size = int(best_guess_llm_batch_size)
        self.best_guess_llm_timeout_sec = best_guess_llm_timeout_sec
        self.record_goal_discovery_sources = record_goal_discovery_sources
        self.refresh_search_memory = refresh_search_memory
        self.record_prompt_attempt_counts = record_prompt_attempt_counts
        self.append_control_decision = append_control_decision
        self.record_hook_failure = record_hook_failure
        self.set_active_strategy = set_active_strategy
        self.set_units_pulled = set_units_pulled
        self.set_search_provider_error = set_search_provider_error
        self.goal_states = goal_states
        self.exported_rows = exported_rows
        self.source_ingestion_ledger = source_ingestion_ledger
        self.last_search_outcomes = last_search_outcomes
        self.search_outcomes = search_outcomes
        self.queries_used = queries_used
        self.orphan_snapshot = orphan_snapshot
        self.hook_failures = hook_failures
        self.criteria_projection_version = str(criteria_projection_version)
        self.missing_tokens = missing_tokens
        self.checkpoint_completed_strategy = checkpoint_completed_strategy
        self.checkpoint_completed_search = checkpoint_completed_search

        self._strategy_ends: dict[str, str] = {}
        self._strategy_seed_queries: dict[str, list[str]] = {}
        self._open_outcomes: dict[str, SearchOutcome] = {}
        self._open_sources: dict[str, PageSource] = {}
        self._accepted_sources: list[dict[str, Any]] = []
        self._episode_records: list[dict[str, Any]] = []
        self._strategy_proposals: list[dict[str, Any]] = []
        # One compact post-verdict observation per completed strategy. This is
        # the run-level memory used by the next string proposal; it is not read
        # by credit, incidence, or any stop predicate.
        self._strategy_learning_history: list[dict[str, Any]] = []
        self._page_guess_reports: list[dict[str, Any]] = []
        self._page_states: dict[str, PageRunState] = {}
        self._pending_followup_outcomes: list[SearchOutcome] = []
        self.acquisition_page_details: list[dict[str, Any]] = []
        self._completed_strategies = 0
        self._completed_run_units: list[dict[str, Any]] = []
        self._resume_proposer_state: dict[str, Any] = {}
        self._active_strategy_key = ""
        self._active_strategy_family = ""
        self._active_strategy_seeds: list[str] = []
        self._active_search_units: list[dict[str, Any]] = []
        self.proposer: Optional[StrategyProposer] = None
        self._page_detail_path = self.answers_dir / "acquisition_page_detail.jsonl"
        self._episodes_path = self.answers_dir / "acquisition_episodes.json"

    # ------------------------------------------------------------------ #
    # Episode declarations: the surface binds; the kernel loops.
    # ------------------------------------------------------------------ #
    def build_run_episode(self) -> Episode:
        self.proposer = StrategyProposer(
            declared=self.eligible_families,
            sample=self.sample_strategies,
            build=self._build_strategy_episode,
            catalog=self.strategy_catalog,
            declared_target_ids=self._declared_target_ids,
            budget=self.budget,
            health=self.health,
            termination=self.termination,
            open_cost_scope=self.open_cost_scope,
            episode_id=self.run_episode_id,
            episode_path=self.run_path,
            run_key=self.run_key,
            record_proposal=self._record_strategy_proposal,
        )
        self.controller.proposer = self.proposer
        if self._resume_proposer_state:
            self.proposer.restore_checkpoint_state(self._resume_proposer_state)
        if self._active_strategy_key:
            self.proposer.resume_with(
                self._build_strategy_episode(
                    self._active_strategy_key,
                    self._active_strategy_family,
                    self._active_strategy_seeds,
                )
            )
        return Episode(
            grain=RUN_GRAIN,
            key=self.run_key,
            source=self.proposer,
            on_unit=self._on_strategy,
            bound=self.episode_unit_safety_cap,
            resume_units=tuple(
                ResumeUnit(
                    label=str(item["label"]),
                    credit=CreditResult(
                        credits=tuple(item.get("credits") or ()),
                        active=bool(item.get("active", True)),
                        note=str(item.get("note") or ""),
                        facets={
                            str(name): tuple(values)
                            for name, values in dict(item.get("facets") or {}).items()
                        },
                    ),
                    counts_toward_verdict=bool(
                        item.get("counts_toward_verdict", True)
                    ),
                )
                for item in self._completed_run_units
            ),
        )

    def build_source_replay_episode(
        self,
        task: SearchTask,
        result: Mapping[str, Any],
        *,
        strategy_key: str = "source_replay#0",
    ) -> Episode:
        """Compose one saved source through the production Episode hierarchy.

        Replay replaces only the provider search with one explicit result.
        Page preparation, chunk ranking, extraction, evidence acceptance,
        typed table mutation, credit assignment, numerical control, hooks, and
        post-strategy exports are the same objects used by a live run. Each
        enclosing source yields its one child and then returns ``None``, so
        physical corpus exhaustion—not a synthetic numerical verdict or unit
        cap—ends the replay.
        """

        if not isinstance(task, SearchTask):
            raise TypeError("source replay requires a SearchTask")
        if not isinstance(result, Mapping):
            raise TypeError("source replay result must be a mapping")
        if not str(strategy_key):
            raise ValueError("source replay strategy_key must be non-empty")

        family = str(strategy_key).split("#", 1)[0]
        outcome = SearchOutcome.for_task(task)
        outcome.search_result_observations.append(
            search_result_observation(dict(result), rank=1)
        )
        self._open_outcomes[task.id] = outcome
        self._active_strategy_key = str(strategy_key)
        self._active_strategy_family = family
        self._active_strategy_seeds = [task.query]

        search_path = (
            (RUN_GRAIN.name, self.run_key),
            (STRATEGY_GRAIN.name, str(strategy_key)),
            (SEARCH_GRAIN.name, task.id),
        )
        search_episode_id = Episode.identity(
            self.controller.context,
            SEARCH_GRAIN,
            task.id,
            parent_path=search_path[:-1],
        ).episode_id
        page_item = self._make_page_item(
            task,
            result,
            1,
            episode_id=search_episode_id,
            episode_path=search_path,
        )
        search_episode = Episode(
            grain=SEARCH_GRAIN,
            key=task.id,
            source=_SingleAcquirableSource(page_item),
            on_unit=lambda item, contribution, record: self._on_page(
                item,
                contribution,
                record,
                outcome,
                str(strategy_key),
                family,
            ),
        )
        strategy_episode = Episode(
            grain=STRATEGY_GRAIN,
            key=str(strategy_key),
            source=_SingleAcquirableSource(search_episode),
            on_unit=lambda item, contribution, record: self._on_search(
                item,
                contribution,
                record,
                str(strategy_key),
                family,
            ),
        )
        return Episode(
            grain=RUN_GRAIN,
            key=self.run_key,
            source=_SingleAcquirableSource(strategy_episode),
            on_unit=self._on_strategy,
        )

    def _build_strategy_episode(
        self,
        strategy_key: str,
        family: str,
        seeds: Sequence[str],
    ) -> Episode:
        resuming = bool(
            self._active_strategy_key
            and self._active_strategy_key == strategy_key
            and self._active_search_units
        )
        if seeds and not resuming:
            self._strategy_seed_queries[strategy_key] = list(seeds)
            self.frontier.enqueue_queries(
                seeds,
                topic="strategy_proposal",
                expansion_op=family,
                producer_class="strategy_proposer",
            )
        if not resuming:
            self._active_search_units = []
        self._active_strategy_key = str(strategy_key)
        self._active_strategy_family = str(family)
        self._active_strategy_seeds = [str(seed) for seed in seeds]
        return Episode(
            grain=STRATEGY_GRAIN,
            key=strategy_key,
            source=StrategySearches(
                strategy_key=strategy_key,
                family=family,
                next_task=self.frontier.next_for,
                make_search=lambda task: self._build_search_episode(
                    task, strategy_key, family
                ),
                budget=self.budget,
                health=self.health,
            ),
            on_unit=lambda unit, contribution, record: self._on_search(
                unit, contribution, record, strategy_key, family
            ),
            resume_units=tuple(
                ResumeUnit(
                    label=str(item["label"]),
                    credit=CreditResult(
                        credits=tuple(item.get("credits") or ()),
                        active=bool(item.get("active", True)),
                        note=str(item.get("note") or ""),
                        facets={
                            str(name): tuple(values)
                            for name, values in dict(item.get("facets") or {}).items()
                        },
                    ),
                    counts_toward_verdict=bool(
                        item.get("counts_toward_verdict", True)
                    ),
                )
                for item in self._active_search_units
            ),
        )

    def _build_search_episode(
        self,
        task: SearchTask,
        strategy_key: str,
        family: str,
    ) -> Episode:
        outcome = SearchOutcome.for_task(task)
        self._open_outcomes[task.id] = outcome
        search_path = (
            (RUN_GRAIN.name, self.run_key),
            (STRATEGY_GRAIN.name, strategy_key),
            (SEARCH_GRAIN.name, task.id),
        )
        search_episode_id = Episode.identity(
            self.controller.context,
            SEARCH_GRAIN,
            task.id,
            parent_path=search_path[:-1],
        ).episode_id
        source = PageSource(
            task=task,
            search_fn=self.search_fn,
            make_page=lambda task, result, rank: self._make_page_item(
                task,
                result,
                rank,
                episode_id=search_episode_id,
                episode_path=search_path,
            ),
            budget=self.budget,
            health=self.health,
            episode_id=search_episode_id,
            episode_path=search_path,
            open_cost_scope=self.open_cost_scope,
            on_results=self._note_search_results,
            on_error=self._note_search_error,
            is_fatal=is_fatal_search_error,
        )
        self._open_sources[task.id] = source
        return Episode(
            grain=SEARCH_GRAIN,
            key=task.id,
            source=source,
            on_unit=lambda unit, contribution, record: self._on_page(
                unit, contribution, record, outcome, strategy_key, family
            ),
        )

    def _make_page_item(
        self,
        task: SearchTask,
        result: Mapping[str, Any],
        rank: int,
        *,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
    ) -> Any:
        """Return the table binding's page Episode or the existing page leaf.

        Graph extraction remains a separate binding path.  The new nested
        chunk method is selected by the presence of the table extractor, not a
        mode flag.
        """

        if self.get_table_extractor() is None:
            return self._make_page_leaf(
                task,
                result,
                rank,
                episode_id=episode_id,
                episode_path=episode_path,
            )

        unit = PageUnit(
            task=task,
            result=result,
            rank=rank,
            episode_id=episode_id,
            episode_path=episode_path,
            label=f"{task.id}#{rank}",
        )
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            outcome = SearchOutcome.for_task(task)
            self._open_outcomes[task.id] = outcome

        with self.open_cost_scope(
            ObservationKind.SOURCE.value,
            unit.label,
            unit.episode_id,
            unit.episode_path,
        ):
            prepared = self.harvester.prepare_page(
                task, dict(result), outcome, rank=rank
            )
            if prepared.candidate is None:
                material = PageMaterial(
                    fate=page_fate(
                        mechanical=prepared.fate,
                        error_class=prepared.error_class,
                    ),
                    text_chars=prepared.text_length,
                )
                return self._material_leaf(unit, material)
            if not self.crediter.basis.columns:
                return self._material_leaf(
                    unit,
                    PageMaterial(
                        fate=page_fate(mechanical=FATE_NO_CREDIT_COLUMNS),
                        text_chars=len(prepared.candidate.text),
                    ),
                )
            source_record = self.harvester.write_source(
                task,
                prepared.candidate,
                outcome,
                rank=rank,
                episode_id=episode_id,
            )

        text = str(source_record.get("text") or "")
        spans = tuple(self.chunk_spans(text, self.chunk_size, self.chunk_overlap))
        if not spans:
            return self._material_leaf(
                unit,
                PageMaterial(
                    fate=page_fate(extraction=EXTRACT_OK),
                    source_id=str(source_record.get("id") or ""),
                    source_record=source_record,
                    ingestion=self._open_ingestion_entry(source_record),
                    reduction=prepared.candidate.reduction,
                    text_chars=len(text),
                ),
            )

        page_path = episode_path + ((PAGE_GRAIN.name, unit.label),)
        page_ref = Episode.identity(
            self.controller.context,
            PAGE_GRAIN,
            unit.label,
            parent_path=episode_path,
        )
        state = PageRunState(
            unit=unit,
            source_record=source_record,
            ingestion=self._open_ingestion_entry(source_record),
            reduction=prepared.candidate.reduction,
            chunks=spans,
            outline=self.page_outline(
                text,
                str(source_record.get("title") or ""),
            ),
        )
        self._page_states[unit.label] = state
        source = LexicalProbeSource(
            state=state,
            propose=self.propose_lexical_probe,
            rank=self.rank_chunks,
            make_probe=lambda key, proposal, ranked: self._make_probe_episode(
                state,
                key,
                proposal,
                ranked,
                page_episode_id=page_ref.episode_id,
                page_path=page_path,
            ),
            open_cost_scope=self.open_cost_scope,
            open_prompt_scope=self.open_prompt_scope,
        )
        return Episode(
            grain=PAGE_GRAIN,
            key=unit.label,
            source=source,
            on_unit=lambda probe, contribution, record: self._on_probe(
                state, probe, contribution, record
            ),
        )

    def _material_leaf(self, unit: PageUnit, material: PageMaterial) -> Leaf:
        return Leaf(
            unit=unit,
            extract=lambda _unit: material,
            accept=self.accept_evidence,
            credit=self.crediter,
            label=unit.label,
        )

    def _make_probe_episode(
        self,
        state: PageRunState,
        probe_key: str,
        proposal: Any,
        ranked_chunks: Sequence[Any],
        *,
        page_episode_id: str,
        page_path: tuple[tuple[str, str], ...],
    ) -> Episode:
        probe_path = page_path + ((LEXICAL_PROBE_GRAIN.name, probe_key),)
        probe_ref = Episode.identity(
            self.controller.context,
            LEXICAL_PROBE_GRAIN,
            probe_key,
            parent_path=page_path,
        )
        source = RankedChunkSource(
            state=state,
            ranked_chunks=ranked_chunks,
            make_leaf=lambda span: self._make_chunk_leaf(
                state,
                span,
                probe_key=probe_key,
                episode_id=probe_ref.episode_id,
                episode_path=probe_path,
            ),
        )
        return Episode(
            grain=LEXICAL_PROBE_GRAIN,
            key=probe_key,
            source=source,
            on_unit=lambda leaf, contribution, record: self._on_chunk(
                state, leaf, contribution, record
            ),
        )

    def _make_chunk_leaf(
        self,
        state: PageRunState,
        span: Any,
        *,
        probe_key: str,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
    ) -> Leaf:
        unit = ChunkUnit(
            page=state.unit,
            span=span,
            source_record=state.source_record,
            episode_id=episode_id,
            episode_path=episode_path,
            probe_key=probe_key,
            label=state.chunk_id(span),
        )
        return Leaf(
            unit=unit,
            extract=self._extract_chunk,
            accept=self.accept_evidence,
            credit=self.crediter,
            label=unit.label,
        )

    def _make_page_leaf(
        self,
        task: SearchTask,
        result: Mapping[str, Any],
        rank: int,
        *,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
    ) -> Leaf:
        unit = PageUnit(
            task=task,
            result=result,
            rank=rank,
            episode_id=episode_id,
            episode_path=episode_path,
            label=f"{task.id}#{rank}",
        )
        return Leaf(
            unit=unit,
            extract=self.fetch_extract,
            accept=self.accept_evidence,
            credit=self.crediter,
            label=unit.label,
        )

    async def _extract_chunk(self, unit: ChunkUnit) -> PageMaterial:
        """Extract one selected chunk; no other chunk is touched by this pull."""

        source_id = str(unit.source_record.get("id") or "")
        chunk_record = {
            "chunk_index": int(unit.span.index),
            "chunk_id": unit.label,
            "source_id": source_id,
            "start_offset": int(unit.span.start_offset),
            "end_offset": int(unit.span.end_offset),
            "text": str(unit.span.text),
            "failed": False,
            "failure_class": "",
            "credits_minted": 0,
            "new_within_page": 0,
            "repeats_within_page": 0,
            "row_credits_minted": 0,
            "probe_key": unit.probe_key,
        }
        extractor = self.get_table_extractor()
        if extractor is None:
            return PageMaterial(
                source_id=source_id,
                fate=page_fate(mechanical=FATE_NO_EXTRACTOR),
                source_record=unit.source_record,
                chunks=(chunk_record,),
                text_chars=len(str(unit.span.text)),
            )

        try:
            with self.open_prompt_scope(unit.episode_id, unit.episode_path):
                with self.open_cost_scope(
                    ObservationKind.SOURCE.value,
                    unit.label,
                    unit.episode_id,
                    unit.episode_path,
                ):
                    call = extractor.forward(str(unit.span.text))
                    result = (
                        await asyncio.wait_for(
                            call, timeout=self.extraction_timeout_sec
                        )
                        if self.extraction_timeout_sec is not None
                        and self.extraction_timeout_sec > 0
                        else await call
                    )
        except Exception as exc:  # noqa: BLE001 - one chunk is one failed unit
            error_class = classify_error(exc)
            chunk_record.update(
                {
                    "failed": True,
                    "failure_class": error_class or type(exc).__name__,
                }
            )
            return PageMaterial(
                source_id=source_id,
                fate=page_fate(
                    extraction=EXTRACT_RAISED,
                    error_class=error_class,
                ),
                source_record=unit.source_record,
                chunks=(chunk_record,),
                text_chars=len(str(unit.span.text)),
            )

        records = [
            {
                "table": row["table"],
                "index": index,
                "values": dict(row["values"]),
                "source_chunks": [unit.label],
            }
            for index, row in enumerate(result.rows)
        ]
        return PageMaterial(
            source_id=source_id,
            fate=page_fate(extraction=EXTRACT_OK),
            records=tuple(records),
            source_record=unit.source_record,
            chunks=(chunk_record,),
            text_chars=len(str(unit.span.text)),
        )

    def _on_chunk(
        self,
        state: PageRunState,
        leaf: Leaf,
        contribution: Any,
        record: Any,
    ) -> None:
        """Close one chunk pull and make it ineligible for every later probe."""

        unit = leaf.unit
        state.processed_chunk_ids.add(unit.label)
        state.chunk_units.append(unit)
        material = contribution.extracted
        if isinstance(material, PageMaterial):
            findings = set(contribution.credit.credits)
            new_findings = findings - state.seen_finding_ids
            repeated_findings = findings & state.seen_finding_ids
            for chunk in material.chunks:
                if isinstance(chunk, dict):
                    chunk["credits_minted"] = len(findings)
                    chunk["new_within_page"] = len(new_findings)
                    chunk["repeats_within_page"] = len(repeated_findings)
            state.seen_finding_ids.update(findings)
            state.materials.append(material)
        successful = sum(1 for item in state.materials if item.fate.judged)
        failed = sum(1 for item in state.materials if not item.fate.judged)
        state.ingestion.update(
            {
                "extraction_state": (
                    "extracting_chunks"
                    if state.remaining_chunks()
                    else "extracted_table_rows"
                    if any(item.records for item in state.materials)
                    else "extracted_no_table_rows"
                ),
                "table_row_count": sum(
                    len(item.records) for item in state.materials
                ),
                "failed_chunks": failed,
                "successful_chunks": successful,
                "chunk_count": len(state.materials),
                "unprocessed_chunk_count": len(state.remaining_chunks()),
            }
        )

    def _on_probe(
        self,
        state: PageRunState,
        episode: Episode,
        contribution: Any,
        record: Any,
    ) -> None:
        """Expose one probe's measured result to the next probe proposal."""

        child = contribution.child
        proposal = dict(state.probe_proposals.get(episode.key) or {})
        proposal.update(
            {
                "probe_key": episode.key,
                "chunks_processed": child.units_consumed if child else 0,
                "distinct_findings": (
                    len(child.distinct_identities) if child else 0
                ),
                "findings_by_channel": (
                    {
                        self.crediter.facet_labels.get(name, name): len(values)
                        for name, values in child.facet_distinct.items()
                    }
                    if child
                    else {}
                ),
                "ended_by": child.ended_by if child else "",
                "unprocessed_chunks": len(state.remaining_chunks()),
                "volume_credit": (
                    record.volume_credit.as_record()
                    if record.volume_credit is not None
                    else None
                ),
            }
        )
        state.probe_history.append(proposal)

    def _page_material(self, state: PageRunState) -> PageMaterial:
        """Project completed chunk work into the existing page artifact shape."""

        judged = [item for item in state.materials if item.fate.judged]
        fate = page_fate(
            extraction=(EXTRACT_OK if judged else EXTRACT_ALL_CHUNKS_FAILED)
        )
        chunks = tuple(
            dict(chunk)
            for material in state.materials
            for chunk in material.chunks
        )
        commits = tuple(
            material.evidence_commit
            for material in state.materials
            if material.evidence_commit is not None
        )
        return PageMaterial(
            source_id=str(state.source_record.get("id") or ""),
            fate=fate,
            records=tuple(
                record
                for material in state.materials
                for record in material.records
            ),
            guesses=tuple(
                guess
                for material in state.materials
                for guess in material.guesses
            ),
            source_record=state.source_record,
            ingestion=state.ingestion,
            reduction=state.reduction,
            chunks=chunks,
            text_chars=len(str(state.source_record.get("text") or "")),
            evidence_commits=commits,
            probe_history=tuple(dict(item) for item in state.probe_history),
        )

    def _attach_page_credit(self, state: PageRunState) -> None:
        if state.unit.credit_detail is not None:
            return
        details = [
            unit.credit_detail
            for unit in state.chunk_units
            if unit.credit_detail is not None
        ]
        state.unit.attach_credit(
            PageCredit(
                attributions=tuple(
                    item
                    for detail in details
                    for item in detail.attributions
                ),
                row_completions=tuple(
                    item
                    for detail in details
                    for item in detail.row_completions
                ),
                row_completion_unavailable=(
                    self.crediter.row_completion_unavailable
                ),
                declared_facets=self.crediter.declared_facets,
                chunk_encounters=tuple(
                    dict(chunk)
                    for material in state.materials
                    for chunk in material.chunks
                ),
            )
        )

    # ------------------------------------------------------------------ #
    # Page leaf: provider mechanics, extraction, evidence acceptance.
    # ------------------------------------------------------------------ #
    async def fetch_extract(self, unit: PageUnit) -> PageMaterial:
        task = unit.task
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            outcome = SearchOutcome.for_task(task)
            self._open_outcomes[task.id] = outcome

        with self.open_prompt_scope(unit.episode_id, unit.episode_path):
            with self.open_cost_scope(
                ObservationKind.SOURCE.value,
                unit.label,
                unit.episode_id,
                unit.episode_path,
            ):
                return await self._acquire_page(unit, outcome)

    async def _acquire_page(
        self,
        unit: PageUnit,
        outcome: SearchOutcome,
    ) -> PageMaterial:
        task = unit.task
        prepared = self.harvester.prepare_page(
            task, dict(unit.result), outcome, rank=unit.rank
        )
        if prepared.candidate is None:
            return PageMaterial(
                fate=page_fate(
                    mechanical=prepared.fate,
                    error_class=prepared.error_class,
                ),
                text_chars=prepared.text_length,
            )
        candidate = prepared.candidate

        table_extractor = self.get_table_extractor()
        graph_extractor = self.get_extractor()
        if table_extractor is None and graph_extractor is None:
            return PageMaterial(
                fate=page_fate(mechanical=FATE_NO_EXTRACTOR),
                text_chars=len(candidate.text),
            )
        if not self.crediter.basis.columns:
            return PageMaterial(
                fate=page_fate(mechanical=FATE_NO_CREDIT_COLUMNS),
                text_chars=len(candidate.text),
            )

        source_record = self.harvester.write_source(
            task, candidate, outcome, rank=unit.rank, episode_id=unit.episode_id
        )
        source_id = str(source_record.get("id") or "")
        ingestion = self._open_ingestion_entry(source_record)
        chunks: list[dict[str, Any]] = []
        try:
            observer = self._chunk_observer(
                chunks,
                source_id=source_id,
                page_text=str(source_record["text"]),
            )
            if table_extractor is not None:
                records = await self.extract_table_text(
                    table_extractor,
                    source_record["text"],
                    source_id,
                    chunk_size=self.chunk_size,
                    overlap=self.chunk_overlap,
                    concurrency=self.extraction_concurrency,
                    timeout=self.extraction_timeout_sec,
                    on_chunk=observer,
                )
                entities: Mapping[str, Mapping[str, Any]] = {}
                relationships: Sequence[Mapping[str, Any]] = ()
            else:
                entities, relationships = await self.extract_text(
                    graph_extractor,
                    source_record["text"],
                    source_id,
                    chunk_size=self.chunk_size,
                    overlap=self.chunk_overlap,
                    concurrency=self.extraction_concurrency,
                    timeout=self.extraction_timeout_sec,
                    on_chunk=observer,
                )
                records = self._extracted_records(entities, relationships)
        except Exception as exc:  # noqa: BLE001 - converted, never raised
            error_class = classify_error(exc)
            ingestion.update(
                {
                    "extraction_state": "extraction_failed",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "error_class": error_class,
                }
            )
            return PageMaterial(
                source_id=source_id,
                fate=page_fate(
                    extraction=EXTRACT_RAISED,
                    error_class=error_class,
                ),
                source_record=source_record,
                ingestion=ingestion,
                reduction=candidate.reduction,
                chunks=tuple(chunks),
                text_chars=len(candidate.text),
            )

        failed_chunks = sum(1 for chunk in chunks if chunk.get("failed"))
        if chunks and failed_chunks == len(chunks):
            ingestion.update(
                {
                    "extraction_state": "extraction_all_chunks_failed",
                    "reason": (
                        f"all {failed_chunks} chunk(s) of this page failed to "
                        f"extract, so zero entities here means 'could not "
                        f"judge', not 'this page carried nothing'"
                    ),
                    "failed_chunks": failed_chunks,
                }
            )
            return PageMaterial(
                source_id=source_id,
                fate=page_fate(extraction=EXTRACT_ALL_CHUNKS_FAILED),
                source_record=source_record,
                ingestion=ingestion,
                reduction=candidate.reduction,
                chunks=tuple(chunks),
                text_chars=len(candidate.text),
            )

        ingestion.update(
            {
                "extraction_state": (
                    "extracted_table_rows"
                    if table_extractor is not None and records
                    else "extracted_no_table_rows"
                    if table_extractor is not None
                    else "extracted_entities"
                    if entities
                    else "extracted_no_entities"
                ),
                "entity_count": len(entities or {}),
                "relationship_count": len(relationships or ()),
                "table_row_count": len(records),
                "failed_chunks": failed_chunks,
                "chunk_count": len(chunks),
            }
        )
        return PageMaterial(
            source_id=source_id,
            fate=page_fate(extraction=EXTRACT_OK),
            entities=entities or {},
            relationships=list(relationships or ()),
            records=records,
            source_record=source_record,
            ingestion=ingestion,
            reduction=candidate.reduction,
            chunks=tuple(chunks),
            text_chars=len(candidate.text),
        )

    async def accept_evidence(
        self,
        unit: PageUnit,
        material: PageMaterial,
    ) -> PageMaterial:
        """Run the bound acceptor, then persist exactly its typed decision."""

        if not material.fate.judged or material.source_record is None:
            return material
        source_record = material.source_record
        ingestion = dict(material.ingestion)
        chunks = [dict(item) for item in material.chunks]
        try:
            document, version, source_chunks = self.evidence_registry.source_records(
                source_id=material.source_id,
                canonical_locator=str(
                    source_record.get("url")
                    or source_record.get("source_url")
                    or material.source_id
                ),
                title=str(source_record.get("title") or ""),
                content=str(source_record.get("text") or ""),
                chunks=chunks,
            )
            runtime_to_registry = {
                str(chunk_record.get("chunk_id") or ""): source_chunk.id
                for chunk_record, source_chunk in zip(chunks, source_chunks)
            }
            records = [
                {
                    **dict(record),
                    "source_chunks": [
                        runtime_to_registry[chunk_id]
                        for chunk_id in (
                            str(item)
                            for item in record.get("source_chunks") or ()
                        )
                        if chunk_id in runtime_to_registry
                    ],
                }
                for record in material.records
                if isinstance(record, Mapping)
            ]
            spans, direct_candidates = self.crediter.assertion_candidates(
                records,
                document=document,
                version=version,
                chunks=source_chunks,
            )
            guesses = await self._page_best_guess(
                records=records,
                source_id=material.source_id,
                source_chunks=source_chunks,
            )
            best_guess_candidates = self.crediter.best_guess_candidates(
                records,
                guesses,
                document=document,
                version=version,
                chunks=source_chunks,
            )
            source_batch_id = self.evidence_registry.register_source_candidates(
                document=document,
                version=version,
                content=str(source_record.get("text") or ""),
                chunks=source_chunks,
                spans=spans,
                candidates=direct_candidates,
                best_guess_candidates=best_guess_candidates,
            )
            decision = self.evidence_acceptor.evaluate(
                direct_candidates=direct_candidates,
                best_guess_candidates=best_guess_candidates,
                spans=spans,
                chunks=source_chunks,
            )
            evidence_commit = self.evidence_registry.commit_acceptance(
                source_batch_id,
                decision,
            )
            accepted_by_chunk: dict[str, set[str]] = {}
            for cell in evidence_commit.accepted_cells:
                accepted_by_chunk.setdefault(cell.chunk_id, set()).add(
                    cell.criterion_id
                )
            for cell in evidence_commit.accepted_best_guess_cells:
                for chunk_id in cell.supporting_chunk_ids:
                    accepted_by_chunk.setdefault(chunk_id, set()).add(
                        cell.criterion_id
                    )
            seen_chunk_credits: set[str] = set()
            for chunk_record, source_chunk in zip(chunks, source_chunks):
                identities = accepted_by_chunk.get(source_chunk.id, set())
                new = identities - seen_chunk_credits
                chunk_record["registry_chunk_id"] = source_chunk.id
                chunk_record["credits_minted"] = len(identities)
                chunk_record["new_within_page"] = len(new)
                chunk_record["repeats_within_page"] = len(identities) - len(new)
                seen_chunk_credits.update(identities)
            return replace(
                material,
                records=tuple(records),
                guesses=tuple(guesses),
                chunks=tuple(chunks),
                evidence_commit=evidence_commit,
            )
        except (OSError, ValueError, LookupError, TypeError) as exc:
            error_class = classify_error(exc)
            ingestion.update(
                {
                    "extraction_state": "evidence_acceptance_failed",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "error_class": error_class,
                }
            )
            return replace(
                material,
                fate=page_fate(
                    extraction=EXTRACT_RAISED,
                    error_class=error_class,
                ),
                ingestion=ingestion,
                chunks=tuple(chunks),
                evidence_commit=None,
            )

    def _chunk_observer(
        self,
        sink: list[dict[str, Any]],
        *,
        source_id: str,
        page_text: str,
    ) -> Callable[..., None]:
        declared = {
            chunk.index: chunk
            for chunk in self.chunk_spans(
                page_text, self.chunk_size, self.chunk_overlap
            )
        }

        def observe(index, chunk_id, entities, relationships, failure) -> None:
            source_chunk = declared[int(index)]
            sink.append(
                {
                    "chunk_index": int(index),
                    "chunk_id": str(chunk_id),
                    "source_id": source_id,
                    "start_offset": source_chunk.start_offset,
                    "end_offset": source_chunk.end_offset,
                    "text": source_chunk.text,
                    "failed": bool(failure),
                    "failure_class": str(failure or ""),
                    "credits_minted": 0,
                    "new_within_page": 0,
                    "repeats_within_page": 0,
                    "row_credits_minted": 0,
                }
            )

        return observe

    def _extracted_records(
        self,
        entities: Mapping[str, Mapping[str, Any]],
        relationships: Sequence[Mapping[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        tables = self.crediter.basis.tables
        out: list[dict[str, Any]] = []
        index = 0
        for record in list((entities or {}).values()) + list(relationships or ()):
            if not isinstance(record, Mapping):
                continue
            attributes = record.get("attributes")
            values: dict[str, Any] = {}
            if isinstance(attributes, Mapping):
                values.update(attributes)
            for key, value in record.items():
                if key in ("attributes", "source_chunks", "source_chunk"):
                    continue
                values.setdefault(str(key), value)
            chunks = record.get("source_chunks") or (
                [record.get("source_chunk")] if record.get("source_chunk") else []
            )
            for table in tables:
                out.append(
                    {
                        "table": table,
                        "index": index,
                        "values": values,
                        "source_chunks": [str(chunk) for chunk in chunks if chunk],
                    }
                )
            index += 1
        return out

    async def _page_best_guess(
        self,
        *,
        records: Sequence[Mapping[str, Any]],
        source_id: str,
        source_chunks: Sequence[SourceChunk],
    ) -> list[dict[str, Any]]:
        columns = self.crediter.best_guess_columns_by_table()
        if not records or not any(columns.values()):
            return []
        report = await self.page_best_guess_fn(
            records=records,
            columns_by_table=columns,
            reported_alternatives_by_table=(
                self.crediter.best_guess_routes_by_table()
            ),
            subject_key_columns_by_table=(
                self.crediter.basis.subject_key_columns
            ),
            source_id=source_id,
            evidence_chunks=[
                {
                    "source_id": source_id,
                    "source_chunk": chunk.id,
                    "text": chunk.text,
                }
                for chunk in source_chunks
            ],
            extract_fn=self.infer_best_guess_candidates,
            llm_batch_size=self.best_guess_llm_batch_size,
            llm_timeout_sec=self.best_guess_llm_timeout_sec,
            evidence_chars=self.best_guess_evidence_chars,
        )
        self._page_guess_reports.append(
            {
                "source_id": source_id,
                "task_count": report.get("task_count"),
                "llm_calls": report.get("llm_calls"),
                "resolution_count": len(report.get("resolutions") or []),
                "errors": report.get("errors") or [],
            }
        )
        return list(report.get("resolutions") or [])

    def _open_ingestion_entry(
        self,
        source_record: Mapping[str, Any],
    ) -> dict[str, Any]:
        source_id = str(source_record.get("id") or "")
        entry = {
            "source_id": source_id,
            "extraction_state": "attempted",
            "reason": "",
            "entity_count": 0,
            "relationship_count": 0,
            "text_chars": len(str(source_record.get("text") or "")),
            "search_episode_id": str(source_record.get("search_episode_id") or ""),
        }
        self.source_ingestion_ledger[source_id] = entry
        return entry

    # ------------------------------------------------------------------ #
    # Post-verdict hooks. Their return values never steer the current unit.
    # ------------------------------------------------------------------ #
    def _on_page(
        self,
        item: Any,
        contribution: Any,
        record: Any,
        outcome: SearchOutcome,
        strategy_key: str,
        family: str,
    ) -> None:
        if isinstance(item, Episode):
            state = self._page_states.pop(item.key, None)
            if state is None:
                self.record_hook_failure(
                    "on_page",
                    item.key,
                    LookupError(f"page state missing for {item.key!r}"),
                )
                return
            self._attach_page_credit(state)
            unit = state.unit
            material = self._page_material(state)
        else:
            unit = item.unit
            material = contribution.extracted
        try:
            self.budget.charge(1)
            self.set_units_pulled(self.budget.spent)
            if isinstance(material, PageMaterial):
                skip = fate_skip_reason(material.fate)
                if skip:
                    outcome.skip(skip)
                if material.source_record is not None:
                    source = dict(material.source_record)
                    self._accepted_sources.append(source)
                    self.record_goal_discovery_sources([source])
                    if material.entities or material.relationships:
                        graph = self.enrich_graph_fn(
                            self.get_graph(),
                            dict(material.entities),
                            list(material.relationships),
                            material.source_id,
                            similarity_threshold=self.similarity_threshold,
                            auto_merge=self.auto_merge_entities,
                        )
                        self.set_graph(graph)
                self._write_page_detail(
                    unit, record, material, strategy_key, family
                )
        except Exception as exc:  # noqa: BLE001 - hook must not unwind the tree
            self.record_hook_failure("on_page", unit.label, exc)

    def _on_search(
        self,
        episode: Episode,
        contribution: Any,
        record: Any,
        strategy_key: str,
        family: str,
    ) -> None:
        child = contribution.child
        try:
            task_id = child.scope_key if child is not None else episode.key
            outcome = self._open_outcomes.pop(task_id, None)
            source = self._open_sources.pop(task_id, None)
            if outcome is None:
                return
            if child is not None and child.ended_by == END_YIELD_STOP:
                remaining = source.remaining if source is not None else 0
                if remaining > 0:
                    outcome.skip("yield_stop", remaining)
                self.append_control_decision(
                    self.controller.write_decision(
                        child,
                        decision_point=DECISION_SEARCH_ITEM_YIELD,
                        family=family,
                    )
                )
            if source is not None and source.cost is not None:
                outcome.cost = dict(source.cost)
            outcome.provider_batch = dict(self.search_provider_batch)
            if source is not None:
                outcome.result_buffer = source.result_buffer
            self.last_search_outcomes.append(outcome)
            self.frontier.record([outcome])
            self.search_outcomes.append(outcome.to_dict())
            self.queries_used.append(outcome.query)
            self.harvester.record_outcome(outcome)
            self.refresh_search_memory()
            self.record_prompt_attempt_counts([outcome])
            self._pending_followup_outcomes.append(outcome)
            self._active_search_units.append(
                {
                    "label": str(episode.label),
                    "credits": list(contribution.credit.credits),
                    "active": bool(contribution.credit.active),
                    "note": str(contribution.credit.note),
                    "facets": {
                        str(name): list(values)
                        for name, values in contribution.credit.facets.items()
                    },
                    "counts_toward_verdict": bool(
                        contribution.counts_toward_verdict
                    ),
                }
            )
            if self.checkpoint_completed_search is not None:
                self.checkpoint_completed_search(child, strategy_key, family)
        except Exception as exc:  # noqa: BLE001 - hook must not unwind the tree
            self.record_hook_failure("on_search", episode.key, exc)

    async def _on_strategy(
        self,
        episode: Episode,
        contribution: Any,
        record: Any,
    ) -> None:
        child = contribution.child
        family = str(episode.key).split("#", 1)[0]
        try:
            if child is not None:
                self._strategy_ends[family] = child.ended_by
                self.append_control_decision(
                    self.controller.write_decision(
                        child,
                        decision_point=DECISION_STRATEGY_YIELD,
                        family=family,
                    )
                )
                self.write_episode_record(child)
                try:
                    self._strategy_learning_history.append(
                        self._strategy_learning_observation(
                            strategy_key=str(episode.key),
                            family=family,
                            record=child,
                            volume_credit=record.volume_credit,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - memory is advisory
                    self.record_hook_failure(
                        "strategy_learning_observation", episode.key, exc
                    )
                observed = int(record.yield_record.unit_index)
                if observed != int(self._completed_strategies):
                    self.record_hook_failure(
                        "strategy_unit_index",
                        episode.key,
                        ValueError(
                            f"local completed-strategy count "
                            f"{self._completed_strategies} disagrees with the "
                            f"run episode's unit index {observed}"
                        ),
                    )
            strategy_episode_id = child.episode_id if child is not None else ""
            strategy_path = (
                (RUN_GRAIN.name, self.run_key),
                (STRATEGY_GRAIN.name, str(episode.key)),
            )
            self.set_active_strategy(strategy_episode_id, strategy_path)
            await self.post_strategy(
                episode.key,
                family,
                strategy_episode_id,
                run_unit_index=int(record.yield_record.unit_index),
            )
        except Exception as exc:  # noqa: BLE001 - hook must not unwind the tree
            self.record_hook_failure("on_strategy", episode.key, exc)
        finally:
            self.set_active_strategy("", ())
            self._completed_strategies += 1
        self._completed_run_units.append(
            {
                "label": str(episode.label),
                "credits": list(contribution.credit.credits),
                "active": bool(contribution.credit.active),
                "note": str(contribution.credit.note),
                "facets": {
                    str(name): list(values)
                    for name, values in contribution.credit.facets.items()
                },
                "counts_toward_verdict": bool(
                    contribution.counts_toward_verdict
                ),
            }
        )
        self._active_strategy_key = ""
        self._active_strategy_family = ""
        self._active_strategy_seeds = []
        self._active_search_units = []
        if self.checkpoint_completed_strategy is not None:
            try:
                result = self.checkpoint_completed_strategy(child, record)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:  # noqa: BLE001 - disclosed hook failure
                self.record_hook_failure("checkpoint", episode.key, exc)

    def checkpoint_state(self) -> dict[str, Any]:
        """Return provider-owned state at a completed strategy boundary."""

        return {
            "completed_run_units": list(self._completed_run_units),
            "completed_strategies": self._completed_strategies,
            "strategy_ends": dict(self._strategy_ends),
            "strategy_seed_queries": {
                key: list(values)
                for key, values in self._strategy_seed_queries.items()
            },
            "episode_records": list(self._episode_records),
            "strategy_proposals": list(self._strategy_proposals),
            "strategy_learning_history": list(
                self._strategy_learning_history
            ),
            "credit_assignments": list(self.crediter.checkpoint_assignments()),
            "proposer": (
                self.proposer.checkpoint_state() if self.proposer else {}
            ),
            "active_strategy": {
                "key": self._active_strategy_key,
                "family": self._active_strategy_family,
                "seeds": list(self._active_strategy_seeds),
                "completed_search_units": list(self._active_search_units),
            },
        }

    def restore_checkpoint_state(self, state: Mapping[str, Any]) -> None:
        """Restore provider-owned state before the run Episode is built."""

        self._completed_run_units = [
            dict(item) for item in (state.get("completed_run_units") or ())
        ]
        self._completed_strategies = int(
            state.get("completed_strategies") or len(self._completed_run_units)
        )
        self._strategy_ends = {
            str(name): str(value)
            for name, value in dict(state.get("strategy_ends") or {}).items()
        }
        self._strategy_seed_queries = {
            str(key): [str(value) for value in values]
            for key, values in dict(
                state.get("strategy_seed_queries") or {}
            ).items()
        }
        self._episode_records = [
            dict(item) for item in (state.get("episode_records") or ())
        ]
        self._strategy_proposals = [
            dict(item) for item in (state.get("strategy_proposals") or ())
        ]
        self._strategy_learning_history = [
            dict(item)
            for item in (state.get("strategy_learning_history") or ())
        ]
        self.crediter.restore_assignments(state.get("credit_assignments") or ())
        self._resume_proposer_state = dict(state.get("proposer") or {})
        active = dict(state.get("active_strategy") or {})
        self._active_strategy_key = str(active.get("key") or "")
        self._active_strategy_family = str(active.get("family") or "")
        self._active_strategy_seeds = [
            str(value) for value in (active.get("seeds") or ())
        ]
        self._active_search_units = [
            dict(item) for item in (active.get("completed_search_units") or ())
        ]

    # ------------------------------------------------------------------ #
    # Source callbacks and provider-binding state.
    # ------------------------------------------------------------------ #
    def eligible_families(self) -> list[str]:
        """Pending families whose last instance ended by honest exhaustion."""

        pending = self.frontier.pending_by_family()
        return [
            family
            for family in pending
            if self._strategy_ends.get(family, END_EXHAUSTED) == END_EXHAUSTED
        ]

    def current_strategy_seed_queries(self) -> list[str]:
        seeds: list[str] = []
        for values in self._strategy_seed_queries.values():
            for seed in values:
                if seed not in seeds:
                    seeds.append(seed)
        return seeds

    def _declared_target_ids(self) -> AbstractSet[str]:
        ids: set[str] = set()
        for state in self.goal_states():
            catalog = state.get("target_catalog") if isinstance(state, Mapping) else None
            for key in ("fill_deficits", "unmet_count_targets", "count_targets"):
                for target in (catalog or {}).get(key) or []:
                    if isinstance(target, Mapping):
                        value = str(target.get("id") or target.get("target_id") or "")
                        if value:
                            ids.add(value)
        return ids

    def accepted_source_terms(self) -> list[str]:
        terms: list[str] = []
        for record in self._accepted_sources[-25:]:
            title = str(record.get("title") or "").strip()
            if title:
                terms.append(title)
        return terms

    def strategy_learning_history(self) -> tuple[Mapping[str, Any], ...]:
        """Completed strategy outcomes available to the next proposer.

        This is post-verdict memory. It can shape later query strings, but it
        cannot revise the completed strategy's credits, estimate, or verdict.
        """

        return tuple(dict(item) for item in self._strategy_learning_history)

    def _strategy_learning_observation(
        self,
        *,
        strategy_key: str,
        family: str,
        record: EpisodeRecord,
        volume_credit: Any = None,
    ) -> dict[str, Any]:
        """Compress one completed strategy into measured search feedback."""

        def observed(curve: Mapping[str, Any]) -> int:
            band = curve.get("observed_results")
            if not isinstance(band, Mapping):
                return 0
            return int(float(band.get("value") or 0))

        def labeled_facets(
            episode_record: EpisodeRecord,
        ) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for channel, estimate in episode_record.facets.items():
                if isinstance(estimate, Mapping):
                    value: Any = dict(estimate)
                elif hasattr(estimate, "as_record"):
                    value = estimate.as_record()
                else:
                    value = estimate
                out[
                    self.crediter.facet_labels.get(
                        str(channel), str(channel)
                    )
                ] = value
            return out

        search_units = {
            unit.child.scope_key: unit
            for unit in record.unit_records
            if unit.child is not None
        }
        skipped: Counter[str] = Counter()
        candidate_fates: Counter[str] = Counter()
        searches: list[dict[str, Any]] = []
        for outcome in self.last_search_outcomes:
            search_unit = search_units.get(outcome.task_id)
            search_record = search_unit.child if search_unit is not None else None
            skipped.update(outcome.skipped_by_reason)
            for candidate in outcome.candidate_source_outcomes:
                fate = str(candidate.get("fate") or "")
                if fate:
                    candidate_fates[fate] += 1
            searches.append(
                {
                    "query": outcome.query,
                    "provider_results": int(outcome.firecrawl_hits),
                    "processed_pages": int(
                        outcome.result_buffer.get("processed_results") or 0
                    ),
                    "unprocessed_pages": int(
                        outcome.result_buffer.get("unprocessed_results") or 0
                    ),
                    "sources_acquired": len(outcome.accepted_source_ids),
                    "duplicate_urls": len(set(outcome.duplicate_urls)),
                    "skipped_by_reason": dict(outcome.skipped_by_reason),
                    "error": str(outcome.error or ""),
                    "ended_by": (
                        search_record.ended_by if search_record is not None else ""
                    ),
                    "distinct_findings": (
                        observed(search_record.curve)
                        if search_record is not None
                        else 0
                    ),
                    "credit_occurrences": (
                        sum(
                            unit.yield_record.credits_observed
                            for unit in search_record.unit_records
                            if unit.yield_record.eligible
                        )
                        if search_record is not None
                        else 0
                    ),
                    "repeat_occurrences": (
                        sum(
                            len(unit.yield_record.repeat_identities)
                            for unit in search_record.unit_records
                            if unit.yield_record.eligible
                        )
                        if search_record is not None
                        else 0
                    ),
                    "incidence_estimate": (
                        dict(search_record.curve)
                        if search_record is not None
                        else {}
                    ),
                    "findings_by_column": (
                        labeled_facets(search_record)
                        if search_record is not None
                        else {}
                    ),
                    "volume_credit": (
                        search_unit.volume_credit.as_record()
                        if search_unit is not None
                        and search_unit.volume_credit is not None
                        else None
                    ),
                }
            )

        return {
            "strategy_key": strategy_key,
            "strategy_family": family,
            "seed_queries": list(
                self._strategy_seed_queries.get(strategy_key) or ()
            ),
            "ended_by": record.ended_by,
            "end_reason": record.end_reason,
            "searches_completed": int(record.units_consumed),
            "distinct_findings": observed(record.curve),
            "incidence_estimate": dict(record.curve),
            "findings_by_column": labeled_facets(record),
            "volume_credit": (
                volume_credit.as_record()
                if volume_credit is not None
                and hasattr(volume_credit, "as_record")
                else None
            ),
            "searches": searches,
            "totals": {
                "provider_results": sum(item["provider_results"] for item in searches),
                "processed_pages": sum(item["processed_pages"] for item in searches),
                "unprocessed_pages": sum(item["unprocessed_pages"] for item in searches),
                "sources_acquired": sum(item["sources_acquired"] for item in searches),
                "duplicate_urls": sum(item["duplicate_urls"] for item in searches),
                "distinct_findings": observed(record.curve),
                "credit_occurrences": sum(
                    item["credit_occurrences"] for item in searches
                ),
                "repeat_occurrences": sum(
                    item["repeat_occurrences"] for item in searches
                ),
                "skipped_by_reason": dict(skipped),
                "candidate_fates": dict(candidate_fates),
            },
            "acquired_source_titles": [
                str(source.get("title") or "").strip()
                for source in self._accepted_sources
                if str(source.get("title") or "").strip()
            ],
        }

    def _record_strategy_proposal(self, row: Mapping[str, Any]) -> None:
        self._strategy_proposals.append(dict(row))
        try:
            self.answers_dir.mkdir(parents=True, exist_ok=True)
            with (self.answers_dir / "strategy_proposals.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps(dict(row), default=str) + "\n")
        except OSError:  # recording never breaks the run
            pass

    def _note_search_results(
        self,
        task: SearchTask,
        results: Sequence[Mapping[str, Any]],
    ) -> None:
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            return
        outcome.firecrawl_hits = len(results)
        for rank, result in enumerate(results, start=1):
            outcome.search_result_observations.append(
                search_result_observation(dict(result), rank=rank)
            )

    def _note_search_error(
        self,
        task: SearchTask,
        exc: BaseException,
        fatal: bool,
    ) -> None:
        outcome = self._open_outcomes.get(task.id)
        if outcome is not None:
            outcome.error = str(exc)
            outcome.skip("search_failed")
        if fatal:
            self.set_search_provider_error(str(exc))
            print(f"  Search provider stopped the run: {exc}")

    def drain_strategy_sources(
        self,
        bootstrap_sources: Sequence[Mapping[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        records = [
            *(dict(record) for record in bootstrap_sources),
            *self._accepted_sources,
        ]
        self._accepted_sources = []
        return records

    def drain_followup_outcomes(self) -> list[SearchOutcome]:
        outcomes = self._pending_followup_outcomes
        self._pending_followup_outcomes = []
        return outcomes

    def reset_strategy_state(self) -> list[dict[str, Any]]:
        summaries = summarize_prompt_arms(self.last_search_outcomes)
        self.harvester.record_prompt_arm_summaries(summaries)
        self.last_search_outcomes.clear()
        self._page_guess_reports = []
        return summaries

    @property
    def page_guess_reports(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._page_guess_reports)

    # ------------------------------------------------------------------ #
    # Durable provider-binding records.
    # ------------------------------------------------------------------ #
    def _write_page_detail(
        self,
        unit: PageUnit,
        record: Any,
        material: PageMaterial,
        strategy_key: str,
        family: str,
    ) -> None:
        detail = unit.credit_detail
        row = {
            "unit_label": unit.label,
            "source_id": material.source_id,
            "task_id": str(unit.task.id),
            "strategy_key": strategy_key,
            "strategy_family": family,
            "rank": unit.rank,
            "episode_id": unit.episode_id,
            "episode_path": [list(segment) for segment in unit.episode_path],
            "fate": material.fate.to_dict(),
            "credit_note": material.fate.credit_note,
            "skip_reason": fate_skip_reason(material.fate),
            "counts_toward_verdict": bool(
                record.yield_record.counts_toward_verdict
            ),
            "numerical_snapshot_after": record.as_record().get(
                "numerical_snapshot_after", {}
            ),
            "spec_digest": self.crediter.spec_digest,
            "crediter_built_at_episode_id": self.run_episode_id,
            "credit_semantics": CREDIT_SEMANTICS,
            "text_chars": material.text_chars,
            "guess_count": len(material.guesses),
            "evidence_commit": (
                material.evidence_commit.to_dict()
                if material.evidence_commit is not None
                else None
            ),
            "evidence_commits": [
                commit.to_dict() for commit in material.evidence_commits
            ],
            "lexical_probes": [
                dict(item) for item in material.probe_history
            ],
            **(detail.to_dict() if detail is not None else {}),
        }
        self.acquisition_page_details.append(row)
        try:
            self.answers_dir.mkdir(parents=True, exist_ok=True)
            with self._page_detail_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, default=str) + "\n")
        except OSError:  # recording never breaks the run
            pass

    def write_episode_record(self, record: EpisodeRecord) -> None:
        if record.scope_level == STRATEGY_GRAIN.name:
            self._episode_records.append(window_episode_record(record.as_record()))
        try:
            self.answers_dir.mkdir(parents=True, exist_ok=True)
            self._episodes_path.write_text(
                json.dumps(
                    {
                        "policy_name": ACQUISITION_POLICY_NAME,
                        "credit_semantics": CREDIT_SEMANTICS,
                        "facet_gate": "crediting_active",
                        "declared_facets": list(self.crediter.declared_facets),
                        "spec_digest": self.crediter.spec_digest,
                        "grains": [
                            grain_disclosure(grain)
                            for grain in GRAIN_ORDER
                        ],
                        "strategies": self._episode_records,
                        "run": (
                            window_episode_record(
                                self.controller.record.as_record()
                            )
                            if self.controller.record is not None
                            else {}
                        ),
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        except OSError:  # recording never breaks the run
            pass

    def stranded_frontier_work(self) -> list[dict[str, Any]]:
        classes: list[dict[str, Any]] = []
        for family, tasks in self.frontier.pending_by_family().items():
            ended = self._strategy_ends.get(family, "")
            if ended == END_YIELD_STOP:
                reason = "abandoned_by_verdict"
            elif self.budget.exhausted:
                reason = "budget_spent"
            elif self.termination.stopped:
                reason = "run_terminated"
            elif ended == "":
                reason = "never_opened"
            else:
                reason = "frontier_exhausted"
            classes.append(
                {
                    "strategy_family": family,
                    "pending_tasks": len(tasks),
                    "class": reason,
                    "last_instance_ended_by": ended,
                    "run_termination_reason": self.termination.reason,
                    "instances_opened": (
                        self.proposer.instances_opened().get(family, 0)
                        if self.proposer is not None
                        else 0
                    ),
                }
            )
        return classes

    def write_acquisition_yield(self) -> None:
        path = self.answers_dir / "acquisition_yield.json"
        payload = self.controller.export()
        payload["stranded_frontier_work"] = self.stranded_frontier_work()
        payload["pages_pulled"] = self.budget.spent
        payload["pages_accepted"] = len(self.source_ingestion_ledger)
        payload["orphan_meter"] = dict(self.orphan_snapshot())
        payload["missing_token_owner"] = {
            "module": "criteria",
            "tokens": len(self.missing_tokens()),
        }
        payload["hook_failures"] = [dict(item) for item in self.hook_failures()]
        payload["criteria_projection_version"] = self.criteria_projection_version
        try:
            path.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - disclosed, never silent
            print(f"  [acquisition] yield export failed: {exc}")

    def run_summary(self) -> dict[str, Any]:
        details = self.acquisition_page_details
        chunk_counts: Counter = Counter()
        rule_counts: Counter = Counter()
        triviality_counts: Counter = Counter()
        source_kind_counts: Counter = Counter()
        counterfactual = 0
        no_credit_pages = 0
        subject_identities: set[str] = set()
        for row in details:
            chunks = row.get("chunk_encounters") or []
            chunk_counts[len(chunks)] += 1
            for attribution in row.get("attributions") or []:
                rule_counts[str(attribution.get("rule") or "")] += 1
                triviality_counts[
                    str(attribution.get("triviality_rule") or "")
                ] += 1
                source_kind_counts[
                    str(attribution.get("source_kind") or "")
                ] += 1
            counterfactual += len(row.get("counterfactual_credits") or [])
            for completion in row.get("row_completions") or []:
                subject_identities.add(str(completion.get("identity") or ""))
            if (
                row.get("counts_toward_verdict")
                and not (row.get("attributions") or [])
                and row.get("skip_reason") == ""
            ):
                no_credit_pages += 1

        exported_subjects = 0
        rows_by_table = self.exported_rows()
        for table, columns in self.crediter.basis.subject_key_columns.items():
            rows = rows_by_table.get(table) or []
            if columns:
                exported_subjects += len(
                    {
                        tuple(str(row.get(column, "")) for column in columns)
                        for row in rows
                        if isinstance(row, Mapping)
                    }
                )
        return {
            "credit_semantics": CREDIT_SEMANTICS,
            "criteria_projection_version": self.criteria_projection_version,
            "pages_pulled": self.budget.spent,
            "pages_with_detail": len(details),
            "credit_rule_counts": dict(rule_counts),
            "triviality_rule_counts": dict(triviality_counts),
            "credit_source_kind_counts": dict(source_kind_counts),
            "counterfactual_credit_count": counterfactual,
            "counterfactual_reading": (
                "the excluded columns could never have become datapoints, so an "
                "empty counterfactual means the exclusion had nothing to remove "
                "on this configuration and NEVER that it was unnecessary"
            ),
            "distinct_completed_subjects": len(subject_identities),
            "distinct_exported_subject_keys": exported_subjects,
            "subject_key_columns": {
                table: list(columns)
                for table, columns in self.crediter.basis.subject_key_columns.items()
            },
            "extracted_pages_with_no_credit": no_credit_pages,
            "chunk_counts": {str(k): v for k, v in sorted(chunk_counts.items())},
            "typed_credit_columns": sum(
                1
                for column in self.crediter.basis.columns
                if column.value_type or column.unit
            ),
            "page_best_guess": {"reports": list(self._page_guess_reports)},
            "proposer": dict(self.proposer.ledger) if self.proposer else {},
            "strategy_instances_opened": (
                self.proposer.instances_opened() if self.proposer else {}
            ),
            "strategy_proposals": list(self._strategy_proposals),
            "stranded_frontier_work": self.stranded_frontier_work(),
            "hook_failures": [dict(item) for item in self.hook_failures()],
            "search_provider_batch": dict(self.search_provider_batch),
        }
    "LEXICAL_PROBE_GRAIN",
    "PAGE_GRAIN",
