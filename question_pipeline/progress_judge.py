"""The page gate's one model call: score a page against the declared contract.

**This module no longer judges the run's progress, and the module name is a
disclosed residual.** Before phase 4E-c it hosted `judge_progress`, which was
handed the complete task state -- the declared stop criteria, the catalog
progress, the universe estimate, the completion scope and the whole table-spec
prompt context, measured at 85,208 rendered characters per window call -- and
asked to return an ``accept | defer | reject`` decision that a branch consumed.
That is `docs/ACQUISITION_LOOP.md` §"Decisions are numerical" by name: "Passing
a curve, a fit, or a table of counts to a model and asking it to decide is the
same violation as asking it outright", and "A model never emits a count, an
estimate, or a verdict that a branch consumes."

What replaces it does string work and nothing else. The payload is (question,
declared target columns, one window of this page's text). The response carries
one declared score and six lists of strings about this page. **There is no
decision field, and the prompt names no gate, no decision word, and no
consequence of the number** -- a model told a gate exists has been handed the
rule back and will encode its verdict into the float. The branch is taken
elsewhere, by `acquisition.page_clears_relevance`, which compares the reported
number against a module constant.

Two scores the old call returned are not merely unread here, they are **not
asked**, which is stronger because nothing can quietly start reading a field
that is never returned:

* ``novelty_score`` was defined as non-duplication relative to the task state,
  and that is exactly what ``rarefaction.accumulator`` computes -- by identity
  dedupe, with f1/f2, and with repeats treated as propagation rather than
  replication. It was an LLM estimate standing in for a measurement that did
  not exist when it was written; 4E-c builds the measurement, so 4E-c retires
  the estimate. It is also the reason the payload was wide: remove the score and
  the payload's reason for being wide goes with it.
* ``fruitfulness_score`` was defined as the likelihood of improving the declared
  deliverables or a source-supported universe estimate -- a progress estimate
  over run state rather than a property of this page's text. A floor over it
  would be a better-disguised violation, not a fix.

``specificity_score``'s definition is carried **verbatim** from the prompt that
predates this design: "likelihood that it contains values or qualifiers at the
grain of the requested final rows." This module authors no score definition, so
the number the branch reads was not chosen to clear anything.

The module keeps its filename. Renaming it moves an ``__init__`` export and
touches import sites inside the largest diff of this build for no behavioural
gain, so the naming residual is recorded here rather than left for a reader to
notice.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from .llm_utils import ModelTier, ask_json, register_call_site_tier
from .windowing import window_stamps, window_text

#: 0M-progress-judge tested the wide `judge_progress` call and found
#: `gpt-5.4-mini` agreeing with the reference model on 0.582 of items against a
#: registered 0.95 threshold. That measurement was about a call this module no
#: longer makes -- a different payload, a different response shape, and a score
#: rather than a label on the branch -- so it cannot license a tier for the new
#: one. 0M's own rule applies instead: a call site not measured there stays on
#: `REASONING`.
_PAGE_GATE_TIER = register_call_site_tier("page-gate", ModelTier.REASONING)

_PAGE_GATE_SYSTEM_PROMPT = """You are reading one web page against a declared
table contract and reporting what it appears to carry.

Report likelihoods and short factual lists. Do not recommend an action, do not
say whether the page should be used, and do not describe what should happen
next. Return only valid JSON in the shape requested by the user."""

#: Serialized-character budget for ONE gate call's slice of the page text. It
#: bounds a call, not the evidence: text larger than this becomes more calls,
#: never a shortened one.
#:
#: Held at its pre-4E-c value deliberately. The narrowed payload makes a larger
#: window affordable, and that is exactly why it is not taken here: changing it
#: changes how much text a single score reasons over and how many calls a page
#: costs, and that is an experiment with a predicted direction, not a tidying
#: step to fold into a fix. On the live earthquake run's accepted sources
#: (already reduced upstream by `reduce_text_to_relevant_windows`) this yields a
#: mean of 2.71 and a maximum of 4 windows per page.
EVIDENCE_WINDOW_CHARS = 7000


@dataclass(frozen=True)
class DeclaredColumn:
    """One declared contract column, as the gate is told about it.

    A typed parameter built by the caller, so this module gains no intra-package
    import beyond `llm_utils` and `windowing` and stays exercisable with a
    constructed column list and a fake client. The caller draws the **set** from
    one owner -- `acquisition.declared_credit_columns` -- so the columns the
    model is asked about are exactly the columns the crediter can credit, and
    the two cannot drift. This module selects nothing.
    """

    table: str
    column: str
    value_type: str = ""
    unit: str = ""
    aliases: tuple[str, ...] = ()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"column": self.column}
        if self.value_type:
            out["value_type"] = self.value_type
        if self.unit:
            out["unit"] = self.unit
        if self.aliases:
            out["aliases"] = list(self.aliases)
        if self.description:
            out["description"] = self.description
        return out


def contract_block(columns: Sequence[DeclaredColumn]) -> dict[str, list[dict]]:
    """The declared columns, grouped by table, exactly as the prompt renders."""

    out: dict[str, list[dict]] = {}
    for column in columns:
        out.setdefault(str(column.table), []).append(column.to_dict())
    return out


@dataclass(frozen=True)
class PageScore:
    """What one page reported against the declared contract.

    ``specificity_score`` is ``None`` when nothing usable was reported -- an
    absent field, an explicit null, an unparseable response, or no window at
    all. ``None`` and ``0.0`` are different facts and this build does not
    conflate them: ``0.0`` is a model saying "no values at the requested grain",
    ``None`` is a model that did not answer. The gate has a third outcome for
    the second case, so an instrument failure never wears a measurement's
    clothes.

    The six lists are string work about this page and nothing branches on them.
    """

    specificity_score: float | None = None
    #: Why no score arrived, as a class label: ``absent``, ``null``,
    #: ``unparseable``, ``no_windows``, or ``""`` when one did.
    score_reason: str = ""
    #: The page's own SUBJECT vocabulary for and against the declared columns,
    #: not the column identifiers. These two fields are the only ones that
    #: become literal query text -- `strategy_state._memory_terms` reads exactly
    #: them and `fallback_query_for_operator` concatenates them into the
    #: returned query, ranked AHEAD of field-name candidates, which that
    #: function's own docstring says come last on purpose. Asking for column
    #: identifiers here would put internal names into query text that the arm
    #: planner's prompt separately forbids there.
    #:
    #: MEASURED, NOT ENFORCED: `_string_list` coerces arbitrary model strings
    #: and validates them against nothing. The run counts, per round, how many
    #: terms entering `_memory_terms` are members of the declared column set --
    #: two-sided, with zero reported as the finding.
    matched_needs: tuple[str, ...] = ()
    missing_needs: tuple[str, ...] = ()
    offtopic_axes: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    better_search_cues: tuple[str, ...] = ()
    avoid_cues: tuple[str, ...] = ()
    reason: str = ""
    #: Which window of this page produced the fields above. ``-1`` when no
    #: window did. Carried as a typed field because the merge below selects the
    #: deciding window by a numerical rule and a reader recomputing that rule
    #: offline needs the index it landed on.
    window_index: int = -1
    #: How many model calls produced this score. One means the page fit one
    #: call; more means the text was windowed and merged; zero means no call
    #: was made.
    window_count: int = 1
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge_page_scores(
    scores: list[PageScore],
    disclosure: dict[str, Any],
) -> PageScore:
    """Merge per-window scores of ONE page into one score.

    THE MERGE IS A MAXIMUM OVER THE NUMBER THE GATE READS, and every other field
    comes from the window that supplied it, so the emitted record is one
    window's actual report rather than a composite no model produced.

    WHY A DISJUNCTION AND NOT A VOTE OR A MEAN. The argument is about the data,
    not about tuning, and it is unchanged from before the gate became numerical:
    the value of a source is concentrated, not spread. The extractable table is
    in one appendix; the quantitative outcome is in one results paragraph; the
    rest of the document is background that would score low on its own and
    correctly so. A majority vote therefore rejects precisely the sources worth
    having, because the windows that saw background outnumber the one that saw
    the table, and a mean does the same thing more quietly. The question is not
    "is every part of this page at the requested grain" -- it is "is this page
    worth extracting at all", and extracting ingests the whole document
    including the window that qualified it.

    That argument is about the quantity, not about the label the old version
    took its maximum over, so it transfers intact. What moved is which
    expression the maximum is taken over: it is now the same one the fate rule
    reads, so a page clears the floor exactly when its best window does.

    WHAT THIS COSTS, MEASURABLY. Max-of-N is an order statistic whose
    expectation rises with N, and here N is document length -- a longer page
    gets more chances to clear. That exposure is not introduced by the change;
    the label disjunction had it too. What the change adds is that it is now a
    number: `window_count` is typed, every window's own score is in
    ``raw["gate_windows"]``, and the clearance rate by window count is
    computable from emitted data.

    A window that reported no usable score sorts below every window that did, so
    an unparseable window can never win the selection from a window that
    answered; ties go to the earliest window, which makes the selection
    deterministic and recomputable offline.
    """

    if not scores:
        return PageScore(
            specificity_score=None,
            score_reason="no_windows",
            reason="page gate produced no windows",
            window_index=-1,
            window_count=0,
            raw={"gate_windows": disclosure},
        )

    def rank(score: PageScore) -> tuple[float, int]:
        value = score.specificity_score
        return (value if value is not None else -1.0, -score.window_index)

    deciding = max(scores, key=rank)
    merged_raw = dict(deciding.raw)
    merged_raw["gate_windows"] = disclosure
    return PageScore(
        specificity_score=deciding.specificity_score,
        score_reason=deciding.score_reason,
        matched_needs=deciding.matched_needs,
        missing_needs=deciding.missing_needs,
        offtopic_axes=deciding.offtopic_axes,
        failure_modes=deciding.failure_modes,
        better_search_cues=deciding.better_search_cues,
        avoid_cues=deciding.avoid_cues,
        reason=deciding.reason,
        window_index=deciding.window_index,
        window_count=len(scores),
        raw=merged_raw,
    )


async def score_page_against_contract(
    llm,
    *,
    question: str,
    columns: Sequence[DeclaredColumn],
    page_text: str = "",
    evidence_window_chars: int = EVIDENCE_WINDOW_CHARS,
) -> PageScore:
    """Ask one model what a page appears to carry for the declared columns.

    Nothing in the payload is shortened. The page text is the one axis that
    windows -- it is a sequence over which the reported property is disjunctive,
    so it splits cleanly and merges by :func:`_merge_page_scores` -- and the
    declared contract is sent whole in every call.

    THE CONTRACT BLOCK IS SENT WHOLE, and it is small enough that this is not a
    concession: over the live run's 22 declared credit columns it renders at
    8,402 characters, against the 85,208 the task state cost per call before
    this narrowing. It is not windowed for the same reason it is not clipped: a
    model shown half a contract reports "absent from this page" about columns it
    was never told to look for.

    THE CALL COUNT is ``ceil(len(page_text) / evidence_window_chars)``, exactly
    as before; only the per-call size moved.
    """

    windows = window_text(page_text or "", budget=evidence_window_chars)
    block = contract_block(columns)
    # Measured AS RENDERED, with the same `indent=2` the prompt uses, so the
    # disclosure never reports a smaller number than the thing it discloses.
    contract_chars = len(json.dumps(block, indent=2, default=str))
    # No text is still one call: the declared contract alone is a scoreable
    # payload, and a zero-call path would make "no text" and "no score" the same
    # observable.
    call_windows: list[str | None] = list(windows) if windows else [None]

    scores: list[PageScore] = []
    window_records: list[dict[str, Any]] = []
    for index, window in enumerate(call_windows):
        stamps = window_stamps(index, len(call_windows))
        prompt = _gate_prompt(
            question=question,
            block=block,
            page_window=window,
            stamps=stamps,
        )
        parsed = await ask_json(
            llm,
            prompt,
            system_prompt=_PAGE_GATE_SYSTEM_PROMPT,
            tier=_PAGE_GATE_TIER,
        )
        score = coerce_page_score(parsed, window_index=index)
        scores.append(score)
        window_records.append(
            {
                **stamps,
                "page_chars": len(window or ""),
                "prompt_chars": len(prompt),
                "specificity_score": score.specificity_score,
                "score_reason": score.score_reason,
                # Kept per window because the merged score takes these from the
                # deciding window only. Nothing branches on them here.
                "matched_needs": list(score.matched_needs),
                "missing_needs": list(score.missing_needs),
                "offtopic_axes": list(score.offtopic_axes),
                "failure_modes": list(score.failure_modes),
                "better_search_cues": list(score.better_search_cues),
                "avoid_cues": list(score.avoid_cues),
            }
        )

    disclosure = {
        "merge_rule": "max_specificity_earliest_window",
        "window_count": len(call_windows),
        "page_chars": len(page_text or ""),
        "evidence_window_chars": max(1, int(evidence_window_chars or 1)),
        "contract_columns": len(columns),
        "contract_chars": contract_chars,
        "contract_chars_measured_as": "rendered json.dumps(indent=2)",
        "contract_windowed": False,
        "prompt_chars_total": sum(
            record["prompt_chars"] for record in window_records
        ),
        "windows": window_records,
    }
    return _merge_page_scores(scores, disclosure)


def _gate_prompt(
    *,
    question: str,
    block: Mapping[str, Any],
    page_window: str | None,
    stamps: Mapping[str, int],
) -> str:
    """One gate call's prompt over one window of the page.

    NAMES NO GATE, NO DECISION WORD, AND NO CONSEQUENCE. The model is asked for
    a likelihood on a declared scale and for six lists of strings about one
    page, and is told nothing about what is done with them.
    """

    if page_window is None:
        page_block = "PAGE TEXT:\n(no page text was available)"
    else:
        page_block = f"""PAGE TEXT (window {stamps["window_index"] + 1} of {stamps["window_count"]}, {len(page_window)} characters, verbatim and unabridged):
{page_window}

You are reading one contiguous window of this page's text, not the whole page.
Report what THIS window supports, by the same standard you would apply to a
whole page. Do not report a column as absent because a different window would
carry it."""

    return f"""QUESTION:
{question}

DECLARED TARGET COLUMNS JSON (complete and unabridged):
{json.dumps(block, indent=2, default=str)}

{page_block}

Use this scale:
- specificity_score: likelihood that it contains values or qualifiers at the
  grain of the requested final rows.

For `matched_needs` and `missing_needs`, report the page's own SUBJECT
VOCABULARY -- the external terms this page uses for the things a declared
column would hold, and the terms it would need and does not use. Do not return
the declared column identifiers themselves; return the words a source author
would write.

Return JSON:
{{
  "specificity_score": 0.0,
  "reason": "one concise sentence",
  "matched_needs": ["subject terms this page carries values for"],
  "missing_needs": ["subject terms a declared column needs and this page lacks"],
  "offtopic_axes": ["why this may be adjacent rather than useful"],
  "failure_modes": ["short generic failure labels"],
  "better_search_cues": ["external terms that could improve the next search"],
  "avoid_cues": ["external terms or source shapes that look unfruitful"]
}}"""


def coerce_page_score(raw: Any, *, window_index: int = 0) -> PageScore:
    """Coerce an arbitrary JSON value into a stable page score.

    An unparseable response produces ``specificity_score=None`` with the reason
    class ``unparseable``. It does **not** mint a substantive low score: a
    judgement minted from a parse failure would read as a page that carries
    nothing, and a stream of them would read as a search producing nothing --
    the silent-failure class this build bans, arriving in the place a numerical
    gate creates for it.
    """

    if not isinstance(raw, Mapping):
        return PageScore(
            specificity_score=None,
            score_reason="unparseable",
            reason="page gate returned no object",
            window_index=window_index,
            raw={"unparseable": raw},
        )

    score, reason_class = _optional_score(raw.get("specificity_score"), raw)
    return PageScore(
        specificity_score=score,
        score_reason=reason_class,
        matched_needs=tuple(_string_list(raw.get("matched_needs"))),
        missing_needs=tuple(_string_list(raw.get("missing_needs"))),
        offtopic_axes=tuple(_string_list(raw.get("offtopic_axes"))),
        failure_modes=tuple(_string_list(raw.get("failure_modes"))),
        better_search_cues=tuple(_string_list(raw.get("better_search_cues"))),
        avoid_cues=tuple(_string_list(raw.get("avoid_cues"))),
        reason=str(raw.get("reason") or "").strip(),
        window_index=window_index,
        raw=dict(raw),
    )


def _optional_score(value: Any, payload: Mapping[str, Any]) -> tuple[float | None, str]:
    """The reported score and why it is absent, never a substituted zero.

    Returns ``(None, class)`` for a missing field, an explicit null, and an
    unparseable value alike -- each with its own class -- and ``(clamped, "")``
    for a real number. The predecessor returned ``0.0`` for all three, which
    under a floor makes every one of them "below the floor": an instrument
    failure wearing a measurement's clothes.
    """

    if "specificity_score" not in payload:
        return None, "absent"
    if value is None:
        return None, "null"
    try:
        return max(0.0, min(1.0, float(value))), ""
    except (TypeError, ValueError):
        return None, "unparseable"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        value = [value]

    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out
