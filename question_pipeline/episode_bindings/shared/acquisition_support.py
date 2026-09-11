"""Reusable contracts and numerical support shared by episode bindings."""

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
    Episode,
    EpisodeRecord,
    EpisodeUpdate,
    EpisodeView,
    EpisodeTree,
    Grain,
    Leaf,
    ResumeUnit,
    SourceEnd,
    UnitRecord,
    UnitView,
)
from ...rarefaction import (
    OBSERVATION_EXCLUDED,
    OBSERVATION_FAILED,
    OBSERVATION_OBSERVED,
    ChannelSchema,
    ControlStep,
    ControllerConfig,
    IncidenceObservation,
    IncidenceState,
    bind_controller,
)
from ... import criteria
from ...control import select_first_clearing, stable_id
from ...costs import CostErrorClass, ObservationKind, classify_error
from ...evidence_registry import (
    AcceptedBestGuessCell,
    BestGuessAssertionCandidate,
    DirectAssertionCandidate,
    EvidenceCommit,
    SourceChunk,
    SourceDocument,
    SourceVersion,
    TextSpan,
)
from ...evidence_acceptance import EvidenceAcceptor
from ...table_specs import ColumnEvidenceRole
from ...tables import (
    ResultContract,
    ResultColumn,
    TableMutation,
    TypedTableStore,
    result_contract,
)
from ...search import (
    SearchFrontier,
    SearchHarvester,
    SearchOutcome,
    SearchTask,
    is_fatal_search_error,
    search_result_observation,
    summarize_prompt_arms,
)

ACQUISITION_POLICY_NAME = "acquisition_yield_v2"

#: Stamped on every emitted acquisition record. The module docstring's
#: separation, in the artifact a later reader actually opens.
CREDIT_SEMANTICS = "single_post_table_logical_slot_credit_v2"


# ==========================================================================
# The six grains -- the one place a policy is declared (charter rule 4)
# ==========================================================================

#: Per-search item policy. Firecrawl may return a provider-sized batch, but the
#: batch is only a buffer. After each one-page pull, the paired numerical
#: component predicts the next page's marginal hypervolume credit. Its upper
#: band must be zero for the declared streak before this policy stops.
DEFAULT_ITEM_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=4
)

#: Chunk policy inside one lexical probe. Replay calibration against 190
#: complete probe episodes places the expected-next-credit cutoff above the
#: zero-yield uncertainty floor while leaving the parent page Episode in
#: charge of proposing another probe over every unprocessed chunk.
DEFAULT_CHUNK_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.06, rho=0.0, streak_length=4
)

#: Lexical-probe policy inside one page.  Its unit is a completed ranking, so
#: it can be calibrated independently from both chunks and Firecrawl pages.
DEFAULT_PAGE_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=4
)

#: Table-query policy inside one detected source table. Its units are query
#: result sets, not chunks, and it owns separate estimator/controller state.
DEFAULT_TABLE_CONTROL = ControllerConfig.uniform(
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

RUN_GRAIN_NAME = "run"
STRATEGY_GRAIN_NAME = "strategy"
SEARCH_GRAIN_NAME = "search"
PAGE_GRAIN_NAME = "page"
TABLE_GRAIN_NAME = "table"
LEXICAL_PROBE_GRAIN_NAME = "lexical_probe"


def _acquisition_grains(
    channel_schema: ChannelSchema,
) -> tuple[tuple[Grain, ...], dict[str, ControllerConfig]]:
    declarations = (
        (
            RUN_GRAIN_NAME,
            "one completed strategy episode",
            "the binding-defined result returned by one completed strategy",
            DEFAULT_RUN_CONTROL,
        ),
        (
            STRATEGY_GRAIN_NAME,
            "one completed search episode of this strategy",
            "the binding-defined result returned by one completed search",
            DEFAULT_STRATEGY_CONTROL,
        ),
        (
            SEARCH_GRAIN_NAME,
            "one fetched and processed page or document from one result list",
            "the binding-defined result returned by that page",
            DEFAULT_ITEM_CONTROL,
        ),
        (
            PAGE_GRAIN_NAME,
            "one completed retrieval episode over one part of the page",
            "the binding-defined result returned by that table or lexical retrieval",
            DEFAULT_PAGE_CONTROL,
        ),
        (
            TABLE_GRAIN_NAME,
            "one deterministic query over one parsed source table",
            "the accepted result identities returned by that table query",
            DEFAULT_TABLE_CONTROL,
        ),
        (
            LEXICAL_PROBE_GRAIN_NAME,
            "one previously unprocessed chunk from the lexical ranking",
            "the binding-defined result returned by that chunk",
            DEFAULT_CHUNK_CONTROL,
        ),
    )
    grains = tuple(
        Grain(
            name=name,
            unit=unit,
            result=result,
            controller=bind_controller(
                channel_schema=channel_schema,
                control=control,
            ),
        )
        for name, unit, result, control in declarations
    )
    return grains, {name: control for name, _unit, _result, control in declarations}


def grain_disclosure(
    grain: Grain,
    control: ControllerConfig,
) -> dict[str, Any]:
    """One grain's numerical declaration for the durable record."""

    return {
        "name": grain.name,
        "unit": grain.unit,
        "result": grain.result,
        "controller": control.as_record(),
    }


def _incidence_state(record: EpisodeRecord) -> IncidenceState:
    state = record.controller_state
    if not isinstance(state, IncidenceState):
        raise TypeError(
            f"episode {record.episode_id!r} did not use the incidence controller"
        )
    return state


def _incidence_step(record: UnitRecord | UnitView) -> ControlStep:
    step = record.controller_step
    if not isinstance(step, ControlStep):
        raise TypeError("unit did not use the incidence controller")
    return step


def _incidence_input(value: object) -> IncidenceObservation:
    if not isinstance(value, IncidenceObservation):
        raise TypeError("unit did not provide an incidence observation")
    return value


def _episode_observation(record: EpisodeRecord) -> IncidenceObservation:
    observations = tuple(
        _incidence_input(unit.controller_input) for unit in record.unit_records
    )
    if record.ended_by not in (END_EXHAUSTED, END_YIELD_STOP):
        reason = f":{record.end_reason}" if record.end_reason else ""
        return IncidenceObservation.excluded(
            f"child ended {record.ended_by}{reason}; its trace is retained but "
            "it does not enter the parent's controller"
        )
    if observations and all(
        observation.status == OBSERVATION_FAILED
        for observation in observations
    ):
        return IncidenceObservation.failed(
            "child made no numerical judgement: every unit failed"
        )
    combined = IncidenceObservation.combine(observations)
    schema = _incidence_state(record).report.channel_schema
    if schema.union_channel is None:
        return combined
    return IncidenceObservation(
        identities=combined.identities,
        channels={
            channel: combined.channels.get(channel, ())
            for channel in schema.base_channels
        },
    )


def _restored_observation(item: Mapping[str, Any]) -> IncidenceObservation:
    counts = bool(item.get("counts_toward_verdict", True))
    active = bool(item.get("active", True))
    status = (
        OBSERVATION_OBSERVED
        if counts and active
        else OBSERVATION_FAILED
        if counts
        else OBSERVATION_EXCLUDED
    )
    return IncidenceObservation(
        identities=(
            tuple(item.get("credits") or ())
            if status == OBSERVATION_OBSERVED
            else ()
        ),
        status=status,
        note=str(item.get("note") or ""),
        channels=(
            {
                str(name): tuple(values)
                for name, values in dict(item.get("facets") or {}).items()
            }
            if status == OBSERVATION_OBSERVED
            else {}
        ),
    )


def _base_prompt_context(record: EpisodeRecord) -> dict[str, Any]:
    state = _incidence_state(record)
    observation = _episode_observation(record)
    return {
        "episode_id": record.episode_id,
        "grain": record.scope_level,
        "key": record.scope_key,
        "units_processed": record.units_consumed,
        "ended_by": record.ended_by,
        "end_reason": record.end_reason,
        "distinct_results": len(observation.identities),
        "results_by_channel": {
            name: len(values) for name, values in observation.channels.items()
        },
        "estimate": state.report.primary.as_record(),
        "verdict": state.verdict.as_record(),
    }


def _facet_estimates(state: IncidenceState) -> dict[str, Any]:
    schema = state.report.channel_schema
    if schema.union_channel is None:
        return {}
    return {
        channel: state.report.estimates[channel].as_record()
        for channel in schema.base_channels
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
    """Binding-local state shared by the child Episodes of one page."""

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
    table_units: list[Any] = field(default_factory=list)
    table_history: list[dict[str, Any]] = field(default_factory=list)
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
    table_history: Sequence[Mapping[str, Any]] = ()


@dataclass(frozen=True)
class PageEpisodeOutput:
    """The page data its parent needs, without the page's full trace."""

    unit: PageUnit
    material: PageMaterial


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

    def __call__(
        self,
        unit: PageUnit,
        material: PageMaterial,
    ) -> IncidenceObservation:
        """Project accepted table state into this binding's controller input."""

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
            return IncidenceObservation.failed(
                "no declared, deliverable contract columns exist; zero credits "
                "here means 'could not judge', not 'barren page'"
            )
        if not fate.judged:
            return IncidenceObservation.failed(fate.disclosure)

        identities = tuple(
            dict.fromkeys(item.identity for item in projected.attributions)
        )
        facets = self._facets(projected)
        return IncidenceObservation(identities=identities, channels=facets)

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
            and unit.episode_path[1][0] == STRATEGY_GRAIN_NAME
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
    state = _incidence_state(record)
    return AcquisitionDecision(
        policy_name=ACQUISITION_POLICY_NAME,
        decision_point=decision_point,
        scope_path=tuple(record.path),
        scope_key=record.scope_key,
        family=family,
        verdict=state.verdict.as_record(),
        curve=state.report.primary.as_record(),
        facets=_facet_estimates(state),
        controller=state.verdict.config.as_record(),
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
    controller_input = unit.get("controller_input")
    credits = (
        controller_input.get("identities")
        if isinstance(controller_input, Mapping)
        else None
    )
    if not isinstance(credits, list) or len(credits) <= PAGE_CREDIT_WINDOW:
        return unit
    head = PAGE_CREDIT_WINDOW // 2
    tail = PAGE_CREDIT_WINDOW - head
    omitted = len(credits) - PAGE_CREDIT_WINDOW
    controller_input = dict(controller_input)
    controller_input["identities"] = credits[:head] + credits[-tail:]
    unit["controller_input"] = controller_input
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

    It binds this surface's channel schema and thresholds into one controller
    function per grain. ``Context`` sees only those functions and their opaque
    inputs. Cost has one owner and it is ``costs.py``.
    """

    crediter: TableCreditAssigner
    budget: SourceBudget
    health: ProviderHealth = field(default_factory=ProviderHealth)
    termination: RunTermination = field(default_factory=RunTermination)

    def __post_init__(self) -> None:
        schema = self.crediter.channel_schema
        self.grains, self.grain_controls = _acquisition_grains(schema)
        self.grain_by_name = {grain.name: grain for grain in self.grains}
        self.context = Context(
            tree=EpisodeTree(
                root=self.grain_by_name[RUN_GRAIN_NAME],
                children={
                    self.grain_by_name[RUN_GRAIN_NAME]: (
                        self.grain_by_name[STRATEGY_GRAIN_NAME],
                    ),
                    self.grain_by_name[STRATEGY_GRAIN_NAME]: (
                        self.grain_by_name[SEARCH_GRAIN_NAME],
                    ),
                    self.grain_by_name[SEARCH_GRAIN_NAME]: (
                        self.grain_by_name[PAGE_GRAIN_NAME],
                    ),
                    self.grain_by_name[PAGE_GRAIN_NAME]: (
                        self.grain_by_name[TABLE_GRAIN_NAME],
                        self.grain_by_name[LEXICAL_PROBE_GRAIN_NAME],
                    ),
                },
            )
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

        run_state = (
            _incidence_state(self.record) if self.record is not None else None
        )
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
                grain_disclosure(grain, self.grain_controls[grain.name])
                for grain in self.grains
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
                    "final_verdict": run_state.verdict.as_record(),
                    "curve": run_state.report.primary.as_record(),
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

__all__ = tuple(name for name in globals() if not name.startswith("__"))
