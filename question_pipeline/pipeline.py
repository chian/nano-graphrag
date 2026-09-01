"""Question-driven GraphRAG pipeline Episode composition.

The default answer mode tries to produce one well-supported answer. Nested
strategy and search Episodes acquire evidence, extend a typed knowledge graph,
answer the question with GASL, and use identified gaps to steer later work.

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
from nano_graphrag.graph_slots import get_source_refs
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
)
from .completion import (
    completion_update_from_critique,
    completion_update_from_estimate,
    completion_scope_actionable,
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
from .evidence_registry import EvidenceRegistry
from .extraction import chunk_spans, chunk_text, enrich_graph, extract_from_text
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
    prompt_scope,
)
from . import acquisition as acq
from .acquisition import (
    RUN_GRAIN,
    AcquisitionController,
    ColumnProjection,
    ProviderHealth,
    RunTermination,
    SourceBudget,
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
    load_seed_frontier_tasks,
    load_seed_search_outcomes,
    load_seed_source_records,
    load_seen_urls,
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
    #: Emergency boundary only. Episode records report ``bound_hit`` when it
    #: fires; it is not a convergence rule. Never exposed as a CLI option.
    episode_unit_safety_cap: int = 1_000_000
    #: The ONE operator-declared run-wide bound: source units PULLED from
    #: provider result lists, accepted or not (mechanical and extraction
    #: failures still consume acquisition work). ``0`` means UNBOUNDED, which
    #: is the default -- safety is absent unless the operator declares it --
    #: and when a declared bound cuts a run the records say ``bound_hit``,
    #: never convergence. Named in the Episode/unit vocabulary deliberately:
    #: the unit is "one fetched page or document", whatever the medium.
    max_source_units: int = 0
    min_source_length: int = 500
    max_source_length: Optional[int] = None
    max_extraction_chars_per_source: Optional[int] = None
    scrape_search_results: bool = False
    table_gap_search_tasks: int = 12
    goal_discovery_text_chars: int = 6000
    #: Query strings the initial seed-planning call emits -- planner string
    #: breadth for one model call, never a stop rule or a wave size.
    initial_seed_queries: int = 6
    #: Candidate strategies one proposer call samples -- string breadth for
    #: the switch edge's model call, never a stop rule. Split out of
    #: ``task_goal_search_tasks``, which used to serve both concepts.
    strategy_candidates_per_proposal: int = 3

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
    answer_mode: str = "natural"
    table_variables: List[str] = field(default_factory=list)
    table_spec_path: Optional[str | List[str]] = None
    seed_tables_dir: Optional[str] = None
    seed_sources_dir: Optional[str] = None
    #: Additional run directories to fall back to when a citation's source id
    #: is not resolvable under this run's own ``sources_dir`` -- typically
    #: rows seeded from an earlier run's tables/graph via ``--graph-path`` /
    #: ``--seed-tables-dir`` whose ``fetched_papers/`` this run never fetched
    #: itself. Each entry is a run's output directory; text is read from
    #: ``<root>/fetched_papers/<source_id>.txt``. Strictly additive: a source
    #: id resolvable locally never consults these. Not searched or rebuilt --
    #: only read for source ids a row already cites.
    evidence_corpus_roots: tuple[str, ...] = ()
    seed_frontier_path: Optional[str] = None
    #: The page-scoped and strategy-scoped best-guess stages are structural parts
    #: of table filling. Both use deterministic derivations and LLM-supported
    #: inference, with every accepted guess anchored to durable evidence.
    #: There is deliberately NO task ceiling: every derivable slot gets a
    #: best-guess task, because a cap decides in advance which cells may be
    #: filled. (`best_guess_max_tasks` is deleted, not defaulted off.)
    best_guess_evidence_chars: int = 5000
    best_guess_llm_batch_size: int = 8
    best_guess_llm_timeout_sec: Optional[float] = None

    # Stopping
    task_goal_search_tasks: int = 0
    completion_probe_tasks: int = 4
    completion_probe_results: int = 5
    completion_probe_waves: int = 2
    target_deficit_max_evolutions: int = 1
    target_prompt_arms_per_evolution: int = 1
    target_queries_per_prompt_arm: int = 1

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

When the state contains `source_catalog`, `strategy_sources`, and
`strategy_source_nodes`, use `source_catalog` to distinguish sources accepted by
the current strategy from prior sources and to inspect their acquisition,
publication, event-time, and graph-reference metadata. `strategy_sources` and
`strategy_source_nodes` are the current strategy's source records and the graph
nodes they directly evidence. These variables are strategy context inside the
full accumulated graph, not a restriction on what GASL may traverse; compare
new with prior sources or follow other graph relations when the question calls
for it.
""".strip()


STRATEGY_SOURCE_NODES_VAR = "strategy_source_nodes"
STRATEGY_SOURCES_VAR = "strategy_sources"
SOURCE_CATALOG_VAR = "source_catalog"
TABLE_REQUIRED_COLUMNS: Dict[str, List[str]] = {}
TABLE_COMPLETENESS_COLUMNS: Dict[str, List[str]] = {}
PIPELINE_MODE_ANSWER = "answer"
PIPELINE_MODE_TABLE_FILL = "table_fill"


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

#: Topic on the ``SearchOutcome`` rows the completion probe emits. Deliberately
#: distinct from the topics existing consumers select, so the row remains
#: visible to cost accounting without entering search-memory or target joins.
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
    `reward.aggregate_cost` counts one error per record carrying a
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
    texts directly and have no `sources_dir` -- the export-hook test, the
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

    if getattr(owner, "sources_dir", None) is not None:
        records = getattr(owner, "_source_records_by_id", None)
        if callable(records):
            return sorted(records()), "accepted_sources_in_sources_dir"
    return sorted(observed_source_ids), "sources_observed_in_rows_no_sources_dir"


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
        if config.pipeline_mode == PIPELINE_MODE_TABLE_FILL:
            if config.answer_mode == "natural":
                config.answer_mode = "table"
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
        # Generic name in code; the on-disk directory keeps its historical
        # name because seeding contracts (`--seed-sources-dir`,
        # `--evidence-corpus-root`) resolve `<root>/fetched_papers/<id>.txt`
        # against runs that already exist.
        self.sources_dir = self.out / "fetched_papers"
        self.answers_dir = self.out / "answers"
        self.tables_dir = self.answers_dir / "tables"
        self.derived_dir = self.answers_dir / "derived"
        self.goals_dir = self.answers_dir / "goals"
        self.table_specs_dir = self.answers_dir / "table_specs"
        for d in (self.graphs_dir, self.sources_dir, self.answers_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.evidence_registry = EvidenceRegistry(
            self.answers_dir / "evidence_registry"
        )

        self.graph = nx.DiGraph()
        self.schema: Optional[DomainSchema] = None
        self.extractor = None
        self.seen_urls: set[str] = load_seen_urls(config.seed_sources_dir)
        self.queries_used: List[str] = []
        #: Source units pulled so far -- mirrors ``source_budget.spent``.
        self.units_pulled = 0
        self.strategy_records: List[Dict[str, Any]] = []
        self.table_exports: List[Dict[str, Any]] = []
        self.search_frontier = SearchFrontier()
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
        if config.pipeline_mode == PIPELINE_MODE_TABLE_FILL and config.task_goal_search_tasks <= 0:
            raise ValueError("table-fill goals require search tasks")
        if config.episode_unit_safety_cap <= 0:
            raise ValueError("episode_unit_safety_cap must be positive")
        if config.target_deficit_max_evolutions <= 0:
            raise ValueError("target_deficit_max_evolutions must be positive")
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
                "cannot be falsified; see table_schema_disclosure in the "
                "strategy Episode records."
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
            if config.pipeline_mode == PIPELINE_MODE_TABLE_FILL
            else None
        )
        self.goal_universe_estimate: Dict[str, Any] = {"status": "missing"}
        self.goal_discovery_sources: List[Dict[str, Any]] = []
        #: Tables the answer layer was asked to compile for the current strategy,
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
        #: Reward credit already paid, carried across strategy Episodes (Phase 3A).  A
        #: criterion is a datapoint once and a source is harvested once; without
        #: this the same yield is re-credited at every artifact write.
        self.reward_credit_ledger = CreditLedger()
        self.seed_best_guess_rows: List[Dict[str, Any]] = load_seed_best_guess_rows(
            config.seed_tables_dir,
        )
        self._bootstrap_sources: List[Dict[str, Any]] = []
        self._gasl_source_seed_nodes: List[Dict[str, Any]] = []
        self._gasl_strategy_sources: List[Dict[str, Any]] = []
        self._gasl_source_catalog: List[Dict[str, Any]] = []

        # -- control layer (Phase 1C) ----------------------------------- #
        # The ledger is append-only.  Every write goes through
        # ``_append_control_decision``; no other code path touches the list.
        self.control_policy = StaticTableFillPolicy()
        self.control_decisions: List[Dict[str, Any]] = list(
            load_seed_control_decisions(config.seed_tables_dir)
        )
        self.seeded_control_decision_count = len(self.control_decisions)
        self.criteria_snapshot: CriteriaSnapshot = empty_snapshot()
        self._strategy_ledger_mark = len(self.control_decisions)
        #: The previous scored strategy Episode's `after` snapshot, carried
        #: forward so the next strategy's `before` IS it rather than a fresh
        #: projection of some other row set. See `_write_reward_exports`.
        self._last_reward_after: Optional[CriteriaSnapshot] = None

        # -- cost accounting (Phase 1B) --------------------------------- #
        # One record per action, never a running total: summing is 3A's
        # business and its attribution rules decide which sums are legitimate.
        self.cost_records: List[Dict[str, Any]] = []
        #: The whole run's orphan baseline, taken once and never rebased, so the
        #: partition identity has both ends. `_strategy_orphan_baseline` is the
        #: one that moves.
        self._run_orphan_baseline = orphan_meter().snapshot().to_dict()
        #: Per-accepted-source field-scope evaluation outcome from the last
        #: grounding pass. Emitted on the strategy record so "examined and found
        #: nothing" and "never examined" are separable in the artifacts.
        self.last_field_provenance_ledger: Dict[str, Any] = {}
        #: Per-source extraction outcome, keyed by source id. Written when text
        #: enters the extractor, so
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
        self.source_budget = SourceBudget(limit=int(config.max_source_units))
        self.provider_health = ProviderHealth()
        self.run_termination = RunTermination()
        self.acquisition = AcquisitionController(
            crediter=self.crediter,
            budget=self.source_budget,
            health=self.provider_health,
            termination=self.run_termination,
        )
        self._active_strategy_episode_id = ""
        self._active_strategy_episode_path: tuple[tuple[str, str], ...] = ()
        #: Every hook failure, as a typed class. A hook may not raise -- the
        #: driver catches nothing around `on_unit` -- so its failure is recorded
        #: here and on the strategy record rather than unwinding the record tree.
        self.hook_failures: List[Dict[str, Any]] = []
        self._seen_target_attempts: set[tuple[str, str]] = set()
        self._target_evolution_counts: Counter[str] = Counter()
        #: Rebased per completed strategy, so a per-strategy residual covers the
        #: interval since the previous one rather than the whole run to date.
        self._strategy_orphan_baseline = orphan_meter().snapshot().to_dict()
        self._harvester = SearchHarvester(
            scrape_fn=self._scrape_fn if config.scrape_search_results else None,
            sources_dir=self.sources_dir,
            seen_urls=self.seen_urls,
            min_source_length=config.min_source_length,
            max_source_length=config.max_source_length,
            max_extraction_chars_per_source=config.max_extraction_chars_per_source,
        )
        self.provider_binding = acq.ProviderBinding(
            controller=self.acquisition,
            run_key=self.out.name,
            episode_unit_safety_cap=config.episode_unit_safety_cap,
            strategy_catalog=frozenset(QUERY_OPERATORS),
            frontier=self.search_frontier,
            search_fn=self._search_fn,
            harvester=self._harvester,
            search_provider_batch=self.search_provider_batch,
            answers_dir=self.answers_dir,
            open_cost_scope=lambda kind, observation_id, episode_id, episode_path: (
                self._cost_scope(
                    kind,
                    observation_id=observation_id,
                    episode_id=episode_id,
                    episode_path=episode_path,
                )
            ),
            open_prompt_scope=lambda episode_id, episode_path: prompt_scope(
                self.out / "prompts" / episode_id,
                episode_id=episode_id,
                episode_path=episode_path,
            ),
            sample_strategies=self._sample_strategies,
            post_strategy=self._run_post_strategy_body,
            get_extractor=lambda: self.extractor,
            extract_text=extract_from_text,
            chunk_spans=chunk_spans,
            page_best_guess_fn=page_best_guess,
            infer_best_guess_candidates=self._infer_best_guess_candidates,
            evidence_registry=self.evidence_registry,
            get_graph=lambda: self.graph,
            set_graph=lambda graph: setattr(self, "graph", graph),
            enrich_graph_fn=enrich_graph,
            similarity_threshold=config.similarity_threshold,
            auto_merge_entities=config.auto_merge_entities,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            extraction_concurrency=config.extraction_concurrency,
            extraction_timeout_sec=config.extraction_timeout_sec,
            best_guess_evidence_chars=config.best_guess_evidence_chars,
            best_guess_llm_batch_size=config.best_guess_llm_batch_size,
            best_guess_llm_timeout_sec=config.best_guess_llm_timeout_sec,
            record_goal_discovery_sources=self._record_goal_discovery_sources,
            refresh_search_memory=self._refresh_search_memory,
            record_prompt_attempt_counts=self._record_prompt_attempt_counts,
            append_control_decision=self._append_control_decision,
            record_hook_failure=self._record_hook_failure,
            set_active_strategy=self._set_active_strategy,
            set_units_pulled=lambda value: setattr(self, "units_pulled", value),
            set_search_provider_error=lambda value: setattr(
                self, "search_provider_error", value
            ),
            goal_states=lambda: self.goal_states,
            exported_rows=lambda: self.seed_tables.rows_by_name,
            source_ingestion_ledger=self.source_ingestion_ledger,
            last_search_outcomes=self.last_search_outcomes,
            search_outcomes=self.search_outcomes,
            queries_used=self.queries_used,
            orphan_snapshot=lambda: orphan_meter().snapshot().to_dict(),
            hook_failures=lambda: self.hook_failures,
            criteria_projection_version=CRITERIA_PROJECTION_VERSION,
            missing_tokens=criteria_missing_tokens,
        )
        self._run_episode_id = self.provider_binding.run_episode_id

        # -- path-selection gate (Phase 2B) ----------------------------- #
        # Records on every run; demotes nothing unless configured to.  2A's
        # experiment failed on both of its registered routes, so a shipped
        # default that deleted rows on ``path_score`` would be asserting more
        # than the measurement supports.  Set this to demote.
        self.path_gate_settings = PathGateSettings()

    # ------------------------------------------------------------------ #
    # Cost accounting (Phase 1B)
    # ------------------------------------------------------------------ #
    def _set_active_strategy(
        self,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
    ) -> None:
        """Receive the binding's active strategy scope for downstream work."""

        self._active_strategy_episode_id = str(episode_id)
        self._active_strategy_episode_path = tuple(episode_path)

    def _record_cost(self, record: CostRecord) -> None:
        """Append one action's cost.  Never sums, never branches."""
        if not self.cost_accounting_enabled:
            return
        payload = record.to_dict()
        self.cost_records.append(payload)
        try:
            self.sources_dir.mkdir(parents=True, exist_ok=True)
            with (self.sources_dir / "cost_records.jsonl").open(
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
        episode_id: str = "",
        episode_path: tuple[tuple[str, str], ...] = (),
    ):
        """Open a meter for one action, or an inert placeholder when off."""
        if not self.cost_accounting_enabled:
            return nullcontext(None)
        return cost_scope(
            kind,
            observation_id=observation_id,
            episode_id=(
                episode_id
                or self._active_strategy_episode_id
                or self._run_episode_id
            ),
            episode_path=(episode_path or self._active_strategy_episode_path),
            sink=self._record_cost,
        )

    def _open_prompt_log(
        self,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
    ) -> None:
        """Start recording prompts owned by one strategy Episode."""

        self._close_prompt_log()
        self._prompt_log_token = prompt_log_open(
            self.out / "prompts" / episode_id,
            episode_id=episode_id,
            episode_path=episode_path,
        )

    def _close_prompt_log(self) -> None:
        token = getattr(self, "_prompt_log_token", None)
        if token is not None:
            prompt_log_close(token)
            self._prompt_log_token = None

    def _episode_cost_records(self, episode_id: str) -> List[Dict[str, Any]]:
        """One Episode's cost records. A filter, not a sum."""
        return [
            record
            for record in self.cost_records
            if str(record.get("episode_id") or "") == episode_id
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
    # sticky `error_class` that `reward.aggregate_cost` counts one error
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
        """The completion probe's provider call and observable outcome row.

        This provider caller intentionally remains outside the acquisition
        composition: it writes no source and mints no incidence. Its fixed
        waves, query count, and result count are restored unchanged here; the
        Phase 1 cleanup only replaces round attribution with Episode identity.
        """

        episode_id = str(getattr(self, "_probe_episode_id", "") or "")
        episode_path = tuple(getattr(self, "_probe_episode_path", ()) or ())
        task = SearchTask(
            query=query,
            topic=PROBE_SEARCH_TOPIC,
            expansion_op="completion_probe",
            episode_id=episode_id,
            producer_class="completion_probe",
            yields_sources=False,
        )
        outcome = SearchOutcome.for_task(task)
        outcome.provider_batch = self._search_batch_metadata(max_results)
        failure: Optional[BaseException] = None
        results: List[Dict[str, Any]] = []
        with self._cost_scope(
            ObservationKind.PROBE_SEARCH.value,
            observation_id=task.id,
            episode_id=episode_id,
            episode_path=episode_path,
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

    def _probe_search_results(
        self,
        query: str,
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """The probe's provider call, exactly as it was before remediation."""

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
        """Put the probe's outcome where every other search outcome lives."""

        if not self.cost_accounting_enabled:
            return
        if meter is not None:
            outcome.cost = meter.snapshot().to_dict()
        record = outcome.to_dict()
        self.search_outcomes.append(record)
        try:
            self.sources_dir.mkdir(parents=True, exist_ok=True)
            with (self.sources_dir / "search_outcomes.jsonl").open(
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
        if self._gasl_source_catalog:
            catalog_contract = make_contract(
                payload_kind="rows",
                data=self._gasl_source_catalog,
                scope="accumulated_accepted_source_catalog",
                usable_by=["PROCESS", "SHOW", "SELECT"],
                grain_type="source",
                grain_keys=["source_id"],
                multiplicity_preserved=False,
                notes=[
                    "One row per known source. acquisition_cohort distinguishes "
                    "the current strategy from prior strategies; it does not "
                    "describe publication recency.",
                    "Publication and event-time fields remain inside "
                    "source_metadata. Graph-only sources explicitly report "
                    "metadata_available=false.",
                ],
            )
            executor.state_manager.store_variable_data(
                SOURCE_CATALOG_VAR,
                list(self._gasl_source_catalog),
                store_in_state=True,
                store_in_context=True,
                description=(
                    "Accumulated source catalog for comparing current-strategy "
                    "sources with prior sources when choosing graph operations."
                ),
                contract=catalog_contract,
            )

        if self._gasl_strategy_sources:
            source_contract = make_contract(
                payload_kind="rows",
                data=self._gasl_strategy_sources,
                scope="current_strategy_accepted_sources",
                usable_by=["PROCESS", "SHOW", "SELECT"],
                grain_type="source",
                grain_keys=["source_id"],
                multiplicity_preserved=True,
                notes=[
                    "Complete metadata for sources accepted by the current "
                    "strategy. Publication/event dates remain source fields; "
                    "accepted_at and accepted_episode_id describe ingestion."
                ],
            )
            executor.state_manager.store_variable_data(
                STRATEGY_SOURCES_VAR,
                list(self._gasl_strategy_sources),
                store_in_state=True,
                store_in_context=True,
                description=(
                    "Sources accepted by the current strategy, with provenance "
                    "and temporal metadata for graph-search strategy selection."
                ),
                contract=source_contract,
            )

        if self._gasl_source_seed_nodes:
            contract = make_contract(
                payload_kind="nodes",
                data=self._gasl_source_seed_nodes,
                label_field="data.entity_name",
                scope="current_strategy_source_evidenced_nodes",
                usable_by=["PROCESS", "GRAPHWALK", "SHOW", "SELECT"],
                grain_type="node",
                grain_keys=["id"],
                multiplicity_preserved=True,
                notes=[
                    "All graph nodes directly evidenced by sources accepted in "
                    "the current strategy. They are starting points, not a graph "
                    "scope; the full accumulated graph remains searchable."
                ],
            )
            executor.state_manager.store_variable_data(
                STRATEGY_SOURCE_NODES_VAR,
                list(self._gasl_source_seed_nodes),
                store_in_state=True,
                store_in_context=True,
                description=(
                    "Current-strategy source-evidenced graph nodes. Use them as "
                    "one possible starting strategy within the full graph."
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

    def _source_budget_available(self) -> bool:
        return not self.source_budget.exhausted

    def _search_budget_available(self) -> bool:
        return self._source_budget_available() and self.search_frontier.pending_count > 0

    def _ensure_search_ready(self) -> None:
        if not self._uses_default_search or not self._search_budget_available():
            return
        if self.config.firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY"):
            return
        raise RuntimeError(
            "No Firecrawl API key. Set --firecrawl-api-key or FIRECRAWL_API_KEY."
        )

    # ------------------------------------------------------------------ #
    # Fetching
    # ------------------------------------------------------------------ #
    # ================================================================== #
    # The composition facade (Phase 4E-c)
    #
    # `acquisition.ProviderBinding` declares the provider Episodes and owns
    # their hooks, callbacks, leaf work, and records. This facade supplies the
    # model string callback and its run view; `run()` makes the single
    # `acquisition.run(...)` invocation, then downstream post-strategy work
    # remains below.
    # ================================================================== #


    async def _sample_strategies(
        self,
        tried: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        """The switch edge's model call. Strings and one number, nothing else."""

        run_path = ((RUN_GRAIN.name, self.out.name),)
        with prompt_scope(
            self.out / "prompts" / self._run_episode_id,
            episode_id=self._run_episode_id,
            episode_path=run_path,
        ):
            return await strategy.propose_distant_strategy(
                self.llm,
                self.config.question,
                run_view=self._proposer_run_view(),
                catalog=QUERY_OPERATORS,
                tried=list(tried),
                # String breadth for one proposer call -- its own named parameter,
                # split from `task_goal_search_tasks`, which serves the deficit
                # planner. One name per concept; neither is a stop rule.
                n=self.config.strategy_candidates_per_proposal,
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
            "accepted_source_terms": self.provider_binding.accepted_source_terms(),
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


    @staticmethod
    def _artifact_stem(artifact_label: int | str) -> str:
        """Filesystem-safe stem for one export pass's artifacts.

        The label is Episode identity (a strategy ``episode_id``) or a named
        non-episode pass (``seed``, ``bootstrap``, ``bootstrap_deficit``,
        ``predeficit_<label>``). Never a round number, and never parsed back:
        artifacts join by the ``episode_id`` field on their records, not by
        filename arithmetic.
        """

        text = str(artifact_label).strip() or "unlabeled"
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)

    def _remaining_source_budget(self) -> int:
        """Source units the run may still pull; ``-1`` states unbounded.

        `control.DecisionContext` spells "no declared unit bound" as ``-1``
        deliberately -- unbounded is stated, never spelled as zero.
        """

        limit = int(self.source_budget.limit)
        if limit <= 0:
            return -1
        return max(0, limit - int(self.source_budget.spent))

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


    def _empty_deliverable_rows(self) -> Dict[str, List[Dict[str, Any]]]:
        if not self.table_spec.is_empty:
            return self.table_spec.empty_rows_by_table()
        return {table_name: [] for table_name in self._table_target_names()}

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
            paper_count=self.units_pulled,
            scope_in=[f"{e['name']}: {e['description']}" for e in entity_types],
            scope_out=[],
            notes="Built by question_pipeline iterative loop.",
        )
        save_graph_metadata(self.graphs_dir, metadata)
        return metadata

    async def _run_gasl(
        self,
        episode_id: str,
        episode_path: tuple[tuple[str, str], ...],
        metadata: Dict[str, Any],
        *,
        graph: Optional[nx.DiGraph] = None,
    ) -> Dict[str, Any]:
        state_file = str(self.answers_dir / f"{episode_id}_gasl_state.json")
        # GASL is synchronous and chatty; run it off the event loop.
        # `asyncio.to_thread` copies the context, so the meter opened here is
        # the one GASL's own `llm.call` reaches inside that thread.
        with self._cost_scope(
            ObservationKind.GASL.value,
            observation_id=f"{episode_id}_gasl",
            episode_id=episode_id,
            episode_path=episode_path,
        ):
            return await asyncio.to_thread(
                self._gasl_runner,
                graph if graph is not None else self.graph,
                metadata,
                state_file,
            )

    # ------------------------------------------------------------------ #
    # Strategy context for one strategy's traversal
    #
    # The batched ingestion path is gone. `_ingest_papers` looped over a wave's
    # papers after the fact, and `_acquisition_item_sink` was the callback the
    # harvester consulted between pages -- both of them the phase-batched shape
    # this phase removes. Extraction now happens inline in the leaf's `extract`,
    # once per page, so the per-search verdict exists while that search's
    # provider-returned buffered results are still unprocessed and have not
    # entered extraction or best-guess work; graph enrichment
    # rides along in the page hook as the decoupled side effect the charter requires.
    # ------------------------------------------------------------------ #
    def _gasl_source_seed_nodes_for_strategy(
        self,
        strategy_sources: List[Dict[str, Any]],
        *,
        graph: nx.DiGraph,
    ) -> List[Dict[str, Any]]:
        source_ids = {
            str(record.get("id") or "").strip()
            for record in strategy_sources
            if str(record.get("id") or "").strip()
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
            )
        ]

    @staticmethod
    def _gasl_strategy_source_rows(
        strategy_sources: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Source-level strategy context, preserving all available metadata.

        A transform over the strategy's accepted source records; the instance
        attribute ``_gasl_strategy_sources`` holds its output while GASL runs.
        """

        return [
            {
                "source_id": str(record.get("id") or ""),
                "title": str(record.get("title") or ""),
                "url": str(record.get("url") or ""),
                "accepted_at": record.get("accepted_at"),
                "accepted_episode_id": record.get("search_episode_id"),
                "source_query": str(record.get("source_query") or ""),
                "source_metadata": dict(record.get("source_metadata") or {}),
            }
            for record in strategy_sources
            if str(record.get("id") or "")
        ]

    def _gasl_source_catalog_for_strategy(
        self,
        strategy_sources: Sequence[Mapping[str, Any]],
        *,
        graph: nx.DiGraph,
    ) -> List[Dict[str, Any]]:
        """All known sources, with current-vs-prior acquisition explicit."""

        current_by_id = {
            str(record.get("id") or "").strip(): dict(record)
            for record in strategy_sources
            if str(record.get("id") or "").strip()
        }
        records = self._source_records_by_id()
        records.update(current_by_id)

        graph_reference_counts: Counter[str] = Counter()
        for _, data in graph.nodes(data=True):
            graph_reference_counts.update(set(get_source_refs(dict(data))))
        edge_records = (
            graph.edges(keys=True, data=True)
            if graph.is_multigraph()
            else (
                (source, target, None, data)
                for source, target, data in graph.edges(data=True)
            )
        )
        for _, _, _, data in edge_records:
            graph_reference_counts.update(set(get_source_refs(dict(data))))

        source_ids = set(records) | set(graph_reference_counts)
        rows: List[Dict[str, Any]] = []
        for source_id in sorted(source_ids):
            record = records.get(source_id, {})
            metadata = record.get("source_metadata")
            if not isinstance(metadata, Mapping):
                metadata = record.get("metadata")
            if not isinstance(metadata, Mapping):
                metadata = {}
            rows.append(
                {
                    "source_id": source_id,
                    "title": str(record.get("title") or ""),
                    "url": str(record.get("url") or ""),
                    "acquisition_cohort": (
                        "current_strategy"
                        if source_id in current_by_id
                        else "prior_strategy"
                    ),
                    "accepted_at": record.get("accepted_at"),
                    "accepted_episode_id": record.get("search_episode_id"),
                    "source_query": str(record.get("source_query") or ""),
                    "source_metadata": dict(metadata),
                    "metadata_available": bool(record),
                    "known_to_graph": source_id in graph_reference_counts,
                    "graph_reference_count": int(
                        graph_reference_counts.get(source_id, 0)
                    ),
                }
            )
        return rows

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

    def _iter_graph_edges(self):
        """Yield graph edges uniformly for directed and multigraph inputs."""

        if self.graph.is_multigraph():
            yield from self.graph.edges(keys=True, data=True)
            return
        for src, dst, data in self.graph.edges(data=True):
            yield src, dst, None, data

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
        # the previous pass's ledger in place, so a grounding pass that
        # grounded nothing reported the prior pass's coverage as its own -- a
        # stale number is worse than a missing one, because it looks like a
        # measurement of this pass. A pass that cannot compute coverage must
        # say so and be excluded, never assumed to have passed.
        self.last_field_provenance_ledger = {
            "computed": False,
            "reason": "grounding did not run this pass",
            "state_counts": {},
            "denominator": "",
            "accepted_source_count": 0,
            "sources": [],
        }
        if not rows_by_table:
            self.last_field_provenance_ledger["reason"] = (
                "no tables were exported this pass, so there were no rows to "
                "ground and coverage is not measurable"
            )
            return rows_by_table

        # Rows seeded from an earlier run (via --graph-path / --seed-tables-dir)
        # can cite chunk ids this run's own sources_dir never fetched. Collect
        # every chunk id any row claims up front so _chunk_texts_by_id can
        # resolve the ones sources_dir misses from evidence_corpus_roots before
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
                "derived this pass, so no row can be promoted to "
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
                            "reason": "no chunk text was resolvable this pass",
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
        # and any future caller that owns its own corpus) has no sources_dir to
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
        belong to any source in this run's own ``sources_dir`` -- typically
        citations on rows seeded from an earlier run. For each such id whose
        source is not already covered by the local corpus, this falls back to
        ``self.config.evidence_corpus_roots`` in order. A source id resolvable
        locally never consults a corpus root; passing no ids, or configuring
        no roots, reproduces the original local-only lookup exactly.
        """

        # INVALIDATION. The cache is keyed on the sources_dir source-id set and
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
        # not depend on every writer of sources_dir remembering to signal.
        # `sources_dir` is the corpus the key is computed from, so its absence is
        # the precondition for keying at all -- a caller that supplies
        # `_chunk_text_cache` directly and has no sources_dir owns its own corpus
        # and has nothing to go stale against. That case must still be loud when
        # it supplies neither, because an empty cache built from no corpus
        # grounds nothing and would look exactly like a corpus with no matches.
        sources_dir = getattr(self, "sources_dir", None)
        cached = getattr(self, "_chunk_text_cache", None)
        if sources_dir is None:
            if cached is None:
                raise AttributeError(
                    "_chunk_texts_by_id needs either a sources_dir to rebuild "
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
            self._chunk_text_cache_invalidation = "caller_supplied_no_sources_dir"
        else:
            current_source_ids = frozenset(self._source_records_by_id())
            chunk_params = (self.config.chunk_size, self.config.chunk_overlap)
            self._chunk_text_cache_invalidation = "keyed_on_sources_dir_source_ids"

        if cached is None or (
            sources_dir is not None
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

        Only consulted for source ids this run's own ``sources_dir`` could not
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
        self, artifact_label: int | str, gasl_result: Dict[str, Any]
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
        current_rows = self._apply_path_gate(artifact_label, current_rows)
        merged_rows = merge_rows_by_table(
            self.seed_tables.rows_by_name,
            current_rows,
        )
        exports = await self._write_table_exports(
            artifact_label,
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
                "episode_id": self._active_strategy_episode_id,
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
            # No task ceiling, deliberately: `best_guess_max_tasks` is deleted,
            # not defaulted off -- a cap here decides in advance which cells
            # may be filled, cutting a priority-sorted list by position.
            "max_tasks": None,
        }
        with self._cost_scope(
            ObservationKind.BEST_GUESS.value,
            observation_id=f"{self._artifact_stem(artifact_label)}_best_guess",
        ):
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
                "episode_id": self._active_strategy_episode_id,
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
                    "episode_id": self._active_strategy_episode_id,
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
        rows = numeric_candidates_from_tables(
            rows_by_name,
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
            "episode_id": self._active_strategy_episode_id,
            "variable": "numeric_candidates",
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
        episode_id = self._active_strategy_episode_id
        if not episode_id:
            # A non-episode export pass (the "seed" / "bootstrap" re-export of
            # carried state) has no strategy Episode to attribute cost or
            # first-harvest credit to -- "Episode level is the finest
            # granularity that is honest here" per `reward.py`'s own
            # docstring, and a bootstrap re-export of the seed state is not an
            # acquisition. Skip scoring rather than crediting against an
            # undefined Episode; the first completed strategy scores from here
            # forward through the normal path.
            return []
        source_records = self._source_records_by_id()
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
        # This runs MID-strategy, so `self.cost_records` is a prefix that keeps
        # growing after scoring. A frozen snapshot is taken, the records in
        # scope are selected by the strategy Episode's own `episode_id` -- the
        # selection `reward.aggregate_cost` documents as the caller's business
        # -- and the ids inside the cut are emitted, so the cut is readable
        # from the export rather than inferred from it.
        cost_snapshot = [
            record for record in self.cost_records if isinstance(record, Mapping)
        ]
        matched_cost_records = [
            record
            for record in cost_snapshot
            if str(record.get("episode_id") or "") == episode_id
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
                evidence_registry=self.evidence_registry,
            )
        after = project_rows(
            current_rows_by_name,
            self.table_spec,
            accepted_source_ids=accepted_source_ids,
            best_guess_resolutions=resolutions,
            deliverable_tables=self._deliverable_tables(current_rows_by_name),
            evidence_registry=self.evidence_registry,
        )
        reward = score_criterion_yield(
            before,
            after,
            episode_id=episode_id,
            accepted_source_ids=accepted_source_ids,
            ledger=self.reward_credit_ledger,
            cost_records=matched_cost_records,
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
            evidence_registry=self.evidence_registry,
        )
        report["before_snapshot_source"] = (
            "previous_pass_after" if chained else "projection_of_previous_rows"
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
            "episode_id": episode_id,
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
            "cost_scored_mid_strategy": True,
            # A pass that genuinely had no cost records says so, rather than
            # presenting a zero sum that reads the same as free work.
            "cost_absent_reason": (
                ""
                if matched_cost_records
                else (
                    f"no cost record carried episode_id={episode_id} at "
                    f"scoring time ({len(cost_snapshot)} record(s) visible); "
                    "the cost block is a sum over nothing, not a measurement "
                    "that this strategy was free"
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
            max_tasks=self.config.table_gap_search_tasks,
        )
        gap_candidates: List[ActionCandidate] = []
        if self.control_ledger_enabled:
            for task in tasks:
                candidate = SearchCandidate.create(
                    surface=ControlSurface.CATALOG_SEARCH,
                    query=task.query,
                    episode_id=self._active_strategy_episode_id,
                    origin=ActionOrigin.DERIVED,
                )
                gap_candidates.append(candidate)
                self._stamp_control_action(task, candidate)
        self._stamp_control_decision(
            tasks,
            self._record_policy_decision(
                ControlSurface.CATALOG_SEARCH,
                gap_candidates,
                max_actions=self.config.table_gap_search_tasks,
            ),
        )
        accepted = self.search_frontier.enqueue(tasks)
        if accepted:
            print(f"  Queued {len(accepted)} table-gap searches")
        return [task.to_dict() for task in accepted]

    def _record_goal_discovery_sources(
        self, source_records: List[Dict[str, Any]]
    ) -> None:
        for record in source_records:
            if record.get("search_topic") != "goal_catalog":
                continue
            source_id = str(record.get("id") or "")
            if not source_id or source_id in self._seen_goal_discovery_source_ids:
                continue
            self._seen_goal_discovery_source_ids.add(source_id)
            self.goal_discovery_sources.append(
                {
                    "id": source_id,
                    "title": record.get("title", ""),
                    "url": record.get("url", ""),
                    "source_query": record.get("source_query", ""),
                    "text": str(record.get("text") or "")[
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
            json_path = self.sources_dir / f"{source_id}.json"
            text_path = self.sources_dir / f"{source_id}.txt"
            if not json_path.exists():
                json_path.write_text(
                    json.dumps(sidecar, indent=2, default=str),
                    encoding="utf-8",
                )
            if not text_path.exists():
                text_path.write_text(text, encoding="utf-8")

        if jsonl_records:
            seed_index = self.sources_dir / "seed_sources.jsonl"
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

        path = self.sources_dir / "seed_search_outcomes.jsonl"
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
            episode_id=str(record.get("search_episode_id") or ""),
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
                    "episode_id": task.episode_id,
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
                    episode_id=str(record.get("episode_id") or ""),
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
                episode_id=str(outcome.get("episode_id") or ""),
            ),
        }

    async def _estimate_task_goal_universe(
        self,
        artifact_label: int | str,
        episode_id: str,
        table_rows: Dict[str, List[Dict[str, Any]]],
        gaps: List[str],
    ) -> Dict[str, Any]:
        """Run the restored fixed-wave completion probe and persist its state.

        The probe mechanics and configured bounds are unchanged from the
        pre-remediation path. Phase 1 changes only their attribution: the
        issuing strategy Episode replaces the deleted round stamp.
        """

        if self.goal_tracker is None:
            return self.goal_universe_estimate

        goal_context = self.goal_tracker.prompt_context(
            table_rows,
            gaps,
            self.goal_universe_estimate,
            self.completion_state,
        )
        previous_probe_episode = getattr(self, "_probe_episode_id", "")
        previous_probe_path = getattr(self, "_probe_episode_path", ())
        self._probe_episode_id = str(episode_id or artifact_label)
        self._probe_episode_path = tuple(self._active_strategy_episode_path)
        try:
            result = await estimate_count_expectations(
                self.llm,
                self.config.question,
                goal_context=goal_context,
                completion_state=scope_probe_context(self.completion_state),
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
            self._probe_episode_id = previous_probe_episode
            self._probe_episode_path = previous_probe_path

        probes: List[Any] = []
        for probe in result.get("search_space_probes") or []:
            if isinstance(probe, Mapping):
                probes.append({**probe, "episode_id": str(episode_id or "")})
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
        (self.goals_dir / f"{artifact_stem}_universe_estimate.json").write_text(
            json.dumps(self.goal_universe_estimate, indent=2, default=str),
            encoding="utf-8",
        )
        (self.goals_dir / f"{artifact_stem}_completion_critique.json").write_text(
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
        if not self._source_budget_available():
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
            table_rows,
            deficits,
        )

    async def _enqueue_target_deficit_tasks(
        self,
        table_rows: Dict[str, List[Dict[str, Any]]],
        deficits: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not deficits:
            return []

        attempt_contexts = self._target_attempt_contexts(deficits)
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
            # THIS IS ONE SHARED PLANNER CALL, not a strategy-scoped
            # one: `target_deficit_queries` runs once over every open deficit,
            # so a proposal's seeds are shared context for every arm of that
            # call, including arms of families the proposal did not name. That
            # does not corrupt a contrast -- the seeds are shared within the
            # call either way, so they cannot differentially bias one sibling
            # against another -- but a reader is entitled to know which call
            # carried them, so it is stated here.
            seed_queries=self.provider_binding.current_strategy_seed_queries(),
        )
        self._persist_deficit_windows(
            self._active_strategy_episode_id or "bootstrap", window_report
        )
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
                    fallback_candidates,
                    max_actions=len(fallback_candidates),
                ),
            )
            accepted.extend(self.search_frontier.enqueue(fallback_tasks))
        if accepted:
            print(f"  Queued {len(accepted)} target-deficit searches")
        return [task.to_dict() for task in accepted]

    def _target_attempt_contexts(
        self,
        deficits: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        contexts: Dict[str, Dict[str, Any]] = {}
        for target in deficits:
            deficit_id = str(target.get("id") or "")
            if not deficit_id:
                continue
            evolution_index = self._next_target_evolution_index(target)
            strategy_attempt_id = self._strategy_attempt_id(
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
        target: Mapping[str, Any],
        evolution_index: int,
    ) -> str:
        """Content identity of one (target, evolution) attempt.

        No pass ordinal participates: `evolution_index` continues from the
        target's own recorded history, so the pair is unique run-wide without
        any global counter.
        """

        payload = {
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

    def _target_deficit_search_task(
        self,
        *,
        query: str,
        target: Dict[str, Any],
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
            episode_id=self._active_strategy_episode_id,
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
        if self.search_provider_error or not self._source_budget_available():
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
                < self.config.target_deficit_max_evolutions
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
        accepted = await self._enqueue_target_deficit_tasks({}, deficits)
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
                    int(attempt.get("sequence") or -1)
                    if str(attempt.get("sequence") or "").isdigit()
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
        """Choose the next mutation family from nested arm contrast."""
        return route_next_family(enriched_target)

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

    def _reward_datapoints_for_episode(
        self,
        episode_id: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """This strategy Episode's `CreditedDatapoint`s, or `None` if unscored.

        `None` -- not `[]` -- means "3A has not scored this Episode", so a
        consumer can distinguish "no yield" from "yield unknown". Guarded by
        the report's own `episode_id` rather than assumed fresh:
        `last_reward_report` is only overwritten inside
        `_write_reward_exports`, which the "no new sources" branch and the
        GASL branch both call before this method runs, but an
        `answer_mode != "table"` run never calls it at all and must not read
        a stale report from a different Episode as if it were this one's.
        """
        report = self.last_reward_report or {}
        if not report or not episode_id:
            return None
        if str(report.get("episode_id") or "") != str(episode_id):
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
        reward_datapoints = self._reward_datapoints_for_episode(
            self._active_strategy_episode_id
        )
        metadata_updates: Dict[str, Dict[str, Any]] = {}
        for outcome in self.last_search_outcomes:
            metadata = outcome.metadata
            if outcome.topic != "target_deficit":
                continue
            if not isinstance(metadata, dict):
                continue
            update = {
                "search_yield": self._search_yield_summary(outcome.to_dict()),
                "post_episode_table_row_hits": sum(
                    table_source_hits[source_id]
                    for source_id in outcome.accepted_source_ids
                ),
                "post_episode_best_guess_hits": sum(
                    best_guess_source_hits[source_id]
                    for source_id in outcome.accepted_source_ids
                ),
                # Phase 3B: real semantic yield, joined by ID from 3A's own
                # `RewardReport.datapoints` -- never re-derived. `None` when
                # this strategy Episode has not been scored (or is not a `table`-mode
                # run), which `search_memory` reads as "not measured yet",
                # not as zero.
                "post_episode_credited_criterion_ids": self._credited_criterion_ids(
                    reward_datapoints,
                    outcome.accepted_source_ids,
                ),
                "post_episode_credited_datapoint_kinds": self._credited_datapoint_kinds(
                    reward_datapoints,
                    outcome.accepted_source_ids,
                ),
                # The cost penalty's own join: 1B's per-action records that
                # this search task opened or nested under it.
                "post_episode_cost_records": self._cost_records_for_task(
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
                        "post_episode_observed_count": observed_count,
                        "post_episode_observed_delta": observed_delta,
                        # Which endpoint was missing, so a None delta is
                        # diagnosable rather than merely absent.
                        "post_episode_observed_delta_unavailable_reason": (
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
                        "post_episode_graph_node_delta": (
                            self.graph.number_of_nodes() - baseline_nodes
                        ),
                        "post_episode_graph_edge_delta": (
                            self.graph.number_of_edges() - baseline_edges
                        ),
                        "post_episode_deficit_count": target.get("deficit_count"),
                        "post_episode_target_status": target.get("status"),
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
        path = self.sources_dir / "search_outcomes.jsonl"
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
        for path in sorted(self.sources_dir.glob("*.json")):
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
            text_path = self.sources_dir / f"{source_id}.txt"
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
        artifact_label: int | str,
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
            / f"{self._artifact_stem(artifact_label)}_deficit_windows.json"
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
            units_pulled=self.units_pulled,
            unit_budget=int(self.config.max_source_units),
            unit_budget_available=self._source_budget_available(),
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
            if previous.get("label") != artifact_label
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
        self._record_task_goal(
            "bootstrap",
            seed_exports,
            gap_search_tasks=[],
            goal_search_tasks=[],
        )

        return seed_exports

    def _drain_bootstrap_sources(self) -> List[Dict[str, Any]]:
        records = self._bootstrap_sources
        self._bootstrap_sources = []
        return records

    async def _enqueue_deficit_searches(
        self,
        artifact_label: int | str,
        table_exports: List[Dict[str, Any]],
        goal_state: Optional[FillGoalState],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if goal_state is None or goal_state.fulfilled:
            return [], []

        table_rows = self._table_rows_by_variable(table_exports)
        table_gap_tasks = self._enqueue_table_gap_searches(table_exports)
        target_deficit_tasks = await self._enqueue_target_deficit_searches(
            table_rows,
            goal_state,
        )
        return table_gap_tasks, target_deficit_tasks

    async def _expand_unfulfilled_table_goal(
        self,
        artifact_label: int | str,
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
            "label": artifact_label,
            "episode_id": self._active_strategy_episode_id,
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
        if not self._source_budget_available():
            expansion["reason"] = "source_budget_exhausted"
            return gap_search_tasks, goal_search_tasks, goal_state, expansion

        expansion["attempted"] = True
        table_gap_tasks, target_deficit_tasks = await self._enqueue_deficit_searches(
            artifact_label,
            table_exports,
            goal_state,
        )
        gap_search_tasks.extend(table_gap_tasks)
        goal_search_tasks.extend(target_deficit_tasks)
        goal_state = self._record_task_goal(
            artifact_label,
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

    def _enqueue_seed_frontier_searches(self) -> List[Dict[str, Any]]:
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
            print(f"  Requeued {len(accepted)} seed frontier searches")
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
        sequences phases. The post-strategy work is `_run_post_strategy_body`,
        called by the run grain's hook once per completed strategy, in its
        existing order and unreordered.
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
            # A named schema is already the extractor contract.  Resolve it
            # before the first acquisition strategy so those pages can be
            # gated, extracted, and credited.  Only schema synthesis must wait
            # for probe pages; delaying an explicitly named schema marked every
            # initial page `no_extractor` and discarded its possible evidence.
            if cfg.schema_name:
                await self._resolve_schema([])
            # The seed search is no longer a phase before the loop: it becomes
            # the run episode's FIRST STRATEGY, family `llm_initial`. Its pages
            # supply schema-synthesis evidence only when no schema was named.
            # In that case they are fetched before an extractor exists and are
            # crediting-disabled under the fate table's `no_extractor` row; the
            # strategy hook then resolves the synthesized schema.  With a named
            # schema, the extractor now exists before this strategy opens.
            print("Seeding search from the question...")
            schema_hint = cfg.schema_name or ""
            run_path = ((RUN_GRAIN.name, self.out.name),)
            with prompt_scope(
                self.out / "prompts" / self._run_episode_id,
                episode_id=self._run_episode_id,
                episode_path=run_path,
            ):
                with self._cost_scope(
                    ObservationKind.STRATEGY_PROPOSAL.value,
                    observation_id=f"{self.out.name}#seed",
                    episode_id=self._run_episode_id,
                    episode_path=run_path,
                ):
                    queries = await strategy.initial_queries(
                        self.llm,
                        cfg.question,
                        n=cfg.initial_seed_queries,
                        schema_hint=schema_hint,
                    )
            print(f"  Initial queries: {queries}")
            self.search_frontier.enqueue_queries(
                queries,
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
            seed_goal_search_tasks = self._enqueue_seed_frontier_searches()
            if (
                not self._universe_estimate_actionable()
                and not seed_goal_search_tasks
                and self.search_frontier.pending_count <= 0
                and not self._bootstrap_sources
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
                        "frontier or source-unit budget before count targets "
                        "could be estimated."
                    ),
                }
                print("  No task-level universe estimate; stopping before GASL.")
                return self._finalize(self._last_answer, self._final_assessment)
            bootstrap_goal_state = self._record_task_goal(
                "bootstrap_deficit",
                seed_exports,
                gap_search_tasks=[],
                goal_search_tasks=seed_goal_search_tasks,
            )
            gap_search_tasks: List[Dict[str, Any]] = []
            goal_search_tasks: List[Dict[str, Any]] = []
            if self._universe_estimate_actionable():
                gap_search_tasks, goal_search_tasks = (
                    await self._enqueue_deficit_searches(
                        "bootstrap",
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
                    "bootstrap_deficit",
                    seed_exports,
                    gap_search_tasks=gap_search_tasks,
                    goal_search_tasks=goal_search_tasks,
                    update_history=False,
                )

        # THE ONE CALL THAT RUNS THE TREE, and the only `run_async` in this
        # package. It builds nothing itself: the controller holds the context,
        # the three episode declarations run through the kernel's loop body, and
        # the run-ending decision is written from the record it returns.
        record = await self.acquisition.run(self.provider_binding.build_run_episode())
        # The run record itself, once, after the tree returns. Its own verdict
        # is read after its hook, so a run that opened no strategy at all still
        # emits a record saying why -- `exhausted` with no units is a fact about
        # the frontier, not an absent artifact.
        self.provider_binding.write_episode_record(record)
        self.provider_binding.write_acquisition_yield()
        return self._finalize(self._last_answer, self._final_assessment)

    async def _run_post_strategy_body(
        self,
        strategy_key: str,
        family: str,
        episode_id: str,
        *,
        run_unit_index: int,
    ) -> None:
        """The post-strategy work, owned by the strategy Episode that ran.

        Called once per completed strategy by the run grain's hook. Every
        artifact it writes is named by Episode identity (`episode_id` and its
        stem), never by a round number; `run_unit_index` is the run Episode's
        own zero-based unit index, carried as local data on the strategy
        record and never used as a continuation offset or artifact identity.

        Each named step is guarded individually. `drive_async` catches nothing
        around a hook, so a failing export must not unwind the whole record
        tree; its failure is recorded as a typed class instead.
        """

        label = episode_id or f"strategy_{strategy_key}"
        stem = self._artifact_stem(label)
        self._open_strategy_ledger_window()
        self._open_prompt_log(episode_id or stem, self._active_strategy_episode_path)
        print(
            f"\n{'#'*70}\nSTRATEGY {strategy_key} "
            f"[run unit {run_unit_index}]\n{'#'*70}"
        )

        accepted_sources = self._drain_strategy_sources()
        if self.extractor is None:
            # The schema is synthesized FROM these pages, so this is the first
            # moment it can exist. Every page of this strategy was
            # crediting-disabled under the `no_extractor` fate.
            await self._guarded(
                "resolve_schema", self._resolve_schema, accepted_sources[:2]
            )
        if accepted_sources:
            print(
                f"  Accepted {len(accepted_sources)} page(s) -> "
                f"{self._graph_summary()}"
            )
        else:
            print("  No new sources accepted by this strategy.")

        followups = await self._guarded(
            "followup_target_evolutions",
            self._enqueue_followup_target_evolutions,
            self._drain_followup_outcomes(),
            self._target_evolution_counts,
        )
        if followups:
            print(f"  Queued {len(followups)} follow-up target-deficit searches")

        if self.graph.number_of_nodes() == 0:
            print("  Graph is still empty; cannot answer yet.")
            self.strategy_records.append(
                {
                    "episode_id": episode_id,
                    "run_unit_index": run_unit_index,
                    "strategy_key": strategy_key,
                    "strategy_family": family,
                    "sources_ingested": len(accepted_sources),
                    "answer": None,
                    "hook_failures": list(self.hook_failures),
                }
            )
            self._record_stop_decision(self._stop_context_for(None))
            self._write_control_ledger()
            self._close_prompt_log()
            return

        no_new_sources_path = (
            self.goal_tracker is not None
            and not accepted_sources
            and self.seed_tables.row_count
            and not self._seed_table_migrations_available()
        )
        gasl_result: Dict[str, Any] = {}
        if no_new_sources_path:
            print(
                "  No new sources accepted; recording current tables "
                "without rerunning GASL."
            )
            table_exports = await self._guarded(
                "table_exports",
                self._write_table_exports,
                label,
                self.seed_tables.rows_by_name,
                seed_row_counts={
                    name: len(rows)
                    for name, rows in self.seed_tables.rows_by_name.items()
                },
                new_row_counts={},
            ) or []
        else:
            await self._guarded("save_graph", self._save_graph_sync, stem)
            metadata = await self._guarded("write_metadata", self._write_metadata_sync)
            print("  Running GASL traversal...")
            self._gasl_source_seed_nodes = self._gasl_source_seed_nodes_for_strategy(
                accepted_sources,
                graph=self.graph,
            )
            self._gasl_strategy_sources = self._gasl_strategy_source_rows(
                accepted_sources
            )
            self._gasl_source_catalog = self._gasl_source_catalog_for_strategy(
                accepted_sources,
                graph=self.graph,
            )
            try:
                gasl_result = await self._guarded(
                    "gasl",
                    self._run_gasl,
                    episode_id or stem,
                    self._active_strategy_episode_path,
                    metadata or {},
                    graph=self.graph,
                ) or {}
            finally:
                self._gasl_source_seed_nodes = []
                self._gasl_strategy_sources = []
                self._gasl_source_catalog = []
            table_exports = await self._guarded(
                "table_exports", self._export_gasl_tables, label, gasl_result
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
            label,
            episode_id,
            self._table_rows_by_variable(table_exports),
            self._gaps,
        )
        goal_state = self._record_task_goal(
            label,
            table_exports,
            gap_search_tasks=gap_search_tasks,
            goal_search_tasks=goal_search_tasks,
        )
        await self._guarded(
            "annotate_target_outcomes",
            self._annotate_recent_target_outcomes_async,
            label,
            goal_state,
            self._table_rows_by_variable(table_exports),
            self.last_best_guess_state,
        )

        deficit_expansion: Dict[str, Any] = {
            "attempted": False,
            "reason": "not_needed",
            "label": label,
            "episode_id": episode_id,
            "pending_before": self.search_frontier.pending_count,
            "pending_after": self.search_frontier.pending_count,
            "gap_search_tasks": 0,
            "goal_search_tasks": 0,
        }
        if goal_state is not None and not goal_state.fulfilled:
            expanded = await self._guarded(
                "expand_goal",
                self._expand_unfulfilled_table_goal,
                label,
                table_exports,
                goal_state,
            )
            if expanded is not None:
                gap_search_tasks, goal_search_tasks, goal_state, deficit_expansion = (
                    expanded
                )
        elif goal_state is None and self._source_budget_available():
            expanded = await self._guarded(
                "enqueue_deficit_searches",
                self._enqueue_deficit_searches,
                label,
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
            self._stop_context_for(goal_state)
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

        strategy_record = {
            "episode_id": episode_id,
            "run_unit_index": run_unit_index,
            "strategy_key": strategy_key,
            "strategy_family": family,
            "queries": [outcome.query for outcome in self.last_search_outcomes],
            "sources_ingested": len(accepted_sources),
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
            "skipped_gasl": no_new_sources_path,
            "control_decisions": self._strategy_control_decisions(),
            "cost_records": self._episode_cost_records(episode_id),
            "table_schema_disclosure": self.table_schema_disclosure,
            "field_provenance_coverage": self.last_field_provenance_ledger,
            "criteria_projection_version": CRITERIA_PROJECTION_VERSION,
            "evidence_registry": self.evidence_registry.summary(),
            "hook_failures": list(self.hook_failures),
            "page_best_guess": list(self.provider_binding.page_guess_reports),
        }
        self.strategy_records.append(strategy_record)
        (self.answers_dir / f"strategy_{stem}.json").write_text(
            json.dumps(strategy_record, indent=2, default=str), encoding="utf-8"
        )
        self._write_control_ledger()
        self.provider_binding.write_acquisition_yield()
        self._record_strategy_residual_cost(episode_id, stem)
        self._reset_strategy_state()
        self._close_prompt_log()

    async def _guarded(self, step: str, fn, *args, **kwargs):
        """Run one post-strategy step; record a failure rather than raising.

        A hook may not raise. Each named step is guarded individually so one
        failing export cannot unwind the record tree, and its failure lands on
        the strategy record as a typed class instead of vanishing.
        """

        try:
            result = fn(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as exc:  # noqa: BLE001 - recorded, never raised at a hook
            self._record_hook_failure(f"strategy_body:{step}", step, exc)
            return None

    def _save_graph_sync(self, stem: str) -> None:
        self._save_graph(stem)

    def _write_metadata_sync(self) -> Dict[str, Any]:
        return self._write_metadata()

    def _annotate_recent_target_outcomes_async(
        self,
        artifact_label: int | str,
        goal_state,
        table_rows,
        best_guess_state,
    ) -> None:
        self._annotate_recent_target_outcomes(
            artifact_label,
            goal_state,
            table_rows=table_rows,
            best_guess_state=best_guess_state,
        )

    def _stop_context_for(self, goal_state) -> StopContext:
        """The stop inputs, with the frontier required at exactly one site.

        The composition tests the frontier where a strategy's source runs out of
        tasks, so an empty frontier is terminal for the run only once every
        eligible family is drained -- which is what `_eligible_families` reports.
        There is no round budget: continuation belongs to the Episode verdicts,
        the declared source-unit bound, and the typed terminal conditions here.
        """

        return StopContext(
            episode_id=self._active_strategy_episode_id,
            goal_mode=self.goal_tracker is not None,
            goal_fulfilled=bool(goal_state is not None and goal_state.fulfilled),
            source_budget_available=self._source_budget_available(),
            frontier_pending=self.search_frontier.pending_count,
            frontier_required=not self.provider_binding.eligible_families(),
            criteria_snapshot_id=self.criteria_snapshot.id,
        )

    def _drain_strategy_sources(self) -> List[Dict[str, Any]]:
        return self.provider_binding.drain_strategy_sources(
            self._drain_bootstrap_sources()
        )

    def _drain_followup_outcomes(self) -> List[SearchOutcome]:
        return self.provider_binding.drain_followup_outcomes()

    def _reset_strategy_state(self) -> None:
        self.last_prompt_arm_summaries = self.provider_binding.reset_strategy_state()

    def _record_strategy_residual_cost(self, episode_id: str, stem: str) -> None:
        """Unattributed spend for THIS strategy's interval, stamped and rebased.

        Two things are needed and only one is obvious. The STAMP: the ORPHAN
        meter's own snapshot carries no Episode identity by construction, and
        the reward selects cost records by ``episode_id``, so an unstamped
        residual would belong to no strategy whatever strategy paid for it.
        The REBASE: `_orphan_cost_delta` measured against the baseline taken
        when the pipeline was constructed, so it was cumulative over the run
        -- taking it per strategy without rebasing hands every strategy the
        whole run's residual to date, and summing them multiply-counts the
        same spend.

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
                "observation_id": f"{stem}#residual",
                "episode_id": str(episode_id or self._run_episode_id),
                "nested_in": "",
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
                episode_id=self._active_strategy_episode_id,
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
                        evidence_registry=self.evidence_registry,
                    )
                    if self.path_gate_settings.gates
                    else None
                ),
                table_specs=self.table_spec,
                settings=self.path_gate_settings,
                criteria_snapshot_id=self.criteria_snapshot.id,
                pending_actions=self.search_frontier.pending_count,
                remaining_source_budget=self._remaining_source_budget(),
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
            evidence_registry=self.evidence_registry,
        )

    def _control_decision_context(
        self,
        surface: ControlSurface,
        *,
        max_actions: int,
    ) -> DecisionContext:
        return DecisionContext(
            surface=surface,
            episode_id=self._active_strategy_episode_id,
            max_actions=int(max_actions),
            pending_actions=self.search_frontier.pending_count,
            remaining_source_budget=self._remaining_source_budget(),
            criteria_snapshot_id=self.criteria_snapshot.id,
        )

    def _record_policy_decision(
        self,
        surface: ControlSurface,
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
        raise, so the two are deliberately written to the same value here.
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
            episode_id=self._active_strategy_episode_id,
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

    def _open_strategy_ledger_window(self) -> None:
        self._strategy_ledger_mark = len(self.control_decisions)

    def _strategy_control_decisions(self) -> List[Dict[str, Any]]:
        return self.control_decisions[self._strategy_ledger_mark :]

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
    def _save_graph(self, stem: str) -> None:
        save_graph(self.graphs_dir / f"{stem}.graphml", self.graph)
        save_graph(self.graphs_dir / "current_graph.graphml", self.graph)

    def _record_run_residual_cost(self) -> None:
        """The TAIL residual: spend since the last strategy closed.

        Unattributed spend is a number here, not silence. It is taken per
        completed strategy (`_record_strategy_residual_cost`), rebased each
        time, and this closes the last interval, attributed to the run Episode
        by its `episode_id`.

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
                "episode_id": self._run_episode_id,
                "nested_in": "",
            }
        )
        self.cost_records.append(residual)


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
            "strategies_completed": len(self.strategy_records),
            # SOURCE UNITS PULLED, accepted or not. The budget charges every
            # pulled page, so this is what `max_source_units` bounds;
            # `pages_accepted` is the other half and both are emitted so
            # nothing is ambiguous. No figure here is compared against one
            # from before the composition.
            "source_units_pulled": self.units_pulled,
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
            "acquisition_summary": self.provider_binding.run_summary(),
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
