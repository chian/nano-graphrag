"""The provider surface, re-stated as a composition of ``rarefaction.Episode``.

Chartered in ``docs/ACQUISITION_LOOP.md``; designed in
``experiments/log/4E-c-provider-composition.md``. The composition is

    run  (unit: one completed strategy episode)
     |__ strategy  (unit: one completed search episode)
          |__ search  (unit: one fetched page; the LEAF, never an episode)

and it runs on **one** ``Episode.run_async`` call. Nothing in this package
contains a ``for`` or ``while`` that pulls a unit, calls ``scoped.observe``,
reads a verdict, or keeps a per-scope list. The loop body is the kernel's, once,
in ``rarefaction.episode.Episode``.

What this module owns
---------------------

1. **The three grains**, each declared once with its unit and credit sentences.
   The run-start ``ColumnProjection`` supplies their one frozen generic channel
   schema before any scope opens. Their numerical controls are declared once
   and consume the same role-based estimate contract.
2. **The crediter**: a pure projection from one page's extracted material onto
   the declared contract columns, in two kinds (per-column values, and
   completed rows). It reads no curve and calls no model.
3. **The fate rule**: what a page's outcome means for ``(active,
   counts_toward_verdict)``, implemented once here and *called* by the
   surface's ``extract`` -- never re-derived by a second module.
4. **The sources**, one per grain, and the typed objects they read before a
   pull (a page budget, provider health, the run's terminal state).
5. **The controller**: it builds the context, the three episode declarations
   and the crediter, calls the kernel once, and writes ledger decisions from
   the emitted records. It consults nothing between units.

What a credit is NOT: a reward datapoint. The reward's standard -- verbatim or
an evidenced best guess, judged, with sources -- is unchanged and lives in
``reward.py``. An acquisition credit is the acquisition-control signal, "this
page carried a value shaped like a declared target column", used to decide
where further fetching is still yielding. Conflating the two would let
operational volume buy reward, which is banned.

**And the two cannot be joined, by construction.** A kind-1 identity is
``table|column|normalized value`` -- it *contains a value*, which a criterion id
deliberately excludes ("A criterion is the *question*, not the answer to it",
``criteria.py``). A kind-2 identity spells the subject as ``col=value`` pairs
while a criterion's subject is a hash. Nothing joins in either direction, and
that is correct. **The one honest join is ``source_id``**, on both sides: a
later phase asking "did the pages this strategy fetched produce datapoints"
joins page source ids to ``reward``'s ``crediting_source_ids`` and to nothing
else. No reward component may read a credit identity, a facet estimate, an
``observed_results`` band, a Q1/Q2 pair, or a Chao2 estimate; and no component may
join ``(table, column)`` to ``(table, field)`` by text, with or without a value
comparison. Credits join by stable ids, never by matching text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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

from rarefaction import (
    END_BOUND_HIT,
    END_EXHAUSTED,
    END_SOURCE_FAILED,
    Context,
    ChannelSchema,
    ControllerConfig,
    CreditResult,
    Episode,
    EpisodeRecord,
    EpisodeView,
    Grain,
    Leaf,
    SourceEnd,
)

from . import criteria
from .control import select_first_clearing, stable_id
from .costs import CostErrorClass, ObservationKind, classify_error
from .provenance import is_provenance_name

__all__ = [
    "ACQUISITION_POLICY_NAME",
    "CHUNK_GRAIN_DISCLOSURE",
    "CREDIT_SEMANTICS",
    "DEFAULT_ITEM_CONTROL",
    "DEFAULT_RUN_CONTROL",
    "DEFAULT_STRATEGY_CONTROL",
    "GATE_BELOW",
    "GATE_CLEARED",
    "GATE_FAILED_OPEN",
    "GATE_NOT_RUN",
    "GATE_UNSCORED",
    "MAX_PROPOSAL_SAMPLES",
    "PAGE_CREDIT_WINDOW",
    "REJECT_OPERATOR_NOT_IN_CATALOG",
    "RELEVANCE_SCORE_FLOOR",
    "RUN_GRAIN",
    "SEARCH_GRAIN",
    "STRATEGY_DISTANCE_FLOOR",
    "STRATEGY_GRAIN",
    "AcquisitionController",
    "AcquisitionDecision",
    "ColumnProjection",
    "CreditAttribution",
    "CreditColumn",
    "GrainDisclosure",
    "PageCredit",
    "PageMaterial",
    "PageSource",
    "PageUnit",
    "ProviderHealth",
    "RunTermination",
    "SourceBudget",
    "StrategyProposer",
    "StrategySearches",
    "declared_credit_columns",
    "join_costs",
    "page_clears_relevance",
    "page_fate",
    "window_episode_record",
]

ACQUISITION_POLICY_NAME = "acquisition_yield_v2"

#: Stamped on every emitted acquisition record. The module docstring's
#: separation, in the artifact a later reader actually opens.
CREDIT_SEMANTICS = "acquisition_control_signal_not_reward_datapoint"


# ==========================================================================
# The three grains -- the one place a policy is declared (charter rule 4)
# ==========================================================================

# These three policies belong only to the retained legacy live controller.
# They remain byte-for-byte available until 4G-b removes that path atomically;
# they are not a second or future target method.

#: Per-search item policy: stop pulling pages from one search's result list
#: when the posterior says fewer than 1 in 4 further pages would credit anything
#: new, at 95% certainty, never before 4 pages. Firecrawl may return a
#: provider-sized batch, but the batch is only a buffer: this rule is the
#: numerical processing stop and is consulted after every one-page pull.
#: ``searches_to_stop`` puts the all-barren firing point at 10 units, and
#: ``min_observations`` moves that crossing at no value this build uses -- it
#: only sets a floor below which the posterior branch is unreachable.
DEFAULT_ITEM_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=4
)

#: Strategy-grain policy (unit = one completed search). All-barren crossing 10:
#: inert until a strategy closes ten barren searches. No number here is changed
#: to make a verdict fire -- reachability is bought with observations, never by
#: moving a threshold.
DEFAULT_STRATEGY_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=8
)

#: Run-grain policy (unit = one completed strategy). All-barren crossing 10, so
#: the verdict is unreachable on any run whose strategy budget is under ten --
#: which is every configuration this build's provider credit can buy. That
#: inertness is REGISTERED with the arithmetic that makes it inert rather than
#: reached by lowering the policy: a threshold fitted to make its own mechanism
#: visible stops being a decision and becomes a constant wearing one's clothes.
DEFAULT_RUN_CONTROL = ControllerConfig.uniform(
    ("overall",), gamma=0.0, rho=0.0, streak_length=8
)

SEARCH_GRAIN = Grain(
    name="search",
    unit=(
        "one fetched page or document from this search's result list: the page "
        "is acquired, gated, and extracted before the next one is pulled"
    ),
    credit=(
        "one non-trivial value for a declared, deliverable, non-key contract "
        "column, or one completed row of a declared table"
    ),
    control=DEFAULT_ITEM_CONTROL,
)

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
GRAIN_ORDER = (RUN_GRAIN, STRATEGY_GRAIN, SEARCH_GRAIN)


@dataclass(frozen=True)
class GrainDisclosure:
    """A grain named and derived, but deliberately NOT bound.

    A distinct type, not a :class:`~rarefaction.Grain`: a ``Grain`` carries a
    ``ControllerConfig`` and ``Context.enter`` would open a scope from it. This
    carries no controller, no estimator state and no verdict, and nothing in the kernel can
    consume it. It exists so the charter's innermost row is unbound *and says
    so*, which is the pattern the charter itself uses for the GASL depth step.

    **OWNED BY THIS MODULE.** The GASL depth step's own disclosure is not
    required to use it -- that surface may say the same thing its own way -- and
    a second surface that genuinely needs this type lifts it into
    ``rarefaction/`` rather than importing it from here. Two surfaces disclosing
    different objects is not a duplicated owner; two surfaces importing one
    provider-surface type would make this module a dependency of a surface that
    has nothing to do with providers.
    """

    name: str
    unit: str
    credit: str
    bound: bool
    bound_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "credit": self.credit,
            "bound": self.bound,
            "bound_reason": self.bound_reason,
        }


CHUNK_GRAIN_DISCLOSURE = GrainDisclosure(
    name="chunk",
    unit=(
        "one chunk of one fetched page's reduced text, as extraction.chunk_text "
        "splits it at the run's chunk_size and overlap"
    ),
    credit=(
        "one non-trivial value for a declared credit column, or one completed "
        "row, present in that chunk's own extraction output before cross-chunk "
        "entity merging"
    ),
    bound=False,
    bound_reason=(
        "credits are minted per page from all of its chunks "
        "(docs/ACQUISITION_LOOP.md); extraction merges entities across chunks "
        "and a merged entity keeps the first chunk's attributes, so a per-chunk "
        "crediter can never observe a completed row and the chartered "
        "row-completeness credit kind would exist nowhere. Binding it would "
        "also serialize extraction's per-chunk concurrency. Per-chunk counts "
        "are emitted as disclosure and a chunk-grain verdict is replayed "
        "offline from them, so a later phase binds this on measurement."
    ),
)


def grain_disclosure(grain: Grain) -> dict[str, Any]:
    """One grain's declaration plus its all-barren crossing, for the record.

    The crossing is emitted beside ``units_consumed`` so "3 observations against
    a crossing of 10" is one line rather than an analyzer step, and so a reader
    can see inertness without recomputing it.
    """

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
BOUND_KIND_RUN_ROUND_BUDGET = "run_round_budget"
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
    "round_budget_exhausted": (END_BOUND_HIT, BOUND_KIND_RUN_ROUND_BUDGET),
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
    every **pulled** page, not every accepted one: under the fate table a page
    the gate refused is still a unit that cost a fetch and a gate call, and a
    budget that charged only acceptances would let a run pull unlimited refused
    pages for free, leaving the stop rule's denominator unbounded.
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
# The page gate's rule -- one implementation, called from `extract`
# ==========================================================================

#: The gate on whether a fetched page is extracted. A page whose reported
#: specificity clears this floor is extracted; one below it is a judged unit
#: that carried nothing.
#:
#: NO MEASUREMENT JUSTIFIES 0.5. It is the midpoint of the [0,1] scale the
#: prompt declares and `_optional_score` clamps to -- chosen because it is the
#: scale's own midpoint rather than fitted to any observation -- and it is
#: registered as an instrument parameter that can move a result, with every
#: page's reported score emitted so a later phase can set it from data. It is a
#: module constant and NOT a `PipelineConfig` knob: a config knob on a threshold
#: invites re-running until the direction flips.
#:
#: A LATER PHASE SETS IT FROM A BLIND RE-DERIVATION, NEVER FROM THE EMITTED
#: DISTRIBUTION ALONE. `evidence-verifier` re-derives from a source chunk
#: whether a page carries a value at the grain of a declared column, without
#: seeing what the pipeline concluded; that measures this score against
#: something other than the model. "Set it from data" using only the emitted
#: histogram decays into moving it until the below-floor count looks right,
#: which is fitting to a number with no referent.
RELEVANCE_SCORE_FLOOR = 0.5

GATE_CLEARED = "cleared"
GATE_BELOW = "below_floor"
GATE_UNSCORED = "unscored"
GATE_FAILED_OPEN = "failed_open"
GATE_NOT_RUN = "not_run"


def page_clears_relevance(
    score: float | None,
    *,
    floor: float = RELEVANCE_SCORE_FLOOR,
) -> tuple[bool, str]:
    """Whether this page is extracted, and the class label saying why.

    Pure: one comparison and one three-way class, recomputable offline from the
    emitted per-page record. ``None`` is NOT zero -- it is
    :data:`GATE_UNSCORED`, and it **fails open**, which is the policy this tree
    already applies when the gate call raises ("relevance gating should not drop
    evidence on LLM failure"). Failing closed would drop evidence on a JSON
    error, and a stream of parse failures would read as a search producing
    nothing.

    THE MODEL IS NOT ON THIS BRANCH. It reports a number whose definition
    predates this design; this comparison decides what the number means for the
    loop. It emits no label, and the prompt that produced the number names no
    gate, no decision word and no consequence -- a model told a gate exists has
    been handed the rule back and will encode its verdict into the float.
    """

    if score is None:
        return True, GATE_UNSCORED
    try:
        value = float(score)
    except (TypeError, ValueError):
        return True, GATE_UNSCORED
    if value >= float(floor):
        return True, GATE_CLEARED
    return False, GATE_BELOW


# ==========================================================================
# The fate table -- a PAIR of axes, so it partitions
# ==========================================================================

#: Mechanical outcomes reached before the gate. First match in this order wins,
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

PRE_GATE_FATES = (
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
    """One page's outcome on both axes, and what the kernel makes of it.

    TWO AXES, NOT ONE FIRST-MATCH LIST. A gate outcome and an extraction outcome
    are independent facts about a page: a gate-off page can still fail
    extraction, and a first-match ordering over a single list either hides that
    or makes the classes overlap -- and ``credit_note`` is a counted class
    label, so overlapping classes make its counts uninterpretable. Each axis is
    itself a partition, so the pair is one.
    """

    #: One of :data:`PRE_GATE_FATES`, or ``""`` when the page reached the gate.
    mechanical: str = ""
    #: One of the ``GATE_*`` labels, or ``""`` when a mechanical fate preempted.
    gate: str = ""
    #: One of the ``EXTRACT_*`` labels, or ``""`` likewise.
    extraction: str = ""
    #: The classified error, for the two classified mechanical rows and for a
    #: raised extraction. A class label from `costs.classify_error`, never prose.
    error_class: str = ""
    #: Why no gate score arrived, when ``gate`` is :data:`GATE_UNSCORED`.
    score_reason: str = ""

    @property
    def credit_note(self) -> str:
        """The counted class label. Composed from both axes, never prose."""

        if self.mechanical:
            if self.error_class:
                return f"not_judged:{self.mechanical}:{self.error_class}"
            return f"not_judged:{self.mechanical}"
        gate = self.gate or GATE_NOT_RUN
        if gate == GATE_UNSCORED and self.score_reason:
            gate = f"{gate}:{self.score_reason}"
        elif gate == GATE_FAILED_OPEN and self.error_class:
            gate = f"{gate}:{self.error_class}"
        extraction = self.extraction or EXTRACT_NOT_RUN
        if extraction == EXTRACT_RAISED and self.error_class:
            extraction = f"{extraction}:{self.error_class}"
        return f"gate:{gate}|extract:{extraction}"

    @property
    def judged(self) -> bool:
        """Whether this page is evidence about the search's yield.

        A mechanical skip is a fact about a URL and stays out. A page the gate
        refused IS a judged unit carrying nothing -- that is precisely the
        observation the search-grain rule is about, and excluding it would let a
        strict gate hold a barren search open indefinitely because the search
        could never accumulate the barren evidence that would end it. An
        extraction that raised, or one whose every chunk failed, is an
        instrument failure and stays out.
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
            "gate": self.gate,
            "extraction": self.extraction,
            "error_class": self.error_class,
            "score_reason": self.score_reason,
            "credit_note": self.credit_note,
            "judged": self.judged,
        }


#: Fate -> the reason a page contributes to ``SearchOutcome.skipped_by_reason``.
#: DECLARED ONCE, HERE, beside the fate rule, under the same single-owner clause
#: as the fate mapping itself: no consumer re-derives it by matching class-label
#: strings, because arm penalties and arm provenance are read from declared
#: fields and never reconstructed from wording.
#:
#: ``GATE_BELOW`` maps to ``not_relevant`` deliberately, and the choice is a
#: registered change rather than an emergent one. ``not_relevant`` is the sole
#: producer of ``search_memory``'s ``off_axis_count``, which is one of three
#: penalty terms on an arm's score and the whole of the ``off_axis`` outcome
#: class that routes ``off_axis_dominant -> target_terminology_swap``. The
#: producer this phase deletes is the model's accept/reject label; mapping the
#: floor's refusal onto the same reason keeps that axis alive, and "the reported
#: specificity for the declared columns was below the floor" is a closer match
#: to "this arm drifted off axis" than a model's decision word was. Retiring one
#: of the four named classes of the pseudo-gradient inside a phase that never
#: set out to change it is the emergent removal this mapping exists to avoid.
#:
#: THE POPULATION CHANGES AND THE DIRECTION IS NOT PREDICTED. How many pages
#: fall below 0.5 relative to how many the label rejected is not knowable
#: without running it, and no prior run may be replayed to guess it. The
#: per-arm ``off_axis_count`` distribution and the count of arms classed
#: ``off_axis`` are emitted per strategy attempt, two-sided: zero across the run
#: means the branch was inert on this configuration and that is reported as the
#: finding -- which is the only way "the branch never fired" can be told from
#: "the branch no longer exists".
FATE_SKIP_REASONS: dict[str, str] = {
    FATE_DUPLICATE_URL: "duplicate_url",
    FATE_FETCH_FAILED: "fetch_failed",
    FATE_BLOCKED_PAGE: "blocked_page",
    FATE_TOO_SHORT: "too_short",
    FATE_TOO_LARGE: "too_large",
    FATE_NO_EXTRACTOR: "no_extractor",
    FATE_NO_CREDIT_COLUMNS: "no_credit_columns",
    GATE_BELOW: "not_relevant",
    EXTRACT_RAISED: "extract_failed",
    EXTRACT_ALL_CHUNKS_FAILED: "extract_all_chunks_failed",
}


def fate_skip_reason(fate: PageFate) -> str:
    """What this page adds to ``SearchOutcome.skipped_by_reason``, or ``""``."""

    if fate.mechanical:
        return FATE_SKIP_REASONS.get(fate.mechanical, "")
    if fate.gate == GATE_BELOW:
        return FATE_SKIP_REASONS[GATE_BELOW]
    return FATE_SKIP_REASONS.get(fate.extraction, "")


def page_fate(
    *,
    mechanical: str = "",
    gate: str = "",
    extraction: str = "",
    error_class: str = "",
    score_reason: str = "",
) -> PageFate:
    """Mint one page's fate. The only constructor callers use.

    ``pipeline`` returns ``PageMaterial`` facts and mints no fate: two modules
    holding opinions about what a fate means is how a model's boolean ended up
    on ``CreditResult.active`` in the first place.
    """

    if mechanical and mechanical not in PRE_GATE_FATES:
        raise ValueError(f"{mechanical!r} is not a declared pre-gate fate")
    return PageFate(
        mechanical=mechanical,
        gate=gate,
        extraction=extraction,
        error_class=error_class,
        score_reason=score_reason,
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
    round_index: int
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
        self.credit_detail = detail


@dataclass(frozen=True)
class PageMaterial:
    """What ``extract`` returns. Facts only -- no ``active`` flag, no fate.

    ``records`` are the extracted records the crediter iterates, each
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
    paper: Optional[Mapping[str, Any]] = None
    ingestion: Mapping[str, Any] = field(default_factory=dict)
    relevance: Optional[Mapping[str, Any]] = None
    reduction: Mapping[str, Any] = field(default_factory=dict)
    #: The gate's recorded facts: score, floor, rule, outcome, reason class,
    #: window count, every window's own score, and which window decided. Route 2
    #: recomputes the fate offline from these, and a later phase reads the
    #: distribution to set the floor.
    gate: Mapping[str, Any] = field(default_factory=dict)
    #: Per-chunk encounters, including whether each chunk's extraction FAILED --
    #: so a chunk-grain replay cannot read an instrument failure as barrenness.
    chunks: Sequence[Mapping[str, Any]] = ()
    #: Model calls and their cost belong to the SOURCE scope this ran inside.
    text_chars: int = 0


# ==========================================================================
# The credit basis -- one owner, and the exclusion is disclosed by class
# ==========================================================================

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NAME_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")

RULE_DECLARED_NAME = "declared_name"
RULE_DECLARED_ALIAS = "declared_alias"
RULE_TOKEN_OVERLAP = "token_overlap"

SOURCE_KIND_VERBATIM = "verbatim"
SOURCE_KIND_BEST_GUESS = "best_guess"


def _tokens(name: Any) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(str(name or "").lower()))


def _normalize_name(name: Any) -> str:
    return _NAME_NORMALIZE_RE.sub("_", str(name or "").lower()).strip("_")


@dataclass(frozen=True)
class CreditColumn:
    """One declared target column, with everything a consumer needs of it.

    Carries the declared fields as well as the matching keys so the ONE
    selection of columns lives here: the gate's contract block renders from this
    object and never goes back to the spec to re-select, which would be a second
    column-selection rule at the renderer.
    """

    table: str
    column: str
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
    """The declared credit columns, the exclusions, and the subject keys.

    ONE PASS, ONE MATCHER, TWO COLUMN SETS. The counterfactual ledger the run
    emits -- what 4C's wider basis *would* have credited -- is computed from
    :attr:`counterfactual` here, not from a second ``declared_credit_columns``
    kept alive to be deliberately wrong. Two implementations of the basis, one
    of them intentionally weaker, is a second owner however it is labelled; and
    a differential computed by a second matcher would be attributable to the
    second matcher rather than to the exclusion it exists to measure.
    """

    columns: tuple[CreditColumn, ...]
    excluded: tuple[ExcludedColumn, ...]
    #: Columns excluded by the criteria predicate that 4C's weaker basis would
    #: have credited: declared, deliverable, non-key, non-provenance columns
    #: that `criteria.is_datapoint_field` refuses.
    counterfactual: tuple[CreditColumn, ...]
    subject_key_columns: Mapping[str, tuple[str, ...]]
    #: The identity-excluded columns, built by the SAME pass that excludes them,
    #: so a declared `value_type`/`unit` on a key column survives its exclusion.
    #: A key column is in neither `columns` nor `counterfactual` -- it is
    #: excluded before either list is built -- so without this the row-credit
    #: rule would check every subject key with an empty type, which is the
    #: permissive direction: "non-empty and not missing" instead of the declared
    #: type's own admission test.
    key_columns: tuple[CreditColumn, ...]
    tables: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": [
                {
                    "table": column.table,
                    "column": column.column,
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
            "counterfactual_columns": [
                {"table": column.table, "column": column.column}
                for column in self.counterfactual
            ],
            "subject_key_columns": {
                table: list(columns)
                for table, columns in self.subject_key_columns.items()
            },
            "key_columns": [
                {
                    "table": column.table,
                    "column": column.column,
                    "value_type": column.value_type,
                    "unit": column.unit,
                }
                for column in self.key_columns
            ],
            "typed_column_count": sum(
                1 for column in self.columns if column.value_type or column.unit
            ),
            # Counted separately because `typed_column_count` counts the credit
            # basis only: a declared type carried on a KEY column would not
            # show there, and its silent loss is what this pair makes legible.
            "typed_key_column_count": sum(
                1 for column in self.key_columns if column.value_type or column.unit
            ),
        }


def declared_credit_columns(table_spec: Any) -> tuple[CreditColumn, ...]:
    """The columns whose values count as acquisition credits.

    Kept as the package's public name for the basis; :func:`credit_basis`
    returns the same computation with its exclusions and its counterfactual set
    attached.
    """

    return credit_basis(table_spec).columns


def credit_basis(table_spec: Any) -> CreditBasis:
    """Compute the credit basis, its exclusions, and its counterfactual, once.

    Declared, deliverable, non-key, non-provenance contract columns that
    ``criteria`` agrees are datapoints.

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

    columns: list[CreditColumn] = []
    excluded: list[ExcludedColumn] = []
    counterfactual: list[CreditColumn] = []
    key_columns: list[CreditColumn] = []
    subject_keys: dict[str, tuple[str, ...]] = {}
    tables: list[str] = []
    spec_tables = getattr(table_spec, "tables", None) or {}
    for table_name, table in spec_tables.items():
        if not getattr(table, "deliverable", True):
            continue
        name = str(table_name)
        tables.append(name)
        subject_keys[name] = tuple(
            str(column)
            for column in (getattr(table, "subject_key_columns", ()) or ())
        )
        keys = {str(k) for k in (getattr(table, "key_columns", ()) or ())}
        keys |= set(subject_keys[name])
        for column in table.all_columns():
            column_name = str(column.name)
            built = _credit_column(name, column)
            if column_name in keys:
                excluded.append(
                    ExcludedColumn(name, column_name, "identity")
                )
                # EXCLUDED FROM THE BASIS, NOT FORGOTTEN. A key column mints no
                # credit, but the row-completeness rule still tests its value,
                # and it tests it against the column's DECLARED type. Carrying
                # the built column here is what keeps that test at the declared
                # standard instead of the permissive fallback.
                if built is not None:
                    key_columns.append(built)
                continue
            exclusion = criteria.datapoint_exclusion_class(column_name)
            if exclusion:
                excluded.append(ExcludedColumn(name, column_name, exclusion))
                # THE COUNTERFACTUAL SET, PARTITIONED OUT OF THIS ONE PASS.
                # The weaker basis this replaced excluded identity columns and
                # the provenance NAME SHAPE and nothing else, so what the
                # criteria-owned basis actually removed is the columns it
                # refuses that the provenance shape does not. That predicate is
                # named here once, to *partition an exclusion list this pass
                # already computed* -- it selects no column and mints no basis,
                # so there is no second `declared_credit_columns` kept alive to
                # be deliberately wrong, which would be a second owner however
                # it was labelled.
                if built is not None and not is_provenance_name(column_name):
                    counterfactual.append(built)
                continue
            if built is not None:
                columns.append(built)
    return CreditBasis(
        columns=tuple(columns),
        excluded=tuple(excluded),
        counterfactual=tuple(counterfactual),
        subject_key_columns=subject_keys,
        key_columns=tuple(key_columns),
        tables=tuple(tables),
    )


def _credit_column(table: str, column: Any) -> Optional[CreditColumn]:
    name = str(column.name)
    aliases = tuple(str(a) for a in (getattr(column, "aliases", ()) or ()))
    names = [name, *aliases]
    token_keys = tuple(dict.fromkeys(_tokens(item) for item in names if _tokens(item)))
    if not token_keys:
        return None
    return CreditColumn(
        table=table,
        column=name,
        token_keys=token_keys,
        normalized_names=(_normalize_name(name),),
        normalized_aliases=tuple(
            dict.fromkeys(_normalize_name(alias) for alias in aliases if alias)
        ),
        aliases=aliases,
        description=str(getattr(column, "description", "") or ""),
        value_type=str(getattr(column, "value_type", "") or ""),
        unit=str(getattr(column, "unit", "") or ""),
    )


# ==========================================================================
# The crediter
# ==========================================================================


@dataclass(frozen=True)
class CreditAttribution:
    """One mint occurrence of one credit identity.

    KEPT PER MINT, NEVER DEDUPED TO THE IDENTITY. When the verbatim pass and the
    page-scoped guess pass both produce one identity, both ``source_kind``s
    survive in the record; deduping would make the verbatim/guessed split an
    artifact of which pass happened to run second. The credit *identity* still
    dedupes -- one identity space, one new credit -- so the attribution count
    and the credit count differ, and the emitted record says why.
    """

    identity: str
    table: str
    column: str
    field: str
    rule: str
    triviality_rule: str
    source_kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "table": self.table,
            "column": self.column,
            "field": self.field,
            "rule": self.rule,
            "triviality_rule": self.triviality_rule,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True)
class RowCreditDetail:
    """One row-completeness credit, and what each of its columns cost.

    ``columns_best_guess`` is the half that makes the second curve honest: a
    ``table|subject_key`` identity minted with twelve of thirteen columns
    guessed is not "the search is producing whole answers", and neither an
    inertness reason nor a blocked reason distinguishes it from a row the
    sources stated. NO RULE READS THE SPLIT -- it is counted and recorded.
    """

    identity: str
    table: str
    columns_verbatim: tuple[str, ...]
    columns_best_guess: tuple[str, ...]
    declared_total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "table": self.table,
            "columns_verbatim": list(self.columns_verbatim),
            "columns_best_guess": list(self.columns_best_guess),
            "declared_total": self.declared_total,
        }


@dataclass(frozen=True)
class CounterfactualCredit:
    """An identity 4C's wider basis would have minted and this one does not."""

    identity: str
    table: str
    column: str
    exclusion_class: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "table": self.table,
            "column": self.column,
            "class": self.exclusion_class,
        }


@dataclass(frozen=True)
class CreditIdentities:
    """One projection's whole output, before it becomes a ``CreditResult``."""

    attributions: tuple[CreditAttribution, ...] = ()
    row_credits: tuple[RowCreditDetail, ...] = ()
    row_credit_blocked: tuple[str, ...] = ()
    row_credit_max_columns_covered: int = 0
    counterfactual: tuple[CounterfactualCredit, ...] = ()

    @property
    def identities(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for attribution in self.attributions:
            seen.setdefault(attribution.identity, None)
        for row in self.row_credits:
            seen.setdefault(row.identity, None)
        return tuple(seen)


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
    row_credits: tuple[RowCreditDetail, ...]
    row_credit_blocked: tuple[str, ...]
    row_credit_inert: Mapping[str, str]
    row_credit_max_columns_covered: int
    counterfactual: tuple[CounterfactualCredit, ...]
    declared_facets: tuple[str, ...]
    chunk_encounters: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributions": [item.to_dict() for item in self.attributions],
            "row_credits": [item.to_dict() for item in self.row_credits],
            "row_credit_blocked": list(self.row_credit_blocked),
            "row_credit_inert_reason": dict(self.row_credit_inert),
            "row_credit_max_columns_covered": self.row_credit_max_columns_covered,
            "counterfactual_credits": [
                item.to_dict() for item in self.counterfactual
            ],
            "declared_facets": list(self.declared_facets),
            "chunk_encounters": [dict(item) for item in self.chunk_encounters],
        }


class ColumnProjection:
    """The what-counts rule: extracted material -> declared contract columns.

    Deterministic. No model, no curve, no instance state that a page could
    leave behind: :meth:`identities` is pure and the per-page counters live in
    the caller's closure, because ``extract`` now calls this object and a memo
    here would make ``extract``'s behaviour depend on ``credit``'s.

    CONSTRUCTED ONCE PER RUN, with two consequences stated rather than left to a
    run to discover: a column the planner adds to the observed spec mid-run
    never credits, and the declared facet set is fixed at run start. The digest
    of the spec it was built from is emitted on every record, so a mid-run spec
    rewrite is legible against a denominator that did not move.
    """

    def __init__(self, table_spec: Any) -> None:
        self._basis = credit_basis(table_spec)
        self._by_table: dict[str, list[CreditColumn]] = {}
        for column in self._basis.columns:
            self._by_table.setdefault(column.table, []).append(column)
        self._counterfactual_by_table: dict[str, list[CreditColumn]] = {}
        for column in self._basis.counterfactual:
            self._counterfactual_by_table.setdefault(column.table, []).append(column)
        self._row_inert: dict[str, str] = {}
        for table in self._basis.tables:
            if not self._basis.subject_key_columns.get(table):
                self._row_inert[table] = (
                    "table declares no subject_key_columns, so no row-completeness "
                    "credit can be minted for it; a flat curve here means 'no "
                    "credit could be minted', not 'no page completed a row'"
                )
            elif not self._by_table.get(table):
                self._row_inert[table] = (
                    "table declares no non-key credit columns, so its "
                    "row-completeness conjunction is over an empty set"
                )
        self._declared_facets = tuple(
            [f"{column.table}|{column.column}" for column in self._basis.columns]
            + [f"{table}|rows" for table in self._basis.tables]
        )
        self._channel_schema = (
            ChannelSchema.partition(self._declared_facets)
            if self._declared_facets
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
    def channel_schema(self) -> ChannelSchema:
        return self._channel_schema

    @property
    def spec_digest(self) -> str:
        return self._spec_digest

    @property
    def row_credit_inert(self) -> Mapping[str, str]:
        return dict(self._row_inert)

    def columns_by_table(self) -> dict[str, list[str]]:
        return {
            table: [column.column for column in columns]
            for table, columns in self._by_table.items()
        }

    # ------------------------------------------------------------------ #
    # the projection
    # ------------------------------------------------------------------ #
    def identities(
        self,
        records: Sequence[Mapping[str, Any]],
        guesses: Sequence[Mapping[str, Any]] = (),
    ) -> CreditIdentities:
        """Project extracted records onto the declared columns. Pure.

        ``records`` are per-extracted-record ``{"table", "index", "values"}``
        mappings; ``guesses`` are best-guess resolutions in the shape
        ``criteria`` reads. Both passes mint into ONE identity space, so a guess
        reproducing a value the page already stated is a repeat encounter rather
        than a second credit -- without which the same value counts twice and
        every curve above it inflates.
        """

        attributions: list[CreditAttribution] = []
        row_credits: list[RowCreditDetail] = []
        blocked: list[str] = []
        counterfactual: list[CounterfactualCredit] = []
        max_covered = 0

        guessed_by_record = self._guessed_values(guesses)

        for position, record in enumerate(records):
            if not isinstance(record, Mapping):
                continue
            table = str(record.get("table") or "")
            values = record.get("values")
            if not isinstance(values, Mapping):
                continue
            index = record.get("index")
            index = int(index) if isinstance(index, int) else position
            columns = self._by_table.get(table) or ()
            guessed = guessed_by_record.get((table, index), {})

            covered_verbatim: dict[str, str] = {}
            for field_name, value in _iter_fields(values):
                match = self._match(field_name, columns)
                if match is None:
                    continue
                column, rule = match
                admitted = self._non_trivial(value, column)
                if admitted is None:
                    continue
                normalized, triviality_rule = admitted
                identity = f"{column.table}|{column.column}|{normalized}"
                attributions.append(
                    CreditAttribution(
                        identity=identity,
                        table=column.table,
                        column=column.column,
                        field=str(field_name),
                        rule=rule,
                        triviality_rule=triviality_rule,
                        source_kind=SOURCE_KIND_VERBATIM,
                    )
                )
                covered_verbatim.setdefault(column.column, normalized)

            covered_guessed: dict[str, str] = {}
            for column_name, value in guessed.items():
                if column_name in covered_verbatim:
                    continue
                column = self._column(table, column_name)
                if column is None:
                    continue
                admitted = self._non_trivial(value, column)
                if admitted is None:
                    continue
                normalized, triviality_rule = admitted
                identity = f"{column.table}|{column.column}|{normalized}"
                attributions.append(
                    CreditAttribution(
                        identity=identity,
                        table=column.table,
                        column=column.column,
                        field=column.column,
                        rule=RULE_DECLARED_NAME,
                        triviality_rule=triviality_rule,
                        source_kind=SOURCE_KIND_BEST_GUESS,
                    )
                )
                covered_guessed.setdefault(column.column, normalized)

            counterfactual.extend(
                self._counterfactual_for(table, values)
            )

            covered = len(covered_verbatim) + len(covered_guessed)
            max_covered = max(max_covered, covered)
            row = self._row_credit(
                table=table,
                values=values,
                covered_verbatim=covered_verbatim,
                covered_guessed=covered_guessed,
                blocked=blocked,
            )
            if row is not None:
                row_credits.append(row)

        return CreditIdentities(
            attributions=tuple(attributions),
            row_credits=tuple(row_credits),
            row_credit_blocked=tuple(dict.fromkeys(blocked)),
            row_credit_max_columns_covered=max_covered,
            counterfactual=tuple(counterfactual),
        )

    def __call__(self, unit: PageUnit, material: PageMaterial) -> CreditResult:
        """The Leaf's ``credit`` slot. Writes the breakdown onto the unit once."""

        fate = material.fate
        projected = (
            self.identities(material.records, material.guesses)
            if fate.judged
            else CreditIdentities()
        )
        detail = PageCredit(
            attributions=projected.attributions,
            row_credits=projected.row_credits,
            row_credit_blocked=projected.row_credit_blocked,
            row_credit_inert=self.row_credit_inert,
            row_credit_max_columns_covered=projected.row_credit_max_columns_covered,
            counterfactual=projected.counterfactual,
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

        identities = projected.identities
        facets = self._facets(projected)
        return CreditResult(credits=identities, facets=facets)

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _facets(self, projected: CreditIdentities) -> dict[str, tuple[str, ...]]:
        """EVERY declared facet on EVERY active result, empty where uncredited.

        The declared set is a property of the table spec, not of which page
        arrived first. With the alternative shape a scope where no page ever
        credits anything emits no facets at all -- indistinguishable from a
        crediter that has no facets, and "every declared column has a curve and
        all of them are flat" and "no column curve exists" are opposite facts.
        Fan-up needs it too: a parent derives its facet names from its children's
        unit records, so a search whose facet set depended on which page arrived
        would give its strategy a facet set depending on which search arrived.

        The groups PARTITION the credit tuple, which the kernel checks: a value
        credit sits in its ``table|column`` facet, a row credit in its
        ``table|rows`` facet, and no credit is in two.
        """

        groups: dict[str, list[str]] = {name: [] for name in self._declared_facets}
        seen: set[str] = set()
        for attribution in projected.attributions:
            if attribution.identity in seen:
                continue
            seen.add(attribution.identity)
            groups[f"{attribution.table}|{attribution.column}"].append(
                attribution.identity
            )
        for row in projected.row_credits:
            if row.identity in seen:
                continue
            seen.add(row.identity)
            groups[f"{row.table}|rows"].append(row.identity)
        return {name: tuple(members) for name, members in groups.items()}

    def _column(self, table: str, column: str) -> Optional[CreditColumn]:
        for candidate in self._by_table.get(table) or ():
            if candidate.column == column:
                return candidate
        return None

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

        Four clauses, all of which must hold: the value normalizes to something
        non-empty; ``criteria`` does not call it missing; it parses as the
        column's declared ``value_type`` where one is declared; and it carries
        the column's declared ``unit`` where one is declared.

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
        if column.unit and not _carries_unit(normalized, column.unit):
            return None
        if not column.value_type:
            return normalized, ("untyped" if not column.unit else f"unit:{column.unit}")
        if not _parses_as(normalized, column.value_type, column.unit):
            return None
        return normalized, column.value_type

    def _counterfactual_for(
        self,
        table: str,
        values: Mapping[str, Any],
    ) -> list[CounterfactualCredit]:
        columns = self._counterfactual_by_table.get(table) or ()
        if not columns:
            return []
        out: list[CounterfactualCredit] = []
        excluded_class = {
            (item.table, item.column): item.exclusion_class
            for item in self._basis.excluded
        }
        for field_name, value in _iter_fields(values):
            match = self._match(field_name, columns)
            if match is None:
                continue
            column, _rule = match
            admitted = self._non_trivial(value, column)
            if admitted is None:
                continue
            out.append(
                CounterfactualCredit(
                    identity=f"{column.table}|{column.column}|{admitted[0]}",
                    table=column.table,
                    column=column.column,
                    exclusion_class=excluded_class.get(
                        (column.table, column.column), ""
                    ),
                )
            )
        return out

    def _row_credit(
        self,
        *,
        table: str,
        values: Mapping[str, Any],
        covered_verbatim: Mapping[str, str],
        covered_guessed: Mapping[str, str],
        blocked: list[str],
    ) -> Optional[RowCreditDetail]:
        """Kind 2: one extracted record that completed a declared row.

        THE RULE. Every column in this table's credit basis carries a
        non-trivial value on THIS record, and every one of the table's declared
        subject-key columns carries a non-trivial value on it too. The unit is
        one extracted record, never the page: a page can carry many subjects,
        and a rule over the page's flattened fields could not say whether one
        subject carried six columns or six subjects carried one each.

        WHAT MAY SATISFY WHICH HALF, AND WHY IT IS NOT SYMMETRIC. A credit
        column may be satisfied by an evidenced best guess -- the charter's own
        definition of this credit kind is "verbatim, **or** an evidenced best
        guess or range", and a conjunction over every declared column from one
        page's verbatim extraction essentially never fires. A **subject key may
        not**: a guessed identity is a manufactured subject, and manufactured
        subjects are how row-completeness volume would be minted from nothing.

        THAT ASYMMETRY IS WHY A CONTRACT CHANGE CAN LOOSEN THIS RULE WITHOUT ANY
        DESIGN CHANGE, AND IT HAS ALREADY DONE SO ONCE. On the deliverable
        earthquake contract, ``magnitude`` was a subject-key column and became
        one of the declared credit columns when the subject grain was narrowed
        (HEAD 6f06549, a separate phase's ruling). So a **guessed** ``magnitude``
        can now contribute to a row-completeness credit where a guessed
        ``magnitude`` previously could not, and the deliverable table's
        row-credit conjunction is that much easier to satisfy. Nothing in this
        module changed to permit it; a column crossed a line in the contract.
        A reader reconstructing why a row credit fired should not have to find
        that in an experiment log, so it is written here, beside the rule, and
        the emitted ``row_credit_rule`` block carries it into the artifact.

        Every row credit records which of its columns were verbatim and which
        were guessed, so the second curve's height is legible as a property of
        the sources or of the guesser. No rule reads that split.

        THE KEY TEST RUNS AT THE KEY COLUMN'S DECLARED STANDARD. A subject key
        is excluded from the credit basis as class ``identity``, so its declared
        ``value_type``/``unit`` reach this test through
        :attr:`CreditBasis.key_columns` -- carried by the same pass that
        excludes it -- rather than being lost and the key checked at the
        permissive fallback. The clause is inert on a contract that declares
        neither field, and ``typed_key_column_count`` in the emitted basis says
        which case a run is in rather than leaving it assumed.
        """

        keys = self._basis.subject_key_columns.get(table) or ()
        declared = [column.column for column in (self._by_table.get(table) or ())]
        if not keys or not declared:
            return None

        key_parts: list[str] = []
        for key in keys:
            column = CreditColumn(
                table=table,
                column=key,
                token_keys=(),
                value_type=_declared_key_type(self._basis, table, key),
                unit=_declared_key_unit(self._basis, table, key),
            )
            admitted = self._non_trivial(_read(values, key), column)
            if admitted is None:
                blocked.append("subject_unbound")
                return None
            key_parts.append(f"{key}={admitted[0]}")

        missing = [
            column
            for column in declared
            if column not in covered_verbatim and column not in covered_guessed
        ]
        if missing:
            return None

        identity = f"{table}|{'|'.join(key_parts)}"
        return RowCreditDetail(
            identity=identity,
            table=table,
            columns_verbatim=tuple(
                column for column in declared if column in covered_verbatim
            ),
            columns_best_guess=tuple(
                column for column in declared if column in covered_guessed
            ),
            declared_total=len(declared),
        )

    @staticmethod
    def _guessed_values(
        guesses: Sequence[Mapping[str, Any]],
    ) -> dict[tuple[str, int], dict[str, Any]]:
        """Admissible guesses, indexed by (table, record index) and column.

        THE ADMISSION TEST HAS ONE OWNER: ``criteria.admits_judged_best_guess``,
        the same predicate the projection applies, exported so this crediter
        cannot keep a second, looser opinion. What that predicate does not carry
        -- "only where no row supplies the field", which the projection applies
        against a row -- is applied at this grain by the caller's own task
        builder, which builds a guess task only for a declared column the
        verbatim pass left missing on that record.
        """

        out: dict[tuple[str, int], dict[str, Any]] = {}
        for resolution in guesses or ():
            if not criteria.admits_judged_best_guess(resolution):
                continue
            table = str(resolution.get("target_table") or "")
            index = int(resolution.get("source_row_index"))
            column = str(resolution.get("canonical_column") or "")
            out.setdefault((table, index), {})[column] = resolution.get(
                "best_guess_value"
            )
        return out


def _declared_key_type(basis: CreditBasis, table: str, key: str) -> str:
    """The declared ``value_type`` of a subject-key column, or ``""``.

    ``key_columns`` IS SEARCHED FIRST AND IS WHERE A SUBJECT KEY ACTUALLY LIVES:
    a key column is excluded from the basis as class ``identity`` before either
    ``columns`` or ``counterfactual`` is built, so a lookup over those two alone
    always returned ``""`` and every subject key was checked at the permissive
    fallback -- non-empty and not missing -- however it was declared. The other
    two lists stay in the lookup because a table may key on a column that a
    different table declares as a credit column, and the declared type is a
    property of the column wherever it is found.
    """

    for column in basis.key_columns + basis.counterfactual + basis.columns:
        if column.table == table and column.column == key:
            return column.value_type
    return ""


def _declared_key_unit(basis: CreditBasis, table: str, key: str) -> str:
    """The declared ``unit`` of a subject-key column, or ``""``. See above."""

    for column in basis.key_columns + basis.counterfactual + basis.columns:
        if column.table == table and column.column == key:
            return column.unit
    return ""


def _read(values: Mapping[str, Any], name: str) -> Any:
    if name in values:
        return values[name]
    normalized = _normalize_name(name)
    for key, value in values.items():
        if _normalize_name(key) == normalized:
            return value
    return None


def _iter_fields(values: Mapping[str, Any]) -> Iterable[tuple[str, Any]]:
    for key, value in values.items():
        if value is None:
            continue
        yield str(key), value


_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?")
_RANGE_SPLIT_RE = re.compile(r"\s*(?:-|–|—|to)\s*", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
_YEAR_RE = re.compile(r"^\d{4}$")


def _carries_unit(text: str, unit: str) -> bool:
    return unit.lower() in text.lower()


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
LeafFactory = Callable[[Any, Mapping[str, Any], int], Leaf]


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
        make_leaf: LeafFactory,
        budget: SourceBudget,
        health: ProviderHealth,
        round_index: int,
        open_cost_scope: Callable[[str, str, int], Any],
        on_results: Optional[Callable[[Any, Sequence[Mapping[str, Any]]], None]] = None,
        on_error: Optional[Callable[[Any, BaseException, bool], None]] = None,
        is_fatal: Callable[[BaseException], bool] = lambda _exc: False,
    ) -> None:
        self._task = task
        self._search_fn = search_fn
        self._make_leaf = make_leaf
        self._budget = budget
        self._health = health
        self._round_index = int(round_index)
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

    def next(self, view: EpisodeView) -> Leaf | None | SourceEnd:
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
        return self._make_leaf(self._task, result, self._next_rank)

    def _issue(self) -> Optional[SourceEnd]:
        """The provider call, inside its own cost scope, on the first pull."""

        end: Optional[SourceEnd] = None
        results: list[Mapping[str, Any]] = []
        with self._open_cost_scope(
            ObservationKind.SEARCH.value, str(self._task.id), self._round_index
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
#: verdict unreachable below ten completed strategies, THIS CONSTANT AND
#: `max_rounds` ARE THE OPERATIVE ENDS OF THE PROPOSING ARC ON ANY RUN SMALLER
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
        open_cost_scope: Callable[[str, str, int], Any],
        round_index: Callable[[], int],
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
        self._round_index = round_index
        self._run_key = run_key
        self._record_proposal = record_proposal
        self._floor = float(distance_floor)
        self._max_samples = max(1, int(max_samples))
        self._opened_content: set[str] = set()
        self._opened: list[dict[str, Any]] = []
        self._opened_token_sets: list[frozenset[str]] = []
        self._instances: dict[str, int] = {}
        self._pulls = 0
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

    async def next(self, view: EpisodeView) -> Episode | None | SourceEnd:
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
        # THE ROUND INDEX COMES FROM ITS ONE OWNER and is NOT `units_consumed`.
        # The two agree only when the run's round offset is zero: the owner is
        # `round_offset + completed strategies` and the view counts completed
        # strategies alone, so on a resumed run (both live launchers pass
        # `--round-offset 3`) this edge would be stamped with a round no other
        # record in the same strategy carries, and `reward.aggregate_round_cost`
        # filters on exactly that field -- dropping the proposer's spend from
        # the round that paid for it. A second expression for `round_index` is
        # the defect this callable exists to prevent.
        with self._open_cost_scope(
            ObservationKind.STRATEGY_PROPOSAL.value,
            f"{self._run_key}#p{self._pulls}",
            int(self._round_index()),
        ):
            episode = await self._pull()
        return episode

    async def _pull(self) -> Episode | None | SourceEnd:
        """The pull itself. IT TAKES NO VIEW, and that is the point.

        Every input is a typed object this class was handed -- the run's
        terminal state, provider health, the page budget, the declared families,
        the declared target ids -- and the round index comes from its owner. The
        proposer reads no curve, no verdict and no unit count, so there is no
        expression here that could disagree with one kept elsewhere.
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

    keys = {record.scope_key}
    labels = {unit.unit_label for unit in record.unit_records}
    out: dict[str, list[dict]] = {"scope": [], "units": []}
    for cost in cost_records:
        observation_id = str(cost.get("observation_id") or "")
        if observation_id in keys:
            out["scope"].append(dict(cost))
        elif observation_id in labels:
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

    crediter: ColumnProjection
    budget: SourceBudget
    health: ProviderHealth = field(default_factory=ProviderHealth)
    termination: RunTermination = field(default_factory=RunTermination)

    def __post_init__(self) -> None:
        schema = self.crediter.channel_schema
        self.context = Context(
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
                "acquisition credit identities do not join to criterion or "
                "transition ids by construction; source_id is the one join, on "
                "both sides"
            ),
            "facet_gate": "crediting_active",
            "grains": [
                grain_disclosure(grain) for grain in GRAIN_ORDER
            ],
            "chunk_grain": CHUNK_GRAIN_DISCLOSURE.to_dict(),
            "credit_basis": self.crediter.basis.to_dict(),
            "spec_digest": self.crediter.spec_digest,
            "declared_facets": list(self.crediter.declared_facets),
            "channel_schema": self.crediter.channel_schema.as_record(),
            "row_credit_rule": ROW_CREDIT_RULE_DISCLOSURE,
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


#: The row-completeness rule, in the artifact rather than only in the code.
#: A reader reconstructing why a row credit fired reads this beside the curve.
ROW_CREDIT_RULE_DISCLOSURE = {
    "rule": (
        "one extracted record carries a non-trivial value for every declared "
        "credit column of its table AND for every one of that table's declared "
        "subject-key columns"
    ),
    "unit": "one extracted record, never the page",
    "credit_columns_may_be_guessed": True,
    "subject_key_columns_may_be_guessed": False,
    "why_asymmetric": (
        "the charter defines this credit kind as 'verbatim, or an evidenced "
        "best guess or range', and a conjunction over every declared column "
        "from one page's verbatim extraction essentially never fires; but a "
        "guessed identity is a manufactured subject, and manufactured subjects "
        "are how row-completeness volume would be minted from nothing"
    ),
    "consequence_of_a_contract_change": (
        "a column that moves OUT of a table's subject key and INTO its credit "
        "basis becomes eligible for a judged best guess where it never was, "
        "which loosens this conjunction on that table without any change to the "
        "rule. On the deliverable earthquake contract `magnitude` made exactly "
        "that move at HEAD 6f06549, so a guessed `magnitude` can now contribute "
        "to a row-completeness credit. The per-row verbatim/guessed split is "
        "emitted for every row credit so this is legible rather than inferred; "
        "no rule reads the split"
    ),
}
