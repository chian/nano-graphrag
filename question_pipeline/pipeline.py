"""Question-driven iterative GraphRAG pipeline orchestrator.

The default answer mode tries to produce one well-supported answer. Each round
searches the web, extends a typed knowledge graph, answers the question with
GASL, and uses identified gaps to steer the next search.

The table-fill mode treats the answer tables as the deliverable. It estimates
the searched answer universe, keeps a durable search frontier, and searches to
fill missing final-table rows until the count targets are covered.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import inspect
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from domain_schemas.schema_loader import DomainSchema, load_domain_schema
from gasl import GASLExecutor, NetworkXAdapter
from gasl.answer_layer import AnswerLayerCompiler
from gasl.contracts import make_contract
from gasl.llm import ArgoBridgeLLM
from graph_metadata import build_metadata, save_graph_metadata
from hpc.common import save_graph
from nano_graphrag.entity_extraction.typed_module import (
    create_domain_extractor_from_schema,
)
from paper_fetching.firecrawl_client import (
    download_paper_content,
    firecrawl_search_batch_metadata,
    search_papers,
)

from . import schema_synthesis, strategy
from .best_guess import (
    BEST_GUESS_CANDIDATE_COLUMNS,
    BEST_GUESS_CONTEXT_COLUMNS,
    best_guess_context_by_row_key,
    page_best_guess,
    run_best_guess_recovery,
    run_best_guess_recovery_local,
)
from .completion import (
    completion_needs_scope_search,
    completion_scope_actionable,
    completion_update_from_critique,
    completion_update_from_estimate,
    load_seed_completion_state,
    merge_completion_state,
    scope_probe_context,
)
from .control import (
    CONTROL_VOCABULARY_VERSION,
    ActionCandidate,
    ActionOrigin,
    AttemptRef,
    ControlSurface,
    DecisionContext,
    OperatorRef,
    PolicyDecision,
    PromptArmRef,
    SearchCandidate,
    StaticTableFillPolicy,
    StopContext,
    StopDecision,
    TargetRef,
    resolve_stop_decision,
    stable_id,
)
from .criteria import (
    CRITERIA_PROJECTION_VERSION,
    CriteriaSnapshot,
    datapoint_fields,
    empty_snapshot,
    is_missing_value,
    missing_tokens as criteria_missing_tokens,
    project_rows,
)
from .path_features import PathScoringContext, build_context
from .path_gate import PathGateResult, PathGateSettings, gate_rows
from .estimator import estimate_count_expectations
from .derived_context import context_slots_from_count_targets
from .derived_context import source_ids_from_row
from .extraction import chunk_text, enrich_graph, extract_from_text
from .goals import (
    FillGoalState,
    TableFillGoalTracker,
    compact_estimate_for_prompt,
    merge_universe_estimates,
    normalize_universe_estimate,
)
from .prompt_log import (
    close_scope as prompt_log_close,
    open_scope as prompt_log_open,
)
from . import acquisition as acq
from .acquisition import (
    CHUNK_GRAIN_DISCLOSURE,
    CREDIT_SEMANTICS,
    RELEVANCE_SCORE_FLOOR,
    RUN_GRAIN,
    SEARCH_GRAIN,
    STRATEGY_GRAIN,
    AcquisitionController,
    ColumnProjection,
    PageMaterial,
    PageSource,
    PageUnit,
    ProviderHealth,
    RunTermination,
    SourceBudget,
    StrategyProposer,
    StrategySearches,
    fate_skip_reason,
    grain_disclosure,
    page_clears_relevance,
    page_fate,
    window_episode_record,
)
from .progress_judge import DeclaredColumn, score_page_against_contract
from rarefaction import (
    END_EXHAUSTED,
    END_YIELD_STOP,
    Contribution,
    Episode,
    EpisodeRecord,
    Leaf,
    UnitRecord,
)
from .provenance import (
    CHUNK_PARAMS_FIELD,
    FIELD_PROVENANCE_SUFFIX,
    derive_field_provenance,
)
from .costs import (
    COST_ACCOUNTING_VERSION,
    CostRecord,
    ObservationKind,
    classify_error,
    cost_scope,
    orphan_meter,
    zero_cost,
)
from .llm_utils import (
    DEFAULT_FAST_MODEL,
    ModelTier,
    TierPolicy,
    attach_tier_policy,
    describe_tiers,
    for_tier,
    instrument_client,
    register_call_site_tier,
)
from .search import (
    SearchFrontier,
    SearchHarvester,
    SearchOutcome,
    SearchTask,
    SourceRelevanceDecision,
    compact_search_result,
    load_seed_frontier_tasks,
    load_seed_search_outcomes,
    load_seed_source_records,
    load_seen_urls,
    is_fatal_search_error,
    search_result_observation,
    summarize_prompt_arms,
    table_gap_search_tasks,
)
from .search_memory import SearchMemory
from .tables import SeedTables, load_seed_tables, merge_rows_by_table
from .numeric_candidates import (
    NUMERIC_CANDIDATE_COLUMNS,
    numeric_candidates_from_tables,
)
from .reward import (
    REWARD_COMPONENT_COLUMNS,
    CreditLedger,
    load_seed_best_guess_rows,
    merge_best_guess_rows,
    score_criterion_yield,
)
from .strategy_state import (
    QUERY_OPERATORS,
    ArmRoutingMode,
    fallback_query_for_operator,
    route_next_family,
)
from .table_specs import (
    TableSpec,
    dump_table_spec_yaml,
    load_table_spec,
    load_table_spec_with_seed_tables,
    observed_table_spec,
)


@dataclass
class PipelineConfig:
    question: str
    pipeline_mode: str = "answer"
    output_dir: str = "./question_runs/run"

    # Schema: if schema_name is set, load it; otherwise synthesize one.
    schema_name: Optional[str] = None
    graph_path: Optional[str] = None
    schema_review_passes: int = 2
    schema_expectations: str = ""

    # Search / corpus limits
    firecrawl_api_key: Optional[str] = None
    max_rounds: int = 4
    #: Pages PULLED from result lists, accepted or not. The docstring changed
    #: with the composition and the flag did not: under the fate table a page
    #: the gate refused is a unit that cost a fetch and a gate call, and a
    #: budget charging only acceptances would let a run pull unlimited refused
    #: pages for free -- leaving the stop rule's denominator unbounded. The run
    #: record emits BOTH counts, pulled and accepted, so nothing is ambiguous,
    #: and no figure is compared across the change.
    max_papers: int = 40
    queries_per_round: int = 6
    min_paper_length: int = 500
    max_paper_length: Optional[int] = None
    max_extraction_chars_per_paper: Optional[int] = None
    search_frontier_mode: str = "batch"
    scrape_search_results: bool = False
    table_gap_search_tasks: int = 12
    goal_discovery_text_chars: int = 6000
    source_relevance_mode: str = "focused"

    # Extraction / merge
    chunk_size: int = 2000
    chunk_overlap: int = 200
    extraction_concurrency: int = 1
    extraction_timeout_sec: Optional[float] = None
    similarity_threshold: float = 0.85
    auto_merge_entities: bool = True
    self_refine: bool = False

    # GASL
    max_gasl_iterations: int = 8
    gasl_graph_scope: str = "auto"
    gasl_new_source_hops: int = 1
    gasl_source_seed_limit: int = 100
    answer_mode: str = "natural"
    table_variables: List[str] = field(default_factory=list)
    table_spec_path: Optional[str | List[str]] = None
    seed_tables_dir: Optional[str] = None
    seed_sources_dir: Optional[str] = None
    #: Additional run directories to fall back to when a citation's source id
    #: is not resolvable under this run's own ``papers_dir`` -- typically
    #: rows seeded from an earlier run's tables/graph via ``--graph-path`` /
    #: ``--seed-tables-dir`` whose ``fetched_papers/`` this run never fetched
    #: itself. Each entry is a run's output directory; text is read from
    #: ``<root>/fetched_papers/<source_id>.txt``. Strictly additive: a source
    #: id resolvable locally never consults these. Not searched or rebuilt --
    #: only read for source ids a row already cites.
    evidence_corpus_roots: tuple[str, ...] = ()
    seed_frontier_path: Optional[str] = None
    round_offset: Optional[int] = None
    numeric_candidate_mode: str = "parsed"
    best_guess_mode: str = "llm"
    #: The PAGE-SCOPED best-guess stage, inside the leaf's ``extract``. It moves
    #: best-guess spend from one call per round to one call per extracted page,
    #: which is a real multiplier and is registered as one. ``"local"`` runs the
    #: deterministic operators only; ``"off"`` skips the stage entirely, in
    #: which case the chartered row-completeness curve is verbatim-only and the
    #: record says so.
    page_best_guess_mode: str = "llm"
    #: ``None`` means no ceiling: every derivable slot gets a best-guess
    #: task. A cap here decides in advance which cells may be filled.
    best_guess_max_tasks: int | None = None
    best_guess_evidence_chars: int = 5000
    best_guess_llm_batch_size: int = 8
    best_guess_llm_timeout_sec: Optional[float] = None

    # Stopping
    task_goal_mode: str = "off"
    task_goal_search_tasks: int = 0
    completion_probe_tasks: int = 4
    completion_probe_results: int = 5
    completion_probe_waves: int = 2
    target_deficit_evolutions_per_round: int = 1
    target_prompt_arms_per_evolution: int = 1
    target_queries_per_prompt_arm: int = 1
    #: Phase 3B: which routing policy chooses the next evolution's mutation
    #: family. ``"contrast"`` is the shipped mechanism (deterministic, from
    #: nested arm contrast); ``"off"`` and ``"random"`` are 3B's ablation
    #: conditions only -- see ``strategy_state.ArmRoutingMode``.
    arm_routing_mode: str = "contrast"
    #: Seeds `ArmRoutingMode.RANDOM`'s draw. Irrelevant under the default
    #: `"contrast"` mode, which is deterministic and touches no RNG.
    arm_routing_seed: int = 0

    # LLM
    model: Optional[str] = None
    # Model serving `ModelTier.FAST` call sites. The tier assignment per call
    # site is fixed by the 0M equivalence campaign; only which concrete model
    # fills the fast tier is configuration.
    fast_model: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


#: The extraction call site's declared tier. 0M-extraction held the chunks and
#: the graph schema fixed and varied only the model; the result and its two
#: sensitivity controls are in `experiments/log/0M-extraction.md`. Extraction is
#: the volume leader, so it was the call site most worth moving and the one
#: measured most carefully.
EXTRACTION_TIER = register_call_site_tier("extraction", ModelTier.REASONING)


TABLE_ANSWER_INSTRUCTIONS = """
Materialize row-shaped LIST variables for the requested tabular answer instead
of treating prose as the deliverable.

Use FIND, GRAPHWALK, PROJECT, COLLAPSE, and PROCESS to produce table variables
whose names end in _table. Preserve source_refs and source_chunks on every row
when provenance exists. Prefer one row per atomic fact, estimate, comparison,
or context over broad joined rows that blur distinct evidence. Keep partial
rows when a counterpart fact is absent; set missing fields to null and explain
the missing evidence in evidence_gap.

For every row about a quantitative estimate, preserve every row-level
qualifier that makes the estimate interpretable. Use the target key columns,
the user's question, and the source authors' strata to decide which qualifiers
belong in the row. When a source states a narrow qualifier plus an
unambiguous broader qualifier, carry both instead of collapsing the row to one
broad bucket.

Never write COLLAPSE, GROUP, AGGREGATE, or JOIN output directly AS a final
table variable unless every emitted row already has stable row keys and
source-level provenance. If candidates need deduplication, first COLLAPSE into
an intermediate variable, then PROCESS those collapsed rows into exact
row-shaped table rows. When a path table needs multiple relationship types,
issue one GRAPHWALK whose follow clause joins all needed edge labels with |.
Do not issue multiple GRAPHWALK commands AS the same variable; AS replaces
rather than appends. Before any COLLAPSE BY a deduplication key, create a
non-empty deduplication key on every candidate row.

When the state already contains `round_source_nodes`, those rows are the
current round's newly accepted source-evidenced graph nodes. Treat that
variable as the first source frontier: GRAPHWALK or PROCESS it before issuing
broad FIND commands. Use broad FIND only as a supplemental fallback after
source-seeded paths have been checked, because continuation rounds should
extract new evidence before revisiting the older graph.
""".strip()


ROUND_SOURCE_NODES_VAR = "round_source_nodes"
TABLE_REQUIRED_COLUMNS: Dict[str, List[str]] = {}
TABLE_COMPLETENESS_COLUMNS: Dict[str, List[str]] = {}
PIPELINE_MODE_ANSWER = "answer"
PIPELINE_MODE_TABLE_FILL = "table_fill"
TASK_GOAL_OFF = "off"
TASK_GOAL_TABLE_FILL = "table_fill"


def _row_chunk_ids(row: Mapping[str, Any]) -> list[str]:
    """Chunk ids this row already claims, from its own row-level provenance."""

    out: list[str] = []
    for key in ("source_chunks", "source_chunk"):
        value = row.get(key)
        if value is None:
            continue
        items = value if isinstance(value, (list, tuple, set)) else [value]
        for item in items:
            for part in str(item).replace(";", ",").split(","):
                part = part.strip().strip("[]'\" ")
                if part:
                    out.append(part)
    return sorted(set(out))


def _source_id_from_chunk_id(chunk_id: str) -> str:
    """Recover the source id a chunk id was minted from.

    Chunk ids are always minted as ``f"{source_id}_chunk_{index}"`` (see
    ``QuestionPipeline._chunk_texts_by_id``), so the source id is everything
    before the last ``_chunk_<digits>`` marker.
    """

    match = re.match(r"^(?P<source_id>.+)_chunk_\d+$", str(chunk_id or ""))
    return match.group("source_id") if match else ""


def _operator_metadata(operator_plan: Dict[str, Any]) -> Dict[str, Any]:
    operator = str(operator_plan.get("operator") or "")
    source_family = str(operator_plan.get("source_family") or "")
    return {
        "strategy_operator": operator,
        "strategy_family": operator,
        "source_family": source_family,
        "operator_attempt": operator_plan.get("attempt_index"),
        "operator_context_tags": operator_plan.get("context_tags", []),
        "operator_last_failure_class": operator_plan.get(
            "last_failure_class",
            "",
        ),
        "operator_exhausted": operator_plan.get("exhausted_operators", []),
        "operator_constraints": operator_plan.get("constraints", []),
    }


#: Filename of the append-only control-decision ledger inside ``answers/``.
CONTROL_LEDGER_FILENAME = "control_decisions.json"

#: Chunks a page must carry before an all-barren chunk-grain verdict COULD have
#: fired, from the same arithmetic as the bound grains: `DEFAULT_ITEM_STOP`'s
#: all-barren crossing. The chunk grain is deliberately UNBOUND (there is no
#: tracker and no policy at that grain), and this constant exists only so the
#: replay can say whether a verdict would have fired -- on `chunk_size=2000`
#: with `overlap=200` that is ten chunks, i.e. about 18,000 reduced characters,
#: so on a page under roughly that size the grain is inert by arithmetic.
_CHUNK_GRAIN_CROSSING = 10

#: Topic on the `SearchOutcome` rows the completion probe emits (Phase 1B).
#: Deliberately not one of the topics any existing consumer selects on, so the
#: row is visible to cost accounting and inert to search memory, goal
#: evaluation, and target-outcome annotation.
PROBE_SEARCH_TOPIC = "completion_probe"


def load_seed_control_decisions(
    seed_tables_dir: Optional[str],
) -> List[Dict[str, Any]]:
    """Read a previous run's control ledger so a resumed run appends to it.

    Resolution mirrors :meth:`QuestionPipeline._load_seed_universe_estimate`:
    the caller points at ``<run>/answers/tables`` and the ledger lives one
    level up.  Nothing here rewrites, renumbers, or deduplicates a record --
    the prefix is carried forward exactly as the earlier run wrote it, which
    is what makes a decision ID stable across an interrupted run.
    """

    if not seed_tables_dir:
        return []

    candidates: List[Path] = []
    for raw in str(seed_tables_dir).split(os.pathsep):
        if not raw.strip():
            continue
        path = Path(raw)
        candidates.extend(
            root / CONTROL_LEDGER_FILENAME
            for root in (path, path.parent, path.parent.parent)
        )

    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        records = (
            payload.get("control_decisions")
            if isinstance(payload, dict)
            else payload
        )
        if not isinstance(records, list):
            continue
        return [record for record in records if isinstance(record, dict)]
    return []


def _normalize_mode(value: str) -> str:
    return str(value or "").strip().replace("-", "_")


def _normalize_pipeline_mode(value: str) -> str:
    mode = _normalize_mode(value or PIPELINE_MODE_ANSWER)
    if mode not in {PIPELINE_MODE_ANSWER, PIPELINE_MODE_TABLE_FILL}:
        raise ValueError("pipeline_mode must be 'answer' or 'table_fill'")
    return mode


def _normalize_task_goal_mode(value: str) -> str:
    mode = _normalize_mode(value or TASK_GOAL_OFF)
    if mode == "table_coverage":
        return TASK_GOAL_TABLE_FILL
    if mode not in {TASK_GOAL_OFF, TASK_GOAL_TABLE_FILL}:
        raise ValueError("task_goal_mode must be 'off' or 'table_fill'")
    return mode


def _normalize_numeric_candidate_mode(value: str) -> str:
    mode = _normalize_mode(value or "parsed")
    if mode not in {"off", "parsed", "all"}:
        raise ValueError("numeric_candidate_mode must be 'off', 'parsed', or 'all'")
    return mode


def _normalize_best_guess_mode(value: str) -> str:
    mode = _normalize_mode(value or "llm")
    if mode not in {"off", "local", "llm"}:
        raise ValueError("best_guess_mode must be 'off', 'local', or 'llm'")
    return mode


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _code_provenance(repo_root: Path) -> Dict[str, Any]:
    """The commit this process is running, and whether the tree was dirty.

    RECORDED BY THE PIPELINE, NOT BY THE LAUNCHER. The `code_snapshot/`
    directory that carries this today is written by per-run shell scripts under
    `experiments/runs/`, so a run launched by a script that predates the
    convention -- or by no script at all -- has no recoverable code version.
    That is not hypothetical: `attempt3` has no `GIT_HEAD`, so its code version
    is unrecoverable and every graph-derived number from it has to be quoted
    without one. A reproducibility mechanism that each new launcher has to
    remember is a mechanism that is absent exactly when someone improvises.

    A bare commit SHA would be a lie for most of this project's runs, because
    most of the work is uncommitted while it runs. `dirty` and the porcelain
    status are therefore recorded alongside it, and `dirty: true` means the SHA
    names the parent commit rather than the code that ran.

    Never inferred and never backfilled: when git is unavailable this returns
    `available: false` with the reason, because an inferred version is exactly
    the fabrication this record exists to prevent.
    """

    def _git(*args: str) -> Optional[str]:
        try:
            done = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"__error__{type(exc).__name__}: {exc}"
        if done.returncode != 0:
            return None
        return done.stdout

    head = _git("rev-parse", "HEAD")
    if head is None or str(head).startswith("__error__"):
        return {
            "available": False,
            "reason": (
                str(head).removeprefix("__error__")
                if head
                else "git rev-parse HEAD failed; this may not be a git checkout"
            ),
        }
    status = _git("status", "--porcelain") or ""
    if str(status).startswith("__error__"):
        status = ""
    dirty_lines = [line for line in status.splitlines() if line.strip()]
    return {
        "available": True,
        "commit": head.strip(),
        "dirty": bool(dirty_lines),
        "dirty_file_count": len(dirty_lines),
        "status_porcelain": dirty_lines,
        "note": (
            "commit names the PARENT of the code that ran; the tree was dirty"
            if dirty_lines
            else "tree was clean; commit names the code that ran"
        ),
    }


def _orphan_interval(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
) -> Dict[str, Any]:
    """The ORPHAN meter's additive counters over one interval, and nothing else.

    ONLY THE ADDITIVE COUNTERS ARE SUBTRACTED, and every non-numeric field is
    dropped rather than carried whole. Carrying them looks harmless and is not:
    `error_class` is a sticky first-error label, and
    `reward.aggregate_round_cost` counts one error per record carrying a
    non-empty one -- so one orphaned error carried onto every strategy's
    residual would inflate the run's reported error count by the number of
    strategies. `llm_model`/`llm_models` would name a model for an interval that
    may not have used it, for the same reason.
    """

    numeric = (
        "provider_calls",
        "provider_credits",
        "returned_hits",
        "fetched_bytes",
        "llm_calls",
        "prompt_tokens",
        "completion_tokens",
        "retries",
        "wall_ms",
    )
    out: Dict[str, Any] = {
        key: (current.get(key) or 0) - (baseline.get(key) or 0) for key in numeric
    }
    out["version"] = current.get("version", COST_ACCOUNTING_VERSION)
    out["error_class"] = ""
    out["llm_model"] = ""
    out["llm_models"] = []
    out["provider_credits_available"] = bool(
        current.get("provider_credits_available")
    )
    out["started_at"] = baseline.get("ended_at") or 0.0
    out["ended_at"] = current.get("ended_at") or 0.0
    return out


def _ingestion_ledger(owner: Any) -> Dict[str, Dict[str, Any]]:
    """Per-source extraction outcomes, or an empty mapping if the owner has none.

    Module-level for the same reason as `_coverage_denominator`, and added
    after the same mistake was made a fourth time: `_ground_field_provenance`
    is bound onto stub objects that carry rows and chunk texts and nothing
    else, so ANY new `self.<attribute>` inside it breaks them. Attributes are
    as unsafe as methods there; only module-level access travels with the
    function.
    """

    return getattr(owner, "source_ingestion_ledger", None) or {}


def _coverage_denominator(
    owner: Any,
    observed_source_ids: set[str],
) -> tuple[List[str], str]:
    """The population a coverage figure is reported against, and its name.

    THE PERMANENT GUARD, AND IT IS MODULE-LEVEL ON PURPOSE.

    `_ground_field_provenance` runs against objects that supply rows and chunk
    texts directly and have no `papers_dir` -- the export-hook test, the
    corpus-root tests, and any caller owning its own corpus. Three separate
    times a new enumeration inside that method raised `AttributeError` on them:
    the chunk-cache keying, the accepted-source ledger, and then a `self.`-bound
    version of this very helper, which recreated the defect while fixing it.

    That third time is the argument for this shape. A METHOD does not travel
    with the function -- a caller binding `_ground_field_provenance` onto a stub
    gets the function but not its helper, so every new helper is a new way to
    break the same callers. A module-level function travels with the module and
    cannot be missed. Reach for `getattr` on the owner here, never on `self` at
    the call site.

    Returns the denominator AND its name, so a coverage figure computed against
    a fallback population can never be silently compared with one computed
    against the accepted set.
    """

    if getattr(owner, "papers_dir", None) is not None:
        records = getattr(owner, "_source_records_by_id", None)
        if callable(records):
            return sorted(records()), "accepted_sources_in_papers_dir"
    return sorted(observed_source_ids), "sources_observed_in_rows_no_papers_dir"


class QuestionPipeline:
    """Iterative search + KG build + GASL answer loop for one question."""

    #: Whether control decisions are recorded.  Recording is observation only:
    #: with it off the pipeline must take the identical action sequence, which
    #: is what the A/A inertness check asserts.  It is the single named flag
    #: this instrumentation is allowed to have.
    control_ledger_enabled: bool = True

    #: Whether per-action costs are recorded (Phase 1B).  Recording is
    #: observation only: nothing in the pipeline branches on a cost field, and
    #: with this off the run must take the identical action sequence, which is
    #: what the A/A inertness check asserts.  Cost *fields* remain present on
    #: every observation either way, as typed zeros, so a consumer never has to
    #: distinguish "absent" from "free".  It is the single named flag this
    #: instrumentation is allowed to have.
    cost_accounting_enabled: bool = True

    def __init__(
        self,
        config: PipelineConfig,
        *,
        llm=None,
        search_fn: Optional[
            Callable[[str, Optional[int]], List[Dict[str, Any]]]
        ] = None,
        scrape_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        extractor_factory: Optional[Callable[[DomainSchema], Any]] = None,
        gasl_runner: Optional[Callable[[nx.DiGraph, Dict[str, Any], str], Dict[str, Any]]] = None,
    ):
        self.config = config
        config.pipeline_mode = _normalize_pipeline_mode(config.pipeline_mode)
        config.task_goal_mode = _normalize_task_goal_mode(config.task_goal_mode)
        if (
            config.pipeline_mode == PIPELINE_MODE_ANSWER
            and config.task_goal_mode != TASK_GOAL_OFF
        ):
            config.pipeline_mode = PIPELINE_MODE_TABLE_FILL
        if config.pipeline_mode == PIPELINE_MODE_TABLE_FILL:
            if config.answer_mode == "natural":
                config.answer_mode = "table"
            if config.task_goal_mode == TASK_GOAL_OFF:
                config.task_goal_mode = TASK_GOAL_TABLE_FILL
            if config.search_frontier_mode == "batch":
                config.search_frontier_mode = "persistent"
            if config.task_goal_search_tasks <= 0:
                config.task_goal_search_tasks = 4

        if llm is not None:
            self.llm = llm
        elif config.model:
            self.llm = ArgoBridgeLLM(model=config.model)
        else:
            self.llm = ArgoBridgeLLM()
        # Which model serves which call site. Call sites declare a typed tier;
        # this fixes what each tier resolves to for this run, and
        # `_finalize` records it so a run's costs stay interpretable.
        attach_tier_policy(
            self.llm,
            TierPolicy(
                reasoning_model=str(getattr(self.llm, "model", "") or ""),
                fast_model=(config.fast_model or DEFAULT_FAST_MODEL),
            ),
        )
        if self.cost_accounting_enabled:
            # At the provider boundary, not at the call sites: extraction and
            # GASL never pass through `llm_utils`, and `schema_synthesis` hands
            # `llm.call_async` straight to the extractor factory.  Instrumenting
            # the client records all three; instrumenting call sites would not.
            instrument_client(self.llm)
        self._search_fn = search_fn or self._default_search_fn
        self._uses_default_search = search_fn is None
        self.search_provider_batch = self._search_batch_metadata()
        self._scrape_fn = scrape_fn or self._default_scrape_fn
        self._extractor_factory = extractor_factory or self._default_extractor_factory
        self._gasl_runner = gasl_runner or self._default_gasl_runner

        self.out = Path(config.output_dir)
        self.graphs_dir = self.out / "graphs"
        self.papers_dir = self.out / "fetched_papers"
        self.answers_dir = self.out / "answers"
        self.tables_dir = self.answers_dir / "tables"
        self.derived_dir = self.answers_dir / "derived"
        self.goals_dir = self.answers_dir / "goals"
        self.table_specs_dir = self.answers_dir / "table_specs"
        self.judgments_dir = self.answers_dir / "judgments"
        for d in (self.graphs_dir, self.papers_dir, self.answers_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.graph = nx.DiGraph()
        self.schema: Optional[DomainSchema] = None
        self.extractor = None
        self.seen_urls: set[str] = load_seen_urls(config.seed_sources_dir)
        self.queries_used: List[str] = []
        self.paper_count = 0
        self.rounds: List[Dict[str, Any]] = []
        self.table_exports: List[Dict[str, Any]] = []
        self.search_frontier = SearchFrontier(mode=config.search_frontier_mode)
        #: The `SearchOutcome`s of the strategy episode that just completed,
        #: written by the `on_search` hook. It replaces `last_search_batch`,
        #: whose `SearchBatch` existed to carry a wave between two deleted loops.
        self.last_search_outcomes: List[SearchOutcome] = []
        self.last_prompt_arm_summaries: List[Dict[str, Any]] = []
        self.search_provider_error = ""
        self.search_outcomes: List[Dict[str, Any]] = []
        config.evidence_corpus_roots = tuple(
            str(root).strip()
            for root in (config.evidence_corpus_roots or ())
            if str(root).strip()
        )
        if config.source_relevance_mode not in {"off", "focused", "all"}:
            raise ValueError("source_relevance_mode must be 'off', 'focused', or 'all'")
        config.gasl_graph_scope = _normalize_mode(config.gasl_graph_scope)
        if config.gasl_graph_scope not in {"auto", "full", "new_sources"}:
            raise ValueError("gasl_graph_scope must be 'auto', 'full', or 'new_sources'")
        if config.gasl_new_source_hops < 0:
            raise ValueError("gasl_new_source_hops must be nonnegative")
        if config.gasl_source_seed_limit < 0:
            raise ValueError("gasl_source_seed_limit must be nonnegative")
        config.numeric_candidate_mode = _normalize_numeric_candidate_mode(
            config.numeric_candidate_mode,
        )
        config.best_guess_mode = _normalize_best_guess_mode(config.best_guess_mode)
        config.page_best_guess_mode = _normalize_best_guess_mode(
            config.page_best_guess_mode
        )
        if config.best_guess_max_tasks is not None and config.best_guess_max_tasks < 0:
            raise ValueError("best_guess_max_tasks must be nonnegative or None")
        if config.best_guess_evidence_chars <= 0:
            raise ValueError("best_guess_evidence_chars must be positive")
        if config.best_guess_llm_batch_size <= 0:
            raise ValueError("best_guess_llm_batch_size must be positive")
        if (
            config.best_guess_llm_timeout_sec is not None
            and config.best_guess_llm_timeout_sec <= 0
        ):
            raise ValueError("best_guess_llm_timeout_sec must be positive")
        if config.pipeline_mode == PIPELINE_MODE_TABLE_FILL:
            if config.answer_mode != "table":
                raise ValueError("table_fill pipeline_mode requires answer_mode='table'")
            if config.task_goal_mode != TASK_GOAL_TABLE_FILL:
                raise ValueError(
                    "table_fill pipeline_mode requires task_goal_mode='table_fill'"
                )
            if config.search_frontier_mode != "persistent":
                raise ValueError(
                    "table_fill pipeline_mode requires search_frontier_mode='persistent'"
                )
        if config.task_goal_mode != TASK_GOAL_OFF and config.answer_mode != "table":
            raise ValueError("table-fill goals require answer_mode='table'")
        if config.task_goal_mode != TASK_GOAL_OFF and config.task_goal_search_tasks <= 0:
            raise ValueError("table-fill goals require search tasks")
        if config.completion_probe_tasks < 0:
            raise ValueError("completion_probe_tasks must be nonnegative")
        if config.completion_probe_results <= 0:
            raise ValueError("completion_probe_results must be positive")
        if config.completion_probe_waves < 0:
            raise ValueError("completion_probe_waves must be nonnegative")
        if config.target_deficit_evolutions_per_round <= 0:
            raise ValueError(
                "target_deficit_evolutions_per_round must be positive"
            )
        if config.target_prompt_arms_per_evolution <= 0:
            raise ValueError("target_prompt_arms_per_evolution must be positive")
        if config.target_queries_per_prompt_arm <= 0:
            raise ValueError("target_queries_per_prompt_arm must be positive")
        self.seed_tables: SeedTables = load_seed_tables(config.seed_tables_dir)
        self.table_spec: TableSpec = load_table_spec_with_seed_tables(
            self.seed_tables.rows_by_name,
            config.seed_tables_dir,
            config.table_spec_path,
        )
        self.table_spec_id = self._table_spec_id(self.table_spec)
        self._required_columns_by_table = self.table_spec.required_columns_by_table()
        self._all_columns_by_table = self.table_spec.all_columns_by_table()
        self._key_columns_by_table = self.table_spec.key_columns_by_table()
        self._cold_start_anchors_by_table = (
            self.table_spec.cold_start_anchors_by_table()
        )
        # Seed-adjacent observed specs intentionally widen the final table
        # contract with every column a prior GASL row happened to emit. That
        # widened map is useful for prompt context and row-gap discovery, but
        # cannot decide whether an explicitly declared table has acquired its
        # first substantive value: an alias key such as ``calendar_year``
        # would make a key-only table look warm. Preserve the explicit spec's
        # column identity for that decision. Older continuations without an
        # explicit spec fall back to the only contract they have.
        explicit_table_spec = load_table_spec(config.table_spec_path)
        explicit_columns = explicit_table_spec.all_columns_by_table()
        self._cold_start_columns_by_table = {
            name: list(
                explicit_columns.get(name)
                or self._all_columns_by_table.get(name, ())
            )
            for name in self._cold_start_anchors_by_table
        }
        self._best_guess_columns_by_table = self.table_spec.best_guess_columns_by_table()
        self._completeness_columns_by_table = (
            self.table_spec.completeness_columns_by_table()
        )
        # The guard that was here read `if not self.table_spec.is_empty`, which
        # tests whether the spec holds tables -- not whether it yielded any
        # columns. Every column accessor on TableSpec filters on
        # `table.deliverable`, so a spec whose tables are all non-deliverable
        # reports `is_empty is False` and hands back `{}`, and the fallback it
        # was guarding could never fire. On the live earthquake run that is
        # exactly what happened: the one table the run exists to produce is
        # `deliverable: false` in all three rounds, so `table_schemas` was `{}`,
        # every row signature fell through to the row-key path, and the round
        # manifest certified 303 of 303 rows complete with no gaps against zero
        # required columns.
        #
        # `TABLE_REQUIRED_COLUMNS` is itself `{}` (line above), so there is no
        # fallback to switch to and the honest response is not a substitution
        # but a declaration: record what the spec yielded and why, so a vacuous
        # schema is distinguishable downstream from a satisfied one.
        self.table_schema_disclosure: Dict[str, Any] = (
            self.table_spec.column_yield_diagnostic()
        )
        if not self.table_schema_disclosure["usable_schema"]:
            print(
                "  [table-spec] WARNING: no usable column schema "
                f"({self.table_schema_disclosure['status']}): "
                f"{self.table_schema_disclosure['reason']}. "
                "Row completeness and fill deficits computed against this spec "
                "cannot be falsified; see table_schema_disclosure in the round "
                "records."
            )
        self.goal_tracker = (
            TableFillGoalTracker(
                table_schemas=self._required_columns_by_table,
                table_columns=self._all_columns_by_table,
                table_key_columns=self._key_columns_by_table,
                cold_start_columns=self._cold_start_columns_by_table,
                cold_start_anchors=self._cold_start_anchors_by_table,
                best_guess_columns=self._best_guess_columns_by_table,
            )
            if config.task_goal_mode == TASK_GOAL_TABLE_FILL
            else None
        )
        self.goal_universe_estimate: Dict[str, Any] = {"status": "missing"}
        self.goal_discovery_sources: List[Dict[str, Any]] = []
        #: Tables the answer layer was asked to compile this round, as opposed
        #: to working variables a traversal left behind. Empty until a GASL
        #: export runs, which is why every consumer treats empty as "no opinion"
        #: and falls back rather than concluding nothing is deliverable.
        self._answer_view_table_names: set[str] = set()
        self._seen_goal_discovery_source_ids: set[str] = set()
        self._validate_seed_tables_declared_by_spec()
        self._ensure_declared_seed_tables()
        self._seed_table_inputs_consumed = False
        self._active_seed_migrations: List[Dict[str, Any]] = []
        self.goal_universe_estimate = self._load_seed_universe_estimate(
            config.seed_tables_dir,
        )
        self.completion_state: Dict[str, Any] = load_seed_completion_state(
            config.seed_tables_dir,
        )
        if config.round_offset is not None and config.round_offset < 0:
            raise ValueError("round_offset must be nonnegative")
        self.round_offset = (
            config.round_offset
            if config.round_offset is not None
            else self.seed_tables.next_round_index
        )

        seed_source_records = load_seed_source_records(config.seed_sources_dir)
        seed_search_outcomes = self._seed_search_outcome_records(
            seed_source_records,
            load_seed_search_outcomes(config.seed_sources_dir),
        )
        self.search_frontier.mark_seen(self._seed_search_tasks(seed_source_records))
        self.search_outcomes.extend(seed_search_outcomes)
        self.search_frontier.mark_seen(
            self._search_outcome_tasks(seed_search_outcomes)
        )
        self.seed_frontier_tasks = load_seed_frontier_tasks(
            config.seed_frontier_path,
        )
        self._record_goal_discovery_sources(seed_source_records)
        self._export_seed_sources(seed_source_records)
        self._export_seed_search_outcomes(seed_search_outcomes)
        self.search_memory = SearchMemory.from_outcomes(self.search_outcomes)
        self._persist_search_memory()
        self.goal_states: List[Dict[str, Any]] = []
        self.derived_table_exports: List[Dict[str, Any]] = []
        self.last_derived_table_exports: List[Dict[str, Any]] = []
        self.best_guess_exports: List[Dict[str, Any]] = []
        self.last_best_guess_exports: List[Dict[str, Any]] = []
        self.last_best_guess_state: Dict[str, Any] = {}
        self.reward_exports: List[Dict[str, Any]] = []
        self.last_reward_exports: List[Dict[str, Any]] = []
        self.last_reward_report: Dict[str, Any] = {}
        #: Reward credit already paid, carried across rounds (Phase 3A).  A
        #: criterion is a datapoint once and a source is harvested once; without
        #: this the same yield is re-credited at every artifact write.
        self.reward_credit_ledger = CreditLedger()
        #: Phase 3B routing. `ArmRoutingMode.CONTRAST` (the default) is
        #: deterministic and needs no RNG; this is only ever consumed by
        #: `ArmRoutingMode.RANDOM`, 3B's ablation control, so a run under the
        #: shipped default never touches it.
        self._arm_routing_rng = random.Random(config.arm_routing_seed)
        self.seed_best_guess_rows: List[Dict[str, Any]] = load_seed_best_guess_rows(
            config.seed_tables_dir,
        )
        self._bootstrap_papers: List[Dict[str, Any]] = []
        self._gasl_source_seed_nodes: List[Dict[str, Any]] = []

        # -- control layer (Phase 1C) ----------------------------------- #
        # The ledger is append-only.  Every write goes through
        # ``_append_control_decision``; no other code path touches the list.
        self.control_policy = StaticTableFillPolicy()
        self.control_decisions: List[Dict[str, Any]] = list(
            load_seed_control_decisions(config.seed_tables_dir)
        )
        self.seeded_control_decision_count = len(self.control_decisions)
        self.criteria_snapshot: CriteriaSnapshot = empty_snapshot()
        self._round_ledger_mark = len(self.control_decisions)
        #: The previous scored round's `after` snapshot, carried forward so the
        #: next round's `before` IS it rather than a fresh projection of some
        #: other row set. See `_write_reward_exports` for why re-projecting
        #: leaked credit into an interval no round scored.
        self._last_reward_after: Optional[CriteriaSnapshot] = None

        # -- cost accounting (Phase 1B) --------------------------------- #
        # One record per action, never a running total: summing is 3A's
        # business and its attribution rules decide which sums are legitimate.
        self.cost_records: List[Dict[str, Any]] = []
        #: The whole run's orphan baseline, taken once and never rebased, so the
        #: partition identity has both ends. `_strategy_orphan_baseline` is the
        #: one that moves.
        self._run_orphan_baseline = orphan_meter().snapshot().to_dict()
        #: Round currently issuing completion probes, or None outside one.
        #: Declared here rather than relied on via `getattr` alone so the
        #: attribute exists for the whole object lifetime.
        self._probe_round_index: Optional[int] = None
        #: Per-accepted-source field-scope evaluation outcome from the last
        #: grounding pass. Emitted on the round record so "examined and found
        #: nothing" and "never examined" are separable in the artifacts.
        self.last_field_provenance_ledger: Dict[str, Any] = {}
        #: Per-source extraction outcome, keyed by source id. Written by
        #: `_ingest_papers` at the moment text enters the extractor, so
        #: "extraction ran" never depends on what extraction returned.
        self.source_ingestion_ledger: Dict[str, Dict[str, Any]] = {}

        # -- the acquisition composition (Phase 4E-c) -------------------- #
        # run > strategy > search > page, one `Episode.run_async` call, in
        # `run()`. docs/ACQUISITION_LOOP.md. Nothing here sequences phases and
        # nothing consults a controller between units.
        #
        # The crediter is built ONCE, from the table contract as it stands now,
        # with two consequences stated rather than left to a run to discover: a
        # column the planner adds to the observed spec mid-run never credits,
        # and the declared facet set is fixed at run start. Its spec digest is
        # emitted on every record so a mid-run spec rewrite is legible against a
        # denominator that did not move.
        self.crediter = ColumnProjection(self.table_spec)
        self.source_budget = SourceBudget(limit=int(config.max_papers))
        self.provider_health = ProviderHealth()
        self.run_termination = RunTermination()
        self.acquisition = AcquisitionController(
            crediter=self.crediter,
            budget=self.source_budget,
            health=self.provider_health,
            termination=self.run_termination,
        )
        #: Per-page surface facts the kernel's frozen record cannot carry:
        #: credit-rule attribution, chunk encounters, exclusions,
        #: counterfactuals, and the gate block. Written durably per page.
        self.acquisition_page_details: List[Dict[str, Any]] = []
        #: How each family's last strategy instance ended, which is the input to
        #: the re-open rule. `exhausted` means the queue was momentarily empty
        #: and the family was never abandoned; `yield_stop` means its own
        #: verdict abandoned it and it stays closed.
        self._strategy_ends: Dict[str, str] = {}
        #: Seed phrasings a proposed strategy suggested, forwarded to the arm
        #: planner as prompt context for that strategy's own planning call.
        self._strategy_seed_queries: Dict[str, List[str]] = {}
        self._page_detail_path = self.answers_dir / "acquisition_page_detail.jsonl"
        self._episodes_path = self.answers_dir / "acquisition_episodes.json"
        #: In-flight per-search state the hooks close over. Keyed by task id and
        #: popped by the `on_search` hook, so nothing accumulates across the run.
        self._open_outcomes: Dict[str, SearchOutcome] = {}
        self._open_sources: Dict[str, PageSource] = {}
        self._accepted_papers: List[Dict[str, Any]] = []
        self._episode_records: List[Dict[str, Any]] = []
        self._strategy_proposals: List[Dict[str, Any]] = []
        self._page_guess_reports: List[Dict[str, Any]] = []
        self._pending_followup_outcomes: List[SearchOutcome] = []
        #: Every hook failure, as a typed class. A hook may not raise -- the
        #: driver catches nothing around `on_unit` -- so its failure is recorded
        #: here and on the round record rather than unwinding the record tree.
        self.hook_failures: List[Dict[str, Any]] = []
        self._gate_columns: Optional[List[DeclaredColumn]] = None
        self._gate_contract_digest_value = ""
        self.proposer: Optional[StrategyProposer] = None
        #: THE ONE EXPRESSION THAT MINTS `round_index`, and it is minted once,
        #: at strategy-open time -- before the strategy's pages are fetched,
        #: which is the constraint that rules out reading it at hook time. It is
        #: carried unchanged into `PageSource`, every `SearchTask`, every
        #: `CostRecord`, the round record stem, `seed_tables.next_round_index`
        #: and the reward call, and the hook reads the run episode's own unit
        #: index and asserts agreement rather than recomputing it.
        self._completed_strategies = 0
        self._current_round_index = self._round_label(0)
        self._seen_target_attempts: set[tuple[str, str]] = set()
        self._target_evolution_counts: Counter[str] = Counter()
        #: Rebased per completed strategy, so a per-strategy residual covers the
        #: interval since the previous one rather than the whole run to date.
        self._strategy_orphan_baseline = orphan_meter().snapshot().to_dict()
        self._last_round_index = self.round_offset
        self._harvester = SearchHarvester(
            scrape_fn=self._scrape_fn if config.scrape_search_results else None,
            papers_dir=self.papers_dir,
            seen_urls=self.seen_urls,
            min_paper_length=config.min_paper_length,
            max_paper_length=config.max_paper_length,
            max_extraction_chars_per_paper=config.max_extraction_chars_per_paper,
        )

        # -- path-selection gate (Phase 2B) ----------------------------- #
        # Records on every run; demotes nothing unless configured to.  2A's
        # experiment failed on both of its registered routes, so a shipped
        # default that deleted rows on ``path_score`` would be asserting more
        # than the measurement supports.  Set this to demote.
        self.path_gate_settings = PathGateSettings()

    # ------------------------------------------------------------------ #
    # Cost accounting (Phase 1B)
    # ------------------------------------------------------------------ #
    def _record_cost(self, record: CostRecord) -> None:
        """Append one action's cost.  Never sums, never branches."""
        if not self.cost_accounting_enabled:
            return
        payload = record.to_dict()
        self.cost_records.append(payload)
        try:
            self.papers_dir.mkdir(parents=True, exist_ok=True)
            with (self.papers_dir / "cost_records.jsonl").open(
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(json.dumps(payload, default=str) + "\n")
        except OSError:  # pragma: no cover - recording never breaks the run
            pass

    def _cost_scope(
        self,
        kind: str,
        *,
        observation_id: str = "",
        round_index: int = 0,
    ):
        """Open a meter for one action, or an inert placeholder when off."""
        if not self.cost_accounting_enabled:
            return nullcontext(None)
        return cost_scope(
            kind,
            observation_id=observation_id,
            round_index=round_index,
            sink=self._record_cost,
        )

    def _open_prompt_log(self, round_index: int | str) -> None:
        """Start recording prompts for one round."""

        self._close_prompt_log()
        self._prompt_log_token = prompt_log_open(
            self.out / "prompts" / self._artifact_stem(round_index),
            round_index=round_index,
        )

    def _close_prompt_log(self) -> None:
        token = getattr(self, "_prompt_log_token", None)
        if token is not None:
            prompt_log_close(token)
            self._prompt_log_token = None

    def _round_cost_records(self, round_index: int) -> List[Dict[str, Any]]:
        """This round's cost records.  A filter, not a sum."""
        return [
            record
            for record in self.cost_records
            if _safe_int(record.get("round_index"), -1) == round_index
        ]

    def _provider_reported_usage(self) -> Dict[str, Any]:
        """The clients' own accumulators, for cross-checking the records.

        This is a **reference reading, never the cost basis**.  It walks the
        tier clones as well as the base client because `for_tier` memoizes a
        separate client per model and each keeps its own `usage`: reading
        `self.llm.usage` alone would report a FAST call site as free.  The
        recorded basis stays the per-call event.
        """
        clients: List[Any] = [self.llm]
        clients.extend((getattr(self.llm, "_tier_clients", None) or {}).values())
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
        per_client: List[Dict[str, Any]] = []
        seen: set[int] = set()
        for client in clients:
            usage = getattr(client, "usage", None)
            if not isinstance(usage, dict) or id(usage) in seen:
                continue
            seen.add(id(usage))
            per_client.append(
                {
                    "model": str(getattr(client, "model", "") or ""),
                    **{key: int(usage.get(key, 0) or 0) for key in totals},
                }
            )
            for key in totals:
                totals[key] += int(usage.get(key, 0) or 0)
        return {"totals": totals, "clients": per_client}

    # `_orphan_cost_delta` is deleted. It measured against the baseline taken
    # when this pipeline was CONSTRUCTED, so it was cumulative over the run --
    # correct for the one record it fed at `_finalize`, and wrong the moment the
    # residual became per-strategy, because every strategy would have been handed
    # the whole run's residual to date and summing them would multiply-count the
    # same spend. It also carried every non-numeric field whole, including the
    # sticky `error_class` that `reward.aggregate_round_cost` counts one error
    # per record for. `_orphan_interval` replaces it: additive counters only,
    # over an interval, rebased on a single snapshot.

    # ------------------------------------------------------------------ #
    # Default real dependencies (swappable by a caller supplying its own)
    # ------------------------------------------------------------------ #
    def _search_batch_metadata(
        self,
        requested_results: Optional[int] = None,
    ) -> Dict[str, Any]:
        """The actual search adapter's batch contract, never a processing cap."""

        if self._uses_default_search:
            return firecrawl_search_batch_metadata(requested_results)
        return {
            "provider": "injected_search_function",
            "api_version": None,
            "endpoint": None,
            "batch_size_owner": "injected_search_function",
            "requested_batch_size": requested_results,
            "provider_max_batch_size": None,
        }

    def _default_search_fn(
        self,
        query: str,
        max_results: Optional[int],
    ) -> List[Dict[str, Any]]:
        api_key = self.config.firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY")
        if not api_key:
            raise RuntimeError(
                "No Firecrawl API key. Set --firecrawl-api-key or FIRECRAWL_API_KEY."
            )
        search_kwargs: Dict[str, Any] = {}
        if max_results is not None:
            search_kwargs["max_results"] = int(max_results)
        return search_papers(
            query=query,
            api_key=api_key,
            raise_on_error=True,
            scrape_results=not self.config.scrape_search_results,
            **search_kwargs,
        )

    def _probe_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """The completion probe's search, now with an outcome row of its own.

        Before 1B this was the one provider call the record never saw. When
        ``_uses_default_search`` is true the branch below issues its own
        ``search_papers`` and bypasses ``_search_fn`` entirely, so no wrapper
        around that attribute observes it; and ``estimator.py`` emits no
        ``SearchOutcome`` either. Probe spend was therefore invisible to reward
        **structurally**, not merely unrecorded — and a reward that cannot see a
        path's cost prefers that path for being free, which is the exact bias
        this phase exists to remove.

        The row carries ``topic="completion_probe"``. Every existing consumer of
        ``search_outcomes`` selects ``target_deficit`` or ``goal_catalog``
        (`SearchMemory.from_outcomes`, `goals.evaluate`,
        `_search_outcome_matches_target`, `_annotate_recent_target_outcomes`),
        so the row is inert to all of them; the A/A ablation is what checks
        that rather than the reasoning.

        **A PROVIDER CALLER OUTSIDE THE ACQUISITION COMPOSITION, DISCLOSED
        RATHER THAN MERELY ABSENT.** The probe issues provider calls and
        composes no ``Episode``, which looks like an acquisition surface that
        escaped the composition and is not one: it acquires no unit and credits
        nothing, because it writes no source by construction. The tree already
        types that -- ``SearchTask.yields_sources=False`` -- so it belongs in a
        cost denominator and must stay out of a yield denominator, and it has
        its own ``PROBE_SEARCH`` cost scope for exactly that reason.
        """
        task = SearchTask(
            query=query,
            topic=PROBE_SEARCH_TOPIC,
            expansion_op="completion_probe",
            # The round this probe actually ran in, set by
            # `_estimate_task_goal_universe` around the estimator call. Falls
            # back to 0 only when no round is in scope (the "seed" bootstrap
            # label), which is the same case `_pipeline_round` returns None for.
            round_index=_safe_int(getattr(self, "_probe_round_index", None), 0),
            producer_class="completion_probe",
            # Structurally incapable of harvesting: this path issues a provider
            # call to measure the search space and never writes a source, so it
            # holds zero `candidate_source_outcomes` and zero acceptances by
            # construction. It belongs in a cost denominator and must be kept
            # out of a yield denominator, and this is the typed way to say so.
            yields_sources=False,
        )
        outcome = SearchOutcome.for_task(task)
        outcome.provider_batch = self._search_batch_metadata(max_results)
        failure: Optional[BaseException] = None
        results: List[Dict[str, Any]] = []
        with self._cost_scope(
            ObservationKind.PROBE_SEARCH.value,
            observation_id=task.id,
        ) as meter:
            try:
                results = self._probe_search_results(query, max_results)
            except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised
                failure = exc
                outcome.error = str(exc)
                outcome.skip("search_failed")
                if meter is not None:
                    meter.add_provider_call(error_class=classify_error(exc))
            else:
                if meter is not None:
                    meter.add_provider_call(returned_hits=len(results))
                outcome.firecrawl_hits = len(results)
                for rank, result in enumerate(results, start=1):
                    outcome.search_result_observations.append(
                        search_result_observation(result, rank=rank)
                    )
        self._record_probe_outcome(outcome, meter)
        if failure is not None:
            raise failure
        return results

    def _probe_search_results(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """The probe's provider call, exactly as it was before 1B."""
        if not self._uses_default_search:
            return self._search_fn(query, max_results)

        api_key = self.config.firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY")
        if not api_key:
            raise RuntimeError(
                "No Firecrawl API key. Set --firecrawl-api-key or FIRECRAWL_API_KEY."
            )
        return search_papers(
            query=query,
            api_key=api_key,
            max_results=max_results,
            raise_on_error=True,
            scrape_results=False,
        )

    def _record_probe_outcome(self, outcome: SearchOutcome, meter) -> None:
        """Put the probe's outcome where every other search outcome lives.

        In `self.search_outcomes` and in `search_outcomes.jsonl`, so
        `record_search_outcomes` and `_rewrite_search_outcomes` pick it up with
        no change to either.
        """
        if not self.cost_accounting_enabled:
            return
        if meter is not None:
            outcome.cost = meter.snapshot().to_dict()
        record = outcome.to_dict()
        self.search_outcomes.append(record)
        try:
            self.papers_dir.mkdir(parents=True, exist_ok=True)
            with (self.papers_dir / "search_outcomes.jsonl").open(
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(json.dumps(record, default=str) + "\n")
        except OSError:  # pragma: no cover - recording never breaks the run
            pass

    def _default_scrape_fn(self, url: str) -> Optional[Dict[str, Any]]:
        api_key = self.config.firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY")
        if not api_key:
            raise RuntimeError(
                "No Firecrawl API key. Set --firecrawl-api-key or FIRECRAWL_API_KEY."
            )
        return download_paper_content(url, api_key)

    def _default_extractor_factory(self, schema: DomainSchema):
        return create_domain_extractor_from_schema(
            schema,
            llm_func=for_tier(self.llm, EXTRACTION_TIER).call_async,
            num_refine_turns=1,
            self_refine=self.config.self_refine,
        )

    def _default_gasl_runner(
        self, graph: nx.DiGraph, metadata: Dict[str, Any], state_file: str
    ) -> Dict[str, Any]:
        adapter = NetworkXAdapter(graph, graph_metadata=metadata)
        executor = GASLExecutor(
            adapter,
            self.llm,
            state_file,
            job_id=self._gasl_job_id(state_file),
        )
        self._seed_gasl_source_nodes(executor)
        self._seed_gasl_table_inputs(executor)
        return executor.run_hypothesis_driven_traversal(
            self._gasl_question(), self.config.max_gasl_iterations
        )

    def _seed_gasl_source_nodes(self, executor: GASLExecutor) -> None:
        if not self._gasl_source_seed_nodes:
            return

        contract = make_contract(
            payload_kind="nodes",
            data=self._gasl_source_seed_nodes,
            label_field="data.entity_name",
            scope="current_round_new_sources",
            usable_by=["PROCESS", "GRAPHWALK", "SHOW", "SELECT"],
            grain_type="node",
            grain_keys=["id"],
            multiplicity_preserved=True,
            notes=[
                "Nodes directly evidenced by papers accepted in the current "
                "round; use before broad graph FIND commands.",
            ],
        )
        executor.state_manager.store_variable_data(
            ROUND_SOURCE_NODES_VAR,
            list(self._gasl_source_seed_nodes),
            store_in_state=True,
            store_in_context=True,
            description=(
                "Current-round source-evidenced graph nodes. Start table-fill "
                "GRAPHWALK commands from this list before broad FIND fallbacks."
            ),
            contract=contract,
        )

    def _seed_gasl_table_inputs(self, executor: GASLExecutor) -> None:
        self._active_seed_migrations = []
        if not self._seed_table_migrations_available():
            return

        for migration in self.table_spec.migrations:
            source_table_name = migration.from_table
            target_table = self.table_spec.tables.get(migration.to_table)
            if target_table is None:
                continue

            source_rows = self.seed_tables.rows_by_name.get(source_table_name, [])
            rows: List[Dict[str, Any]] = []
            for index, row in enumerate(source_rows):
                if not isinstance(row, dict):
                    continue
                match = self._seed_row_match(
                    row,
                    target_table,
                    migration=migration,
                )
                if not match.get("matches"):
                    continue
                rows.append(
                    {
                        **row,
                        "_seed_table": source_table_name,
                        "_seed_source_table": source_table_name,
                        "_seed_target_table": migration.to_table,
                        "_seed_row_index": index,
                        "_seed_match_columns": match["matched_columns"],
                        "_seed_unmatched_required_columns": match[
                            "unmatched_required_columns"
                        ],
                    }
                )
            if not rows:
                continue

            variable_name = migration.input_variable_name()
            self._active_seed_migrations.append(migration.to_dict())
            notes = [
                f"Rows exported by {source_table_name} in a prior "
                f"table-fill run and prefiltered as candidates for "
                f"{migration.to_table}.",
                "Candidate rows may be dropped when they do not satisfy "
                "the destination table contract.",
                migration.instructions,
            ]
            contract = make_contract(
                payload_kind="rows",
                data=rows,
                scope="prior_exported_table_rows",
                usable_by=["PROCESS", "SHOW", "SELECT"],
                grain_type="seed_table_row",
                grain_keys=["_seed_table", "_seed_row_index"],
                multiplicity_preserved=False,
                notes=[note for note in notes if note],
            )
            executor.state_manager.store_variable_data(
                variable_name,
                rows,
                store_in_state=True,
                store_in_context=True,
                description=(
                    f"Prefiltered prior rows from {source_table_name} for "
                    f"migration into {migration.to_table}."
                ),
                contract=contract,
            )

        self._seed_table_inputs_consumed = True

    @staticmethod
    def _gasl_job_id(state_file: str) -> str:
        path = Path(state_file)
        return f"{path.parent.parent.name}_{path.stem}"

    def _gasl_question(self) -> str:
        if self.config.answer_mode != "table":
            return self.config.question
        sections = [
            self.config.question,
            f"TABLE ANSWER MODE:\n{TABLE_ANSWER_INSTRUCTIONS}",
        ]
        table_context = self._table_mode_context()
        if table_context:
            sections.append(table_context)
        return "\n\n".join(sections)

    def _table_mode_context(self) -> str:
        table_names = self._table_target_names()
        if not table_names:
            return ""

        target_lines = "\n".join(f"- {name}" for name in table_names)
        spec_section = ""
        if not self.table_spec.is_empty:
            prompt_context = self.table_spec.prompt_context()
            if self._active_seed_migrations:
                prompt_context["migrations"] = self._active_seed_migrations
            else:
                prompt_context["migrations"] = []
            spec_section = (
                "\n\nTABLE SPEC JSON:\n"
                f"{json.dumps(prompt_context, indent=2)}\n"
                "\nTreat the table spec as the complete final deliverable "
                "contract. If migrations are present, each input_variable is "
                "already prefiltered for its from_table to to_table edge; "
                "PROCESS that variable into the listed to_table before mining "
                "the graph for additional evidence, and drop remaining "
                "candidate rows that do not fit the destination contract."
            )
        return f"""CURRENT TABLE TARGETS:
The run is continuing or scoring these exact table variable names:
{target_lines}
{spec_section}

Reuse an exact listed name whenever its rows match the view you are
materializing. Do not rename a listed table by adding summary words, swapping
token order, or using a near-synonym. Create a new `_table` variable only for a
genuinely separate view that is not covered by a listed target."""

    def _table_target_names(self) -> List[str]:
        if not self.table_spec.is_empty:
            return sorted(
                str(name).strip()
                for name in self.table_spec.deliverable_names()
                if str(name).strip()
            )

        names = {
            str(name).strip()
            for name in self.config.table_variables
            if str(name).strip()
        }
        names.update(self.seed_tables.rows_by_name)
        for target in self.goal_universe_estimate.get("count_targets") or []:
            if not isinstance(target, dict):
                continue
            table_name = str(target.get("target_table") or "").strip()
            if table_name:
                names.add(table_name)
        return sorted(names)

    def _paper_budget_available(self) -> bool:
        return not self.source_budget.exhausted

    def _search_budget_available(self) -> bool:
        has_query_source = (
            self.config.queries_per_round > 0
            or self.search_frontier.pending_count > 0
        )
        return self._paper_budget_available() and has_query_source

    def _ensure_search_ready(self) -> None:
        if not self._uses_default_search or not self._search_budget_available():
            return
        if self.config.firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY"):
            return
        raise RuntimeError(
            "No Firecrawl API key. Set --firecrawl-api-key or FIRECRAWL_API_KEY."
        )

    def _round_label(self, local_round_idx: int) -> int:
        return self.round_offset + local_round_idx

    @staticmethod
    def _artifact_stem(artifact_label: int | str) -> str:
        if isinstance(artifact_label, int):
            return f"round_{artifact_label}"
        return str(artifact_label).strip() or "artifact"

    @staticmethod
    def _pipeline_round(artifact_label: int | str) -> int | None:
        return artifact_label if isinstance(artifact_label, int) else None

    # ------------------------------------------------------------------ #
    # Fetching
    # ------------------------------------------------------------------ #
    # ================================================================== #
    # The composition (Phase 4E-c)
    #
    # `docs/ACQUISITION_LOOP.md` §"The template". This section declares the
    # parts; the kernel runs them. There is no loop here that pulls a unit,
    # calls `scoped.observe`, reads a verdict, or keeps a per-scope list. The
    # loops that remain iterate over emitted records, declared columns and
    # extracted fields, and none of them acquires anything.
    # ================================================================== #

    def _build_run_episode(self) -> Episode:
        """Declare the whole tree. One `Episode`, three grains, one call.

        THE RUN EPISODE SPANS THE WHOLE PROCESS, and the round loop is gone.
        A stop rule's history is a statement about its own units, so a run
        episode opened per acquisition span would restart its history before it
        could ever fire -- "a constant pretending to be a decision" -- and
        `Context.enter` raises on re-opening a path besides. So there is exactly
        one run episode per pipeline process, the per-round work became its
        `on_unit` hook, and **a round is now a completed strategy**.
        """

        self.proposer = StrategyProposer(
            declared=self._eligible_families,
            sample=self._sample_strategies,
            build=self._build_strategy_episode,
            catalog=frozenset(QUERY_OPERATORS),
            declared_target_ids=self._declared_target_ids,
            budget=self.source_budget,
            health=self.provider_health,
            termination=self.run_termination,
            open_cost_scope=self._acquisition_cost_scope,
            # The ONE expression, handed over as a callable because the pull
            # happens before the strategy it will open exists. Never
            # recomputed from the episode view: see `StrategyProposer.next`.
            round_index=lambda: self._round_index,
            run_key=self.out.name,
            record_proposal=self._record_strategy_proposal,
        )
        self.acquisition.proposer = self.proposer
        bound = (
            int(self.config.max_rounds) if int(self.config.max_rounds) > 0 else None
        )
        return Episode(
            grain=RUN_GRAIN,
            key=self.out.name,
            source=self.proposer,
            on_unit=self._on_strategy,
            # A CAP, disclosed as a cap and never presented as a decision. When
            # `max_rounds <= 0` -- a supported configuration -- the run episode
            # has NO unit bound and termination rests entirely on the run
            # source's three typed checks: the run's terminal state, provider
            # health, and the page budget.
            bound=bound,
        )

    def _build_strategy_episode(
        self,
        strategy_key: str,
        family: str,
        seeds: Sequence[str],
    ) -> Episode:
        """One strategy instance, keyed ``family#instance``.

        Instance-scoped because `open_scope` raises on a re-opened path and the
        deterministic planner routes the same family again by design; the family
        travels as a field, so every ledger grouping, arm join and curve
        comparison stays by family.
        """

        if seeds:
            self._strategy_seed_queries[strategy_key] = list(seeds)
        return Episode(
            grain=STRATEGY_GRAIN,
            key=strategy_key,
            source=StrategySearches(
                strategy_key=strategy_key,
                family=family,
                next_task=self.search_frontier.next_for,
                make_search=lambda task: self._build_search_episode(
                    task, strategy_key, family
                ),
                budget=self.source_budget,
                health=self.provider_health,
            ),
            on_unit=lambda unit, contribution, record: self._on_search(
                unit, contribution, record, strategy_key, family
            ),
        )

    def _build_search_episode(
        self,
        task: SearchTask,
        strategy_key: str,
        family: str,
    ) -> Episode:
        round_index = self._round_index
        task = self._stamp_round_index(task, round_index)
        outcome = SearchOutcome.for_task(task)
        self._open_outcomes[task.id] = outcome
        source = PageSource(
            task=task,
            search_fn=self._search_fn,
            make_leaf=self._make_page_leaf,
            budget=self.source_budget,
            health=self.provider_health,
            round_index=round_index,
            open_cost_scope=self._acquisition_cost_scope,
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

    def _make_page_leaf(
        self,
        task: SearchTask,
        result: Dict[str, Any],
        rank: int,
    ) -> Leaf:
        """One page, bound to its grain's parts at construction.

        The label is a PULL-TIME identity and never the source id: `Leaf` is
        frozen before `extract` runs and the source id is minted inside it, so a
        label taken from the source id would name a value the kernel never sees.
        It is also the SOURCE cost record's `observation_id`, so every page --
        including one refused before a source id exists -- has one joinable cost
        record, where those bytes used to be attributed to the search's meter.
        """

        unit = PageUnit(
            task=task,
            result=result,
            rank=rank,
            round_index=self._round_index,
            label=f"{task.id}#{rank}",
        )
        return Leaf(
            unit=unit,
            extract=self.fetch_judge_extract,
            credit=self.crediter,
            label=unit.label,
        )

    # ------------------------------------------------------------------ #
    # extract: the leaf's string work. IT NEVER RAISES.
    # ------------------------------------------------------------------ #
    async def fetch_judge_extract(self, unit: PageUnit) -> PageMaterial:
        """Fetch, gate and extract ONE page, and never raise.

        The driver catches nothing, so one raise here would unwind the whole
        record tree and the run would emit no record at all. Every expected
        failure is therefore converted into a typed fate, classified through
        `costs.classify_error` -- an existing owner, not a second classifier.
        `BaseException` is deliberately NOT caught: `KeyboardInterrupt` and
        `SystemExit` legitimately end the process, and swallowing them would be
        the silent failure in the other direction.

        THIS FUNCTION MINTS NO `active` FLAG AND NO FATE CLASS. It returns facts
        -- the gate's score, the floor, the rule's outcome, the extraction's
        chunk failures -- and `acquisition` decides once what they mean.
        """

        task = unit.task
        outcome = self._open_outcomes.get(task.id)
        if outcome is None:
            outcome = SearchOutcome.for_task(task)
            self._open_outcomes[task.id] = outcome

        with self._cost_scope(
            ObservationKind.SOURCE.value,
            observation_id=unit.label,
            round_index=unit.round_index,
        ):
            return await self._acquire_page(unit, outcome)

    async def _acquire_page(
        self,
        unit: PageUnit,
        outcome: SearchOutcome,
    ) -> PageMaterial:
        task = unit.task
        prepared = self._harvester.prepare_page(
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

        # Fates 6 and 7 sit AHEAD of the gate, so a page nothing could credit
        # never pays for a gate call -- a cost improvement and a correctness one:
        # paying a model to score a page against a contract that cannot yet be
        # extracted buys nothing.
        if self.extractor is None:
            return PageMaterial(
                fate=page_fate(mechanical=acq.FATE_NO_EXTRACTOR),
                text_chars=len(candidate.text),
            )
        if not self.crediter.basis.columns:
            return PageMaterial(
                fate=page_fate(mechanical=acq.FATE_NO_CREDIT_COLUMNS),
                text_chars=len(candidate.text),
            )

        gate, gate_record, relevance = await self._gate_page(task, unit, candidate)
        cleared, gate_outcome = gate
        if not cleared:
            outcome.relevance_decisions.append(relevance)
            self._harvester.record_candidate_outcome(
                outcome,
                dict(unit.result),
                rank=unit.rank,
                fate=fate_skip_reason(page_fate(gate=gate_outcome)),
                reason=gate_record.get("rule", ""),
                text_length=len(candidate.text),
            )
            return PageMaterial(
                fate=page_fate(
                    gate=gate_outcome,
                    extraction=acq.EXTRACT_NOT_RUN,
                    score_reason=str(gate_record.get("reason_class") or ""),
                ),
                gate=gate_record,
                relevance=relevance,
                text_chars=len(candidate.text),
            )
        outcome.relevance_decisions.append(relevance)

        paper = self._harvester.write_paper(
            task, candidate, outcome, rank=unit.rank
        )
        source_id = str(paper.get("id") or "")
        ingestion = self._open_ingestion_entry(source_id, paper)

        chunks: List[Dict[str, Any]] = []
        try:
            entities, relationships = await extract_from_text(
                self.extractor,
                paper["text"],
                source_id,
                chunk_size=self.config.chunk_size,
                overlap=self.config.chunk_overlap,
                concurrency=self.config.extraction_concurrency,
                timeout=self.config.extraction_timeout_sec,
                on_chunk=self._chunk_observer(chunks),
            )
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
                    gate=gate_outcome,
                    extraction=acq.EXTRACT_RAISED,
                    error_class=error_class,
                    score_reason=str(gate_record.get("reason_class") or ""),
                ),
                paper=paper,
                ingestion=ingestion,
                gate=gate_record,
                relevance=relevance,
                reduction=candidate.reduction,
                chunks=tuple(chunks),
                text_chars=len(candidate.text),
            )

        # A PAGE WHOSE EVERY CHUNK FAILED IS NOT A BARREN PAGE.
        # `extract_from_text` converts a per-chunk timeout or exception into an
        # empty result, so without this test such a page reaches the "extracted"
        # row, enters the search grain's stop history with zero credits, and a
        # stream of them reads as a result list that has stopped yielding.
        # `docs/ACQUISITION_LOOP.md`: "a stream of zero-credit units that merely
        # *looks* barren would drive a false stop."
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
                fate=page_fate(
                    gate=gate_outcome,
                    extraction=acq.EXTRACT_ALL_CHUNKS_FAILED,
                    score_reason=str(gate_record.get("reason_class") or ""),
                ),
                paper=paper,
                ingestion=ingestion,
                gate=gate_record,
                relevance=relevance,
                reduction=candidate.reduction,
                chunks=tuple(chunks),
                text_chars=len(candidate.text),
            )

        records = self._extracted_records(entities, relationships)
        ingestion.update(
            {
                "extraction_state": (
                    "extracted_entities" if entities else "extracted_no_entities"
                ),
                "entity_count": len(entities or {}),
                "relationship_count": len(relationships or ()),
                "failed_chunks": failed_chunks,
                "chunk_count": len(chunks),
            }
        )
        guesses = await self._page_best_guess(
            records=records,
            source_id=source_id,
            page_text=str(paper.get("text") or ""),
        )
        return PageMaterial(
            source_id=source_id,
            fate=page_fate(
                gate=gate_outcome,
                extraction=acq.EXTRACT_OK,
                score_reason=str(gate_record.get("reason_class") or ""),
            ),
            entities=entities or {},
            relationships=list(relationships or ()),
            records=records,
            guesses=guesses,
            paper=paper,
            ingestion=ingestion,
            gate=gate_record,
            relevance=relevance,
            reduction=candidate.reduction,
            chunks=tuple(chunks),
            text_chars=len(candidate.text),
        )

    async def _gate_page(
        self,
        task: SearchTask,
        unit: PageUnit,
        candidate: Any,
    ) -> tuple[tuple[bool, str], Dict[str, Any], Dict[str, Any]]:
        """Score the page, then apply the RULE. The model is not on the branch.

        Fate 8 (`gate_off`) is a declared rule on a config value and fate 9
        (`failed_open`) a declared rule on an exception path -- neither is a
        model verdict -- and both admit the page for extraction, as does fate 10
        (`unscored`), because a parse failure is not evidence about a page.
        """

        if not self._should_gate_source(task):
            record = {
                "score": None,
                "floor": RELEVANCE_SCORE_FLOOR,
                "rule": "gate not run by declared config",
                "outcome": acq.GATE_NOT_RUN,
                "reason_class": "gate_off",
                "window_count": 0,
                "window_scores": [],
                "deciding_window_index": -1,
            }
            return (True, acq.GATE_NOT_RUN), record, self._relevance_record(
                unit, candidate, record, accepted=True
            )

        try:
            score = await score_page_against_contract(
                self.llm,
                question=self.config.question,
                columns=self._declared_gate_columns(),
                page_text=candidate.text,
            )
        except Exception as exc:  # noqa: BLE001 - the tree's existing fail-open
            record = {
                "score": None,
                "floor": RELEVANCE_SCORE_FLOOR,
                "rule": "gate call raised",
                "outcome": acq.GATE_FAILED_OPEN,
                "reason_class": classify_error(exc),
                "error": f"{type(exc).__name__}: {exc}",
                "window_count": 0,
                "window_scores": [],
                "deciding_window_index": -1,
            }
            return (True, acq.GATE_FAILED_OPEN), record, self._relevance_record(
                unit, candidate, record, accepted=True
            )

        cleared, gate_outcome = page_clears_relevance(score.specificity_score)
        windows = (score.raw.get("gate_windows") or {}).get("windows") or []
        record = {
            "score": score.specificity_score,
            "floor": RELEVANCE_SCORE_FLOOR,
            "rule": "specificity_score >= RELEVANCE_SCORE_FLOOR",
            "outcome": gate_outcome,
            "reason_class": score.score_reason,
            "window_count": score.window_count,
            "window_scores": [
                window.get("specificity_score") for window in windows
            ],
            "deciding_window_index": score.window_index,
            "contract_columns": len(self._declared_gate_columns()),
            "contract_digest": self._gate_contract_digest(),
            "spec_digest": self.crediter.spec_digest,
        }
        self._record_page_gate_score(task, unit, score, record)
        return (cleared, gate_outcome), record, self._relevance_record(
            unit, candidate, record, accepted=cleared, score=score
        )

    def _relevance_record(
        self,
        unit: PageUnit,
        candidate: Any,
        gate: Mapping[str, Any],
        *,
        accepted: bool,
        score: Any = None,
    ) -> Dict[str, Any]:
        decision = SourceRelevanceDecision(
            accept=bool(accepted),
            reason=str(gate.get("rule") or ""),
            gate_score=gate.get("score"),
            gate_floor=float(gate.get("floor") or 0.0),
            gate_outcome=str(gate.get("outcome") or ""),
            gate_rule=str(gate.get("rule") or ""),
            metadata={
                "gate": dict(gate),
                # String work about this page, carried for `search_memory`'s
                # counters and briefs. No predicate reads any of it.
                "matched_needs": list(getattr(score, "matched_needs", ()) or ()),
                "missing_needs": list(getattr(score, "missing_needs", ()) or ()),
                "offtopic_axes": list(getattr(score, "offtopic_axes", ()) or ()),
                "failure_modes": list(getattr(score, "failure_modes", ()) or ()),
                "better_search_cues": list(
                    getattr(score, "better_search_cues", ()) or ()
                ),
                "avoid_cues": list(getattr(score, "avoid_cues", ()) or ()),
            },
        )
        return {
            "url": candidate.url,
            "title": str(unit.result.get("title") or ""),
            **decision.to_dict(),
        }

    def _declared_gate_columns(self) -> List[DeclaredColumn]:
        """What the gate is asked about: EXACTLY the crediter's basis.

        One object, one selection. The columns the model is asked to look for
        are the columns the crediter can credit, so the two cannot drift, and a
        column the criteria-owned basis excludes -- `evidence_gap`, the producer
        grading its own output -- is not merely uncredited but never named to
        the gate.

        THE BLIND SPOT THIS SHARES WITH THE CREDIT ACCUMULATOR, stated because
        it is the one class of page whose value the loop cannot see: declared
        subject-key columns are excluded from the basis by construction (a
        key-only row warms nothing), so they are excluded from this ask too. A
        page carrying only declared key values is scored against columns it does
        not claim to carry, and mints no credit even when extracted -- while
        being exactly the page a row credit and a criterion's subject identity
        need. The run emits the count of extracted pages that minted zero
        credits while supplying a complete declared subject key, so an
        under-admission of identity-bearing evidence is legible rather than
        inferred.
        """

        if self._gate_columns is None:
            self._gate_columns = [
                DeclaredColumn(
                    table=column.table,
                    column=column.column,
                    value_type=column.value_type,
                    unit=column.unit,
                    aliases=column.aliases,
                    description=column.description,
                )
                for column in self.crediter.basis.columns
            ]
        return self._gate_columns

    def _gate_contract_digest(self) -> str:
        if self._gate_contract_digest_value == "":
            from .progress_judge import contract_block

            self._gate_contract_digest_value = stable_id(
                contract_block(self._declared_gate_columns())
            )
        return self._gate_contract_digest_value

    def _chunk_observer(self, sink: List[Dict[str, Any]]):
        """Per-chunk encounters, including FAILURE, for the unbound chunk grain.

        The counters live in this closure and not on the crediter, which is
        constructed once per run and must stay pure: `extract` now calls the
        crediter, so a per-page memo on it would make `extract`'s behaviour
        depend on `credit`'s.
        """

        seen: set[str] = set()

        def observe(index, chunk_id, entities, relationships, failure) -> None:
            projected = self.crediter.identities(
                self._extracted_records(
                    {
                        str(getattr(entity, "entity_name", "") or index): entity.to_dict()
                        for entity in entities
                    }
                    if entities and not isinstance(entities, Mapping)
                    else (entities or {}),
                    relationships or (),
                )
            )
            identities = projected.identities
            new = [item for item in identities if item not in seen]
            seen.update(identities)
            sink.append(
                {
                    "chunk_index": int(index),
                    "chunk_id": str(chunk_id),
                    "failed": bool(failure),
                    "failure_class": str(failure or ""),
                    "credits_minted": len(identities),
                    "new_within_page": len(new),
                    "repeats_within_page": len(identities) - len(new),
                    "row_credits_minted": len(projected.row_credits),
                }
            )

        return observe

    def _extracted_records(
        self,
        entities: Mapping[str, Mapping[str, Any]],
        relationships: Sequence[Mapping[str, Any]] = (),
    ) -> List[Dict[str, Any]]:
        """One record per extracted entity and relationship, per declared table.

        The unit of row completeness is ONE extracted record, so the crediter
        must see each record's fields together. A flattened stream of every
        entity's attributes cannot say whether one subject carried six columns
        or six subjects carried one each, and crediting a row on it would be
        volume with an identity attached.

        The same record is offered against every declared table: a page does not
        know which table it fills, and the projection's own column matching
        decides. That is a property of the contract, not a guess about the page.
        """

        tables = self.crediter.basis.tables
        out: List[Dict[str, Any]] = []
        index = 0
        for record in list((entities or {}).values()) + list(relationships or ()):
            if not isinstance(record, Mapping):
                continue
            attributes = record.get("attributes")
            values: Dict[str, Any] = {}
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
        page_text: str,
    ) -> List[Dict[str, Any]]:
        """The page-scoped guess stage, inside `extract` and inside SOURCE cost.

        Its output is an ACQUISITION CONTROL SIGNAL and is written into no
        exported row: the round-end pass over exported rows remains the only
        writer of the `judged_best_guess_*` basis and therefore the only input
        to `criteria`, to reward, and to any datapoint claim. The two counts are
        not expected to agree -- different evidence scopes, one page against
        every accepted source -- and their divergence is the measurement.
        """

        if self.config.page_best_guess_mode == "off" or not records:
            return []
        report = await page_best_guess(
            records=records,
            columns_by_table=self.crediter.columns_by_table(),
            source_id=source_id,
            page_text=page_text,
            extract_fn=(
                self._infer_best_guess_candidates
                if self.config.page_best_guess_mode == "llm"
                else None
            ),
            llm_batch_size=self.config.best_guess_llm_batch_size,
            llm_timeout_sec=self.config.best_guess_llm_timeout_sec,
            evidence_chars=self.config.best_guess_evidence_chars,
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
        source_id: str,
        paper: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Recorded BEFORE extraction is called, never after.

        That is the property that makes "extraction ran and found nothing"
        distinguishable from "extraction never ran": an attempted state that
        depended on what came back would be a relabelled inference.
        """

        entry = {
            "source_id": source_id,
            "extraction_state": "attempted",
            "reason": "",
            "entity_count": 0,
            "relationship_count": 0,
            "text_chars": len(str(paper.get("text") or "")),
            "round_index": _safe_int(paper.get("search_round_index"), 0),
        }
        self.source_ingestion_ledger[source_id] = entry
        return entry

    # ------------------------------------------------------------------ #
    # hooks -- which hook writes which decision
    #
    # A grain's hook runs once per unit of that grain, BEFORE the loop reads
    # that grain's own verdict, and `c.child` is the unit's record. So a hook
    # can never see the verdict that ends its own episode -- which is why the
    # strategy-ending decision is written at the RUN grain's hook, and why the
    # run-ending decision has no hook at all.
    #
    # NO HOOK MAY RAISE: `drive_async` catches nothing around `on_unit`, so one
    # raise unwinds the whole record tree. Each hook's body is guarded and its
    # failure recorded as a typed class. `BaseException` is not caught.
    # ------------------------------------------------------------------ #
    def _on_page(
        self,
        leaf: Leaf,
        contribution: Contribution,
        record: UnitRecord,
        outcome: SearchOutcome,
        strategy_key: str,
        family: str,
    ) -> None:
        """A page produces NO policy decision. Side effects and the ledger only.

        The kernel hands a hook the unit its SOURCE yielded, which at this grain
        is the `Leaf`; the `PageUnit` the crediter wrote its breakdown onto is
        `leaf.unit`.
        """

        unit = leaf.unit
        material = contribution.extracted
        try:
            self.source_budget.charge(1)
            self.paper_count = self.source_budget.spent
            if isinstance(material, PageMaterial):
                skip = fate_skip_reason(material.fate)
                if skip:
                    outcome.skip(skip)
                if material.paper is not None:
                    self._accepted_papers.append(dict(material.paper))
                    self._record_goal_discovery_sources([dict(material.paper)])
                    self.graph = enrich_graph(
                        self.graph,
                        dict(material.entities),
                        list(material.relationships),
                        material.source_id,
                        similarity_threshold=self.config.similarity_threshold,
                        auto_merge=self.config.auto_merge_entities,
                    )
                self._write_page_detail(unit, record, material, strategy_key, family)
        except Exception as exc:  # noqa: BLE001 - a hook must not unwind the tree
            self._record_hook_failure("on_page", unit.label, exc)

    def _on_search(
        self,
        episode: Episode,
        contribution: Contribution,
        record: UnitRecord,
        strategy_key: str,
        family: str,
    ) -> None:
        """One completed search: write its outcome, and its yield decision."""

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
                    # A DECISION, NEVER SILENT: every unprocessed buffered
                    # result is counted under a reason a reader can distinguish
                    # from a relevance or a budget skip. The provider already
                    # returned it; no page LLM work ran for it.
                    outcome.skip("yield_stop", remaining)
                self._append_control_decision(
                    self.acquisition.write_decision(
                        child,
                        decision_point=acq.DECISION_SEARCH_ITEM_YIELD,
                        family=family,
                    )
                )
            if source is not None and source.cost is not None:
                outcome.cost = dict(source.cost)
            outcome.provider_batch = dict(self.search_provider_batch)
            if source is not None:
                outcome.result_buffer = source.result_buffer
            self.last_search_outcomes.append(outcome)
            self.search_frontier.record([outcome])
            self.search_outcomes.append(outcome.to_dict())
            self.queries_used.append(outcome.query)
            self._harvester.record_outcome(outcome)
            self._refresh_search_memory()
            self._record_prompt_attempt_counts([outcome])
            self._pending_followup_outcomes.append(outcome)
        except Exception as exc:  # noqa: BLE001 - a hook must not unwind the tree
            self._record_hook_failure("on_search", episode.key, exc)

    async def _on_strategy(
        self,
        episode: Episode,
        contribution: Contribution,
        record: UnitRecord,
    ) -> None:
        """One completed strategy: THE ROUND BODY, plus the strategy decision.

        This is the hook that can see a strategy's own verdict; the strategy
        grain's own hook cannot. Every step of the round body is individually
        guarded and its failure recorded as a typed class on the round record,
        so one failing export cannot unwind the record tree.
        """

        child = contribution.child
        family = str(episode.key).split("#", 1)[0]
        round_index = self._round_index
        try:
            if child is not None:
                self._strategy_ends[family] = child.ended_by
                self._append_control_decision(
                    self.acquisition.write_decision(
                        child,
                        decision_point=acq.DECISION_STRATEGY_YIELD,
                        family=family,
                    )
                )
                self._write_episode_record(child)
                # The two readings of the round index agree by construction --
                # the source saw `units_consumed` before the pull and the unit
                # record carries `units - 1` after the observe -- so a
                # divergence is a failure that names itself.
                observed = int(record.yield_record.unit_index)
                if observed != int(round_index) - int(self.round_offset):
                    self._record_hook_failure(
                        "round_index",
                        episode.key,
                        ValueError(
                            f"round index {round_index} disagrees with the run "
                            f"episode's unit index {observed}"
                        ),
                    )
            await self._run_round_body(round_index, episode.key, family)
        except Exception as exc:  # noqa: BLE001 - a hook must not unwind the tree
            self._record_hook_failure("on_strategy", episode.key, exc)
        finally:
            self._advance_round()

    # ------------------------------------------------------------------ #
    # the sources' typed callbacks
    # ------------------------------------------------------------------ #
    def _eligible_families(self) -> List[str]:
        """Families with pending frontier work that MAY open an instance.

        A written rule over the child records the run already holds, with no
        model and no threshold -- an `ended_by` comparison against declared
        constants:

        * ``exhausted``  -> yes, if the frontier holds work for it. The queue
          was momentarily empty; it was never abandoned.
        * ``yield_stop`` -> no. Its own verdict abandoned it, and re-running it
          is the verdict undone.
        * ``bound_hit``  -> no. A budget is spent; re-running spends more of it.
        * ``source_failed`` -> no. The stream died, and provider health ends the
          run anyway.

        THIS IS NOT THE DELETED WITHIN-ROUND DEMOTION GATE. That interleaved
        searches across strategies inside a round and carried an all-stopped
        override; this runs one strategy episode at a time and never revives a
        family its own verdict abandoned. The override is replaced by the run
        grain's own verdict -- a verdict this build's provider budget cannot
        reach, so what is deleted is a within-round switch capability and what
        replaces it is registered inert on these configurations.

        **WHAT BOUNDS THE RE-OPEN CYCLE**, since a barren search enqueues
        follow-up evolutions and a refilled frontier makes an ``exhausted``
        family eligible again. Four bounds, and each is a number:
        ``target_evolution_counts`` caps how many evolutions one deficit may
        spawn per the configured limit; every PULLED page charges
        ``SourceBudget``, so a run that pulls pages advances toward
        ``max_papers``; a run that pulls no page still consumes one run-grain
        unit per strategy and ends on ``Episode(RUN).bound`` when
        ``max_rounds > 0``; and when ``max_rounds <= 0`` it ends on
        ``RunTermination`` or ``budget.exhausted`` at the run source's first
        two checks. The per-family instance count is emitted on the run record.
        """

        pending = self.search_frontier.pending_by_family()
        return [
            family
            for family in pending
            if self._strategy_ends.get(family, END_EXHAUSTED) == END_EXHAUSTED
        ]

    def _current_strategy_seed_queries(self) -> List[str]:
        """Seeds proposed for any strategy opened so far, deduped.

        Recorded on the proposal row as a hint and forwarded as context. NO
        PREDICATE READS THEM: what reaches one is `control.stable_id` over the
        normalized seed set, which is content-addressing rather than
        text-steering -- the distinction between this and a prose chain where a
        generated string reaches a branch.
        """

        seeds: List[str] = []
        for values in self._strategy_seed_queries.values():
            for seed in values:
                if seed not in seeds:
                    seeds.append(seed)
        return seeds

    def _declared_target_ids(self) -> set[str]:
        ids: set[str] = set()
        for state in self.goal_states:
            catalog = state.get("target_catalog") if isinstance(state, dict) else None
            for key in ("fill_deficits", "unmet_count_targets", "count_targets"):
                for target in (catalog or {}).get(key) or []:
                    if isinstance(target, Mapping):
                        value = str(target.get("id") or target.get("target_id") or "")
                        if value:
                            ids.add(value)
        return ids

    async def _sample_strategies(
        self,
        tried: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        """The switch edge's model call. Strings and one number, nothing else."""

        return await strategy.propose_distant_strategy(
            self.llm,
            self.config.question,
            run_view=self._proposer_run_view(),
            catalog=QUERY_OPERATORS,
            tried=list(tried),
            n=self.config.task_goal_search_tasks or 3,
        )

    def _proposer_run_view(self) -> Dict[str, Any]:
        """The proposer's payload, DECLARED FIELD BY FIELD.

        Every field is context and none reaches a predicate: the accept rule
        reads a code-minted content key and a reported distance
        (`control.select_first_clearing`) and nothing else, so no prose in here
        can reach a branch by construction. It deliberately does NOT draw from
        `strategy_memory` records, so the page gate's `matched_needs` /
        `missing_needs` and `search_memory`'s judge-emitted cue counters do not
        enter this prompt at all.
        """

        latest_goal = self.goal_states[-1] if self.goal_states else {}
        return {
            "declared_table_contract": (
                self.table_spec.prompt_context()
                if not self.table_spec.is_empty
                else {}
            ),
            "declared_credit_columns": [
                {"table": column.table, "column": column.column}
                for column in self.crediter.basis.columns
            ],
            "criteria_snapshot_id": self.criteria_snapshot.id,
            "observed_deficits": (
                (latest_goal.get("target_catalog") or {}).get("fill_deficits")
                if isinstance(latest_goal, dict)
                else []
            )
            or [],
            "accepted_source_terms": self._accepted_source_terms(),
            "pages_pulled": self.source_budget.spent,
            "pages_budget": self.source_budget.limit,
            "completed_strategies": [
                {
                    "scope_key": decision.get("scope_key"),
                    "strategy_family": decision.get("strategy_family"),
                    "units_consumed": decision.get("units_consumed"),
                    "ended_by": decision.get("ended_by"),
                    "distinct_credits": (decision.get("curve") or {}).get("distinct"),
                }
                for decision in self.acquisition.decision_records
                if decision.get("decision_point") == acq.DECISION_STRATEGY_YIELD
            ],
        }

    def _accepted_source_terms(self) -> List[str]:
        terms: List[str] = []
        for paper in self._accepted_papers[-25:]:
            title = str(paper.get("title") or "").strip()
            if title:
                terms.append(title)
        return terms

    def _record_strategy_proposal(self, row: Mapping[str, Any]) -> None:
        """Every candidate, accepted or not, with its reported distance.

        So the live run measures the distance distribution and a later phase can
        set the floor from data instead of from a constant's docstring; and so
        route 2 recomputes the accept decision offline from this file alone,
        which needs the content key, the returned index, the sample number and
        the opened-key set as it stood at that pull -- all of which are here.
        """

        self._strategy_proposals.append(dict(row))
        try:
            self.answers_dir.mkdir(parents=True, exist_ok=True)
            with (self.answers_dir / "strategy_proposals.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps(dict(row), default=str) + "\n")
        except OSError:  # pragma: no cover - recording never breaks the run
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
            self.search_provider_error = str(exc)
            print(f"  Search provider stopped the run: {exc}")

    def _acquisition_cost_scope(
        self,
        kind: str,
        observation_id: str,
        round_index: int,
    ):
        """The cost scope the sources open. ONE OWNER, and it is `costs.py`.

        The episode carries no meter. This forwards to the pipeline's own
        scope helper, which returns an inert placeholder when cost accounting is
        off -- so the A/A ablation survives the SEARCH scope's move into the
        page source and applies identically to the new STRATEGY_PROPOSAL scope.
        """

        return self._cost_scope(
            kind,
            observation_id=observation_id,
            round_index=int(round_index),
        )

    # ------------------------------------------------------------------ #
    # round index: ONE expression, minted once, at strategy-open time
    # ------------------------------------------------------------------ #
    @property
    def _round_index(self) -> int:
        return self._current_round_index

    def _advance_round(self) -> None:
        self._last_round_index = self._current_round_index
        self._current_round_index = self._round_label(self._completed_strategies + 1)
        self._completed_strategies += 1

    def _stamp_round_index(self, task: SearchTask, round_index: int) -> SearchTask:
        """Carry the one expression onto the task, and nothing else writes it.

        `_write_paper` copies it to `search_round_index`, `_source_records_by_id`
        collects it, and `reward.score_criterion_yield`'s first-harvest window
        reads it from there -- which is what closes the chain the reward's own
        contract forbids taking from a transition.
        """

        if task.round_index == round_index:
            return task
        return SearchTask(
            query=task.query,
            id=task.id,
            parent_id=task.parent_id,
            topic=task.topic,
            expansion_op=task.expansion_op,
            gap=task.gap,
            round_index=int(round_index),
            depth=task.depth,
            yields_sources=task.yields_sources,
            producer_class=task.producer_class,
            metadata=dict(task.metadata),
        )

    def _record_hook_failure(
        self,
        hook: str,
        key: str,
        exc: BaseException,
    ) -> None:
        record = {
            "hook": hook,
            "key": str(key),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "error_class": classify_error(exc),
        }
        self.hook_failures.append(record)
        print(f"  [acquisition] {hook} failed on {key}: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ #
    # per-page and per-episode records
    # ------------------------------------------------------------------ #
    def _write_page_detail(
        self,
        unit: PageUnit,
        record: UnitRecord,
        material: PageMaterial,
        strategy_key: str,
        family: str,
    ) -> None:
        """The sidecar. NOT a projection of the episode tree.

        `UnitRecord` is a frozen kernel type and the episode file carries
        `as_record()` verbatim, so the surface facts the kernel cannot hold live
        here and join by `unit_label`. No number in it is derivable from the
        episodes file, which is what makes it a second route rather than a
        second reading of the first.
        """

        detail = unit.credit_detail
        row = {
            "unit_label": unit.label,
            "source_id": material.source_id,
            "task_id": str(unit.task.id),
            "strategy_key": strategy_key,
            "strategy_family": family,
            "rank": unit.rank,
            "round_index": unit.round_index,
            "fate": material.fate.to_dict(),
            "credit_note": material.fate.credit_note,
            "skip_reason": fate_skip_reason(material.fate),
            "counts_toward_verdict": bool(record.yield_record.counts_toward_verdict),
            "gate": dict(material.gate),
            "spec_digest": self.crediter.spec_digest,
            "crediter_built_at_round": self.round_offset,
            "credit_semantics": CREDIT_SEMANTICS,
            "text_chars": material.text_chars,
            "guess_count": len(material.guesses),
            **(detail.to_dict() if detail is not None else {}),
        }
        self.acquisition_page_details.append(row)
        try:
            self.answers_dir.mkdir(parents=True, exist_ok=True)
            with self._page_detail_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, default=str) + "\n")
        except OSError:  # pragma: no cover - recording never breaks the run
            pass

    def _write_episode_record(self, record: EpisodeRecord) -> None:
        """Durable per completed strategy, not once at the end.

        The precedent and the argument are in this file already: a real 3h run
        killed in round 11 left no ledger at all, which is why
        `_append_control_decision` writes on append.
        """

        if record.scope_level == STRATEGY_GRAIN.name:
            self._episode_records.append(window_episode_record(record.as_record()))
        try:
            self.answers_dir.mkdir(parents=True, exist_ok=True)
            self._episodes_path.write_text(
                json.dumps(
                    {
                        "policy_name": acq.ACQUISITION_POLICY_NAME,
                        "credit_semantics": CREDIT_SEMANTICS,
                        "facet_gate": "crediting_active",
                        "declared_facets": list(self.crediter.declared_facets),
                        "spec_digest": self.crediter.spec_digest,
                        "grains": [
                            grain_disclosure(grain)
                            for grain in (RUN_GRAIN, STRATEGY_GRAIN, SEARCH_GRAIN)
                        ],
                        "chunk_grain": CHUNK_GRAIN_DISCLOSURE.to_dict(),
                        "strategies": self._episode_records,
                        "run": (
                            window_episode_record(self.acquisition.record.as_record())
                            if self.acquisition.record is not None
                            else {}
                        ),
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        except OSError:  # pragma: no cover - recording never breaks the run
            pass
    def _should_gate_source(self, task: SearchTask) -> bool:
        mode = self.config.source_relevance_mode
        if mode == "off":
            return False
        if mode == "all":
            return True
        if self.config.pipeline_mode == PIPELINE_MODE_TABLE_FILL:
            return task.topic in {"goal_catalog", "target_deficit", "table_gap"}
        return task.topic in {"target_deficit", "table_gap"}

    @staticmethod
    def _compact_search_result(result: Dict[str, Any]) -> Dict[str, Any]:
        return compact_search_result(result)

    def _empty_deliverable_rows(self) -> Dict[str, List[Dict[str, Any]]]:
        if not self.table_spec.is_empty:
            return self.table_spec.empty_rows_by_table()
        return {table_name: [] for table_name in self._table_target_names()}

    def _record_page_gate_score(
        self,
        task: SearchTask,
        unit: "PageUnit",
        score: Any,
        gate: Mapping[str, Any],
    ) -> None:
        """Every gate call, as recorded facts.

        `progress_judgments.jsonl` CHANGES SHAPE with the narrowed call: it
        loses `decision`, `fruitfulness_score`, `novelty_score` and
        `coverage_delta` -- none of which is asked for any more -- and gains the
        gate block. Nothing joins that file across the change, and the run
        record says so.

        What it carries is what route 2 needs to recompute the fate offline and
        what a later phase needs to set the floor from the observed
        distribution: the reported score, the floor, the rule, its outcome, its
        reason class, and every window's own score.
        """

        self.judgments_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": "page_gate",
            "unit_label": unit.label,
            "task": task.to_dict(),
            "result": self._compact_search_result(dict(unit.result)),
            "gate": dict(gate),
            "page_score": score.to_dict() if hasattr(score, "to_dict") else {},
        }
        with (self.judgments_dir / "progress_judgments.jsonl").open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(json.dumps(record, default=str) + "\n")

    # ------------------------------------------------------------------ #
    # Schema resolution
    # ------------------------------------------------------------------ #
    async def _resolve_schema(self, probe_papers: List[Dict[str, Any]]) -> None:
        if self.config.schema_name:
            print(f"  Loading existing schema: {self.config.schema_name}")
            self.schema = load_domain_schema(self.config.schema_name)
        else:
            print("  No schema supplied -- synthesizing one for the question.")
            result = await schema_synthesis.synthesize_schema(
                self.llm,
                self.config.question,
                sample_texts=[{"id": p["id"], "text": p["text"]} for p in probe_papers],
                expectations=self.config.schema_expectations,
                max_review_passes=self.config.schema_review_passes,
                run_extraction_test=bool(probe_papers),
            )
            self.schema = result.schema
            schema_synthesis.write_schema_yaml(self.schema, self.out / "schema.yaml")
            (self.out / "schema_synthesis_history.json").write_text(
                json.dumps(result.history, indent=2, default=str), encoding="utf-8"
            )
        self.extractor = self._extractor_factory(self.schema)

    # ------------------------------------------------------------------ #
    # Graph persistence + GASL
    # ------------------------------------------------------------------ #
    def _load_seed_graph(self) -> bool:
        if not self.config.graph_path:
            return False

        graph_path = Path(self.config.graph_path)
        if not graph_path.exists():
            raise FileNotFoundError(f"Seed graph not found: {graph_path}")

        self.graph = nx.read_graphml(graph_path)
        print(f"  Loaded seed graph: {graph_path} -> {self._graph_summary()}")
        return True

    def _graph_summary(self) -> str:
        type_counts: Dict[str, int] = {}
        for _, data in self.graph.nodes(data=True):
            t = data.get("entity_type", "UNKNOWN")
            type_counts[t] = type_counts.get(t, 0) + 1
        top = sorted(type_counts.items(), key=lambda kv: -kv[1])[:12]
        return (
            f"{self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges. "
            f"Entity types: {', '.join(f'{t}={n}' for t, n in top)}"
        )

    def _top_entities(self, n: int = 25) -> List[str]:
        ranked = sorted(self.graph.degree(), key=lambda kv: (-kv[1], str(kv[0])))
        return [node for node, _ in ranked[:n]]

    def _write_metadata(self) -> Dict[str, Any]:
        entity_types = [
            {"name": k, "description": v.description}
            for k, v in self.schema.entity_types.items()
        ]
        relationship_types = [
            {"name": k, "description": v.description}
            for k, v in self.schema.relationship_types.items()
        ]
        metadata = build_metadata(
            kg_id=self.out.name,
            kg_version="iterative",
            domain_name=self.schema.domain_name,
            domain_description=self.schema.domain_description,
            guiding_question=self.config.question,
            entity_types=entity_types,
            relationship_types=relationship_types,
            search_queries=self.queries_used,
            search_sources=["pubmed.ncbi.nlm.nih.gov", "biorxiv.org"],
            paper_count=self.paper_count,
            scope_in=[f"{e['name']}: {e['description']}" for e in entity_types],
            scope_out=[],
            notes="Built by question_pipeline iterative loop.",
        )
        save_graph_metadata(self.graphs_dir, metadata)
        return metadata

    async def _run_gasl(
        self,
        round_idx: int,
        metadata: Dict[str, Any],
        *,
        graph: Optional[nx.DiGraph] = None,
    ) -> Dict[str, Any]:
        state_file = str(self.answers_dir / f"round_{round_idx}_gasl_state.json")
        # GASL is synchronous and chatty; run it off the event loop.
        # `asyncio.to_thread` copies the context, so the meter opened here is
        # the one GASL's own `llm.call` reaches inside that thread.
        with self._cost_scope(
            ObservationKind.GASL.value,
            observation_id=f"round_{round_idx}_gasl",
            round_index=round_idx,
        ):
            return await asyncio.to_thread(
                self._gasl_runner,
                graph if graph is not None else self.graph,
                metadata,
                state_file,
            )

    # ------------------------------------------------------------------ #
    # Graph scoping for one round's traversal
    #
    # The batched ingestion path is gone. `_ingest_papers` looped over a wave's
    # papers after the fact, and `_acquisition_item_sink` was the callback the
    # harvester consulted between pages -- both of them the phase-batched shape
    # this phase removes. Extraction now happens inline in the leaf's `extract`,
    # once per page, so the per-search verdict exists while that search's
    # provider-returned buffered results are still unprocessed and have not
    # entered page relevance, extraction, or best-guess work; graph enrichment
    # rides along in the page hook as the decoupled side effect the charter requires.
    # ------------------------------------------------------------------ #
    def _gasl_graph_for_round(self, round_papers: List[Dict[str, Any]]) -> nx.DiGraph:
        scope = self.config.gasl_graph_scope
        use_new_sources = scope == "new_sources" or (
            scope == "auto"
            and self.config.pipeline_mode == PIPELINE_MODE_TABLE_FILL
            and bool(round_papers)
        )
        if not use_new_sources:
            return self.graph

        source_ids = {
            str(paper.get("id") or "").strip()
            for paper in round_papers
            if str(paper.get("id") or "").strip()
        }
        if not source_ids:
            return self.graph

        graph = self._source_neighborhood_graph(
            source_ids,
            hops=self.config.gasl_new_source_hops,
        )
        if graph.number_of_nodes() == 0:
            return self.graph
        return graph

    def _gasl_source_seed_nodes_for_round(
        self,
        round_papers: List[Dict[str, Any]],
        *,
        graph: nx.DiGraph,
    ) -> List[Dict[str, Any]]:
        if self.config.gasl_source_seed_limit <= 0:
            return []

        source_ids = {
            str(paper.get("id") or "").strip()
            for paper in round_papers
            if str(paper.get("id") or "").strip()
        }
        if not source_ids:
            return []

        scored_ids: Dict[Any, tuple[int, int, str]] = {}
        for node_id, data in graph.nodes(data=True):
            if str(node_id) in source_ids or self._mentions_any(data, source_ids):
                scored_ids[node_id] = (0, graph.degree(node_id), str(node_id))

        for src, dst, data in graph.edges(data=True):
            if not self._mentions_any(data, source_ids):
                continue
            for node_id in (src, dst):
                scored_ids.setdefault(
                    node_id,
                    (1, graph.degree(node_id), str(node_id)),
                )

        return [
            {
                "id": node_id,
                "data": dict(graph.nodes[node_id]),
                "type": "node",
            }
            for node_id in sorted(
                scored_ids,
                key=lambda node_id: (
                    scored_ids[node_id][0],
                    -scored_ids[node_id][1],
                    scored_ids[node_id][2],
                ),
            )[: self.config.gasl_source_seed_limit]
        ]

    def _source_neighborhood_nodes(
        self,
        source_ids: set[str],
        *,
        hops: int,
    ) -> set[Any]:
        nodes: set[Any] = set()
        for node_id, data in self.graph.nodes(data=True):
            if str(node_id) in source_ids or self._mentions_any(data, source_ids):
                nodes.add(node_id)

        for src, dst, data in self.graph.edges(data=True):
            if self._mentions_any(data, source_ids):
                nodes.add(src)
                nodes.add(dst)

        frontier = set(nodes)
        for _ in range(hops):
            expanded: set[Any] = set()
            for node_id in frontier:
                if node_id not in self.graph:
                    continue
                expanded.update(self.graph.predecessors(node_id))
                expanded.update(self.graph.successors(node_id))
            expanded -= nodes
            if not expanded:
                break
            nodes.update(expanded)
            frontier = expanded
        return nodes

    def _source_neighborhood_graph(
        self,
        source_ids: set[str],
        *,
        hops: int,
    ) -> nx.DiGraph:
        scoped = self.graph.__class__()
        scoped.graph.update(self.graph.graph)

        for node_id, data in self.graph.nodes(data=True):
            if str(node_id) in source_ids or self._mentions_any(data, source_ids):
                scoped.add_node(node_id, **dict(data))

        for src, dst, key, data in self._iter_graph_edges():
            if not self._mentions_any(data, source_ids):
                continue
            self._copy_node(scoped, src)
            self._copy_node(scoped, dst)
            self._copy_edge(scoped, src, dst, key, data)

        seen = set(scoped.nodes)
        frontier = set(scoped.nodes)
        for _ in range(max(0, hops)):
            expanded: set[Any] = set()
            for node_id in frontier:
                for src, dst, key, data in self._iter_incident_edges(node_id):
                    self._copy_node(scoped, src)
                    self._copy_node(scoped, dst)
                    self._copy_edge(scoped, src, dst, key, data)
                    expanded.add(src)
                    expanded.add(dst)
            expanded -= seen
            if not expanded:
                break
            seen.update(expanded)
            frontier = expanded

        return scoped

    def _iter_graph_edges(self):
        if self.graph.is_multigraph():
            yield from self.graph.edges(keys=True, data=True)
            return
        for src, dst, data in self.graph.edges(data=True):
            yield src, dst, None, data

    def _iter_incident_edges(self, node_id: Any):
        if node_id not in self.graph:
            return
        if self.graph.is_multigraph():
            yield from self.graph.out_edges(node_id, keys=True, data=True)
            if self.graph.is_directed():
                yield from self.graph.in_edges(node_id, keys=True, data=True)
            return
        for src, dst, data in self.graph.out_edges(node_id, data=True):
            yield src, dst, None, data
        if self.graph.is_directed():
            for src, dst, data in self.graph.in_edges(node_id, data=True):
                yield src, dst, None, data

    def _copy_node(self, graph: nx.DiGraph, node_id: Any) -> None:
        if node_id in graph or node_id not in self.graph:
            return
        graph.add_node(node_id, **dict(self.graph.nodes[node_id]))

    @staticmethod
    def _copy_edge(
        graph: nx.DiGraph,
        src: Any,
        dst: Any,
        key: Any,
        data: Dict[str, Any],
    ) -> None:
        if graph.is_multigraph():
            graph.add_edge(src, dst, key=key, **dict(data))
        else:
            graph.add_edge(src, dst, **dict(data))

    @classmethod
    def _mentions_any(cls, value: Any, needles: set[str]) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return any(needle in value for needle in needles)
        if isinstance(value, dict):
            return any(cls._mentions_any(inner, needles) for inner in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(cls._mentions_any(inner, needles) for inner in value)
        return any(needle in str(value) for needle in needles)

    def _ground_field_provenance(
        self,
        rows_by_table: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Attribute each cell to the chunks whose text actually contains it.

        Row-level `source_chunks` says "some chunk of this document supported
        this row", which cannot support a claim about one cell. This derives
        `<field>_source_chunks` per field, which `criteria.py` reads to promote
        `ROW_REF_ACCEPTED` to `FIELD_REF_ACCEPTED`.

        Deterministic by construction: a field is attributed to a chunk when
        its value appears verbatim in that chunk's text. No model is consulted,
        so no citation can be fabricated -- a model is the only component that
        could invent one. Values that are *not* verbatim get no field citation,
        which is the honest outcome: they are derived rather than quoted, and
        belong to the judged-best-guess basis with its judge and sources.

        Only the columns `criteria` itself counts as datapoints are grounded.
        Identity columns -- the endpoints and type of the edge a row was
        materialised from -- are supported by construction, so matching their
        text in a chunk would attach evidence to something no criterion asks
        about. Asking `criteria.datapoint_fields` rather than keeping a local
        list is what keeps the two from drifting apart.
        """

        # Reset FIRST, on every entry. Both early returns below previously left
        # the previous round's ledger in place, so a round that grounded
        # nothing reported the prior round's coverage as its own -- a stale
        # number is worse than a missing one, because it looks like a
        # measurement of this round. A round that cannot compute coverage must
        # say so and be excluded, never assumed to have passed.
        self.last_field_provenance_ledger = {
            "computed": False,
            "reason": "grounding did not run this round",
            "state_counts": {},
            "denominator": "",
            "accepted_source_count": 0,
            "sources": [],
        }
        if not rows_by_table:
            self.last_field_provenance_ledger["reason"] = (
                "no tables were exported this round, so there were no rows to "
                "ground and coverage is not measurable"
            )
            return rows_by_table

        # Rows seeded from an earlier run (via --graph-path / --seed-tables-dir)
        # can cite chunk ids this run's own papers_dir never fetched. Collect
        # every chunk id any row claims up front so _chunk_texts_by_id can
        # resolve the ones papers_dir misses from evidence_corpus_roots before
        # grounding starts, rather than silently leaving them unscoped.
        extra_chunk_ids: set[str] = set()
        for rows in rows_by_table.values():
            for row in rows:
                if isinstance(row, dict):
                    extra_chunk_ids.update(_row_chunk_ids(row))

        texts = self._chunk_texts_by_id(extra_chunk_ids)
        if not texts:
            # Previously an unconditional silent return: a run with no
            # resolvable chunk text at all produced exactly the artifacts of a
            # run with nothing to ground, and neither said so.
            print(
                "  Field provenance: SKIPPED -- no chunk text could be rebuilt "
                f"for any source ({len(extra_chunk_ids)} cited chunk id(s) "
                "across the tables, 0 resolvable). No field citations are "
                "derived this round, so no row can be promoted to "
                "FIELD_REF_ACCEPTED."
            )
            accepted, denominator = _coverage_denominator(self, set())
            self.last_field_provenance_ledger.update(
                {
                    "reason": (
                        "no chunk text could be rebuilt for any source, so no "
                        "source could be examined at field scope"
                    ),
                    "denominator": denominator,
                    "accepted_source_count": len(accepted),
                    "state_counts": {"not_examined": len(accepted)},
                    "sources": [
                        {
                            "source_id": source_id,
                            "field_scope_state": "not_examined",
                            "reason": "no chunk text was resolvable this round",
                            "extraction_state": str(
                                (
                                    _ingestion_ledger(self).get(source_id)
                                    or {}
                                ).get("extraction_state")
                                or "not_extracted"
                            ),
                        }
                        for source_id in accepted
                    ],
                }
            )
            return rows_by_table

        grounded_fields = 0
        grounded_rows = 0
        mismatched = 0
        uncited = 0
        unresolvable = 0
        unresolvable_chunk_ids: set[str] = set()
        # PER-SOURCE EVALUATION OUTCOME. Three states, recorded, never inferred.
        #
        # "field provenance ran over this source and matched nothing" and
        # "field provenance never reached this source" previously left the
        # identical trace: the source simply did not appear in any
        # `<field>_source_chunks`. Those are opposite facts about a run -- one
        # is a negative observation, the other is a coverage hole -- and a
        # reader could not separate them from any artifact.
        #
        # They are separated here, at the only place that knows: this loop is
        # what does or does not reach a source. A reader must never reconstruct
        # the state from whether a source appears in a citation, because that
        # absence is exactly the ambiguity being removed.
        cited_sources: set[str] = set()
        scoped_sources: set[str] = set()
        supported_sources: set[str] = set()
        unresolvable_sources: set[str] = set()
        mismatch_sources: set[str] = set()
        params = f"{self.config.chunk_size}:{self.config.chunk_overlap}"
        out: Dict[str, List[Dict[str, Any]]] = {}
        for name, rows in rows_by_table.items():
            groundable = set(datapoint_fields(name, rows, self.table_spec))
            new_rows: List[Dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    new_rows.append(row)
                    continue
                # Only this row's own chunks may attribute it. Searching the
                # whole corpus would attach any document that happens to
                # contain the string, which is coincidence, not provenance.
                # Chunk ids persist in seeded rows exported by earlier runs.
                # If `chunk_size` changed since, `X_chunk_3` now resolves to
                # different text and the citation would be silently wrong, so
                # a row is grounded only when its recorded chunking matches
                # what we can rebuild. Unstamped legacy rows are not grounded.
                stamped = str(row.get(CHUNK_PARAMS_FIELD) or "")
                pre_chunk_ids = list(_row_chunk_ids(row))
                cited_sources.update(
                    source
                    for chunk_id in pre_chunk_ids
                    if (source := _source_id_from_chunk_id(chunk_id))
                )
                if stamped and stamped != params:
                    mismatched += 1
                    mismatch_sources.update(
                        source
                        for chunk_id in pre_chunk_ids
                        if (source := _source_id_from_chunk_id(chunk_id))
                    )
                    new_rows.append(row)
                    continue
                row_chunk_ids = pre_chunk_ids
                scope = {
                    chunk_id: texts[chunk_id]
                    for chunk_id in row_chunk_ids
                    if chunk_id in texts
                }
                if not scope:
                    # Counted and reported, with the two causes kept apart.
                    # This branch was a bare `continue`, and that is what let a
                    # stale chunk cache hide for two full rounds: both
                    # neighbouring branches count and print, so a row that
                    # vanished here left no trace anywhere while its neighbours
                    # were fully accounted for. "This row cited nothing" and
                    # "this row cited chunks I could not rebuild" are different
                    # failures with different fixes -- the first is an
                    # extraction gap, the second is a corpus gap -- and they
                    # must not share one observable.
                    if not row_chunk_ids:
                        uncited += 1
                    else:
                        unresolvable += 1
                        unresolvable_chunk_ids.update(row_chunk_ids)
                        unresolvable_sources.update(
                            source
                            for chunk_id in row_chunk_ids
                            if (source := _source_id_from_chunk_id(chunk_id))
                        )
                    new_rows.append(row)
                    continue
                # Every source in scope WAS examined: its chunk text was read
                # and compared against this row's values. Recorded before the
                # match runs, so the examined set never depends on the outcome.
                scoped_sources.update(
                    source
                    for chunk_id in scope
                    if (source := _source_id_from_chunk_id(chunk_id))
                )
                row = {**row, CHUNK_PARAMS_FIELD: params}
                new_row, report = derive_field_provenance(
                    row, scope, groundable_fields=groundable
                )
                if report["fields_grounded_verbatim"]:
                    grounded_rows += 1
                    grounded_fields += len(report["fields_grounded_verbatim"])
                    for grounded_field in report["fields_grounded_verbatim"]:
                        for chunk_id in new_row.get(
                            f"{grounded_field}{FIELD_PROVENANCE_SUFFIX}", ()
                        ):
                            source = _source_id_from_chunk_id(str(chunk_id))
                            if source:
                                supported_sources.add(source)
                new_rows.append(new_row)
            out[name] = new_rows

        # One recorded outcome per ACCEPTED source, so coverage of the grounding
        # step is a fact in the artifacts rather than something a reader infers
        # from silence. Built over the accepted set, not over the sources that
        # happened to appear, because a source that appears nowhere is exactly
        # the case being made visible.
        # The denominator is the ACCEPTED set where one can be enumerated. A
        # caller that supplies rows and chunk texts directly (test harnesses,
        # and any future caller that owns its own corpus) has no papers_dir to
        # enumerate, and the ledger says which denominator it used rather than
        # silently reporting coverage against a different population.
        accepted_sources, denominator = _coverage_denominator(self, 
            cited_sources | scoped_sources | supported_sources
        )
        source_ledger: List[Dict[str, Any]] = []
        for source_id in accepted_sources:
            if source_id in supported_sources:
                state, reason = "examined_supported", ""
            elif source_id in scoped_sources:
                state, reason = (
                    "examined_unsupported",
                    "chunk text was read and compared; no declared datapoint "
                    "field matched it verbatim",
                )
            elif source_id in unresolvable_sources:
                state, reason = (
                    "not_examined",
                    "rows cite this source but its chunk text could not be "
                    "rebuilt from this run's corpus",
                )
            elif source_id in mismatch_sources:
                state, reason = (
                    "not_examined",
                    "every row citing this source records a different chunking "
                    f"than the current {params} split, so its chunk ids would "
                    "resolve to different text",
                )
            elif source_id in cited_sources:
                state, reason = (
                    "not_examined",
                    "cited by a row that was skipped before scoping",
                )
            else:
                # "No row cites this source" is a statement about a step
                # UPSTREAM of grounding, and on its own it is exactly the
                # ambiguity this ledger exists to remove -- extraction ran and
                # found nothing (a genuine negative) and extraction never ran
                # (an instrument failure) both produce no row. The extraction
                # ledger is joined in here so the two are separable, rather
                # than closing the collapse at field scope and re-opening it
                # one layer up.
                state = "not_examined"
                ingestion = _ingestion_ledger(self).get(source_id) or {}
                extraction_state = str(
                    ingestion.get("extraction_state") or "not_extracted"
                )
                if extraction_state == "extracted_no_entities":
                    reason = (
                        "no exported row cites this source because extraction "
                        "read its full text and produced zero entities -- a "
                        "genuine negative observation, not a coverage hole"
                    )
                elif extraction_state == "extracted_entities":
                    reason = (
                        "extraction produced entities for this source but no "
                        "exported row cites it, so the row was lost between "
                        "the graph and the answer table -- a traversal or "
                        "export gap, not an extraction gap"
                    )
                elif extraction_state == "extraction_failed":
                    reason = (
                        "extraction raised on this source, so it never entered "
                        f"the graph: {ingestion.get('reason') or 'unknown error'}"
                    )
                else:
                    reason = (
                        "extraction never ran on this source, so it produced "
                        "no row and no field citation; it was accepted but "
                        "never ingested"
                    )
            source_ledger.append(
                {
                    "source_id": source_id,
                    "field_scope_state": state,
                    "reason": reason,
                    # Carried on every entry so row scope and field scope can be
                    # read together without a second join.
                    "extraction_state": str(
                        (_ingestion_ledger(self).get(source_id) or {}).get(
                            "extraction_state"
                        )
                        or "not_extracted"
                    ),
                }
            )
        state_counts: Dict[str, int] = {}
        for entry in source_ledger:
            state_counts[entry["field_scope_state"]] = (
                state_counts.get(entry["field_scope_state"], 0) + 1
            )
        self.last_field_provenance_ledger = {
            "computed": True,
            "reason": "",
            "accepted_source_count": len(accepted_sources),
            "denominator": denominator,
            "state_counts": state_counts,
            "chunk_params": params,
            "resolvable_chunk_count": len(texts),
            "sources": source_ledger,
        }
        print(
            "  Field provenance coverage: "
            + ", ".join(
                f"{state}={count}"
                for state, count in sorted(state_counts.items())
            )
            + f" over {len(accepted_sources)} accepted source(s)"
        )

        if mismatched:
            print(
                f"  Field provenance: {mismatched} row(s) not grounded -- their "
                f"chunking differs from the current {params} split, so their "
                f"chunk ids would resolve to different text"
            )
        if uncited:
            print(
                f"  Field provenance: {uncited} row(s) not grounded -- they "
                "record no source_chunks at all, so there is nothing to "
                "attribute their cells to"
            )
        if unresolvable:
            unresolved_sources = sorted(
                {
                    source_id
                    for chunk_id in unresolvable_chunk_ids
                    if (source_id := _source_id_from_chunk_id(chunk_id))
                    and chunk_id not in texts
                }
            )
            print(
                f"  Field provenance: {unresolvable} row(s) not grounded -- "
                f"they cite {len(unresolvable_chunk_ids)} chunk id(s) from "
                f"{len(unresolved_sources)} source(s) whose text could not be "
                f"rebuilt from this run's corpus ({len(texts)} chunk(s) "
                "available). These rows can never be credited until their "
                "sources resolve"
            )
        if grounded_rows:
            print(
                f"  Field provenance: {grounded_fields} cell(s) across "
                f"{grounded_rows} row(s) grounded verbatim in their own chunks"
            )
        return out

    def _chunk_texts_by_id(
        self, extra_chunk_ids: Iterable[str] = ()
    ) -> Dict[str, str]:
        """chunk id -> chunk text, rebuilt from the fetched source documents.

        Chunking is deterministic, so the same split the extractor saw is
        recoverable from the stored text; nothing extra needs persisting.

        ``extra_chunk_ids`` are chunk ids a caller needs resolved that may not
        belong to any source in this run's own ``papers_dir`` -- typically
        citations on rows seeded from an earlier run. For each such id whose
        source is not already covered by the local corpus, this falls back to
        ``self.config.evidence_corpus_roots`` in order. A source id resolvable
        locally never consults a corpus root; passing no ids, or configuring
        no roots, reproduces the original local-only lookup exactly.
        """

        # INVALIDATION. The cache is keyed on the papers_dir source-id set and
        # the chunking parameters, because both change what the cache should
        # contain and neither is observable from the cached dict itself.
        #
        # Built once and never rebuilt, this guard made the cache a snapshot of
        # whichever round happened to ground first. `_source_records_by_id`
        # re-globs on every call and is uncached, so every other reader saw new
        # papers immediately; only this one did not. The consequence was not a
        # slow path but a wrong answer: a row citing only round-1 or round-2
        # papers found none of its chunk ids in `texts`, fell into the silent
        # `if not scope` skip below, was never stamped, and was therefore never
        # credited -- so `credited_datapoints` read 0 for every round after the
        # first and the reward gradient was flat by construction.
        #
        # Keying on the id set rather than a dirty flag means correctness does
        # not depend on every writer of papers_dir remembering to signal.
        # `papers_dir` is the corpus the key is computed from, so its absence is
        # the precondition for keying at all -- a caller that supplies
        # `_chunk_text_cache` directly and has no papers_dir owns its own corpus
        # and has nothing to go stale against. That case must still be loud when
        # it supplies neither, because an empty cache built from no corpus
        # grounds nothing and would look exactly like a corpus with no matches.
        papers_dir = getattr(self, "papers_dir", None)
        cached = getattr(self, "_chunk_text_cache", None)
        if papers_dir is None:
            if cached is None:
                raise AttributeError(
                    "_chunk_texts_by_id needs either a papers_dir to rebuild "
                    "chunk texts from or a pre-supplied _chunk_text_cache; "
                    "this object has neither, and returning an empty mapping "
                    "would silently ground nothing"
                )
            current_source_ids = getattr(
                self, "_chunk_text_cache_source_ids", None
            )
            chunk_params = getattr(self, "_chunk_text_cache_params", None)
            # Recorded rather than merely skipped. This is the one path where
            # invalidation does not run, so it states itself on the instance
            # instead of being inferable only from the absence of a rebuild.
            self._chunk_text_cache_invalidation = "caller_supplied_no_papers_dir"
        else:
            current_source_ids = frozenset(self._source_records_by_id())
            chunk_params = (self.config.chunk_size, self.config.chunk_overlap)
            self._chunk_text_cache_invalidation = "keyed_on_papers_dir_source_ids"

        if cached is None or (
            papers_dir is not None
            and (
                getattr(self, "_chunk_text_cache_source_ids", None)
                != current_source_ids
                or getattr(self, "_chunk_text_cache_params", None) != chunk_params
            )
        ):
            texts: Dict[str, str] = {}
            for source_id, record in self._source_records_with_text_by_id().items():
                body = str(record.get("text") or "")
                if not body:
                    continue
                for index, chunk in enumerate(
                    chunk_text(body, self.config.chunk_size, self.config.chunk_overlap)
                ):
                    texts[f"{source_id}_chunk_{index}"] = chunk
            self._chunk_text_cache = texts
            self._chunk_text_cache_source_ids = current_source_ids
            self._chunk_text_cache_params = chunk_params

        texts = self._chunk_text_cache
        evidence_corpus_roots = getattr(self.config, "evidence_corpus_roots", ())
        if not evidence_corpus_roots:
            return texts

        missing_source_ids: set[str] = set()
        for chunk_id in extra_chunk_ids:
            if chunk_id in texts:
                continue
            source_id = _source_id_from_chunk_id(chunk_id)
            if source_id:
                missing_source_ids.add(source_id)

        for source_id in missing_source_ids:
            body = self._resolve_source_text_from_corpus_roots(source_id)
            if not body:
                continue
            for index, chunk in enumerate(
                chunk_text(body, self.config.chunk_size, self.config.chunk_overlap)
            ):
                texts.setdefault(f"{source_id}_chunk_{index}", chunk)

        return texts

    def _resolve_source_text_from_corpus_roots(
        self, source_id: str
    ) -> Optional[str]:
        """Text for ``source_id`` from ``evidence_corpus_roots``, first hit wins.

        Only consulted for source ids this run's own ``papers_dir`` could not
        resolve -- see ``_chunk_texts_by_id``. Misses are cached too, so a
        citation no root has costs one filesystem probe per root, once, not
        once per grounding pass.
        """

        cache = getattr(self, "_corpus_root_text_cache", None)
        if cache is None:
            cache = {}
            self._corpus_root_text_cache = cache
        if source_id in cache:
            return cache[source_id]

        text: Optional[str] = None
        for root in getattr(self.config, "evidence_corpus_roots", ()):
            candidate = Path(root) / "fetched_papers" / f"{source_id}.txt"
            try:
                candidate_text = candidate.read_text(encoding="utf-8")
            except OSError:
                continue
            if candidate_text:
                text = candidate_text
                break
        cache[source_id] = text
        return text

    async def _export_gasl_tables(
        self, round_idx: int | str, gasl_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        if self.config.answer_mode != "table":
            return []

        final_state = gasl_result.get("final_state") or {}
        exports: List[Dict[str, Any]] = []
        rows_by_name = self._compiled_answer_view_tables(final_state)
        # A compiled answer view is a declared output: the answer layer was
        # asked to build it. The raw sweep below takes every LIST variable
        # whose name happens to end in `_table`, which is how a traversal's
        # intermediate working variables arrive. Both are worth exporting for
        # inspection; only the first is an answer, and the distinction is lost
        # after the merge, so record it here.
        self._answer_view_table_names = set(rows_by_name)
        raw_rows_by_name = self._raw_gasl_table_variables(final_state)
        for name, rows in raw_rows_by_name.items():
            rows_by_name.setdefault(name, rows)

        current_rows = {
            name: self._table_export_rows(
                name,
                rows,
                required_columns=self._required_columns(name),
            )
            for name, rows in rows_by_name.items()
            if isinstance(rows, list)
        }
        current_rows = self._ground_field_provenance(current_rows)
        current_rows = self._apply_path_gate(round_idx, current_rows)
        merged_rows = merge_rows_by_table(
            self.seed_tables.rows_by_name,
            current_rows,
        )
        exports = await self._write_table_exports(
            round_idx,
            merged_rows,
            seed_row_counts={
                name: len(rows)
                for name, rows in self.seed_tables.rows_by_name.items()
            },
            new_row_counts={
                name: len(rows)
                for name, rows in current_rows.items()
            },
        )
        self.seed_tables = SeedTables(
            rows_by_name=merged_rows,
            sources=self.seed_tables.sources,
        )
        return exports

    async def _export_seed_tables(
        self, artifact_label: int | str = "seed",
    ) -> List[Dict[str, Any]]:
        if self.config.answer_mode != "table":
            return []
        if not self.seed_tables.rows_by_name:
            return []

        return await self._write_table_exports(
            artifact_label,
            self.seed_tables.rows_by_name,
            seed_row_counts={
                name: len(rows)
                for name, rows in self.seed_tables.rows_by_name.items()
            },
            new_row_counts={},
        )

    async def _write_table_exports(
        self,
        artifact_label: int | str,
        rows_by_name: Dict[str, List[Dict[str, Any]]],
        *,
        seed_row_counts: Dict[str, int],
        new_row_counts: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        artifact_stem = self._artifact_stem(artifact_label)
        exports: List[Dict[str, Any]] = []
        rows_by_name = {
            **self.table_spec.empty_rows_by_table(),
            **rows_by_name,
        }
        table_names = self._export_table_names(rows_by_name)
        for name in table_names:
            items = rows_by_name.get(name)
            if not isinstance(items, list):
                continue

            self.tables_dir.mkdir(parents=True, exist_ok=True)
            json_path = self.tables_dir / f"{artifact_stem}_{name}.json"
            csv_path = self.tables_dir / f"{artifact_stem}_{name}.csv"
            json_path.write_text(
                json.dumps(items, indent=2, default=str), encoding="utf-8"
            )

            csv_written = False
            if all(isinstance(item, dict) for item in items):
                self._write_table_csv(csv_path, items, table_name=name)
                csv_written = True

            record = {
                "artifact_label": artifact_label,
                "pipeline_round": self._pipeline_round(artifact_label),
                "variable": name,
                "rows": len(items),
                "seed_rows": seed_row_counts.get(name, 0),
                "new_rows": new_row_counts.get(name, 0),
                "json_path": str(json_path),
                "csv_path": str(csv_path) if csv_written else None,
                "validation": self._validate_table(name, items),
                "gaps": self._diagnostic_table_gaps(name, items),
            }
            exports.append(record)
            self.table_exports.append(record)

        if exports:
            manifest_path = self.tables_dir / f"{artifact_stem}_manifest.json"
            manifest_path.write_text(
                json.dumps(exports, indent=2, default=str), encoding="utf-8"
            )
            self._write_observed_table_spec(artifact_label, rows_by_name, table_names)

        self.last_derived_table_exports = await self._write_derived_exports(
            artifact_label,
            {
                table_name: rows_by_name.get(table_name, [])
                for table_name in table_names
            },
        )
        return exports

    async def _write_derived_exports(
        self,
        artifact_label: int | str,
        rows_by_name: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        best_guess_state = await self._run_best_guess_recovery(
            artifact_label,
            rows_by_name,
        )
        best_guess_context = best_guess_context_by_row_key(best_guess_state)
        numeric_exports = self._write_numeric_candidate_exports(
            artifact_label,
            rows_by_name,
            best_guess_context_by_row=best_guess_context,
        )
        self.last_reward_exports = self._write_reward_exports(
            artifact_label,
            previous_rows_by_name=self.seed_tables.rows_by_name,
            current_rows_by_name=rows_by_name,
            best_guess_state=best_guess_state,
        )
        self.seed_best_guess_rows = merge_best_guess_rows(
            self.seed_best_guess_rows,
            best_guess_state.get("resolutions") or [],
        )
        exports = [
            *self.last_best_guess_exports,
            *numeric_exports,
            *self.last_reward_exports,
        ]
        self._write_derived_manifest(artifact_label, exports)
        return exports

    async def _run_best_guess_recovery(
        self,
        artifact_label: int | str,
        rows_by_name: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        if self.config.best_guess_mode == "off":
            self.last_best_guess_exports = []
            self.last_best_guess_state = {}
            return {}

        source_records = self._source_records_with_text_by_id()
        source_texts = {
            source_id: str(record.get("text") or "")
            for source_id, record in source_records.items()
        }
        source_metadata = {
            source_id: {
                key: value
                for key, value in record.items()
                if key != "text"
            }
            for source_id, record in source_records.items()
        }
        graph_records = self._graph_records_by_source_id(
            set(source_records),
            per_source_limit=16,
        )

        kwargs = {
            "count_targets": [
                *(self.goal_universe_estimate.get("count_targets") or []),
                *(self.goal_universe_estimate.get("unestimated_count_targets") or []),
            ],
            "slot_targets": self.table_spec.best_guess_slot_targets(),
            "source_records": source_metadata,
            "graph_records": graph_records,
            "max_tasks": self.config.best_guess_max_tasks,
        }
        with self._cost_scope(
            ObservationKind.BEST_GUESS.value,
            observation_id=f"{self._artifact_stem(artifact_label)}_best_guess",
            round_index=_safe_int(self._pipeline_round(artifact_label), 0),
        ):
            if self.config.best_guess_mode == "llm":
                state = await run_best_guess_recovery(
                    rows_by_name,
                    **kwargs,
                    source_texts=source_texts,
                    evidence_chars=self.config.best_guess_evidence_chars,
                    llm_batch_size=self.config.best_guess_llm_batch_size,
                    llm_timeout_sec=self.config.best_guess_llm_timeout_sec,
                    progress_fn=self._best_guess_progress_writer(artifact_label),
                    extract_fn=self._infer_best_guess_candidates,
                )
            else:
                state = run_best_guess_recovery_local(rows_by_name, **kwargs)

        self.last_best_guess_exports = self._write_best_guess_exports(
            artifact_label,
            state,
        )
        self.last_best_guess_state = state
        return state

    def _best_guess_progress_writer(self, artifact_label: int | str):
        artifact_stem = self._artifact_stem(artifact_label)
        self.derived_dir.mkdir(parents=True, exist_ok=True)
        path = self.derived_dir / f"{artifact_stem}_best_guess_progress.jsonl"

        def write_progress(record: Dict[str, Any]) -> None:
            payload = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "artifact_label": artifact_label,
                "pipeline_round": self._pipeline_round(artifact_label),
                **record,
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, default=str) + "\n")
            print(
                "  Best-guess "
                f"{payload.get('operator')} {payload.get('event')} "
                f"batch={payload.get('batch_index', '-')}/"
                f"{payload.get('batch_count', '-')}",
                flush=True,
            )

        return write_progress

    async def _infer_best_guess_candidates(
        self,
        operator: str,
        tasks: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return await strategy.infer_best_guess_candidates(
            self.llm,
            self.config.question,
            operator=operator,
            tasks=tasks,
            evidence=evidence,
        )

    def _write_best_guess_exports(
        self,
        artifact_label: int | str,
        state: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        artifact_stem = self._artifact_stem(artifact_label)
        self.derived_dir.mkdir(parents=True, exist_ok=True)
        records = [
            (
                "best_guess_plan",
                state.get("plan") or [],
                None,
            ),
            (
                "best_guess_attempts",
                state.get("attempts") or [],
                None,
            ),
            (
                "best_guess_tasks",
                state.get("tasks") or [],
                None,
            ),
            (
                "best_guess_candidates",
                state.get("candidates") or [],
                list(BEST_GUESS_CANDIDATE_COLUMNS),
            ),
            (
                "best_guess_context",
                state.get("resolutions") or [],
                list(BEST_GUESS_CONTEXT_COLUMNS),
            ),
            (
                "best_guess_strategy_state",
                [
                    {
                        "coverage": state.get("coverage") or {},
                        "operator_summary": state.get("operator_summary") or [],
                        "overlap": state.get("overlap") or [],
                        "errors": state.get("errors") or [],
                    }
                ],
                None,
            ),
        ]
        exports: List[Dict[str, Any]] = []
        for variable, rows, columns in records:
            json_path = self.derived_dir / f"{artifact_stem}_{variable}.json"
            csv_path = self.derived_dir / f"{artifact_stem}_{variable}.csv"
            json_path.write_text(
                json.dumps(rows, indent=2, default=str),
                encoding="utf-8",
            )
            if columns is None:
                columns = []
                for row in rows:
                    if isinstance(row, dict):
                        columns.extend(
                            key for key in row if key not in columns
                        )
            self._write_rows_csv(csv_path, rows, fieldnames=columns)
            exports.append(
                {
                    "artifact_label": artifact_label,
                    "pipeline_round": self._pipeline_round(artifact_label),
                    "variable": variable,
                    "rows": len(rows),
                    "json_path": str(json_path),
                    "csv_path": str(csv_path),
                }
            )

        self.best_guess_exports.extend(exports)
        return exports

    def _write_numeric_candidate_exports(
        self,
        artifact_label: int | str,
        rows_by_name: Dict[str, List[Dict[str, Any]]],
        *,
        best_guess_context_by_row: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if self.config.answer_mode != "table":
            return []
        if self.config.numeric_candidate_mode == "off":
            return []

        rows = numeric_candidates_from_tables(
            rows_by_name,
            mode=self.config.numeric_candidate_mode,
            context_slots=self._derived_context_slots(),
            source_records=self._source_records_by_id(),
            best_guess_context_by_row=best_guess_context_by_row,
        )
        artifact_stem = self._artifact_stem(artifact_label)
        self.derived_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.derived_dir / f"{artifact_stem}_numeric_candidates.json"
        csv_path = self.derived_dir / f"{artifact_stem}_numeric_candidates.csv"
        json_path.write_text(
            json.dumps(rows, indent=2, default=str),
            encoding="utf-8",
        )
        self._write_rows_csv(
            csv_path,
            rows,
            fieldnames=list(NUMERIC_CANDIDATE_COLUMNS),
        )
        record = {
            "artifact_label": artifact_label,
            "pipeline_round": self._pipeline_round(artifact_label),
            "variable": "numeric_candidates",
            "mode": self.config.numeric_candidate_mode,
            "rows": len(rows),
            "json_path": str(json_path),
            "csv_path": str(csv_path),
        }
        self.derived_table_exports.append(record)
        return [record]

    def _write_reward_exports(
        self,
        artifact_label: int | str,
        *,
        previous_rows_by_name: Dict[str, List[Dict[str, Any]]],
        current_rows_by_name: Dict[str, List[Dict[str, Any]]],
        best_guess_state: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if self.config.answer_mode != "table":
            return []

        # Both sides go through `criteria.project_rows`, so reward reads the
        # same projection every other consumer joins on rather than parsing
        # rows for itself.  The allowlist is explicit: the spec guard defaults
        # open, and a working table reaching the projection would put
        # best-guess *candidates* -- including rejected ones -- on the scoring
        # surface.
        #
        # That was written as though the allowlist already prevented working
        # tables from scoring. It did not. Its no-spec fallback was every table
        # handed in, and a traversal hands in its intermediate variables too,
        # so on a run that declared no spec the allowlist named the very tables
        # it existed to exclude. `_declared_table_names` now supplies the
        # missing statement of intent.
        round_index = self._pipeline_round(artifact_label)
        if round_index is None:
            # Pre-existing gap, not a 3B defect: `_pipeline_round` returns
            # `None` for a non-numeric artifact label (e.g. the "seed"
            # bootstrap export), and `reward.score_criterion_yield` has no
            # round to attribute cost or first-harvest credit to -- "round
            # level is the finest granularity that is honest here" per its
            # own docstring, and a bootstrap re-export of the seed state is
            # not a round. Skip scoring rather than crediting against an
            # undefined round; the first real numbered round scores from here
            # forward through the normal path.
            return []
        source_records = self._source_records_by_id()
        first_accepted_round = {
            source_id: int(record.get("search_round_index") or 0)
            for source_id, record in source_records.items()
        }
        accepted_source_ids = sorted(source_records)
        resolutions = (best_guess_state or {}).get("resolutions") or []

        # THE CHAIN IS CARRIED, NOT RECONSTRUCTED.
        #
        # `before` used to be a fresh projection of `self.seed_tables.rows_by_name`.
        # That is a different row set from the one the previous round scored as
        # its `after`, so consecutive rounds did not meet: on the live
        # earthquake run round 1's `after` was `fd2cc58a60dabcfd` while round
        # 2's `before` was `615fb3d17f39bd35`, and the recorded round-2
        # `before` is reproducible as the projection of the round-1 *exported*
        # table -- confirming the two sides were built from different rows.
        #
        # Whatever appeared in that gap was scored by nobody. It is not a
        # rounding error in the credit: it is an interval of the run that no
        # round's reward covers, with no error and no disclosure, and it
        # compounds with every additional round. The round-0-only symptom that
        # motivated this work masked it, because a chain that credits zero for
        # every later round looks the same whether or not it is continuous.
        #
        # Making `before` literally the stored `after` object removes the gap
        # by construction rather than by keeping two derivations in agreement,
        # which is the kind of invariant that holds until someone edits one of
        # them.
        # THE COST CUT IS RECORDED, NOT LEFT TO BE RECONSTRUCTED.
        #
        # This runs MID-round, so `self.cost_records` is a prefix that keeps
        # growing after scoring. The export stated the resulting sum and not the
        # cut it came from, so re-summing the finished list against the export
        # over-counts: on the recorded run round 0 the reward saw 21 records
        # while 57 records ultimately carry `round_index: 0`, a 2.0-2.7x gap.
        # Recovering the true cut afterwards required finding the unique prefix
        # that reproduced all fifteen cost fields at once -- sound, but nobody
        # should have to do it, and a reader who did not realise the list had
        # grown would simply get a wrong number with nothing to warn them.
        #
        # A frozen snapshot is scored, and the ids inside it are emitted, so the
        # cut is readable from the export rather than inferred from it.
        cost_snapshot = [
            record for record in self.cost_records if isinstance(record, Mapping)
        ]
        matched_cost_records = [
            record
            for record in cost_snapshot
            if _safe_int(record.get("round_index"), -1) == round_index
        ]
        cost_observation_ids = [
            str(record.get("observation_id") or "") for record in matched_cost_records
        ]

        chained = self._last_reward_after is not None
        if chained:
            before = self._last_reward_after
        else:
            before = project_rows(
                previous_rows_by_name,
                self.table_spec,
                accepted_source_ids=accepted_source_ids,
                deliverable_tables=self._deliverable_tables(previous_rows_by_name),
            )
        after = project_rows(
            current_rows_by_name,
            self.table_spec,
            accepted_source_ids=accepted_source_ids,
            best_guess_resolutions=resolutions,
            deliverable_tables=self._deliverable_tables(current_rows_by_name),
        )
        reward = score_criterion_yield(
            before,
            after,
            round_index=round_index,
            first_accepted_round=first_accepted_round,
            ledger=self.reward_credit_ledger,
            cost_records=cost_snapshot,
        )
        self.reward_credit_ledger = reward.ledger
        report = reward.to_dict()

        # Closing the chain removes the leak but would also hide the thing that
        # caused it: the `after` snapshots are taken over different rows than
        # the exports. So the projection the old code would have used is still
        # computed and compared, and the disagreement is reported rather than
        # silently resolved. `chain_continuous: false` here means this round's
        # carried `before` does not match a fresh projection of the previous
        # exported state -- credit is no longer lost either way, but the two
        # derivations disagree and someone should know which is right.
        rebuilt = project_rows(
            previous_rows_by_name,
            self.table_spec,
            accepted_source_ids=accepted_source_ids,
            deliverable_tables=self._deliverable_tables(previous_rows_by_name),
        )
        report["before_snapshot_source"] = (
            "previous_round_after" if chained else "projection_of_previous_rows"
        )
        report["before_snapshot_rebuilt_id"] = rebuilt.id
        report["chain_continuous"] = (not chained) or before.id == rebuilt.id
        if chained and before.id != rebuilt.id:
            report["chain_divergence_reason"] = (
                "the previous round's `after` snapshot and a fresh projection "
                "of the previous exported rows do not agree, so the two are "
                "built from different row sets; scoring uses the carried "
                "`after` so no interval goes uncredited"
            )

        self._last_reward_after = after
        self.last_reward_report = report
        artifact_stem = self._artifact_stem(artifact_label)
        self.derived_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.derived_dir / f"{artifact_stem}_reward.json"
        csv_path = self.derived_dir / f"{artifact_stem}_reward.csv"
        components = reward.components()
        json_path.write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )
        self._write_rows_csv(
            csv_path,
            components,
            fieldnames=list(REWARD_COMPONENT_COLUMNS),
        )
        record = {
            "artifact_label": artifact_label,
            "pipeline_round": round_index,
            "variable": "criterion_yield_reward",
            "score": report.get("score"),
            "credited_datapoints": reward.datapoint_count,
            "cost_available": reward.cost_available,
            # The exact cut the cost block was computed over, so the export can
            # be reconciled against the finished record list without guessing
            # which prefix was in scope. `cost_records_scored` is what the sum
            # actually covers; `cost_records_visible_at_scoring` is how much of
            # the list existed at that moment; the ids pin it exactly.
            "cost_records_scored": len(matched_cost_records),
            "cost_records_visible_at_scoring": len(cost_snapshot),
            "cost_record_observation_ids": cost_observation_ids,
            "cost_scored_mid_round": True,
            # A round that genuinely had no cost records says so, rather than
            # presenting a zero sum that reads the same as free work.
            "cost_absent_reason": (
                ""
                if matched_cost_records
                else (
                    f"no cost record carried round_index={round_index} at "
                    f"scoring time ({len(cost_snapshot)} record(s) visible); "
                    "the cost block is a sum over nothing, not a measurement "
                    "that this round was free"
                )
            ),
            # The snapshot-chain fields were written into the reward JSON but
            # never onto this record, so every consumer reading exports saw
            # `chain_continuous: None` -- indistinguishable from a chain that
            # was checked and found broken. A run gate cannot assert on a field
            # that is never emitted, so absent and false must not look alike.
            "chain_continuous": report.get("chain_continuous"),
            "before_snapshot_source": report.get("before_snapshot_source"),
            "before_criteria_snapshot_id": report.get(
                "before_criteria_snapshot_id"
            ),
            "after_criteria_snapshot_id": report.get("after_criteria_snapshot_id"),
            "before_snapshot_rebuilt_id": report.get("before_snapshot_rebuilt_id"),
            "chain_divergence_reason": report.get("chain_divergence_reason", ""),
            "rows": len(components),
            "json_path": str(json_path),
            "csv_path": str(csv_path),
        }
        self.reward_exports.append(record)
        self.derived_table_exports.append(record)
        return [record]

    def _write_derived_manifest(
        self,
        artifact_label: int | str,
        exports: List[Dict[str, Any]],
    ) -> None:
        if not exports:
            return
        artifact_stem = self._artifact_stem(artifact_label)
        self.derived_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.derived_dir / f"{artifact_stem}_manifest.json"
        manifest_path.write_text(
            json.dumps(exports, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _compiled_answer_view_tables(
        final_state: Dict[str, Any],
    ) -> Dict[str, List[Dict[str, Any]]]:
        runtime_view = {
            "state_variables": final_state.get("variables", {}),
            "context_variables": {},
            "produced_artifacts": final_state.get("produced_artifacts", []),
            "history": final_state.get("history", []),
        }
        views = AnswerLayerCompiler().build_views(runtime_view)
        tables: Dict[str, List[Dict[str, Any]]] = {}
        for view in views:
            if view.kind != "evidence_table":
                continue
            # Evidence-table views identify their source in the typed view,
            # not by duplicating that identity into the payload.  Reading only
            # payload["table_name"] therefore discarded every ordinary GASL
            # row variable, including variables whose names exactly matched a
            # declared table spec; only the separate `_table` raw-variable
            # fallback could ever export rows.
            table_name = view.payload.get("table_name") or view.source_variable
            rows = view.payload.get("rows")
            if table_name and isinstance(rows, list):
                tables[str(table_name)] = [
                    row.get("raw", row) if isinstance(row, dict) else row
                    for row in rows
                ]
        return tables

    @staticmethod
    def _raw_gasl_table_variables(
        final_state: Dict[str, Any],
    ) -> Dict[str, List[Any]]:
        tables: Dict[str, List[Any]] = {}
        for name, variable in (final_state.get("variables") or {}).items():
            if not (
                isinstance(variable, dict)
                and variable.get("_meta", {}).get("type") == "LIST"
                and name.endswith("_table")
            ):
                continue

            raw_items = variable.get("items") or []
            if isinstance(raw_items, list):
                tables[name] = raw_items
        return tables

    @classmethod
    def _table_export_rows(
        cls,
        name: str,
        rows: List[Any],
        *,
        required_columns: List[str] | None = None,
    ) -> List[Any]:
        export_rows: List[Any] = []
        for row in rows:
            if not isinstance(row, dict):
                export_rows.append(row)
                continue
            if not cls._row_matches_export_table(name, row):
                continue

            nested = row.get("items")
            if not nested and isinstance(row.get(name), list):
                nested = row.get(name)
            if isinstance(nested, list) and nested:
                nested_dicts = [
                    item
                    for item in nested
                    if (
                        isinstance(item, dict)
                        and cls._row_matches_export_table(name, item)
                    )
                ]
                if nested_dicts:
                    for nested_row in nested_dicts:
                        export_rows.append(
                            cls._with_table_group_metadata(
                                name,
                                nested_row,
                                row,
                                required_columns=required_columns,
                            )
                        )
                    continue

            export_rows.append(cls._with_required_table_columns(row, required_columns))

        return export_rows

    @staticmethod
    def _row_matches_export_table(name: str, row: Dict[str, Any]) -> bool:
        table_name = row.get("table_name")
        return not table_name or table_name == name

    @classmethod
    def _with_table_group_metadata(
        cls,
        name: str,
        nested_row: Dict[str, Any],
        group_row: Dict[str, Any],
        *,
        required_columns: List[str] | None = None,
    ) -> Dict[str, Any]:
        row = dict(nested_row)
        for field in (
            "deduplication_key",
            "group_key",
            "group_name",
            "supporting_path_count",
            "occurrence_count",
        ):
            if field in group_row and cls._is_missing(row.get(field)):
                row[field] = group_row[field]
        return cls._with_required_table_columns(row, required_columns)

    @staticmethod
    def _with_required_table_columns(
        row: Dict[str, Any],
        required_columns: List[str] | None = None,
    ) -> Dict[str, Any]:
        return {
            **{
                column: row.get(column, "")
                for column in (required_columns or [])
            },
            **row,
        }

    def _validate_table(self, name: str, rows: List[Any]) -> Dict[str, Any]:
        required = self._required_columns(name)
        completeness_columns = self._completeness_columns(name)
        row_dicts = [row for row in rows if isinstance(row, dict)]
        missing_by_column = {
            column: sum(
                1 for row in row_dicts if self._is_missing(row.get(column))
            )
            for column in completeness_columns
        }
        # A row is "complete" when no column it must carry is missing. With no
        # columns to check, `all(...)` over an empty sequence is vacuously true
        # and every row is certified complete -- which is how the live
        # earthquake run's round-2 manifest reported 303 of 303 rows complete
        # with zero gaps on a table whose spec declares no required columns at
        # all. Unmeasurable and satisfied produced the identical artifact.
        #
        # The self-declared route is measurable regardless, because a row that
        # carries its own `completeness` field is asserting something falsifiable.
        self_declared = any("completeness" in row for row in row_dicts)
        checked_columns = list(completeness_columns or required)
        measurable = bool(self_declared or checked_columns)

        if self_declared:
            complete_rows = sum(
                1 for row in row_dicts if row.get("completeness") == "complete"
            )
        elif checked_columns:
            complete_rows = sum(
                1
                for row in row_dicts
                if all(
                    not self._is_missing(row.get(column))
                    for column in checked_columns
                )
            )
        else:
            complete_rows = None

        validation: Dict[str, Any] = {
            "required_columns": required,
            "rows": len(rows),
            "dict_rows": len(row_dicts),
            "completeness_measurable": measurable,
            "completeness_basis": (
                "row-declared completeness field"
                if self_declared
                else "required/completeness columns"
                if checked_columns
                else "none"
            ),
            "completeness_checked_columns": checked_columns,
            "complete_rows": complete_rows,
            "partial_rows": (
                None if complete_rows is None
                else max(0, len(row_dicts) - complete_rows)
            ),
            "missing_by_column": {
                column: missing
                for column, missing in missing_by_column.items()
                if missing
            },
        }
        if not measurable:
            # Fail closed with a reason rather than defaulting to a pass. A
            # consumer that does `float(complete_rows or 0)` on this now gets a
            # visibly wrong zero instead of an invisibly wrong full count, and
            # a consumer that reads the flag gets the truth.
            validation["completeness_unavailable_reason"] = (
                f"table {name!r} declares no required or completeness columns "
                "and no row declares its own completeness, so row completeness "
                "cannot be falsified; complete_rows and partial_rows are "
                "unavailable rather than vacuously satisfied"
            )
        return validation

    @classmethod
    def _diagnostic_table_gaps(cls, name: str, rows: List[Any]) -> List[str]:
        if name != "measurement_gap_table":
            return []

        gaps: List[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            subject = (
                row.get("subject")
                or row.get("target")
                or row.get("entity")
                or row.get("name")
                or "unknown subject"
            )
            missing = row.get("missing_measurement") or "measurement"
            evidence_gap = row.get("evidence_gap") or "missing cross-view evidence"
            gaps.append(f"{missing} missing for {subject}: {evidence_gap}")
        return gaps

    @staticmethod
    def _is_missing(value: Any) -> bool:
        """Whether a cell means "nothing here", with ONE owner for the tokens.

        This module kept a fifth eight-token set until phase 4E-c, in the module
        that writes the tables; `criteria` owns the vocabulary now and this
        gains ten tokens. THE DIRECTION IS REGISTERED: this predicate drives
        `missing_by_column` and `complete_rows` in `_validate_table`, the
        group-metadata backfill and seed-row column matching, so more tokens
        reading as missing means more cells counted missing, fewer rows counted
        complete, and more table-gap searches -- in the very run that measures
        the composition.

        The EMPTY-COLLECTION clause stays local and deliberately does not move
        to `criteria`. It is a SHAPE rule, not a token rule, and folding it into
        the owner would ride a second, unregistered semantic change into
        `_subject_key_values` and `_project_field` on the same version bump --
        one bump carrying two changes, one of them undisclosed.
        """

        if isinstance(value, (list, tuple, set, dict)) and not value:
            return True
        return is_missing_value(value)

    def _table_gaps(self, exports: List[Dict[str, Any]]) -> List[str]:
        if self.config.answer_mode != "table":
            return []

        by_variable = {export.get("variable"): export for export in exports}
        gaps: List[str] = []
        for table_name in (self.config.table_variables or list(by_variable)):
            export = by_variable.get(table_name)
            if export is None:
                gaps.append(f"{table_name} was not materialized.")
                continue

            validation = export.get("validation") or {}
            if not validation.get("rows"):
                gaps.append(f"{table_name} was materialized with zero rows.")

            gaps.extend(export.get("gaps") or [])

            if validation and not validation.get("completeness_measurable", True):
                # Without this the vacuous case emits no gaps at all, which is
                # indistinguishable from a table with nothing missing.
                gaps.append(
                    f"{table_name} completeness is unmeasurable: "
                    f"{validation.get('completeness_unavailable_reason') or 'no checkable columns'}"
                )

            missing = validation.get("missing_by_column") or {}
            rows = validation.get("dict_rows") or validation.get("rows") or 0
            # Every missing column, not the worst five. The list is sorted by
            # missing count, so a `[:5]` decided which columns the next round
            # was allowed to search by their rank on the very quantity a search
            # would change -- a column below the cut is never searched, stays
            # missing, and is below the cut again next round.
            for column, count in sorted(missing.items(), key=lambda item: -item[1]):
                gaps.append(f"{table_name} is missing {column} in {count}/{rows} rows.")

        return gaps

    def _enqueue_table_gap_searches(
        self,
        round_idx: int,
        exports: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if self.config.answer_mode != "table":
            return []
        if self.config.table_gap_search_tasks <= 0:
            return []

        gap_rows: List[Dict[str, Any]] = []
        for export in exports:
            variable = str(export.get("variable") or "")
            if "gap" in variable:
                gap_rows.extend(self._read_export_rows(exports, variable))
        if not gap_rows:
            return []

        tasks = table_gap_search_tasks(
            gap_rows,
            round_index=round_idx,
            max_tasks=self.config.table_gap_search_tasks,
        )
        gap_candidates: List[ActionCandidate] = []
        if self.control_ledger_enabled:
            for task in tasks:
                candidate = SearchCandidate.create(
                    surface=ControlSurface.CATALOG_SEARCH,
                    query=task.query,
                    round_index=round_idx,
                    origin=ActionOrigin.DERIVED,
                )
                gap_candidates.append(candidate)
                self._stamp_control_action(task, candidate)
        self._stamp_control_decision(
            tasks,
            self._record_policy_decision(
                ControlSurface.CATALOG_SEARCH,
                round_idx,
                gap_candidates,
                max_actions=self.config.table_gap_search_tasks,
            ),
        )
        accepted = self.search_frontier.enqueue(tasks)
        if accepted:
            print(
                f"  Queued {len(accepted)} table-gap searches "
                f"for round {round_idx}"
            )
        return [task.to_dict() for task in accepted]

    def _record_goal_discovery_sources(self, papers: List[Dict[str, Any]]) -> None:
        for paper in papers:
            if paper.get("search_topic") != "goal_catalog":
                continue
            source_id = str(paper.get("id") or "")
            if not source_id or source_id in self._seen_goal_discovery_source_ids:
                continue
            self._seen_goal_discovery_source_ids.add(source_id)
            self.goal_discovery_sources.append(
                {
                    "id": source_id,
                    "title": paper.get("title", ""),
                    "url": paper.get("url", ""),
                    "source_query": paper.get("source_query", ""),
                    "text": str(paper.get("text") or "")[
                        : self.config.goal_discovery_text_chars
                    ],
                }
            )

    def _export_seed_sources(self, records: List[Dict[str, Any]]) -> None:
        if not records:
            return

        jsonl_records: List[Dict[str, Any]] = []
        for record in records:
            source_id = str(record.get("id") or "").strip()
            text = str(record.get("text") or "")
            if not source_id or not text:
                continue

            sidecar = {
                key: value
                for key, value in record.items()
                if key != "text"
            }
            jsonl_records.append(sidecar)
            json_path = self.papers_dir / f"{source_id}.json"
            text_path = self.papers_dir / f"{source_id}.txt"
            if not json_path.exists():
                json_path.write_text(
                    json.dumps(sidecar, indent=2, default=str),
                    encoding="utf-8",
                )
            if not text_path.exists():
                text_path.write_text(text, encoding="utf-8")

        if jsonl_records:
            seed_index = self.papers_dir / "seed_sources.jsonl"
            seed_index.write_text(
                "".join(
                    json.dumps(record, default=str) + "\n"
                    for record in jsonl_records
                ),
                encoding="utf-8",
            )

    def _export_seed_search_outcomes(self, records: List[Dict[str, Any]]) -> None:
        if not records:
            return

        path = self.papers_dir / "seed_search_outcomes.jsonl"
        path.write_text(
            "".join(json.dumps(record, default=str) + "\n" for record in records),
            encoding="utf-8",
        )

    @staticmethod
    def _seed_search_tasks(records: List[Dict[str, Any]]) -> List[SearchTask]:
        tasks: List[SearchTask] = []
        seen: set[str] = set()
        for record in records:
            task = QuestionPipeline._seed_search_task(record)
            if task is None or task.id in seen:
                continue
            seen.add(task.id)
            tasks.append(task)
        return tasks

    @staticmethod
    def _seed_search_task(record: Dict[str, Any]) -> Optional[SearchTask]:
        payload = record.get("search_task")
        if isinstance(payload, dict):
            query = str(payload.get("query") or "").strip()
            if query:
                return SearchTask(
                    query=query,
                    id=str(payload.get("id") or ""),
                    parent_id=payload.get("parent_id"),
                    topic=str(payload.get("topic") or "batch"),
                    expansion_op=str(payload.get("expansion_op") or "direct"),
                    gap=str(payload.get("gap") or ""),
                    round_index=int(payload.get("round_index") or 0),
                    depth=int(payload.get("depth") or 0),
                    producer_class="seed_source",
                    metadata=(
                        dict(payload.get("metadata"))
                        if isinstance(payload.get("metadata"), dict)
                        else {}
                    ),
                )

        query = str(record.get("source_query") or "").strip()
        if not query:
            return None
        return SearchTask(
            query=query,
            id=str(record.get("search_task_id") or ""),
            topic=str(record.get("search_topic") or "batch"),
            expansion_op=str(record.get("search_expansion_op") or "direct"),
            gap=str(record.get("search_gap") or ""),
            round_index=int(record.get("search_round_index") or 0),
            producer_class="seed_source",
            metadata=(
                dict(record.get("search_metadata"))
                if isinstance(record.get("search_metadata"), dict)
                else {}
            ),
        )

    @staticmethod
    def _seed_search_outcomes(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        outcomes: Dict[str, Dict[str, Any]] = {}
        for record in records:
            task = QuestionPipeline._seed_search_task(record)
            if task is None:
                continue
            outcome = outcomes.setdefault(
                task.id,
                {
                    "task_id": task.id,
                    "query": task.query,
                    "topic": task.topic,
                    "expansion_op": task.expansion_op,
                    "gap": task.gap,
                    "round_index": task.round_index,
                    "firecrawl_hits": 0,
                    "accepted_source_ids": [],
                    "accepted_urls": [],
                    "duplicate_urls": [],
                    "skipped_by_reason": {},
                    "scrape_failed_urls": [],
                    "text_reductions": [],
                    "metadata": dict(task.metadata),
                    "error": "",
                },
            )
            outcome["firecrawl_hits"] += 1
            source_id = str(record.get("id") or "").strip()
            if source_id:
                outcome["accepted_source_ids"].append(source_id)
            url = str(record.get("url") or "").strip()
            if url:
                outcome["accepted_urls"].append(url)
        return list(outcomes.values())

    @staticmethod
    def _search_outcome_tasks(records: List[Dict[str, Any]]) -> List[SearchTask]:
        tasks: List[SearchTask] = []
        for record in records:
            query = str(record.get("query") or "").strip()
            if not query:
                continue
            if str(record.get("topic") or "") == PROBE_SEARCH_TOPIC:
                # A completion probe never went through the frontier, so a
                # resumed run must not mark it seen there.  1B made probe
                # searches emit outcomes; this keeps that additive by holding
                # the seeded frontier to exactly the tasks it held before.
                continue
            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            tasks.append(
                SearchTask(
                    query=query,
                    id=str(record.get("task_id") or ""),
                    topic=str(record.get("topic") or "batch"),
                    expansion_op=str(record.get("expansion_op") or "direct"),
                    gap=str(record.get("gap") or ""),
                    round_index=int(record.get("round_index") or 0),
                    producer_class="seed_outcome",
                    metadata=metadata,
                )
            )
        return tasks

    @staticmethod
    def _seed_search_outcome_records(
        source_records: List[Dict[str, Any]],
        outcome_records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        task_ids_with_outcomes = {
            str(record.get("task_id") or "")
            for record in outcome_records
            if isinstance(record, dict)
        }
        synthetic_outcomes = [
            outcome
            for outcome in QuestionPipeline._seed_search_outcomes(source_records)
            if outcome.get("task_id") not in task_ids_with_outcomes
        ]
        return [
            QuestionPipeline._with_seed_cost_fields(outcome)
            for outcome in (*outcome_records, *synthetic_outcomes)
        ]

    @staticmethod
    def _with_seed_cost_fields(outcome: Dict[str, Any]) -> Dict[str, Any]:
        """Give a seeded outcome the cost block every outcome carries.

        Two ways a row reaches `search_outcomes` without one: read verbatim from
        a run that predates cost accounting, or synthesized from a seed source
        record by `_seed_search_outcomes`, which builds its dict literally.
        Either way the row would arrive with the field **absent**, and a
        consumer cannot tell an unrecorded action from a free one — which is the
        distinction the typed zero exists to preserve.

        The zero here is honest rather than convenient: an earlier run's spend is
        genuinely not known to this run, and `provider_credits_available` stays
        False. What the field asserts is the shape, not that the search was free.
        """
        if isinstance(outcome.get("cost"), dict) and outcome["cost"]:
            return outcome
        return {
            **outcome,
            "cost": zero_cost(
                observation_kind=ObservationKind.SEARCH.value,
                observation_id=str(outcome.get("task_id") or ""),
                round_index=_safe_int(outcome.get("round_index"), 0),
            ),
        }

    async def _estimate_task_goal_universe(
        self,
        artifact_label: int | str,
        table_rows: Dict[str, List[Dict[str, Any]]],
        gaps: List[str],
    ) -> Dict[str, Any]:
        if self.goal_tracker is None:
            return self.goal_universe_estimate

        goal_context = self.goal_tracker.prompt_context(
            table_rows,
            gaps,
            self.goal_universe_estimate,
            self.completion_state,
        )
        # The round the probes actually run in, so their outcome rows carry it.
        # `_probe_search` builds its own `SearchTask` and had no way to know the
        # round, so every probe row defaulted to `round_index=0` regardless of
        # when it ran: on the recorded run all 32 completion probes read as
        # round 0 against 7 records that genuinely were. Any per-round yield
        # curve built over `search_outcomes` therefore front-loads 32 records
        # into round 0 and collapses afterwards -- which is precisely the
        # "yield dies after round 0" shape such a curve would be used to test.
        probe_round = self._pipeline_round(artifact_label)
        previous_probe_round = getattr(self, "_probe_round_index", None)
        self._probe_round_index = probe_round
        try:
            result = await estimate_count_expectations(
                self.llm,
                self.config.question,
                goal_context=goal_context,
                completion_state=scope_probe_context(self.completion_state),
                # The COMPACTED projection, not the raw stored dict.
                # `self.goal_universe_estimate` is loaded from disk and handed
                # straight into the planner prompt, bypassing the typed-field
                # allowlist that `compact_estimate_for_prompt` applies -- so on
                # a seeded or resumed run the stored `scope_summary` ("Counts
                # are Chao1 richness estimates over the observed sample...")
                # reached a live prompt describing deleted machinery. Fixing it
                # only inside the projection closed one door of two; this is
                # the other. The allowlist is the mechanism either way, so no
                # artifact is rewritten and nothing is matched by name.
                previous_estimate=compact_estimate_for_prompt(
                    self.goal_universe_estimate,
                    table_rows=table_rows,
                ),
                search_fn=self._probe_search,
                max_iterations=self.config.completion_probe_waves,
                queries_per_iteration=self.config.completion_probe_tasks,
                results_per_query=self.config.completion_probe_results,
            )
        finally:
            self._probe_round_index = previous_probe_round

        # `search_space_probes` are built inside the estimator, which has no
        # round either, so `pipeline_round` came back None on every probe. It is
        # stamped here rather than there because this is the layer that knows
        # the round; the estimator stays round-agnostic.
        probes = []
        for probe in result.get("search_space_probes") or []:
            if isinstance(probe, Mapping):
                probes.append({**probe, "pipeline_round": probe_round})
            else:
                probes.append(probe)
        result["search_space_probes"] = probes

        estimate = result.get("estimate") or {}
        self.goal_universe_estimate = merge_universe_estimates(
            self.goal_universe_estimate,
            estimate,
            table_rows=table_rows,
        )
        self.completion_state = merge_completion_state(
            self.completion_state,
            {
                **completion_update_from_estimate(self.goal_universe_estimate),
                "search_space_probes": result.get("search_space_probes") or [],
            },
        )
        critique = result.get("critique") or {}
        if critique:
            self.completion_state = merge_completion_state(
                self.completion_state,
                completion_update_from_critique(critique),
            )
        self._persist_completion_state(artifact_label)
        self.goals_dir.mkdir(parents=True, exist_ok=True)
        artifact_stem = self._artifact_stem(artifact_label)
        path = self.goals_dir / f"{artifact_stem}_universe_estimate.json"
        path.write_text(
            json.dumps(self.goal_universe_estimate, indent=2, default=str),
            encoding="utf-8",
        )
        critique_path = self.goals_dir / f"{artifact_stem}_completion_critique.json"
        critique_path.write_text(
            json.dumps(critique, indent=2, default=str),
            encoding="utf-8",
        )
        (self.goals_dir / f"{artifact_stem}_expectation_attempts.json").write_text(
            json.dumps(result.get("attempts") or [], indent=2, default=str),
            encoding="utf-8",
        )
        (self.goals_dir / f"{artifact_stem}_expectation_summary.json").write_text(
            json.dumps(
                {
                    # `rarefaction`, `current_row_rarefaction` and
                    # `evidence_summary` are gone with the Chao1 estimator that
                    # produced them. What survives is the breadth probes
                    # themselves, which are observations rather than an
                    # extrapolation from observations.
                    "search_space_probes": result.get("search_space_probes") or [],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        self._print_universe_expectation(
            artifact_label,
            self.goal_universe_estimate,
            critique,
        )
        return self.goal_universe_estimate

    async def _enqueue_target_deficit_searches(
        self,
        round_idx: int,
        table_rows: Dict[str, List[Dict[str, Any]]],
        goal_state: FillGoalState,
    ) -> List[Dict[str, Any]]:
        if self.goal_tracker is None:
            return []
        if self.config.task_goal_search_tasks <= 0:
            return []
        if self.search_provider_error:
            print(
                "  Target search paused after provider error: "
                f"{self.search_provider_error}"
            )
            return []
        if not self._paper_budget_available():
            return []

        deficits = self._deficits_with_strategy_history(
            goal_state.target_catalog.get("fill_deficits")
            or goal_state.target_catalog.get("unmet_count_targets")
            or []
        )
        deficits = [
            deficit
            for deficit in deficits
            if not (
                isinstance(deficit.get("operator_plan"), dict)
                and deficit["operator_plan"].get("exhausted")
            )
        ]
        if not deficits:
            return []

        return await self._enqueue_target_deficit_tasks(
            round_idx,
            table_rows,
            deficits,
        )

    async def _enqueue_target_deficit_tasks(
        self,
        round_idx: int,
        table_rows: Dict[str, List[Dict[str, Any]]],
        deficits: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not deficits:
            return []

        attempt_contexts = self._target_attempt_contexts(round_idx, deficits)
        planned, window_report = await strategy.target_deficit_queries(
            self.llm,
            self.config.question,
            goal_context=self.goal_tracker.prompt_context(
                table_rows,
                [],
                self.goal_universe_estimate,
                self.completion_state,
            ),
            deficits=deficits,
            n=self.config.task_goal_search_tasks,
            arms_per_target=self.config.target_prompt_arms_per_evolution,
            queries_per_arm=self.config.target_queries_per_prompt_arm,
            # THE PROPOSED STRATEGY'S SEEDS REACH THE PROMPT WHOSE OUTPUT IS
            # THE ARMS. The proposer yields the strategy only; its
            # `query_seeds` are recorded as a hint and handed here as declared
            # prompt context, because the run source hashes them into the
            # strategy's content key -- and a key computed over content the run
            # never used would make the untried test discriminate on nothing,
            # instantiate byte-identical arms from two different proposals, and
            # leave the proposer's novelty fictional.
            #
            # THIS IS THE ROUND'S SHARED PLANNER CALL, not a strategy-scoped
            # one: `target_deficit_queries` runs once over every open deficit,
            # so a proposal's seeds are shared context for every arm of that
            # call, including arms of families the proposal did not name. That
            # does not corrupt a contrast -- the seeds are shared within the
            # call either way, so they cannot differentially bias one sibling
            # against another -- but a reader is entitled to know which call
            # carried them, so it is stated here.
            seed_queries=self._current_strategy_seed_queries(),
        )
        self._persist_deficit_windows(round_idx, window_report)
        targets_by_name = {}
        for target in deficits:
            if not isinstance(target, dict):
                continue
            target_name = str(
                target.get("target_name") or target.get("name") or ""
            ).strip()
            if target_name:
                targets_by_name[target_name.lower()] = target
        targets_by_id = {
            str(target.get("id") or ""): target
            for target in deficits
            if isinstance(target, dict)
        }
        tasks = []
        planned_candidates: List[ActionCandidate] = []
        for item in planned:
            target = targets_by_id.get(str(item.get("target_id") or ""))
            if target is None:
                target = targets_by_name.get(
                    str(item.get("target_name") or "").lower(),
                )
            if target is None and len(deficits) == 1:
                target = deficits[0]
            if not isinstance(target, dict):
                continue
            context = attempt_contexts.get(str(target.get("id") or ""))
            if context is None:
                continue
            prompt_arm = self._prompt_arm_metadata(item, context)
            operator_plan = target.get("operator_plan") or {}
            query_index = _safe_int(item.get("query_index"), 0)
            rationale = item.get("rationale", "")
            task = self._target_deficit_search_task(
                query=item["query"],
                target=target,
                round_idx=round_idx,
                rationale=rationale,
                operator_plan=operator_plan,
                strategy_origin="llm",
                attempt_context=context,
                prompt_arm=prompt_arm,
                query_index=query_index,
            )
            task.metadata["table_spec_id"] = self.table_spec_id
            self._record_strategy_baseline(task)
            if self.control_ledger_enabled:
                candidate = self._target_search_candidate(
                    query=item["query"],
                    target=target,
                    round_idx=round_idx,
                    operator_plan=operator_plan,
                    attempt_context=context,
                    prompt_arm=prompt_arm,
                    query_index=query_index,
                    rationale=rationale,
                    origin=ActionOrigin.LLM,
                )
                planned_candidates.append(candidate)
                self._stamp_control_action(task, candidate)
            tasks.append(task)

        self._stamp_control_decision(
            tasks,
            self._record_policy_decision(
                ControlSurface.TARGET_SEARCH,
                round_idx,
                planned_candidates,
                max_actions=self.config.task_goal_search_tasks,
            ),
        )
        accepted = self.search_frontier.enqueue(tasks)
        covered_target_ids = {
            str(task.metadata.get("fill_deficit_id") or "")
            for task in accepted
        }
        fallback_tasks = []
        fallback_candidates: List[ActionCandidate] = []
        for target in deficits:
            deficit_id = str(target.get("id") or "")
            if deficit_id in covered_target_ids:
                continue
            fallback_query = self._fallback_target_deficit_query(target)
            if not fallback_query:
                continue
            context = attempt_contexts.get(deficit_id)
            if context is None:
                continue
            fallback_rationale = (
                "Fallback strategy for a target omitted by the planner."
            )
            fallback_arm = self._fallback_prompt_arm_metadata(context)
            fallback_operator_plan = target.get("operator_plan") or {}
            task = self._target_deficit_search_task(
                query=fallback_query,
                target=target,
                round_idx=round_idx,
                rationale=fallback_rationale,
                operator_plan=fallback_operator_plan,
                strategy_origin="fallback",
                attempt_context=context,
                prompt_arm=fallback_arm,
                query_index=0,
            )
            task.metadata["table_spec_id"] = self.table_spec_id
            self._record_strategy_baseline(task)
            if self.control_ledger_enabled:
                candidate = self._target_search_candidate(
                    query=fallback_query,
                    target=target,
                    round_idx=round_idx,
                    operator_plan=fallback_operator_plan,
                    attempt_context=context,
                    prompt_arm=fallback_arm,
                    query_index=0,
                    rationale=fallback_rationale,
                    origin=ActionOrigin.FALLBACK,
                )
                fallback_candidates.append(candidate)
                self._stamp_control_action(task, candidate)
            fallback_tasks.append(task)
        if fallback_tasks:
            self._stamp_control_decision(
                fallback_tasks,
                self._record_policy_decision(
                    ControlSurface.TARGET_SEARCH,
                    round_idx,
                    fallback_candidates,
                    max_actions=len(fallback_candidates),
                ),
            )
            accepted.extend(self.search_frontier.enqueue(fallback_tasks))
        if accepted:
            print(
                f"  Queued {len(accepted)} target-deficit searches "
                f"for round {round_idx}"
            )
        return [task.to_dict() for task in accepted]

    def _target_attempt_contexts(
        self,
        round_idx: int,
        deficits: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        contexts: Dict[str, Dict[str, Any]] = {}
        for target in deficits:
            deficit_id = str(target.get("id") or "")
            if not deficit_id:
                continue
            evolution_index = self._next_target_evolution_index(target)
            strategy_attempt_id = self._strategy_attempt_id(
                round_idx,
                target,
                evolution_index,
            )
            contexts[deficit_id] = {
                "strategy_attempt_id": strategy_attempt_id,
                "evolution_index": evolution_index,
            }
        return contexts

    @staticmethod
    def _strategy_attempt_id(
        round_idx: int,
        target: Mapping[str, Any],
        evolution_index: int,
    ) -> str:
        payload = {
            "round": round_idx,
            "target": target.get("id") or target.get("target_id") or target.get("name"),
            "target_table": target.get("target_table"),
            "evolution_index": evolution_index,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _prompt_arm_metadata(
        item: Mapping[str, Any],
        attempt_context: Mapping[str, Any],
    ) -> Dict[str, Any]:
        arm_index = _safe_int(item.get("prompt_arm_index"), 0)
        name = str(item.get("prompt_arm_name") or f"arm_{arm_index}").strip()
        payload = {
            "strategy_attempt_id": attempt_context.get("strategy_attempt_id"),
            "prompt_arm_index": arm_index,
            "prompt_arm_name": name,
            "prompt_delta": item.get("prompt_delta") or "",
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return {
            "prompt_arm_id": hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16],
            "prompt_arm_name": name,
            "prompt_arm_index": arm_index,
            "prompt_delta": str(item.get("prompt_delta") or "").strip(),
            "prompt_hypothesis": str(
                item.get("prompt_hypothesis") or item.get("rationale") or ""
            ).strip(),
            "expected_source_shape": str(
                item.get("expected_source_shape") or ""
            ).strip(),
        }

    @staticmethod
    def _fallback_prompt_arm_metadata(
        attempt_context: Mapping[str, Any],
    ) -> Dict[str, Any]:
        payload = {
            "strategy_attempt_id": attempt_context.get("strategy_attempt_id"),
            "prompt_arm_index": 0,
            "prompt_arm_name": "fallback",
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return {
            "prompt_arm_id": hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16],
            "prompt_arm_name": "fallback",
            "prompt_arm_index": 0,
            "prompt_delta": "deterministic fallback",
            "prompt_hypothesis": "Planner omitted this target; use the selected operator fallback.",
            "expected_source_shape": "selected operator default",
        }

    @staticmethod
    def _next_target_evolution_index(target: Mapping[str, Any]) -> int:
        evolution_indices = []
        for attempt in target.get("strategy_history") or []:
            if not isinstance(attempt, Mapping):
                continue
            try:
                evolution_indices.append(int(attempt.get("evolution_index") or 0))
            except (TypeError, ValueError):
                continue
        return max(evolution_indices, default=-1) + 1

    @staticmethod
    def _target_deficit_search_task(
        *,
        query: str,
        target: Dict[str, Any],
        round_idx: int,
        rationale: str,
        operator_plan: Dict[str, Any],
        strategy_origin: str,
        attempt_context: Mapping[str, Any],
        prompt_arm: Mapping[str, Any],
        query_index: int,
    ) -> SearchTask:
        deficit_id = str(target.get("id") or "")
        target_id = str(target.get("target_id") or deficit_id)
        operator_metadata = _operator_metadata(operator_plan)
        return SearchTask(
            query=query,
            topic="target_deficit",
            expansion_op="llm_target_deficit",
            gap=deficit_id,
            round_index=round_idx,
            # THE ONE ARM-BEARING PRODUCER. Every other producer declares an
            # empty `prompt_arm_id`, and the invariant is stated over this
            # population alone.
            producer_class="target_deficit_planner",
            metadata={
                "fill_deficit_id": deficit_id,
                "fill_deficit_type": target.get("deficit_type", ""),
                "target_id": target_id,
                "target_name": target.get("target_name") or target.get("name", ""),
                "target_table": target.get("target_table", ""),
                "key_columns": target.get("key_columns", []),
                "missing_fields": target.get("missing_fields", []),
                "anchor_values": target.get("anchor_values", {}),
                "evidence_gap": target.get("evidence_gap", ""),
                "expected_minimum_count": target.get("expected_minimum_count"),
                "observed_count": target.get("observed_count"),
                "deficit_count": target.get("deficit_count"),
                "known_missing_examples": target.get(
                    "known_missing_examples",
                    [],
                ),
                "rationale": rationale,
                **operator_metadata,
                "strategy_origin": strategy_origin,
                "strategy_attempt_id": attempt_context.get(
                    "strategy_attempt_id",
                    "",
                ),
                "evolution_index": attempt_context.get("evolution_index"),
                "prompt_arm_id": prompt_arm.get("prompt_arm_id", ""),
                "prompt_arm_name": prompt_arm.get("prompt_arm_name", ""),
                "prompt_arm_index": prompt_arm.get("prompt_arm_index", 0),
                "prompt_delta": prompt_arm.get("prompt_delta", ""),
                "prompt_hypothesis": prompt_arm.get("prompt_hypothesis", ""),
                "expected_source_shape": prompt_arm.get(
                    "expected_source_shape",
                    "",
                ),
                "query_index": query_index,
            },
        )

    def _record_strategy_baseline(self, task: SearchTask) -> None:
        task.metadata["baseline_graph_nodes"] = self.graph.number_of_nodes()
        task.metadata["baseline_graph_edges"] = self.graph.number_of_edges()

    @staticmethod
    def _fallback_target_deficit_query(target: Dict[str, Any]) -> str:
        return fallback_query_for_operator(target)

    async def _enqueue_followup_target_evolutions(
        self,
        outcomes: Sequence[SearchOutcome],
        round_idx: int,
        target_evolution_counts: Mapping[str, int],
    ) -> List[Dict[str, Any]]:
        """Plan a follow-up evolution for each attempt that accepted nothing.

        THE SAME TRIGGER, NOW AT THE SAME GRAIN AS THE FACT. It used to run
        inside the deleted wave loop over a merged batch; it now takes the
        outcomes the `on_search` hook wrote for the strategy that just closed.
        `target_evolution_counts` is a run-scoped cap on how many evolutions one
        deficit may spawn, and it is what bounds the family re-open cycle
        together with the page budget every pulled page charges.
        """

        if self.goal_tracker is None:
            return []
        if self.config.task_goal_search_tasks <= 0:
            return []
        if self.search_provider_error or not self._paper_budget_available():
            return []

        failed_attempts: Dict[str, List[Any]] = {}
        for outcome in outcomes:
            if outcome.topic != "target_deficit":
                continue
            metadata = outcome.metadata if isinstance(outcome.metadata, dict) else {}
            strategy_attempt_id = str(
                metadata.get("strategy_attempt_id") or outcome.task_id
            )
            failed_attempts.setdefault(strategy_attempt_id, []).append(outcome)

        targets: Dict[str, Dict[str, Any]] = {}
        for outcomes in failed_attempts.values():
            if any(outcome.accepted_source_ids for outcome in outcomes):
                continue
            metadata = (
                outcomes[0].metadata
                if isinstance(outcomes[0].metadata, dict)
                else {}
            )
            target = self._target_deficit_from_metadata(metadata)
            deficit_id = str(target.get("id") or "")
            if (
                deficit_id
                and int(target_evolution_counts.get(deficit_id) or 0)
                < self.config.target_deficit_evolutions_per_round
            ):
                targets.setdefault(deficit_id, target)

        deficits = [
            target
            for target in self._deficits_with_strategy_history(list(targets.values()))
            if not (
                isinstance(target.get("operator_plan"), dict)
                and target["operator_plan"].get("exhausted")
            )
        ]
        accepted = await self._enqueue_target_deficit_tasks(round_idx, {}, deficits)
        if accepted:
            print(
                f"  Queued {len(accepted)} follow-up target-deficit "
                "searches from prompt-arm outcomes"
            )
        return accepted

    def _record_prompt_attempt_counts(
        self,
        outcomes: Sequence[SearchOutcome],
    ) -> None:
        """Count one attempt per (target, strategy attempt), run-scoped."""

        seen_attempts = self._seen_target_attempts
        target_counts = self._target_evolution_counts
        for outcome in outcomes:
            metadata = outcome.metadata if isinstance(outcome.metadata, dict) else {}
            attempt_id = str(metadata.get("strategy_attempt_id") or "")
            if not attempt_id:
                continue

            target_id = str(
                metadata.get("fill_deficit_id")
                or metadata.get("target_id")
                or ""
            )
            if not target_id:
                continue

            key = (target_id, attempt_id)
            if key in seen_attempts:
                continue
            seen_attempts.add(key)
            target_counts[target_id] += 1

    @staticmethod
    def _target_deficit_from_metadata(metadata: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(
                metadata.get("fill_deficit_id")
                or metadata.get("target_id")
                or ""
            ),
            "deficit_type": metadata.get("fill_deficit_type", ""),
            "target_id": metadata.get("target_id", ""),
            "target_name": metadata.get("target_name", ""),
            "name": metadata.get("target_name", ""),
            "target_table": metadata.get("target_table", ""),
            "key_columns": metadata.get("key_columns", []),
            "missing_fields": metadata.get("missing_fields", []),
            "anchor_values": metadata.get("anchor_values", {}),
            "evidence_gap": metadata.get("evidence_gap", ""),
            "expected_minimum_count": metadata.get("expected_minimum_count"),
            "observed_count": metadata.get("observed_count"),
            "deficit_count": metadata.get("deficit_count"),
            "known_missing_examples": metadata.get("known_missing_examples", []),
        }

    def _deficits_with_strategy_history(
        self,
        deficits: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        enriched: List[Dict[str, Any]] = []
        for target in deficits:
            if not isinstance(target, dict):
                continue
            deficit_id = str(target.get("id") or "")
            if not deficit_id:
                continue
            memory_records = self.search_memory.to_deficit_context(target)
            attempts = [
                attempt
                for record in memory_records
                for attempt in record.get("attempts", [])
                if isinstance(attempt, dict)
            ]
            attempts = sorted(
                attempts,
                key=lambda attempt: (
                    int(attempt.get("round") or -1)
                    if str(attempt.get("round") or "").isdigit()
                    else -1,
                    int(attempt.get("evolution_index") or -1)
                    if str(attempt.get("evolution_index") or "").isdigit()
                    else -1,
                    int(attempt.get("prompt_arm_index") or -1)
                    if str(attempt.get("prompt_arm_index") or "").isdigit()
                    else -1,
                    str(attempt.get("strategy_attempt_id") or ""),
                ),
            )
            enriched_target = {
                **target,
                # Every attempt, not the most recent eight. The planner prompt
                # instructs "do not repeat a previous query for the same
                # deficit", and that instruction is only enforceable over the
                # attempts the planner can see -- with a tail of 8 it could
                # freely reissue the ninth-oldest query, which is precisely the
                # stalled-search behaviour `strategy_history` exists to prevent.
                #
                # Growth is absorbed correctly rather than ignored: deficits are
                # the windowed axis in `strategy.target_deficit_queries`, so a
                # longer history produces more windows, never a shortened
                # catalog. LATENT on every recorded run -- the largest observed
                # history is 2 attempts against a limit of 8, so this clip has
                # never bound and no recorded result is affected by it.
                "strategy_history": attempts,
                "strategy_memory": memory_records,
            }
            enriched_target["operator_plan"] = self._route_operator_plan(
                enriched_target
            )
            enriched.append(enriched_target)
        return enriched

    def _route_operator_plan(self, enriched_target: Dict[str, Any]) -> Dict[str, Any]:
        """The next evolution's mutation family for one target deficit.

        Phase 3B: routes from nested arm contrast under
        `self.config.arm_routing_mode` (default ``"contrast"``, deterministic
        -- see `strategy_state.route_next_family`). ``"off"``/``"random"``
        exist only for 3B's own A/B/C ablation and are never the default a
        production run picks.
        """
        mode = str(self.config.arm_routing_mode or "contrast")
        try:
            routing_mode = ArmRoutingMode(mode)
        except ValueError:
            routing_mode = ArmRoutingMode.CONTRAST
        return route_next_family(
            enriched_target,
            mode=routing_mode,
            rng=self._arm_routing_rng if routing_mode is ArmRoutingMode.RANDOM else None,
        )

    @staticmethod
    def _search_outcome_matches_target(
        outcome: Dict[str, Any],
        *,
        fill_deficit_id: str,
        target_id: str,
        target_name: str,
        target_table: str,
        key_columns: List[str],
    ) -> bool:
        if outcome.get("topic") != "target_deficit":
            return False

        metadata = outcome.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        if metadata.get("fill_deficit_id") == fill_deficit_id:
            return True
        if metadata.get("target_id") == target_id:
            return True

        outcome_name = str(metadata.get("target_name") or "").lower()
        if target_name and outcome_name == target_name:
            return True

        outcome_table = str(metadata.get("target_table") or "")
        if not target_table or outcome_table != target_table:
            return False

        current_keys = {
            str(column).strip()
            for column in key_columns
            if str(column).strip()
        }
        previous_keys = {
            str(column).strip()
            for column in metadata.get("key_columns") or []
            if str(column).strip()
        }
        return bool(current_keys & previous_keys)

    def _reward_datapoints_for_round(
        self,
        artifact_label: int | str,
    ) -> Optional[List[Dict[str, Any]]]:
        """This round's `CreditedDatapoint`s, or `None` if not yet scored.

        `None` -- not `[]` -- means "3A has not scored this round", so a
        consumer can distinguish "no yield" from "yield unknown". Guarded by
        `round_index` rather than assumed fresh: `last_reward_report` is only
        overwritten inside `_write_reward_exports`, which the "no new papers"
        branch and the GASL branch both call before this method runs, but a
        `answer_mode != "table"` run never calls it at all and must not read
        a stale report from a different round as if it were this one's.
        """
        report = self.last_reward_report or {}
        if not report:
            return None
        if int(report.get("round_index") or -1) != int(
            self._pipeline_round(artifact_label)
        ):
            return None
        datapoints = report.get("datapoints")
        return list(datapoints) if isinstance(datapoints, list) else []

    @staticmethod
    def _credited_criterion_ids(
        reward_datapoints: Optional[List[Dict[str, Any]]],
        accepted_source_ids: Sequence[str],
    ) -> Optional[List[str]]:
        """Which criteria this outcome's accepted sources helped credit.

        Joined by ID alone: a datapoint counts for this outcome iff its
        `crediting_source_ids` intersects the sources *this* search task's
        outcome accepted. Two outcomes (two arms) that both accepted the same
        source both see it -- that overlap is exactly what the duplicate
        penalty in `search_memory` is built to catch, not something to
        collapse away here.
        """
        if reward_datapoints is None:
            return None
        accepted = {str(value) for value in accepted_source_ids}
        if not accepted:
            return []
        return sorted(
            {
                str(datapoint.get("criterion_id") or "")
                for datapoint in reward_datapoints
                if accepted & {str(v) for v in datapoint.get("crediting_source_ids") or []}
            }
            - {""}
        )

    @staticmethod
    def _credited_datapoint_kinds(
        reward_datapoints: Optional[List[Dict[str, Any]]],
        accepted_source_ids: Sequence[str],
    ) -> Optional[List[str]]:
        if reward_datapoints is None:
            return None
        accepted = {str(value) for value in accepted_source_ids}
        if not accepted:
            return []
        return [
            str(datapoint.get("datapoint_kind") or "")
            for datapoint in reward_datapoints
            if accepted & {str(v) for v in datapoint.get("crediting_source_ids") or []}
        ]

    def _cost_records_for_task(self, task_id: str) -> List[Dict[str, Any]]:
        """1B's own per-action records for one search task, joined by ID.

        Includes records `nested_in` this task (e.g. a source fetch opened
        under the search action) as well as the task's own -- 1B's scopes do
        not nest their spend, so this is a plain filter, not a sum that could
        double-count.
        """
        key = str(task_id or "")
        if not key:
            return []
        return [
            dict(record)
            for record in self.cost_records
            if str(record.get("observation_id") or "") == key
            or str(record.get("nested_in") or "") == key
        ]

    def _annotate_recent_target_outcomes(
        self,
        artifact_label: int | str,
        goal_state: Optional[FillGoalState],
        *,
        table_rows: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        best_guess_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        if goal_state is None:
            return

        targets = (
            goal_state.target_catalog.get("fill_deficits")
            or goal_state.target_estimate.get("count_targets")
            or []
        )
        if not self.last_search_outcomes:
            return

        table_source_hits = self._source_row_hit_counts(table_rows or {})
        best_guess_source_hits = self._best_guess_source_hit_counts(
            best_guess_state or {},
        )
        reward_datapoints = self._reward_datapoints_for_round(artifact_label)
        metadata_updates: Dict[str, Dict[str, Any]] = {}
        for outcome in self.last_search_outcomes:
            metadata = outcome.metadata
            if outcome.topic != "target_deficit":
                continue
            if not isinstance(metadata, dict):
                continue
            update = {
                "search_yield": self._search_yield_summary(outcome.to_dict()),
                "post_round_table_row_hits": sum(
                    table_source_hits[source_id]
                    for source_id in outcome.accepted_source_ids
                ),
                "post_round_best_guess_hits": sum(
                    best_guess_source_hits[source_id]
                    for source_id in outcome.accepted_source_ids
                ),
                # Phase 3B: real semantic yield, joined by ID from 3A's own
                # `RewardReport.datapoints` -- never re-derived. `None` when
                # this round has not been scored (or is not a `table`-mode
                # run), which `search_memory` reads as "not measured yet",
                # not as zero.
                "post_round_credited_criterion_ids": self._credited_criterion_ids(
                    reward_datapoints,
                    outcome.accepted_source_ids,
                ),
                "post_round_credited_datapoint_kinds": self._credited_datapoint_kinds(
                    reward_datapoints,
                    outcome.accepted_source_ids,
                ),
                # The cost penalty's own join: 1B's per-action records that
                # this search task opened or nested under it.
                "post_round_cost_records": self._cost_records_for_task(
                    outcome.task_id
                ),
            }
            target = self._target_for_outcome_metadata(metadata, targets)
            if target is not None:
                # A delta is only a measurement when BOTH endpoints were
                # measured. `int(x or 0)` on a missing baseline made
                # `observed_count - previous_count` equal to `observed_count`,
                # so a task whose baseline was never recorded reported its
                # entire standing count as the yield it produced this round --
                # crediting a search for rows that predated it. Absent
                # endpoints therefore yield an absent delta, declared as such.
                raw_previous = metadata.get("observed_count")
                raw_observed = target.get("observed_count")
                previous_count = (
                    None if raw_previous is None else int(raw_previous)
                )
                observed_count = (
                    None if raw_observed is None else int(raw_observed)
                )
                observed_delta = (
                    None
                    if previous_count is None or observed_count is None
                    else observed_count - previous_count
                )
                baseline_nodes = int(
                    metadata.get("baseline_graph_nodes")
                    or self.graph.number_of_nodes()
                )
                baseline_edges = int(
                    metadata.get("baseline_graph_edges")
                    or self.graph.number_of_edges()
                )
                update.update(
                    {
                        "post_round_observed_count": observed_count,
                        "post_round_observed_delta": observed_delta,
                        # Which endpoint was missing, so a None delta is
                        # diagnosable rather than merely absent.
                        "post_round_observed_delta_unavailable_reason": (
                            ""
                            if observed_delta is not None
                            else "; ".join(
                                reason
                                for reason, missing in (
                                    ("no recorded baseline observed_count", previous_count is None),
                                    ("target carries no observed_count", observed_count is None),
                                )
                                if missing
                            )
                        ),
                        "post_round_graph_node_delta": (
                            self.graph.number_of_nodes() - baseline_nodes
                        ),
                        "post_round_graph_edge_delta": (
                            self.graph.number_of_edges() - baseline_edges
                        ),
                        "post_round_deficit_count": target.get("deficit_count"),
                        "post_round_target_status": target.get("status"),
                    }
                )
            metadata.update(update)
            metadata_updates[outcome.task_id] = update

        if not metadata_updates:
            return

        for outcome in self.search_outcomes:
            task_id = str(outcome.get("task_id") or "")
            update = metadata_updates.get(task_id)
            if update is None:
                continue
            metadata = outcome.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                outcome["metadata"] = metadata
            metadata.update(update)
        self._rewrite_search_outcomes()
        self._refresh_search_memory()
        self.last_prompt_arm_summaries = summarize_prompt_arms(
            self.last_search_outcomes
        )
        self._write_prompt_arm_yield(artifact_label)

    @staticmethod
    def _source_row_hit_counts(
        table_rows: Mapping[str, List[Dict[str, Any]]],
    ) -> Counter:
        counts: Counter = Counter()
        for rows in table_rows.values():
            for row in rows:
                if isinstance(row, Mapping):
                    counts.update(source_ids_from_row(row))
        return counts

    @staticmethod
    def _best_guess_source_hit_counts(best_guess_state: Mapping[str, Any]) -> Counter:
        counts: Counter = Counter()
        for row in best_guess_state.get("resolutions") or []:
            if isinstance(row, Mapping):
                counts.update(str(value) for value in row.get("source_ids") or [])
        return counts

    def _write_prompt_arm_yield(self, artifact_label: int | str) -> None:
        summaries = [
            summary
            for summary in summarize_prompt_arms(self.last_search_outcomes)
            if summary.get("strategy_attempt_id")
        ]
        if not summaries:
            return
        self.goals_dir.mkdir(parents=True, exist_ok=True)
        path = (
            self.goals_dir
            / f"{self._artifact_stem(artifact_label)}_prompt_arm_yield.json"
        )
        path.write_text(json.dumps(summaries, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def _catalog_progress_snapshot(estimate: Dict[str, Any]) -> Dict[str, Any]:
        count_targets = [
            target
            for target in estimate.get("count_targets") or []
            if isinstance(target, dict)
        ]
        unestimated_targets = [
            target
            for target in estimate.get("unestimated_count_targets") or []
            if isinstance(target, dict)
        ]
        status = str(estimate.get("status") or "missing").strip() or "missing"
        return {
            "status": status,
            "count_target_count": len(count_targets),
            "unestimated_count": len(unestimated_targets),
            "target_family_count": len(count_targets) + len(unestimated_targets),
        }

    @staticmethod
    def _search_yield_summary(outcome: Dict[str, Any]) -> Dict[str, Any]:
        skipped = outcome.get("skipped_by_reason")
        if not isinstance(skipped, dict):
            skipped = {}
        return {
            "firecrawl_hits": int(outcome.get("firecrawl_hits") or 0),
            "accepted_source_count": len(outcome.get("accepted_source_ids") or []),
            "duplicate_url_count": len(outcome.get("duplicate_urls") or []),
            "scrape_failed_count": len(outcome.get("scrape_failed_urls") or []),
            "not_relevant_count": int(skipped.get("not_relevant") or 0),
            "error": str(outcome.get("error") or ""),
        }

    def _outcome_matches_current_table_spec(self, outcome: Dict[str, Any]) -> bool:
        if self.table_spec.is_empty:
            return True
        metadata = outcome.get("metadata")
        if not isinstance(metadata, dict):
            return False
        return metadata.get("table_spec_id") == self.table_spec_id

    @staticmethod
    def _table_spec_id(table_spec: TableSpec) -> str:
        if table_spec.is_empty:
            return ""
        payload = json.dumps(
            table_spec.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _target_for_outcome_metadata(
        metadata: Dict[str, Any],
        targets: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        target_id = str(metadata.get("target_id") or "")
        target_name = str(metadata.get("target_name") or "").lower()
        target_table = str(metadata.get("target_table") or "")
        key_columns = {
            str(column).strip()
            for column in metadata.get("key_columns") or []
            if str(column).strip()
        }
        for target in targets:
            if not isinstance(target, dict):
                continue
            if target_id and str(target.get("id") or "") == target_id:
                return target
            if target_name and str(target.get("name") or "").lower() == target_name:
                return target
            if target_table and str(target.get("target_table") or "") == target_table:
                target_keys = {
                    str(column).strip()
                    for column in target.get("key_columns") or []
                    if str(column).strip()
                }
                if key_columns & target_keys:
                    return target
        return None

    def _rewrite_search_outcomes(self) -> None:
        path = self.papers_dir / "search_outcomes.jsonl"
        path.write_text(
            "".join(
                json.dumps(outcome, default=str) + "\n"
                for outcome in self.search_outcomes
            ),
            encoding="utf-8",
        )

    def _refresh_search_memory(self) -> None:
        self.search_memory = SearchMemory.from_outcomes(self.search_outcomes)
        self._persist_search_memory()

    def _persist_search_memory(self) -> None:
        if not getattr(self, "search_memory", None):
            return
        self.goals_dir.mkdir(parents=True, exist_ok=True)
        path = self.goals_dir / "search_memory.json"
        path.write_text(
            json.dumps(self.search_memory.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def _persist_completion_state(
        self,
        artifact_label: int | str | None = None,
    ) -> None:
        payload = {
            **self.completion_state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.completion_state = payload
        self.goals_dir.mkdir(parents=True, exist_ok=True)
        (self.goals_dir / "completion_state.json").write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        if artifact_label is None:
            return
        path = self.goals_dir / (
            f"{self._artifact_stem(artifact_label)}_completion_state.json"
        )
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def _source_records_by_id(self) -> Dict[str, Dict[str, Any]]:
        records: Dict[str, Dict[str, Any]] = {}
        for path in sorted(self.papers_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue

            source_id = str(record.get("id") or path.stem).strip()
            if not source_id:
                continue
            records[source_id] = record
        return records

    def _source_records_with_text_by_id(self) -> Dict[str, Dict[str, Any]]:
        records = self._source_records_by_id()
        for source_id, record in records.items():
            text_path = self.papers_dir / f"{source_id}.txt"
            try:
                record["text"] = text_path.read_text(encoding="utf-8")
            except OSError:
                record["text"] = ""
        return records

    def _graph_records_by_source_id(
        self,
        source_ids: set[str],
        *,
        per_source_limit: int,
    ) -> Dict[str, List[Dict[str, Any]]]:
        records: Dict[str, List[Dict[str, Any]]] = {
            source_id: []
            for source_id in source_ids
        }
        if not source_ids:
            return records

        for node_id, data in self.graph.nodes(data=True):
            matches = self._matching_source_ids(data, source_ids)
            if not matches:
                continue
            record = {
                "kind": "node",
                "id": str(node_id),
                "degree": self.graph.degree(node_id),
                "data": self._compact_graph_mapping(data),
            }
            for source_id in matches:
                if len(records[source_id]) < per_source_limit:
                    records[source_id].append(record)

        for src, dst, _, data in self._iter_graph_edges():
            matches = self._matching_source_ids(data, source_ids)
            if not matches:
                continue
            record = {
                "kind": "edge",
                "src": str(src),
                "dst": str(dst),
                "data": self._compact_graph_mapping(data),
            }
            for source_id in matches:
                if len(records[source_id]) < per_source_limit:
                    records[source_id].append(record)
        return records

    @staticmethod
    def _matching_source_ids(value: Any, source_ids: set[str]) -> List[str]:
        text = json.dumps(value, default=str) if not isinstance(value, str) else value
        return [source_id for source_id in source_ids if source_id in text]

    @classmethod
    def _compact_graph_mapping(cls, value: Mapping[str, Any]) -> Dict[str, Any]:
        compact: Dict[str, Any] = {}
        for key, inner in value.items():
            if inner is None:
                continue
            if isinstance(inner, (str, int, float, bool)):
                text = str(inner)
                compact[str(key)] = text[:497] + "..." if len(text) > 500 else inner
            elif isinstance(inner, Mapping):
                nested = cls._compact_graph_mapping(inner)
                if nested:
                    compact[str(key)] = nested
            elif isinstance(inner, (list, tuple, set)):
                compact[str(key)] = [
                    str(item)[:500]
                    for item in list(inner)[:8]
                    if item is not None
                ]
        return compact

    def _load_seed_universe_estimate(
        self,
        seed_tables_dir: Optional[str],
    ) -> Dict[str, Any]:
        if not seed_tables_dir:
            return {"status": "missing"}

        roots: List[Path] = []
        for raw in str(seed_tables_dir).split(os.pathsep):
            if not raw.strip():
                continue
            path = Path(raw)
            roots.extend(
                candidate
                for candidate in (
                    path,
                    path.parent,
                    path.parent / "goals",
                    path.parent.parent / "goals",
                )
                if candidate.exists()
            )

        candidates = sorted(
            {
                file_path
                for root in roots
                if root.is_dir()
                for file_path in root.glob("*_universe_estimate.json")
            },
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return normalize_universe_estimate(
                    payload,
                    table_rows=self._goal_seed_rows(),
                )
        return {"status": "missing"}

    def _goal_seed_rows(self) -> Dict[str, List[Dict[str, Any]]]:
        if self.table_spec.is_empty:
            return self.seed_tables.rows_by_name
        return {
            name: self.seed_tables.rows_by_name.get(name, [])
            for name in self.table_spec.deliverable_names()
        }

    def _derived_context_slots(self) -> List[Dict[str, Any]]:
        slots = context_slots_from_count_targets(
            [
                *(self.goal_universe_estimate.get("count_targets") or []),
                *(self.goal_universe_estimate.get("unestimated_count_targets") or []),
            ],
        )
        slots.extend(self.table_spec.context_slots())

        merged: Dict[str, Dict[str, Any]] = {}
        for slot in slots:
            name = str(slot.get("name") or "").strip()
            if not name:
                continue
            current = merged.setdefault(name, {"name": name, "field_hints": []})
            current["field_hints"] = list(
                dict.fromkeys(
                    [
                        *current.get("field_hints", []),
                        *(slot.get("field_hints") or []),
                    ]
                )
            )
        return list(merged.values())

    def _ensure_declared_seed_tables(self) -> None:
        if self.table_spec.is_empty:
            return
        for name in self.table_spec.deliverable_names():
            self.seed_tables.rows_by_name.setdefault(name, [])

    def _validate_seed_tables_declared_by_spec(self) -> None:
        if self.table_spec.is_empty or not self.seed_tables.rows_by_name:
            return

        declared_tables = set(self.table_spec.tables)
        omitted_tables = sorted(
            table_name
            for table_name, rows in self.seed_tables.rows_by_name.items()
            if rows and table_name not in declared_tables
        )
        if not omitted_tables:
            return

        raise ValueError(
            "effective table spec omits seeded table(s): "
            f"{', '.join(omitted_tables)}. "
            "When --seed-tables-dir is used, seed tables with rows must be "
            "declared by either an adjacent observed table spec or an "
            "explicit --table-spec-path file. Declare intentionally retired "
            "seed tables with deliverable: false."
        )

    def _seed_row_match(
        self,
        row: Dict[str, Any],
        table: Any,
        *,
        migration: Any | None = None,
    ) -> Dict[str, Any]:
        required = [
            column
            for column in table.required_columns()
            if column != "row_key"
        ]
        matched_columns: List[str] = []
        for column in table.all_columns():
            if self._row_matches_column(row, column):
                matched_columns.append(column.name)

        context_terms = self._seed_migration_context_terms(table, migration)
        row_value_key = self._seed_match_key(self._row_value_text(row))
        matched_context_terms = [
            term
            for term in context_terms
            if term in row_value_key
        ]
        matched_set = set(matched_columns)
        matched_required = [
            column
            for column in required
            if column in matched_set
        ]
        threshold = min(2, len(required)) if required else 1
        matched_required_threshold = (
            len(matched_required) >= threshold
            if required
            else bool(matched_columns)
        )
        matches = (
            bool(matched_context_terms)
            if migration is not None
            else matched_required_threshold
        )
        return {
            "matches": matches,
            "matched_columns": matched_columns,
            "matched_context_terms": matched_context_terms,
            "matched_required_columns": matched_required,
            "unmatched_required_columns": [
                column
                for column in required
                if column not in matched_set
            ],
        }

    def _row_matches_column(self, row: Dict[str, Any], column: Any) -> bool:
        row_keys = {
            self._seed_match_key(key): key
            for key in row
        }
        for term in [column.name, *column.aliases, *column.field_hints]:
            normalized = self._seed_match_key(term)
            if not normalized:
                continue
            key = row_keys.get(normalized)
            if key is not None and not self._is_missing(row.get(key)):
                return True
            if self._seed_match_term_too_generic(normalized):
                continue
            for row_key, original in row_keys.items():
                if normalized in row_key and not self._is_missing(row.get(original)):
                    return True
        return False

    @staticmethod
    def _seed_match_key(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")

    @staticmethod
    def _row_value_text(value: Any) -> str:
        if isinstance(value, Mapping):
            return " ".join(
                QuestionPipeline._row_value_text(inner)
                for inner in value.values()
            )
        if isinstance(value, (list, tuple, set)):
            return " ".join(
                QuestionPipeline._row_value_text(inner)
                for inner in value
            )
        return str(value or "")

    @classmethod
    def _seed_migration_context_terms(
        cls,
        table: Any,
        migration: Any | None,
    ) -> List[str]:
        terms: List[str] = []
        for value in [
            getattr(table, "name", ""),
            getattr(table, "description", ""),
            getattr(table, "grain", ""),
            getattr(migration, "to_table", "") if migration is not None else "",
            getattr(migration, "instructions", "") if migration is not None else "",
        ]:
            terms.extend(
                term
                for term in re.split(r"[^A-Za-z0-9]+", str(value or "").lower())
                if not cls._seed_match_term_too_generic(term)
            )

        return sorted(set(terms))

    @staticmethod
    def _seed_match_term_too_generic(value: str) -> bool:
        return value in {
            "about",
            "and",
            "answer",
            "assumptions",
            "atomic",
            "best",
            "broad",
            "can",
            "carry",
            "column",
            "context",
            "contexts",
            "distinct",
            "drop",
            "exact",
            "estimate",
            "estimates",
            "field",
            "final",
            "for",
            "from",
            "guess",
            "item",
            "into",
            "keep",
            "like",
            "level",
            "measure",
            "method",
            "methods",
            "metric",
            "model",
            "name",
            "not",
            "number",
            "one",
            "other",
            "per",
            "preserve",
            "provenance",
            "qualifier",
            "qualifiers",
            "reported",
            "row",
            "rows",
            "source",
            "table",
            "text",
            "that",
            "to",
            "type",
            "unit",
            "units",
            "value",
            "values",
            "with",
        } or len(value) < 3

    def _seed_table_migrations_available(self) -> bool:
        if self._seed_table_inputs_consumed:
            return False
        return any(
            bool(self.seed_tables.rows_by_name.get(migration.from_table))
            for migration in self.table_spec.migrations
        )

    def _export_table_names(
        self,
        rows_by_name: Dict[str, List[Dict[str, Any]]],
    ) -> List[str]:
        if not self.table_spec.is_empty:
            return self.table_spec.deliverable_names()
        return self.config.table_variables or sorted(rows_by_name)

    def _persist_deficit_windows(
        self,
        round_idx: int | str,
        report: Mapping[str, Any],
    ) -> None:
        """Record how the deficit catalog was split across planner calls.

        Written so a reader sees three windows over sixteen deficits yielding N
        tasks directly, rather than inferring the split from a ratio of counts
        the way this run's evidence batching had to be reconstructed.
        """

        if not report:
            return
        self.goals_dir.mkdir(parents=True, exist_ok=True)
        path = (
            self.goals_dir
            / f"{self._artifact_stem(round_idx)}_deficit_windows.json"
        )
        path.write_text(
            json.dumps(dict(report), indent=2, default=str),
            encoding="utf-8",
        )

    def _declared_table_names(self) -> List[str]:
        """Tables this run asked for, as opposed to ones it merely produced.

        The spec's deliverables when it declares any; otherwise the answer
        views the answer layer was asked to compile. A run may legitimately
        declare no spec at all, and then the compiled views are the only
        statement of intent the run contains.
        """

        declared = self.table_spec.deliverable_names() if self.table_spec else []
        if declared:
            return sorted(declared)
        return sorted(self._answer_view_table_names)

    def _deliverable_tables(
        self,
        rows_by_name: Mapping[str, List[Dict[str, Any]]],
    ) -> List[str]:
        """The explicit allowlist of tables the reward projection may score.

        Declared tables when the run declares any, intersected with what was
        actually handed in.  Otherwise the tables handed in.

        The point of naming them is that `project_rows`'s spec guard defaults
        *open*: a table absent from the spec projects as a deliverable, so with
        no spec a rejected best-guess candidate would project as supported with
        the value "false".  An allowlist fails closed.

        The final fallback is the loose one, and it is why this used to leak:
        a traversal's intermediate `*_table` working variables are handed in
        alongside the answers, and with nothing declared they all scored. Two
        of them carried field-scoped provenance columns, so they were fully
        creditable, and on recorded data they inflated a round's credited
        datapoints by more than half.
        """

        declared = self._declared_table_names()
        present = sorted(
            str(name) for name in (rows_by_name or {}) if str(name).strip()
        )
        if declared:
            allowed = [name for name in present if name in set(declared)]
            return allowed or sorted(declared)
        return present

    def _all_columns(self, table_name: str) -> List[str]:
        if self._all_columns_by_table:
            return self._all_columns_by_table.get(table_name, [])
        return TABLE_REQUIRED_COLUMNS.get(table_name, [])

    def _required_columns(self, table_name: str) -> List[str]:
        if self._required_columns_by_table:
            return self._required_columns_by_table.get(table_name, [])
        return TABLE_REQUIRED_COLUMNS.get(table_name, [])

    def _completeness_columns(self, table_name: str) -> List[str]:
        if self._completeness_columns_by_table:
            return self._completeness_columns_by_table.get(table_name, [])
        return TABLE_COMPLETENESS_COLUMNS.get(table_name, [])

    def _write_observed_table_spec(
        self,
        artifact_label: int | str,
        rows_by_name: Dict[str, List[Dict[str, Any]]],
        table_names: List[str],
    ) -> None:
        spec = observed_table_spec(
            {
                table_name: rows_by_name.get(table_name, [])
                for table_name in table_names
            },
            base=self.table_spec,
            table_names=table_names,
            declared_names=self._declared_table_names(),
        )
        self.table_specs_dir.mkdir(parents=True, exist_ok=True)
        path = (
            self.table_specs_dir
            / f"{self._artifact_stem(artifact_label)}_observed_table_spec.yaml"
        )
        path.write_text(dump_table_spec_yaml(spec), encoding="utf-8")

    def _record_task_goal(
        self,
        artifact_label: int | str,
        table_exports: List[Dict[str, Any]],
        *,
        gap_search_tasks: List[Dict[str, Any]],
        goal_search_tasks: List[Dict[str, Any]],
        update_history: bool = True,
    ) -> Optional[FillGoalState]:
        if self.goal_tracker is None:
            return None

        rows_by_variable = self._table_rows_by_variable(table_exports)
        # Every control decision taken after this point joins on this ID.
        self._refresh_criteria_snapshot(rows_by_variable)
        state = self.goal_tracker.evaluate(
            artifact_label=artifact_label,
            table_rows=rows_by_variable,
            universe_estimate=self.goal_universe_estimate,
            completion_state=self.completion_state,
            search_frontier=self.search_frontier.to_dict(),
            search_outcomes=self.search_outcomes,
            paper_count=self.paper_count,
            max_papers=self.config.max_papers,
            paper_budget_available=self._paper_budget_available(),
            gap_search_tasks=gap_search_tasks,
            goal_search_tasks=goal_search_tasks,
            update_history=update_history,
        )
        self.goals_dir.mkdir(parents=True, exist_ok=True)
        path = self.goals_dir / (
            f"{self._artifact_stem(artifact_label)}_stop_criteria.json"
        )
        payload = state.to_dict()
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        entry = {**payload, "json_path": str(path)}
        self.goal_states = [
            previous
            for previous in self.goal_states
            if previous.get("label", previous.get("round")) != artifact_label
        ]
        self.goal_states.append(entry)
        self._print_task_goal_state(state)
        return state

    # ------------------------------------------------------------------ #
    # Summing a field that a target may legitimately not have.
    #
    # `int(target.get(field) or 0)` makes "this target has no identifiable
    # estimate" and "this target expects zero" the same addend, and once summed
    # the two are unrecoverable. That is worse than the fabricated number it
    # replaces: a large wrong estimate is conspicuous, whereas a total quietly
    # short by the absent terms reads as a measurement.
    #
    # Deliberately framed around "the estimate is unavailable" rather than
    # around any particular estimator. Which estimator produces the number is
    # changing; that a count can be unidentifiable is intrinsic to estimating
    # one at all, so this does not need revisiting when the producer changes.
    #
    # The sum is taken over the targets that DID declare the field, and the
    # number that did not is carried alongside rather than folded in. A partial
    # sum is a real quantity -- what the run can account for -- and dropping
    # terms is only dishonest when the drop is undeclared. Returning None for
    # the whole sum would discard eleven usable measurements because a twelfth
    # is missing.
    # ------------------------------------------------------------------ #

    @staticmethod
    def _sum_declared(
        targets: Iterable[Mapping[str, Any]],
        field: str,
    ) -> tuple[int, int]:
        """Return (sum over targets declaring ``field``, count that did not)."""

        total = 0
        undeclared = 0
        for target in targets:
            if not isinstance(target, Mapping):
                continue
            value = target.get(field)
            if value is None:
                undeclared += 1
                continue
            try:
                total += int(value)
            except (TypeError, ValueError):
                undeclared += 1
        return total, undeclared

    @staticmethod
    def _fmt_declared(total: int, undeclared: int) -> str:
        """Render a partial sum so the absence is visible in the line itself."""

        if not undeclared:
            return str(total)
        if not total:
            return f"unavailable({undeclared} target(s) with no estimate)"
        return f"{total}(+{undeclared} with no estimate)"

    def _print_task_goal_state(self, state: FillGoalState) -> None:
        targets = state.target_estimate.get("count_targets") or []
        # `expected` was the Chao1 extrapolation and is gone; `floor` is the
        # observed census, which is the only count left that was ever measured.
        floor, floor_missing = self._sum_declared(targets, "expected_minimum_count")
        observed, observed_missing = self._sum_declared(targets, "observed_count")
        deficit, deficit_missing = self._sum_declared(targets, "deficit_count")
        print(
            "  Task goal: "
            f"fulfilled={state.fulfilled} "
            f"count_targets={len(targets)} "
            f"observed={self._fmt_declared(observed, observed_missing)} "
            f"floor={self._fmt_declared(floor, floor_missing)} "
            f"deficit={self._fmt_declared(deficit, deficit_missing)} "
            f"pending={state.search_frontier['pending_tasks']}"
        )

    def _print_completion_probes(self, summaries: List[Dict[str, Any]]) -> None:
        print(f"  Completion probes: {len(summaries)} breadth sample(s)")
        for summary in summaries[:6]:
            print(
                "    - "
                f"{self._clip(summary.get('query'), 120)} -> "
                f"{summary.get('result_count_bucket') or 'unknown'} "
                f"({summary.get('unique_url_count', 0)} urls, "
                f"{summary.get('unique_domain_count', 0)} domains)"
            )
            purpose = self._clip(summary.get("purpose"), 140)
            if purpose:
                print(f"      purpose: {purpose}")
            if summary.get("domains"):
                print(
                    "      domains: "
                    + ", ".join(str(item) for item in summary["domains"][:5])
                )
            if summary.get("titles"):
                print(
                    "      titles: "
                    + " | ".join(
                        self._clip(item, 90)
                        for item in summary["titles"][:3]
                    )
                )
            if summary.get("error"):
                print(f"      error: {self._clip(summary.get('error'), 160)}")

    def _print_universe_expectation(
        self,
        artifact_label: int | str,
        estimate: Mapping[str, Any],
        critique: Mapping[str, Any],
    ) -> None:
        targets = [
            target
            for target in estimate.get("count_targets") or []
            if isinstance(target, Mapping)
        ]
        floor, floor_missing = self._sum_declared(
            targets, "expected_minimum_count"
        )
        observed, observed_missing = self._sum_declared(targets, "observed_count")
        deficit, deficit_missing = self._sum_declared(targets, "deficit_count")
        print(
            "  Completion estimate "
            f"{self._artifact_stem(artifact_label)}: "
            f"status={estimate.get('status') or 'missing'} "
            f"scope_status={self.completion_state.get('scope_status') or 'missing'} "
            f"count_targets={len(targets)} "
            f"observed={self._fmt_declared(observed, observed_missing)} "
            f"floor={self._fmt_declared(floor, floor_missing)} "
            f"deficit={self._fmt_declared(deficit, deficit_missing)} "
            f"unestimated={len(estimate.get('unestimated_count_targets') or [])} "
            f"out_of_scope={len(estimate.get('out_of_scope_count_targets') or [])}"
        )
        scope = self._clip(estimate.get("scope_summary"), 180)
        if scope:
            print(f"    scope: {scope}")
        self._print_completion_targets(targets)
        issues = estimate.get("estimate_issues") or []
        if issues:
            self._print_completion_items("estimate issues", issues)
        bins = estimate.get("underexplored_bins") or []
        if bins:
            self._print_completion_items("underexplored bins", bins)
        if estimate.get("unresolved_questions"):
            self._print_completion_list(
                "unresolved",
                estimate.get("unresolved_questions") or [],
            )
        if estimate.get("suggested_queries"):
            self._print_completion_list(
                "suggested",
                estimate.get("suggested_queries") or [],
            )
        if critique:
            print(
                "    critique: "
                f"accepted={bool(critique.get('accepted') or critique.get('accept'))} "
                f"{self._clip(critique.get('rationale'), 160)}"
            )

    #: `supporting_source_id_kind` values whose ids are keys into
    #: `goal_discovery_sources`, which mints its ids as `uuid4()` at fetch
    #: time. A target declaring any other kind names sources from a different
    #: namespace, so the lookup below would miss every id and silently print
    #: nothing; those ids are shown as themselves instead.
    _REGISTRY_SOURCE_ID_KINDS = frozenset({"goal_discovery_source"})

    def _print_completion_targets(self, targets: List[Mapping[str, Any]]) -> None:
        sources_by_id = {
            str(source.get("id") or ""): source
            for source in self.goal_discovery_sources
            if isinstance(source, Mapping)
        }
        for target in targets[:6]:
            source_ids = [
                str(source_id)
                for source_id in target.get("supporting_source_ids") or []
            ]
            source_id_kind = str(
                target.get("supporting_source_id_kind") or ""
            ).strip()
            print(
                "    - "
                f"{self._clip(target.get('name'), 80)}: "
                f"observed={target.get('observed_count') or 0} "
                f"floor={target.get('expected_minimum_count') or 0} "
                f"deficit={target.get('deficit_count') or 0} "
                f"table={target.get('target_table') or ''}"
            )
            basis = self._clip(target.get("basis"), 180)
            if basis:
                print(f"      basis: {basis}")
            if source_id_kind and source_id_kind not in self._REGISTRY_SOURCE_ID_KINDS:
                labels = [
                    self._clip(source_id, 90) for source_id in source_ids[:3]
                ]
                kind_note = f" ({source_id_kind})"
            else:
                labels = [
                    self._source_label(source_id, sources_by_id.get(source_id))
                    for source_id in source_ids[:3]
                ]
                kind_note = ""
            labels = [label for label in labels if label]
            if labels:
                print(f"      sources{kind_note}: " + " | ".join(labels))

    def _print_completion_items(
        self,
        label: str,
        items: List[Mapping[str, Any]],
    ) -> None:
        print(f"    {label}:")
        for item in items[:4]:
            axis = self._clip(item.get("axis") or item.get("name"), 60)
            description = self._clip(
                item.get("description") or item.get("reason"),
                160,
            )
            if axis and description:
                print(f"      - {axis}: {description}")
            elif axis or description:
                print(f"      - {axis or description}")
            queries = item.get("suggested_queries") or []
            if queries:
                print("        query: " + self._clip(queries[0], 160))

    def _print_completion_list(self, label: str, items: List[Any]) -> None:
        cleaned = [
            self._clip(item, 140)
            for item in items
            if str(item or "").strip()
        ]
        if cleaned:
            print(f"    {label}: " + " | ".join(cleaned[:4]))

    @staticmethod
    def _source_label(source_id: str, source: Mapping[str, Any] | None) -> str:
        if not source:
            return source_id
        title = (
            source.get("title")
            or source.get("name")
            or source.get("source_title")
            or source.get("url")
            or ""
        )
        if isinstance(source.get("metadata"), Mapping):
            title = title or source["metadata"].get("title") or ""
        return f"{source_id}:{QuestionPipeline._clip(title, 70)}"

    @staticmethod
    def _clip(value: Any, limit: int = 120) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."

    async def _bootstrap_task_goal(self) -> List[Dict[str, Any]]:
        if self.goal_tracker is None:
            return []

        seed_exports = await self._export_seed_tables()
        seed_table_rows = self._table_rows_by_variable(seed_exports)
        first_round_idx = self._round_label(0)
        await self._estimate_task_goal_universe(
            f"bootstrap_{first_round_idx}",
            seed_table_rows,
            [],
        )
        self._record_task_goal(
            f"bootstrap_{first_round_idx}",
            seed_exports,
            gap_search_tasks=[],
            goal_search_tasks=[],
        )

        return seed_exports

    def _drain_bootstrap_papers(self) -> List[Dict[str, Any]]:
        papers = self._bootstrap_papers
        self._bootstrap_papers = []
        return papers

    async def _enqueue_deficit_searches(
        self,
        round_idx: int,
        table_exports: List[Dict[str, Any]],
        goal_state: Optional[FillGoalState],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if goal_state is None or goal_state.fulfilled:
            return [], []

        table_rows = self._table_rows_by_variable(table_exports)
        table_gap_tasks = self._enqueue_table_gap_searches(
            round_idx,
            table_exports,
        )
        if self._needs_more_expectation_search(goal_state):
            await self._estimate_task_goal_universe(
                f"predeficit_{round_idx}",
                table_rows,
                [],
            )
        target_deficit_tasks = await self._enqueue_target_deficit_searches(
            round_idx,
            table_rows,
            goal_state,
        )
        return table_gap_tasks, target_deficit_tasks

    async def _expand_unfulfilled_table_goal(
        self,
        current_round_idx: int | str,
        next_round_idx: int,
        table_exports: List[Dict[str, Any]],
        goal_state: Optional[FillGoalState],
    ) -> tuple[
        List[Dict[str, Any]],
        List[Dict[str, Any]],
        Optional[FillGoalState],
        Dict[str, Any],
    ]:
        gap_search_tasks: List[Dict[str, Any]] = []
        goal_search_tasks: List[Dict[str, Any]] = []
        expansion = {
            "attempted": False,
            "reason": "",
            "current_round": current_round_idx,
            "next_round": next_round_idx,
            "pending_before": self.search_frontier.pending_count,
            "pending_after": self.search_frontier.pending_count,
            "gap_search_tasks": 0,
            "goal_search_tasks": 0,
        }
        if goal_state is None or goal_state.fulfilled:
            expansion["reason"] = (
                "task_goal_fulfilled"
                if goal_state is not None
                else "task_goal_unavailable"
            )
            return gap_search_tasks, goal_search_tasks, goal_state, expansion
        if not self._paper_budget_available():
            expansion["reason"] = "paper_budget_exhausted"
            return gap_search_tasks, goal_search_tasks, goal_state, expansion

        expansion["attempted"] = True
        table_gap_tasks, target_deficit_tasks = await self._enqueue_deficit_searches(
            next_round_idx,
            table_exports,
            goal_state,
        )
        gap_search_tasks.extend(table_gap_tasks)
        goal_search_tasks.extend(target_deficit_tasks)
        goal_state = self._record_task_goal(
            current_round_idx,
            table_exports,
            gap_search_tasks=gap_search_tasks,
            goal_search_tasks=goal_search_tasks,
            update_history=False,
        )
        expansion["pending_after"] = self.search_frontier.pending_count
        expansion["gap_search_tasks"] = len(gap_search_tasks)
        expansion["goal_search_tasks"] = len(goal_search_tasks)
        if gap_search_tasks or goal_search_tasks:
            expansion["reason"] = "queued_deficit_searches"
        elif self.search_provider_error:
            expansion["reason"] = "search_provider_error"
            expansion["error"] = self.search_provider_error
        else:
            expansion["reason"] = "no_deficit_searches_queued"
        return gap_search_tasks, goal_search_tasks, goal_state, expansion

    def _enqueue_seed_frontier_searches(self, round_idx: int) -> List[Dict[str, Any]]:
        if not self.seed_frontier_tasks:
            return []

        tasks = [
            SearchTask(
                query=task.query,
                id=task.id,
                parent_id=task.parent_id,
                topic=task.topic,
                expansion_op=task.expansion_op,
                gap=task.gap,
                round_index=round_idx,
                depth=task.depth,
                producer_class=task.producer_class or "seed_frontier",
                metadata=dict(task.metadata),
            )
            for task in self.seed_frontier_tasks
            if self._seed_frontier_task_allowed(task)
        ]
        self.seed_frontier_tasks = []
        accepted = self.search_frontier.enqueue(tasks)
        if accepted:
            print(
                f"  Requeued {len(accepted)} seed frontier searches "
                f"for round {round_idx}"
            )
        return [task.to_dict() for task in accepted]

    def _seed_frontier_task_allowed(self, task: SearchTask) -> bool:
        if self.table_spec.is_empty:
            return True
        metadata = task.metadata if isinstance(task.metadata, dict) else {}
        target_table = str(metadata.get("target_table") or "").strip()
        return (
            not target_table
            or target_table in set(self.table_spec.deliverable_names())
        )

    def _universe_estimate_ready(self) -> bool:
        return (
            self.goal_universe_estimate.get("status") == "estimated"
            and bool(self.goal_universe_estimate.get("count_targets"))
        )

    def _universe_estimate_actionable(self) -> bool:
        return completion_scope_actionable(
            self.completion_state,
            self.goal_universe_estimate,
        )

    def _needs_more_expectation_search(self, goal_state: FillGoalState) -> bool:
        estimate = goal_state.target_estimate
        return completion_needs_scope_search(
            self.completion_state,
            estimate,
        )

    def _table_rows_by_variable(
        self,
        exports: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        table_names = self._export_table_names({}) or [
            str(export.get("variable"))
            for export in exports
            if export.get("variable")
        ]
        return {
            table_name: self._read_export_rows(exports, table_name)
            for table_name in table_names
        }

    @staticmethod
    def _read_export_rows(
        exports: List[Dict[str, Any]],
        variable: str,
    ) -> List[Dict[str, Any]]:
        export = next((item for item in exports if item.get("variable") == variable), None)
        if not export or not export.get("json_path"):
            return []

        path = Path(str(export["json_path"]))
        if not path.exists():
            return []

        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        return [row for row in rows if isinstance(row, dict)]

    def _write_table_csv(
        self,
        path: Path,
        rows: List[Dict[str, Any]],
        *,
        table_name: str = "",
    ) -> None:
        fieldnames: List[str] = (
            list(self._all_columns(table_name))
            or list(self._required_columns(table_name))
        )
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)

        QuestionPipeline._write_rows_csv(path, rows, fieldnames=fieldnames)

    @staticmethod
    def _write_rows_csv(
        path: Path,
        rows: List[Dict[str, Any]],
        *,
        fieldnames: List[str],
    ) -> None:
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)

        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        key: (
                            value
                            if value is None or isinstance(value, (str, int, float, bool))
                            else json.dumps(value, ensure_ascii=True, default=str)
                        )
                        for key, value in row.items()
                    }
                )

    async def run(self) -> Dict[str, Any]:
        """Prepare the frontier, then run the composition ONCE.

        THE ROUND LOOP IS GONE. `pipeline.py` composes episodes; it no longer
        sequences phases. What was the body of `for local_round_idx in ...` is
        now `_run_round_body`, called by the run grain's hook once per completed
        strategy, in its existing order and unreordered.
        """

        cfg = self.config
        print(f"\n{'='*70}\nQuestion-driven pipeline\n{'='*70}")
        print(f"Question: {cfg.question}\nOutput:   {self.out}\n")
        if self.seed_tables.row_count:
            print(
                "  Loaded seed tables: "
                f"{self.seed_tables.row_count} rows across "
                f"{len(self.seed_tables.rows_by_name)} tables"
            )
        if self.seen_urls:
            print(f"  Loaded {len(self.seen_urls)} seed source URLs")

        seeded_from_graph = self._load_seed_graph()

        if seeded_from_graph:
            await self._resolve_schema([])
        else:
            self._ensure_search_ready()
            # The seed search is no longer a phase before the loop: it becomes
            # the run episode's FIRST STRATEGY, family `llm_initial`. Its pages
            # are fetched before the schema exists -- the schema is synthesized
            # *from* them -- so every one of them is crediting-disabled under
            # the fate table's `no_extractor` row and the strategy contributes
            # no credits and does not enter the run's stop history. That is the
            # correct arithmetic: a strategy that could not judge anything is
            # not evidence that the run is saturated. The schema is resolved by
            # that strategy's own hook, from the papers it accepted.
            print(
                f"Round {self._round_label(0)}: "
                "seeding search from the question..."
            )
            schema_hint = cfg.schema_name or ""
            queries = await strategy.initial_queries(
                self.llm, cfg.question, n=cfg.queries_per_round, schema_hint=schema_hint
            )
            print(f"  Initial queries: {queries}")
            self.search_frontier.enqueue_queries(
                queries,
                round_index=self._round_label(0),
                topic="initial",
                expansion_op="llm_initial",
                producer_class="seed_query",
            )

        self._last_answer = ""
        self._gaps: List[str] = []
        self._final_assessment: Dict[str, Any] = {}
        if self.goal_tracker is not None:
            print("  Bootstrapping task-level goal from current tables...")
            seed_exports = await self._bootstrap_task_goal()
            seed_goal_search_tasks = self._enqueue_seed_frontier_searches(
                self._round_label(0),
            )
            if (
                not self._universe_estimate_actionable()
                and not seed_goal_search_tasks
                and self.search_frontier.pending_count <= 0
                and not self._bootstrap_papers
            ):
                # ENGINE-AUTHORED, NOT MODEL-AUTHORED. This assessment is
                # written by the pipeline when no model was consulted, so
                # `confidence: 0.0` here means "not asked", not "asked and
                # unsure", and `rationale` is the engine's prose rather than a
                # model's judgment. A consumer that reads either as model
                # output is reading the wrong thing.
                self._final_assessment = {
                    "sufficient": False,
                    "confidence": 0.0,
                    "gaps": ["Task-level answer universe was not estimated."],
                    "rationale": (
                        "Goal-discovery search exhausted the available search "
                        "frontier or paper budget before count targets could "
                        "be estimated."
                    ),
                }
                print("  No task-level universe estimate; stopping before GASL.")
                return self._finalize(self._last_answer, self._final_assessment)
            bootstrap_goal_state = self._record_task_goal(
                f"bootstrap_deficit_{self._round_label(0)}",
                seed_exports,
                gap_search_tasks=[],
                goal_search_tasks=seed_goal_search_tasks,
            )
            gap_search_tasks: List[Dict[str, Any]] = []
            goal_search_tasks: List[Dict[str, Any]] = []
            if self._universe_estimate_actionable():
                gap_search_tasks, goal_search_tasks = (
                    await self._enqueue_deficit_searches(
                        self._round_label(0),
                        seed_exports,
                        bootstrap_goal_state,
                    )
                )
                goal_search_tasks = [
                    *seed_goal_search_tasks,
                    *goal_search_tasks,
                ]
            else:
                goal_search_tasks = seed_goal_search_tasks
            if gap_search_tasks or goal_search_tasks:
                self._record_task_goal(
                    f"bootstrap_deficit_{self._round_label(0)}",
                    seed_exports,
                    gap_search_tasks=gap_search_tasks,
                    goal_search_tasks=goal_search_tasks,
                    update_history=False,
                )

        # THE ONE CALL THAT RUNS THE TREE, and the only `run_async` in this
        # package. It builds nothing itself: the controller holds the context,
        # the three episode declarations run through the kernel's loop body, and
        # the run-ending decision is written from the record it returns.
        record = await self.acquisition.run(self._build_run_episode())
        # The run record itself, once, after the tree returns. Its own verdict
        # is read after its hook, so a run that opened no strategy at all still
        # emits a record saying why -- `exhausted` with no units is a fact about
        # the frontier, not an absent artifact.
        self._write_episode_record(record)
        self._write_acquisition_yield()
        return self._finalize(self._last_answer, self._final_assessment)

    async def _run_round_body(
        self,
        round_idx: int,
        strategy_key: str,
        family: str,
    ) -> None:
        """The per-round work, moved out of the deleted loop and unreordered.

        Called once per completed strategy by the run grain's hook. **A ROUND IS
        NOW A COMPLETED STRATEGY**: `round_index` is the run episode's unit
        index rather than a wave counter. It appears on `SearchTask.round_index`,
        every `CostRecord.round_index`, the reward chain's `round_index`,
        artifact stems, and `seed_tables.next_round_index` for a resumed run;
        all of those need only a monotone integer stable within the process, so
        all of them keep working -- but the NUMBER differs from what a wave-based
        run would have written, and nothing compares one against the other.

        Each named step is guarded individually. `drive_async` catches nothing
        around a hook, so a failing export must not unwind the whole record
        tree; its failure is recorded as a typed class instead.
        """

        cfg = self.config
        self._open_round_ledger_window()
        self._open_prompt_log(round_idx)
        print(f"\n{'#'*70}\nROUND {round_idx}  [strategy {strategy_key}]\n{'#'*70}")

        round_papers = self._drain_round_papers()
        if self.extractor is None:
            # The schema is synthesized FROM these pages, so this is the first
            # moment it can exist. Every page of this strategy was
            # crediting-disabled under the `no_extractor` fate.
            await self._guarded("resolve_schema", self._resolve_schema, round_papers[:2])
        if round_papers:
            print(f"  Accepted {len(round_papers)} page(s) -> {self._graph_summary()}")
        else:
            print("  No new papers accepted by this strategy.")

        followups = await self._guarded(
            "followup_target_evolutions",
            self._enqueue_followup_target_evolutions,
            self._drain_followup_outcomes(),
            round_idx,
            self._target_evolution_counts,
        )
        if followups:
            print(f"  Queued {len(followups)} follow-up target-deficit searches")

        if self.graph.number_of_nodes() == 0:
            print("  Graph is still empty; cannot answer yet.")
            self.rounds.append(
                {
                    "round": round_idx,
                    "strategy_key": strategy_key,
                    "strategy_family": family,
                    "papers_ingested": len(round_papers),
                    "answer": None,
                    "hook_failures": list(self.hook_failures),
                }
            )
            self._record_stop_decision(self._stop_context_for(round_idx, None))
            self._write_control_ledger()
            self._close_prompt_log()
            return

        no_new_papers_path = (
            self.goal_tracker is not None
            and not round_papers
            and self.seed_tables.row_count
            and not self._seed_table_migrations_available()
        )
        gasl_result: Dict[str, Any] = {}
        if no_new_papers_path:
            print(
                "  No new papers accepted; recording current tables "
                "without rerunning GASL."
            )
            table_exports = await self._guarded(
                "table_exports",
                self._write_table_exports,
                round_idx,
                self.seed_tables.rows_by_name,
                seed_row_counts={
                    name: len(rows)
                    for name, rows in self.seed_tables.rows_by_name.items()
                },
                new_row_counts={},
            ) or []
        else:
            await self._guarded("save_graph", self._save_graph_sync, round_idx)
            metadata = await self._guarded("write_metadata", self._write_metadata_sync)
            print("  Running GASL traversal...")
            gasl_graph = self._gasl_graph_for_round(round_papers)
            if gasl_graph is not self.graph:
                print(
                    "  GASL graph scope: "
                    f"{gasl_graph.number_of_nodes()} nodes, "
                    f"{gasl_graph.number_of_edges()} edges"
                )
            self._gasl_source_seed_nodes = self._gasl_source_seed_nodes_for_round(
                round_papers,
                graph=gasl_graph,
            )
            try:
                gasl_result = await self._guarded(
                    "gasl",
                    self._run_gasl,
                    round_idx,
                    metadata or {},
                    graph=gasl_graph,
                ) or {}
            finally:
                self._gasl_source_seed_nodes = []
            table_exports = await self._guarded(
                "table_exports", self._export_gasl_tables, round_idx, gasl_result
            ) or []
            self._last_answer = gasl_result.get("final_answer", "") or ""

        if self.goal_tracker is not None:
            self._gaps = self._table_gaps(table_exports)
            # ENGINE-AUTHORED, NOT MODEL-AUTHORED, as above.
            assessment = {
                "sufficient": False,
                "confidence": 0.0,
                "gaps": self._gaps,
                "rationale": (
                    "Table-fill mode controls stopping through exported "
                    "table coverage and task-level stop criteria."
                ),
            }
            print(f"  Table gaps: {len(self._gaps)}")
        else:
            print(f"  Answer ({len(self._last_answer)} chars): {self._last_answer[:300]}")
            assessment = await self._guarded(
                "assess_answer",
                strategy.assess_answer,
                self.llm,
                cfg.question,
                answer=self._last_answer,
                graph_summary=self._graph_summary(),
            ) or {"sufficient": False, "confidence": 0.0, "gaps": [], "rationale": ""}
            self._gaps = [
                *(assessment.get("gaps", []) or []),
                *self._table_gaps(table_exports),
            ]
        self._final_assessment = assessment

        gap_search_tasks: List[Dict[str, Any]] = []
        goal_search_tasks: List[Dict[str, Any]] = []
        await self._guarded(
            "universe_estimate",
            self._estimate_task_goal_universe,
            round_idx,
            self._table_rows_by_variable(table_exports),
            self._gaps,
        )
        goal_state = self._record_task_goal(
            round_idx,
            table_exports,
            gap_search_tasks=gap_search_tasks,
            goal_search_tasks=goal_search_tasks,
        )
        await self._guarded(
            "annotate_target_outcomes",
            self._annotate_recent_target_outcomes_async,
            round_idx,
            goal_state,
            self._table_rows_by_variable(table_exports),
            self.last_best_guess_state,
        )

        deficit_expansion: Dict[str, Any] = {
            "attempted": False,
            "reason": "not_needed",
            "current_round": round_idx,
            "next_round": self._round_label(self._completed_strategies + 1),
            "pending_before": self.search_frontier.pending_count,
            "pending_after": self.search_frontier.pending_count,
            "gap_search_tasks": 0,
            "goal_search_tasks": 0,
        }
        if goal_state is not None and not goal_state.fulfilled:
            expanded = await self._guarded(
                "expand_goal",
                self._expand_unfulfilled_table_goal,
                round_idx,
                self._round_label(self._completed_strategies + 1),
                table_exports,
                goal_state,
            )
            if expanded is not None:
                gap_search_tasks, goal_search_tasks, goal_state, deficit_expansion = (
                    expanded
                )
        elif goal_state is None and self._paper_budget_available():
            expanded = await self._guarded(
                "enqueue_deficit_searches",
                self._enqueue_deficit_searches,
                self._round_label(self._completed_strategies + 1),
                table_exports,
                goal_state,
            )
            if expanded is not None:
                gap_search_tasks, goal_search_tasks = expanded

        # THE STOP DECISION IS A RECORD, AND THE RUN SOURCE IS WHAT READS IT.
        # `orchestration_stop_override` is a pure function that raises nothing,
        # so the deleted loop's `if stop_decision.stop: break` had to be
        # replaced by something a source can read before a pull -- otherwise the
        # composition would have one decision edge, "does this run continue",
        # with no rule at all.
        stop_decision = self._record_stop_decision(
            self._stop_context_for(round_idx, goal_state)
        )
        if stop_decision is not None and stop_decision.stop:
            self.run_termination.stopped = True
            self.run_termination.reason = stop_decision.reason.value
            self.run_termination.decision_id = stop_decision.id
            print(
                f"\n  Run termination recorded: {stop_decision.reason.value} "
                f"(frontier_pending={stop_decision.context.frontier_pending}, "
                f"source_budget_available="
                f"{stop_decision.context.source_budget_available})"
            )

        round_record = {
            "round": round_idx,
            "strategy_key": strategy_key,
            "strategy_family": family,
            "queries": [outcome.query for outcome in self.last_search_outcomes],
            "papers_ingested": len(round_papers),
            "pages_pulled": self.source_budget.spent,
            "graph_nodes": self.graph.number_of_nodes(),
            "graph_edges": self.graph.number_of_edges(),
            "answer": self._last_answer,
            "assessment": assessment,
            "gasl_iterations": gasl_result.get("iterations"),
            "search_outcomes": [
                outcome.to_dict() for outcome in self.last_search_outcomes
            ],
            "table_exports": table_exports,
            "derived_table_exports": self.last_derived_table_exports,
            "gap_search_tasks": gap_search_tasks,
            "goal_search_tasks": goal_search_tasks,
            "deficit_expansion": deficit_expansion,
            "task_goal": goal_state.to_dict() if goal_state else None,
            "skipped_gasl": no_new_papers_path,
            "control_decisions": self._round_control_decisions(),
            "cost_records": self._round_cost_records(round_idx),
            "table_schema_disclosure": self.table_schema_disclosure,
            "field_provenance_coverage": self.last_field_provenance_ledger,
            "criteria_projection_version": CRITERIA_PROJECTION_VERSION,
            "hook_failures": list(self.hook_failures),
            "page_best_guess": list(self._page_guess_reports),
        }
        self.rounds.append(round_record)
        (self.answers_dir / f"round_{round_idx}.json").write_text(
            json.dumps(round_record, indent=2, default=str), encoding="utf-8"
        )
        self._write_control_ledger()
        self._write_acquisition_yield()
        self._record_strategy_residual_cost(round_idx)
        self._reset_round_state()
        self._close_prompt_log()

    async def _guarded(self, step: str, fn, *args, **kwargs):
        """Run one round-body step; record a failure rather than raising.

        A hook may not raise. Each named step is guarded individually so one
        failing export cannot unwind the record tree, and its failure lands on
        the round record as a typed class instead of vanishing.
        """

        try:
            result = fn(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as exc:  # noqa: BLE001 - recorded, never raised at a hook
            self._record_hook_failure(f"round:{step}", step, exc)
            return None

    def _save_graph_sync(self, round_idx: int) -> None:
        self._save_graph(round_idx)

    def _write_metadata_sync(self) -> Dict[str, Any]:
        return self._write_metadata()

    def _annotate_recent_target_outcomes_async(
        self,
        round_idx: int,
        goal_state,
        table_rows,
        best_guess_state,
    ) -> None:
        self._annotate_recent_target_outcomes(
            round_idx,
            goal_state,
            table_rows=table_rows,
            best_guess_state=best_guess_state,
        )

    def _stop_context_for(self, round_idx: int, goal_state) -> StopContext:
        """The stop inputs, with the frontier required at exactly one site.

        The composition tests the frontier where a strategy's source runs out of
        tasks, so an empty frontier is terminal for the run only once every
        eligible family is drained -- which is what `_eligible_families` reports.
        """

        return StopContext(
            round_index=round_idx,
            goal_mode=self.goal_tracker is not None,
            goal_fulfilled=bool(goal_state is not None and goal_state.fulfilled),
            source_budget_available=self._paper_budget_available(),
            frontier_pending=self.search_frontier.pending_count,
            frontier_required=not self._eligible_families(),
            round_budget_available=(
                int(self.config.max_rounds) <= 0
                or (self._completed_strategies + 1) < int(self.config.max_rounds)
            ),
            criteria_snapshot_id=self.criteria_snapshot.id,
        )

    def _drain_round_papers(self) -> List[Dict[str, Any]]:
        papers = [*self._drain_bootstrap_papers(), *self._accepted_papers]
        self._accepted_papers = []
        return papers

    def _drain_followup_outcomes(self) -> List[SearchOutcome]:
        outcomes = self._pending_followup_outcomes
        self._pending_followup_outcomes = []
        return outcomes

    def _reset_round_state(self) -> None:
        self.last_prompt_arm_summaries = summarize_prompt_arms(
            self.last_search_outcomes
        )
        self._harvester.record_prompt_arm_summaries(self.last_prompt_arm_summaries)
        self.last_search_outcomes = []
        self._page_guess_reports = []

    def _record_strategy_residual_cost(self, round_idx: int) -> None:
        """Unattributed spend for THIS strategy's interval, stamped and rebased.

        Two things are needed and only one is obvious. The stamp: the ORPHAN
        meter's own snapshot carries `round_index=0` by construction, and
        `reward.aggregate_round_cost` filters on that field, so an unstamped
        residual lands in round 0 whatever round paid for it. The REBASE:
        `_orphan_cost_delta` measures against the baseline taken when the
        pipeline was constructed, so it is cumulative over the run -- taking it
        per strategy without rebasing hands every strategy the whole run's
        residual to date, and summing them multiply-counts the same spend.

        ONE SNAPSHOT SERVES BOTH READS. `CostMeter` is explicitly shared across
        threads and `snapshot()` reads its fields without the lock, so taking a
        second snapshot for the next baseline could lose an interval between the
        two reads. Taking one and using it for both makes the identity telescope
        exactly, even on a torn read.
        """

        if not self.cost_accounting_enabled:
            return
        current = orphan_meter().snapshot().to_dict()
        baseline = self._strategy_orphan_baseline
        self._strategy_orphan_baseline = current
        residual = _orphan_interval(baseline, current)
        residual.update(
            {
                "observation_kind": ObservationKind.RUN_RESIDUAL.value,
                "observation_id": f"{self.out.name}#r{round_idx}",
                "nested_in": "",
                "round_index": int(round_idx),
            }
        )
        self.cost_records.append(residual)

    # ------------------------------------------------------------------ #
    # Control decision ledger (Phase 1C)
    #
    # Wiring only.  Every policy question is answered by `control.py` and
    # every criteria identifier comes from `criteria.py`; this section moves
    # typed records between them and the run's artifacts, and decides nothing.
    # ------------------------------------------------------------------ #
    def _write_acquisition_yield(self) -> None:
        """The summary view, written durably per completed strategy.

        A PROJECTION of `acquisition_episodes.json`, and it says so in its own
        payload along with the keys it does not carry -- so a reader who checks
        only the summary is told, in the summary, that it is one. That is the
        4E-b lesson: a disposable runner projected the emitted record through a
        summary that silently dropped a field the registration predicted about,
        and both confirmation routes read that same projection.
        """

        path = self.answers_dir / "acquisition_yield.json"
        payload = self.acquisition.export()
        payload["stranded_frontier_work"] = self._stranded_frontier_work()
        payload["pages_pulled"] = self.source_budget.spent
        payload["pages_accepted"] = len(self.source_ingestion_ledger)
        payload["orphan_meter"] = orphan_meter().snapshot().to_dict()
        payload["missing_token_owner"] = {
            "module": "criteria",
            "tokens": len(criteria_missing_tokens()),
        }
        payload["hook_failures"] = list(self.hook_failures)
        payload["page_best_guess_mode"] = self.config.page_best_guess_mode
        payload["criteria_projection_version"] = CRITERIA_PROJECTION_VERSION
        try:
            path.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - disclosed, never silent
            print(f"  [acquisition] yield export failed: {exc}")

    def _stranded_frontier_work(self) -> List[Dict[str, Any]]:
        """Pending frontier tasks nobody will run, BY FAMILY AND BY REASON.

        "The frontier still carries that strategy's unpulled tasks at run end"
        is the expected observable for a family its own verdict abandoned, and a
        DIFFERENT FACT for one that merely ran out of queued work at the instant
        it was pulled, or one stranded because the budget went. Reporting all
        three the same way would read a silent failure as a success, so each row
        carries the class that produced it.
        """

        classes: List[Dict[str, Any]] = []
        for family, tasks in self.search_frontier.pending_by_family().items():
            ended = self._strategy_ends.get(family, "")
            if ended == END_YIELD_STOP:
                reason = "abandoned_by_verdict"
            elif self.source_budget.exhausted:
                reason = "budget_spent"
            elif self.run_termination.stopped:
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
                    "run_termination_reason": self.run_termination.reason,
                    "instances_opened": (
                        self.proposer.instances_opened().get(family, 0)
                        if self.proposer is not None
                        else 0
                    ),
                }
            )
        return classes

    def _append_control_decision(
        self,
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """The only writer of ``control_decisions``.

        Append-only, literally: this method appends and nothing anywhere
        mutates, reorders, deduplicates, or removes an existing record.  A
        superseded decision is followed by a new record.  ``ledger_index``
        is positional and is deliberately absent from every stable ID, so a
        resumed run that carries a prefix forward continues the numbering
        instead of renumbering it.
        """

        record = {"ledger_index": len(self.control_decisions), **dict(payload)}
        self.control_decisions.append(record)
        # Durable on append, not on round boundary.  A run killed mid-round
        # otherwise loses every decision it made since the last round record,
        # which makes "the same decision IDs across a resumed run" a claim
        # about nothing -- verified against a real 3h run that was killed in
        # round 11 and left no ledger at all (experiments/log/1C-r2.md).
        self._write_control_ledger()
        return record

    # ------------------------------------------------------------------ #
    # Path-selection gate (Phase 2B)
    #
    # Wiring only.  Scoring is `path_features.py`, admission is
    # `path_gate.py`, ranking is `control.py`, and "supported" is
    # `criteria.py`.  Nothing below decides any of those.
    # ------------------------------------------------------------------ #
    def _apply_path_gate(
        self,
        artifact_label: int | str,
        rows_by_table: Dict[str, List[Any]],
    ) -> Dict[str, List[Any]]:
        """Record a PATH_SELECTION decision per table; admit what it admits."""

        if not self.control_ledger_enabled:
            return rows_by_table

        # ``-1`` for an artifact label that is not a numbered round (``seed``
        # and friends).  It is in every candidate ID on this surface, so it
        # must be deterministic and must not collide with round 0.
        pipeline_round = self._pipeline_round(artifact_label)
        round_index = int(pipeline_round) if pipeline_round is not None else -1
        accepted = sorted(self._source_records_by_id())
        gated: Dict[str, List[Any]] = {}
        for name in sorted(rows_by_table):
            items = rows_by_table[name]
            if not isinstance(items, list) or not items:
                gated[name] = items
                continue
            positions = [
                index for index, row in enumerate(items) if isinstance(row, dict)
            ]
            if not positions:
                gated[name] = items
                continue

            candidates = [items[index] for index in positions]
            result = gate_rows(
                candidates,
                policy=self.control_policy,
                round_index=round_index,
                table=name,
                context=self._path_scoring_context(name, accepted),
                # The projection of *these* rows: the exemption asks whether a
                # subject already has support, and a snapshot of some other row
                # set answers a different question.  Skipped when the gate
                # cannot demote, because it is the expensive part.
                snapshot=(
                    project_rows(
                        {name: candidates},
                        self.table_spec,
                        accepted_source_ids=accepted,
                    )
                    if self.path_gate_settings.gates
                    else None
                ),
                table_specs=self.table_spec,
                settings=self.path_gate_settings,
                criteria_snapshot_id=self.criteria_snapshot.id,
                pending_actions=self.search_frontier.pending_count,
                remaining_source_budget=max(
                    0, int(self.config.max_papers) - int(self.paper_count)
                ),
            )
            self._append_control_decision(
                result.to_ledger_record(
                    artifact_path=self._write_path_gate_artifact(
                        artifact_label, name, result
                    )
                )
            )

            keep = {positions[index] for index in result.admitted_indices}
            gated[name] = [
                row
                for index, row in enumerate(items)
                if index not in set(positions) or index in keep
            ]
        return gated

    def _path_scoring_context(
        self,
        table: str,
        accepted_source_ids: List[str],
    ) -> PathScoringContext:
        spec = self.table_spec.tables.get(table)
        return build_context(
            self.criteria_snapshot,
            table=table,
            key_columns=tuple(spec.key_columns) if spec is not None else (),
            accepted_source_ids=accepted_source_ids,
            # Priors come from rows already held, never from the rows being
            # scored: a route that voted on its own relation type being
            # productive would be scoring itself.
            prior_rows=self.seed_tables.rows_by_name.get(table, []),
        )

    def _write_path_gate_artifact(
        self,
        artifact_label: int | str,
        table: str,
        result: PathGateResult,
    ) -> str:
        """Full per-route detail, out of line from the ledger.

        The ledger is rewritten on every append and one traversal round
        produces tens of thousands of routes, so the route list lives here and
        the ledger record points at it by ``decision_id``.
        """

        directory = self.answers_dir / "path_selection"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self._artifact_stem(artifact_label)}_{table}.json"
        path.write_text(
            json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        return str(path)

    def _refresh_criteria_snapshot(
        self,
        rows_by_variable: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        """Re-project the current tables so decisions carry a real snapshot ID.

        The ID is `criteria.py`'s, never reconstructed here: a ledger written
        against an invented snapshot ID joins to nothing later.
        """

        if not self.control_ledger_enabled:
            return
        self.criteria_snapshot = project_rows(
            rows_by_variable,
            self.table_spec,
            accepted_source_ids=sorted(self._source_records_by_id()),
        )

    def _control_decision_context(
        self,
        surface: ControlSurface,
        round_index: int,
        *,
        max_actions: int,
    ) -> DecisionContext:
        return DecisionContext(
            surface=surface,
            round_index=int(round_index),
            max_actions=int(max_actions),
            pending_actions=self.search_frontier.pending_count,
            remaining_source_budget=max(
                0,
                int(self.config.max_papers) - int(self.paper_count),
            ),
            criteria_snapshot_id=self.criteria_snapshot.id,
        )

    def _record_policy_decision(
        self,
        surface: ControlSurface,
        round_index: int,
        candidates: List[ActionCandidate],
        *,
        max_actions: int,
    ) -> Optional[PolicyDecision]:
        """Record one ranking decision.  Observation only: the caller keeps
        enqueuing exactly what it enqueued before this method existed."""

        if not self.control_ledger_enabled or not candidates:
            return None
        context = self._control_decision_context(
            surface,
            round_index,
            max_actions=max_actions,
        )
        decision = self.control_policy.rank_actions(context, list(candidates))
        self._append_control_decision(decision.to_dict())
        return decision

    def _record_stop_decision(self, context: StopContext) -> Optional[StopDecision]:
        if not self.control_ledger_enabled:
            return None
        decision = resolve_stop_decision(context, self.control_policy)
        self._append_control_decision(
            {
                **decision.to_dict(),
                "candidate_action_ids": [],
                "ranked_action_ids": [],
                "selected_action_ids": [],
            }
        )
        return decision

    def _stop_context(
        self,
        *,
        round_index: int,
        local_round_idx: int,
        goal_state: Optional[FillGoalState],
        assessment: Mapping[str, Any] | None,
        frontier_required: bool,
    ) -> StopContext:
        """Project the loop's own continuation inputs onto 1A's stop vocabulary.

        ``frontier_required`` is per-site rather than global because the loop
        is: an empty frontier is terminal where the loop tests it and not
        where it does not.
        """

        # `assessment` is no longer read here. It still carries `sufficient`
        # and `confidence`, both model-emitted, and both are now REPORTED
        # rather than gating: `gaps` and `rationale` from the same payload are
        # genuinely semantic and stay. What the model says is missing is a
        # model's job; whether that is enough is arithmetic, and the arithmetic
        # reads the two counts below instead.
        return StopContext(
            round_index=round_index,
            goal_mode=self.goal_tracker is not None,
            goal_fulfilled=bool(goal_state is not None and goal_state.fulfilled),
            source_budget_available=self._paper_budget_available(),
            frontier_pending=self.search_frontier.pending_count,
            frontier_required=bool(frontier_required),
            round_budget_available=(
                int(self.config.max_rounds) <= 0
                or (local_round_idx + 1) < int(self.config.max_rounds)
            ),
            criteria_snapshot_id=self.criteria_snapshot.id,
        )

    def _stamp_control_action(
        self,
        task: SearchTask,
        candidate: ActionCandidate,
    ) -> None:
        """Carry the ledger join keys onto the task that executes the action.

        Join keys only.  ``ActionCandidate.to_metadata()`` also projects
        operator, attempt, and prompt-arm fields onto keys this pipeline
        already writes, and overwriting those would make recording a
        behaviour change rather than an observation.  ``action_origin`` is
        written *beside* baseline's ``strategy_origin`` -- `control.py:515`
        emits the origin under `action_origin` while `search_memory.py:251`
        reads `strategy_origin` through a ``.get(..., "")`` that cannot
        raise.  ``tests/test_decision_ledger.py`` pins the two to the same
        value so that mismatch cannot reappear silently.
        """

        task.metadata["control_action_id"] = candidate.id
        task.metadata["control_surface"] = candidate.surface.value
        task.metadata["action_origin"] = candidate.origin.value
        task.metadata["criteria_snapshot_id"] = self.criteria_snapshot.id

    @staticmethod
    def _stamp_control_decision(
        tasks: List[SearchTask],
        decision: Optional[PolicyDecision],
    ) -> None:
        if decision is None:
            return
        for task in tasks:
            task.metadata["control_decision_id"] = decision.id
            task.metadata["policy_state_id"] = decision.state.id

    def _target_search_candidate(
        self,
        *,
        query: str,
        target: Mapping[str, Any],
        round_idx: int,
        operator_plan: Mapping[str, Any],
        attempt_context: Mapping[str, Any],
        prompt_arm: Mapping[str, Any],
        query_index: int,
        rationale: str,
        origin: ActionOrigin,
    ) -> SearchCandidate:
        return SearchCandidate.create(
            surface=ControlSurface.TARGET_SEARCH,
            query=query,
            round_index=round_idx,
            operator=OperatorRef.from_mapping(operator_plan),
            attempt=AttemptRef.from_mapping(attempt_context),
            prompt_arm=PromptArmRef.from_mapping(prompt_arm),
            query_index=query_index,
            rationale=rationale,
            origin=origin,
            target=TargetRef.from_mapping(
                {
                    **dict(target),
                    "criteria_snapshot_id": self.criteria_snapshot.id,
                }
            ),
        )

    def _open_round_ledger_window(self) -> None:
        self._round_ledger_mark = len(self.control_decisions)

    def _round_control_decisions(self) -> List[Dict[str, Any]]:
        return self.control_decisions[self._round_ledger_mark :]

    def _write_control_ledger(self) -> None:
        if not self.control_ledger_enabled:
            return
        self.answers_dir.mkdir(parents=True, exist_ok=True)
        (self.answers_dir / CONTROL_LEDGER_FILENAME).write_text(
            json.dumps(
                {
                    "control_vocabulary_version": CONTROL_VOCABULARY_VERSION,
                    "seeded_control_decision_count": (
                        self.seeded_control_decision_count
                    ),
                    "count": len(self.control_decisions),
                    "control_decisions": self.control_decisions,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _save_graph(self, round_idx: int) -> None:
        save_graph(self.graphs_dir / f"round_{round_idx}.graphml", self.graph)
        save_graph(self.graphs_dir / "current_graph.graphml", self.graph)

    def _record_run_residual_cost(self) -> None:
        """The TAIL residual: spend since the last strategy closed.

        Unattributed spend is a number here, not silence. It used to be one
        record for the whole run, carrying `round_index=0` by construction --
        which `reward.aggregate_round_cost` filters on, so every unattributed
        call in the run was counted in round 0 whatever round paid for it. It is
        now taken per completed strategy (`_record_strategy_residual_cost`),
        rebased each time, and this closes the last interval carrying the LAST
        round index rather than 0.

        The identity that makes this checkable: the sum of every `RUN_RESIDUAL`
        record's counters equals the run's whole orphan delta, emitted on the
        run record. Any difference is a double count or a dropped interval, and
        either way it names itself.
        """
        if not self.cost_accounting_enabled:
            return
        current = orphan_meter().snapshot().to_dict()
        residual = _orphan_interval(self._strategy_orphan_baseline, current)
        self._strategy_orphan_baseline = current
        residual.update(
            {
                "observation_kind": ObservationKind.RUN_RESIDUAL.value,
                "observation_id": f"{self.out.name}#tail",
                "nested_in": "",
                "round_index": int(self._last_round_index),
            }
        )
        self.cost_records.append(residual)

    def _acquisition_run_summary(self) -> Dict[str, Any]:
        """The run's own acquisition observables, every one of them two-sided.

        Each is emitted whether it is zero or not, because a zero is a finding
        here rather than an absence: a floor nothing fell below was decorative
        on this configuration, an empty counterfactual means the exclusion had
        nothing to remove, and a chunk grain no page reached is inert rather
        than unnecessary.
        """

        details = self.acquisition_page_details
        gate_outcomes: Counter = Counter()
        deciles: Counter = Counter()
        clearance_by_windows: Dict[int, Dict[str, int]] = {}
        chunk_counts: Counter = Counter()
        chunk_would_fire = 0
        rule_counts: Counter = Counter()
        triviality_counts: Counter = Counter()
        source_kind_counts: Counter = Counter()
        counterfactual = 0
        row_guess_split: Counter = Counter()
        key_only_pages = 0
        subject_identities: set[str] = set()
        for row in details:
            gate = row.get("gate") or {}
            gate_outcomes[str(gate.get("outcome") or "")] += 1
            score = gate.get("score")
            if isinstance(score, (int, float)):
                deciles[min(9, int(float(score) * 10))] += 1
            windows = int(gate.get("window_count") or 0)
            bucket = clearance_by_windows.setdefault(
                windows, {"pages": 0, "cleared": 0}
            )
            bucket["pages"] += 1
            if gate.get("outcome") == acq.GATE_CLEARED:
                bucket["cleared"] += 1
            chunks = row.get("chunk_encounters") or []
            chunk_counts[len(chunks)] += 1
            if len(chunks) >= _CHUNK_GRAIN_CROSSING and not any(
                chunk.get("new_within_page") for chunk in chunks
            ):
                chunk_would_fire += 1
            for attribution in row.get("attributions") or []:
                rule_counts[str(attribution.get("rule") or "")] += 1
                triviality_counts[str(attribution.get("triviality_rule") or "")] += 1
                source_kind_counts[str(attribution.get("source_kind") or "")] += 1
            counterfactual += len(row.get("counterfactual_credits") or [])
            for credit in row.get("row_credits") or []:
                row_guess_split[len(credit.get("columns_best_guess") or [])] += 1
                subject_identities.add(str(credit.get("identity") or ""))
            if (
                row.get("counts_toward_verdict")
                and not (row.get("attributions") or [])
                and row.get("row_credit_max_columns_covered") == 0
                and row.get("skip_reason") == ""
            ):
                key_only_pages += 1

        exported_subjects = 0
        for table, columns in self.crediter.basis.subject_key_columns.items():
            rows = self.seed_tables.rows_by_name.get(table) or []
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
            "criteria_projection_version": CRITERIA_PROJECTION_VERSION,
            "pages_pulled": self.source_budget.spent,
            "pages_with_detail": len(details),
            "gate_outcomes": dict(gate_outcomes),
            # P4E-c-11: a COUNT says whether the floor fired; the DISTRIBUTION
            # says whether it could have fired at a nearby value, and the two
            # configurations that produce the same count license opposite next
            # moves. Zero below the floor means the floor was decorative on this
            # configuration -- reported as the finding, never as "the gate
            # worked".
            "gate_score_deciles": {str(k): v for k, v in sorted(deciles.items())},
            "gate_floor": RELEVANCE_SCORE_FLOOR,
            # C48, second clause: WHY THIS ARTIFACT CARRIES NO AGREEMENT RATE
            # BETWEEN THE RULE AND A LABEL. Its absence is a design consequence
            # and must never read as an oversight, and the label must never be
            # reintroduced to "restore" the number.
            "no_rule_label_agreement_rate": (
                "the page gate's prompt emits a specificity score and NO accept "
                "or reject word, so no label exists to agree with and no "
                "agreement rate is computable from any emitted field. This is "
                "deliberate: a label the same model emitted alongside the score "
                "would measure the model against itself, and re-adding one to "
                "compute this number would re-create the decision edge 4E-c "
                "removed. The deciles above are a DISTRIBUTION, not a ground "
                "truth -- moving `gate_floor` until the below-floor count looks "
                "right is fitting to a number with no referent. The floor moves "
                "only on a blind re-derivation from the source chunk "
                "(`evidence-verifier`), never on this histogram alone."
            ),
            # P4E-c-11b: max-over-windows is an order statistic whose
            # expectation rises with N, and here N is document length. The
            # change does not introduce that exposure; it makes it a number.
            "clearance_by_window_count": {
                str(k): v for k, v in sorted(clearance_by_windows.items())
            },
            # NOT A COUNTERFACTUAL OF THE FLOOR, and this says so. A page below
            # the floor was never extracted, so its credits exist in no record
            # and no counterfactual over this floor is computable from emitted
            # data. Recomputing verdicts with below-floor pages treated as
            # barren bounds the influence; it does not measure what the rule
            # cost.
            "gate_influence_is_a_bound_not_a_counterfactual": True,
            "credit_rule_counts": dict(rule_counts),
            "triviality_rule_counts": dict(triviality_counts),
            "credit_source_kind_counts": dict(source_kind_counts),
            "counterfactual_credit_count": counterfactual,
            "counterfactual_reading": (
                "the excluded columns could never have become datapoints, so an "
                "empty counterfactual means the exclusion had nothing to remove "
                "on this configuration and NEVER that it was unnecessary"
            ),
            # RC8: the second curve's height as a property of the sources or of
            # the guesser. No rule reads this split.
            "row_credit_guessed_column_counts": {
                str(k): v for k, v in sorted(row_guess_split.items())
            },
            # RC9: construct-once freezes the subject-key COLUMN list, not the
            # VALUES, and a kind-2 identity is over normalized values extracted
            # per page. Identity churn at the outermost decision edge is legible
            # here rather than inferred.
            "distinct_row_credit_identities": len(subject_identities),
            "distinct_exported_subject_keys": exported_subjects,
            "subject_key_columns": {
                table: list(columns)
                for table, columns in self.crediter.basis.subject_key_columns.items()
            },
            # RC10: the one class of page the loop cannot see.
            "extracted_pages_with_no_credit": key_only_pages,
            # The gate's prose reaches the next query's literal text through
            # `strategy_state._memory_terms`, and that chain is pre-existing and
            # not this phase's to close. What this phase owes is that its
            # narrowing does not WIDEN it, measured BY KIND rather than only by
            # count: a term count that falls while column identifiers replace
            # subject vocabulary would read as the safe direction while the
            # query surface degrades. Two-sided -- zero declared-column-name
            # terms means the narrowing did not change the kind of vocabulary in
            # the chain, and that is the finding.
            "memory_term_kinds": self._memory_term_kinds(),
            # P4E-c-3: the chunk grain is UNBOUND and its verdict is replayed
            # offline. If no page reaches the crossing the grain is inert on
            # this configuration and that is the finding.
            "chunk_counts": {str(k): v for k, v in sorted(chunk_counts.items())},
            "chunk_grain_crossing": _CHUNK_GRAIN_CROSSING,
            "pages_where_a_chunk_verdict_would_have_fired": chunk_would_fire,
            "typed_credit_columns": sum(
                1
                for column in self.crediter.basis.columns
                if column.value_type or column.unit
            ),
            "page_best_guess": {
                "mode": self.config.page_best_guess_mode,
                "reports": list(self._page_guess_reports),
            },
            "proposer": dict(self.proposer.ledger) if self.proposer else {},
            # C37: the whole per-family map. `stranded_frontier_work` reports
            # instances only for families that still hold pending tasks, so a
            # family that opened and drained its queue appears nowhere in that
            # list -- which is precisely the case the re-open bound is about.
            "strategy_instances_opened": (
                self.proposer.instances_opened() if self.proposer else {}
            ),
            "strategy_proposals": list(self._strategy_proposals),
            "stranded_frontier_work": self._stranded_frontier_work(),
            "hook_failures": list(self.hook_failures),
            "search_provider_batch": dict(self.search_provider_batch),
        }

    def _memory_term_kinds(self) -> Dict[str, Any]:
        """Terms entering the query-text chain, split by kind, per round.

        A set test over data the run already holds: the two fields
        `strategy_state._memory_terms` reads, against the declared column
        vocabulary. It measures the chain; it does not gate it, and nothing
        branches on the result.
        """

        declared = {
            column.column.lower()
            for column in self.crediter.basis.columns
        } | {
            str(name).lower()
            for names in self.crediter.basis.subject_key_columns.values()
            for name in names
        }
        by_round: Dict[int, Dict[str, int]] = {}
        for outcome in self.search_outcomes:
            if not isinstance(outcome, Mapping):
                continue
            round_index = _safe_int(outcome.get("round_index"), 0)
            bucket = by_round.setdefault(
                round_index, {"terms": 0, "declared_column_names": 0}
            )
            for decision in outcome.get("relevance_decisions") or []:
                if not isinstance(decision, Mapping):
                    continue
                metadata = decision.get("metadata")
                metadata = metadata if isinstance(metadata, Mapping) else {}
                for key in ("matched_needs", "missing_needs"):
                    for term in metadata.get(key) or []:
                        bucket["terms"] += 1
                        if str(term).strip().lower() in declared:
                            bucket["declared_column_names"] += 1
        return {
            "declared_column_vocabulary": sorted(declared),
            "by_round": {str(k): v for k, v in sorted(by_round.items())},
        }

    def _orphan_partition(self) -> Dict[str, Any]:
        """P4E-c-10: the residual records partition the run's orphan delta.

        Any difference is a double count or a dropped interval, and either way
        it names itself. Recomputable by addition from the emitted records.
        """

        keys = ("llm_calls", "prompt_tokens", "completion_tokens", "provider_calls")
        summed = {
            key: sum(
                _safe_int(record.get(key), 0)
                for record in self.cost_records
                if record.get("observation_kind") == ObservationKind.RUN_RESIDUAL.value
            )
            for key in keys
        }
        current = orphan_meter().snapshot().to_dict()
        total = {
            key: _safe_int(current.get(key), 0)
            - _safe_int(self._run_orphan_baseline.get(key), 0)
            for key in keys
        }
        return {
            "summed_over_residual_records": summed,
            "run_orphan_delta": total,
            "partitions": summed == total,
        }

    def _finalize(self, answer: str, assessment: Dict[str, Any]) -> Dict[str, Any]:
        self._record_run_residual_cost()
        result = {
            "question": self.config.question,
            "final_answer": answer,
            "assessment": assessment,
            "rounds": len(self.rounds),
            # PAGES PULLED, accepted or not. The budget charges every pulled
            # page, so this is what `max_papers` bounds; `pages_accepted` is the
            # other half and both are emitted so nothing is ambiguous. No figure
            # here is compared against one from before the composition.
            "papers_fetched": self.paper_count,
            "pages_pulled": self.source_budget.spent,
            "pages_accepted": len(self.source_ingestion_ledger),
            "graph_nodes": self.graph.number_of_nodes(),
            "graph_edges": self.graph.number_of_edges(),
            "schema": self.schema.domain_name if self.schema else None,
            "graph_path": str(self.graphs_dir / "current_graph.graphml"),
            "answer_mode": self.config.answer_mode,
            "table_exports": self.table_exports,
            "derived_table_exports": self.derived_table_exports,
            "best_guess_exports": self.best_guess_exports,
            "reward_exports": self.reward_exports,
            "search_frontier": self.search_frontier.to_dict(),
            "search_outcomes": self.search_outcomes,
            "search_memory": self.search_memory.to_dict(),
            "completion_state": self.completion_state,
            "task_goals": self.goal_states,
            "goal_universe_estimate": self.goal_universe_estimate,
            "goal_discovery_sources": self.goal_discovery_sources,
            # Which model served which call site on this run. A run's costs are
            # uninterpretable without it, so it travels with the run.
            "model_tiers": describe_tiers(self.llm),
            "control_vocabulary_version": CONTROL_VOCABULARY_VERSION,
            "criteria_snapshot_id": self.criteria_snapshot.id,
            "seeded_control_decision_count": self.seeded_control_decision_count,
            "control_decisions": self.control_decisions,
            "criteria_projection_version": CRITERIA_PROJECTION_VERSION,
            "missing_token_owner": {
                "module": "criteria",
                "tokens": len(criteria_missing_tokens()),
            },
            "acquisition": self.acquisition.export(),
            "acquisition_summary": self._acquisition_run_summary(),
            "cost_accounting_version": COST_ACCOUNTING_VERSION,
            "cost_accounting_enabled": self.cost_accounting_enabled,
            "cost_records": self.cost_records,
            # "Not attributed" is a number here, not silence.
            "orphan_meter": orphan_meter().snapshot().to_dict(),
            "orphan_partition": self._orphan_partition(),
            # Reference readings, not the cost basis. `provider_reported_usage`
            # is what the clients' own accumulators say, walking the tier clones
            # as well as the base client; the recorded basis stays the per-call
            # event. They are here so the two can be compared.
            "provider_reported_usage": self._provider_reported_usage(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            # Emitted by the pipeline itself so code provenance survives a run
            # launched without the snapshot script. Never inferred.
            "code_provenance": _code_provenance(REPO_ROOT),
            "config": {
                **self.config.to_dict(),
                # Resolved runtime metadata: PipelineConfig owns acquisition
                # budgets, while the active search adapter owns its batch.
                "search_provider_batch": dict(self.search_provider_batch),
            },
        }
        self._write_control_ledger()
        (self.out / "final_answer.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
        if self.config.pipeline_mode == PIPELINE_MODE_TABLE_FILL:
            print(
                f"\n{'='*70}\nTABLE FILL COMPLETE\n{'='*70}\n"
                f"Exported {len(self.table_exports)} table snapshots.\n"
            )
        else:
            print(f"\n{'='*70}\nFINAL ANSWER\n{'='*70}\n{answer}\n")
        print(f"Saved: {self.out / 'final_answer.json'}")
        return result
