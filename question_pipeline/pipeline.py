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
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from domain_schemas.schema_loader import DomainSchema, load_domain_schema
from gasl import GASLExecutor, NetworkXAdapter
from gasl.answer_layer import AnswerLayerCompiler
from gasl.llm import ArgoBridgeLLM
from graph_metadata import build_metadata, save_graph_metadata
from hpc.common import save_graph
from nano_graphrag.entity_extraction.typed_module import (
    create_domain_extractor_from_schema,
)
from paper_fetching.firecrawl_client import (
    download_paper_content,
    search_papers,
)

from . import schema_synthesis, strategy
from .extraction import enrich_graph, extract_from_text
from .goals import (
    FillGoalState,
    TableFillGoalTracker,
    merge_universe_estimates,
    normalize_universe_estimate,
)
from .search import (
    SearchBatch,
    SearchFrontier,
    SearchHarvester,
    SearchTask,
    load_seed_search_outcomes,
    load_seed_source_records,
    load_seen_urls,
    table_gap_search_tasks,
)
from .search_memory import SearchMemory
from .tables import SeedTables, load_seed_tables, merge_rows_by_table
from .numeric_candidates import (
    NUMERIC_CANDIDATE_COLUMNS,
    numeric_candidates_from_tables,
)
from .strategy_state import (
    fallback_query_for_operator,
    plan_catalog_operator,
    plan_target_operator,
)


@dataclass
class PipelineConfig:
    question: str
    pipeline_mode: str = "answer"
    output_dir: str = "./question_runs/run"

    # Schema: if schema_name is set, load it; otherwise synthesize one.
    schema_name: Optional[str] = None
    graph_path: Optional[str] = None
    schema_review_rounds: int = 2
    schema_expectations: str = ""

    # Search / corpus limits
    firecrawl_api_key: Optional[str] = None
    max_rounds: int = 4
    max_papers: int = 40
    papers_per_round: int = 8
    papers_per_query: int = 3
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
    answer_mode: str = "natural"
    table_variables: List[str] = field(default_factory=list)
    seed_tables_dir: Optional[str] = None
    seed_sources_dir: Optional[str] = None
    round_offset: Optional[int] = None
    numeric_candidate_mode: str = "parsed"

    # Stopping
    target_confidence: float = 0.75
    task_goal_mode: str = "off"
    task_goal_search_tasks: int = 0

    # LLM
    model: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


TABLE_ANSWER_INSTRUCTIONS = """
Materialize row-shaped LIST variables for the requested tabular answer instead
of treating prose as the deliverable.

Use FIND, GRAPHWALK, PROJECT, COLLAPSE, and PROCESS to produce table variables
whose names end in _table. Preserve source_refs and source_chunks on every row
when provenance exists. Prefer one row per atomic fact, estimate, comparison,
or context over broad joined rows that blur distinct evidence. Keep partial
rows when a counterpart fact is absent; set missing fields to null and explain
the missing evidence in evidence_gap.

Never write COLLAPSE, GROUP, AGGREGATE, or JOIN output directly AS a final
table variable unless every emitted row already has stable row keys and
source-level provenance. If candidates need deduplication, first COLLAPSE into
an intermediate variable, then PROCESS those collapsed rows into exact
row-shaped table rows. When a path table needs multiple relationship types,
issue one GRAPHWALK whose follow clause joins all needed edge labels with |.
Do not issue multiple GRAPHWALK commands AS the same variable; AS replaces
rather than appends. Before any COLLAPSE BY a deduplication key, create a
non-empty deduplication key on every candidate row.
""".strip()


TABLE_REQUIRED_COLUMNS: Dict[str, List[str]] = {}
TABLE_COMPLETENESS_COLUMNS: Dict[str, List[str]] = {}
PIPELINE_MODE_ANSWER = "answer"
PIPELINE_MODE_TABLE_FILL = "table_fill"
TASK_GOAL_OFF = "off"
TASK_GOAL_TABLE_FILL = "table_fill"


def _operator_metadata(operator_plan: Dict[str, Any]) -> Dict[str, Any]:
    operator = str(operator_plan.get("operator") or "")
    source_family = str(operator_plan.get("source_family") or "")
    return {
        "strategy_operator": operator,
        "strategy_family": operator,
        "source_family": source_family,
        "operator_attempt": operator_plan.get("attempt_index"),
        "operator_last_failure_class": operator_plan.get(
            "last_failure_class",
            "",
        ),
        "operator_exhausted": operator_plan.get("exhausted_operators", []),
        "operator_constraints": operator_plan.get("constraints", []),
    }


_CATALOG_STATUS_RANK = {
    "missing": 0,
    "insufficient_evidence": 1,
    "estimated": 2,
}


def _catalog_snapshot_metadata(
    prefix: str,
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        f"{prefix}_status": snapshot.get("status", "missing"),
        f"{prefix}_count_target_count": int(
            snapshot.get("count_target_count") or 0,
        ),
        f"{prefix}_unestimated_count": int(
            snapshot.get("unestimated_count") or 0,
        ),
        f"{prefix}_target_family_count": int(
            snapshot.get("target_family_count") or 0,
        ),
    }


def _catalog_snapshot_from_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    status = str(metadata.get("baseline_catalog_status") or "missing")
    count_target_count = int(metadata.get("baseline_catalog_count_target_count") or 0)
    unestimated_count = int(metadata.get("baseline_catalog_unestimated_count") or 0)
    target_family_count = int(metadata.get("baseline_catalog_target_family_count") or 0)
    return {
        "status": status,
        "status_rank": _CATALOG_STATUS_RANK.get(status, 0),
        "count_target_count": count_target_count,
        "unestimated_count": unestimated_count,
        "target_family_count": target_family_count,
    }


def _catalog_progress_delta_metadata(
    baseline: Dict[str, Any],
    post: Dict[str, Any],
) -> Dict[str, Any]:
    status_delta = int(post.get("status_rank") or 0) - int(
        baseline.get("status_rank") or 0,
    )
    count_target_delta = int(post.get("count_target_count") or 0) - int(
        baseline.get("count_target_count") or 0,
    )
    unestimated_delta = int(baseline.get("unestimated_count") or 0) - int(
        post.get("unestimated_count") or 0,
    )
    target_family_delta = int(post.get("target_family_count") or 0) - int(
        baseline.get("target_family_count") or 0,
    )
    return {
        "post_catalog_status_delta": status_delta,
        "post_catalog_count_target_delta": count_target_delta,
        "post_catalog_unestimated_delta": unestimated_delta,
        "post_catalog_target_family_delta": target_family_delta,
        "post_catalog_progress_delta": sum(
            max(0, delta)
            for delta in (
                status_delta,
                count_target_delta,
                unestimated_delta,
                target_family_delta,
            )
        ),
    }


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


class QuestionPipeline:
    """Iterative search + KG build + GASL answer loop for one question."""

    def __init__(
        self,
        config: PipelineConfig,
        *,
        llm=None,
        search_fn: Optional[Callable[[str, int], List[Dict[str, Any]]]] = None,
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
        self._search_fn = search_fn or self._default_search_fn
        self._uses_default_search = search_fn is None
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
        self.last_search_batch = SearchBatch()
        self.search_provider_error = ""
        self.search_outcomes: List[Dict[str, Any]] = []
        if config.source_relevance_mode not in {"off", "focused", "all"}:
            raise ValueError("source_relevance_mode must be 'off', 'focused', or 'all'")
        config.gasl_graph_scope = _normalize_mode(config.gasl_graph_scope)
        if config.gasl_graph_scope not in {"auto", "full", "new_sources"}:
            raise ValueError("gasl_graph_scope must be 'auto', 'full', or 'new_sources'")
        if config.gasl_new_source_hops < 0:
            raise ValueError("gasl_new_source_hops must be nonnegative")
        config.numeric_candidate_mode = _normalize_numeric_candidate_mode(
            config.numeric_candidate_mode,
        )
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
        self.goal_tracker = (
            TableFillGoalTracker(
                table_schemas=TABLE_REQUIRED_COLUMNS,
            )
            if config.task_goal_mode == TASK_GOAL_TABLE_FILL
            else None
        )
        self.goal_universe_estimate: Dict[str, Any] = {"status": "missing"}
        self.goal_discovery_sources: List[Dict[str, Any]] = []
        self._seen_goal_discovery_source_ids: set[str] = set()
        self.seed_tables: SeedTables = load_seed_tables(config.seed_tables_dir)
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
        self._record_goal_discovery_sources(seed_source_records)
        self._export_seed_sources(seed_source_records)
        self._export_seed_search_outcomes(seed_search_outcomes)
        self.search_memory = SearchMemory.from_outcomes(self.search_outcomes)
        self._persist_search_memory()
        self.goal_states: List[Dict[str, Any]] = []
        self.derived_table_exports: List[Dict[str, Any]] = []
        self.last_derived_table_exports: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Default real dependencies (swappable for tests)
    # ------------------------------------------------------------------ #
    def _default_search_fn(self, query: str, max_results: int) -> List[Dict[str, Any]]:
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
        )

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
            llm_func=self.llm.call_async,
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
        return executor.run_hypothesis_driven_traversal(
            self._gasl_question(), self.config.max_gasl_iterations
        )

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
        return f"""CURRENT TABLE TARGETS:
The run is continuing or scoring these exact table variable names:
{target_lines}

Reuse an exact listed name whenever its rows match the view you are
materializing. Do not rename a listed table by adding summary words, swapping
token order, or using a near-synonym. Create a new `_table` variable only for a
genuinely separate view that is not covered by a listed target."""

    def _table_target_names(self) -> List[str]:
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
        return (
            self.paper_count < self.config.max_papers
            and self.config.papers_per_round > 0
            and self.config.papers_per_query > 0
        )

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

    # ------------------------------------------------------------------ #
    # Fetching
    # ------------------------------------------------------------------ #
    async def _fetch_papers(
        self,
        queries: List[str],
        cap: int,
        *,
        round_idx: int = 0,
        topic: str = "initial",
        expansion_op: str = "llm_initial",
    ) -> List[Dict[str, Any]]:
        """Search each query through the shared frontier and harvest path."""
        queued_before = self.search_frontier.pending_count
        tasks = self.search_frontier.enqueue_queries(
            queries,
            round_index=round_idx,
            topic=topic,
            expansion_op=expansion_op,
        )
        wave = self.search_frontier.next_wave(queued_before + len(tasks))
        harvester = SearchHarvester(
            search_fn=self._search_fn,
            scrape_fn=self._scrape_fn if self.config.scrape_search_results else None,
            source_relevance_fn=self._source_relevance_decision,
            papers_dir=self.papers_dir,
            seen_urls=self.seen_urls,
            min_paper_length=self.config.min_paper_length,
            max_paper_length=self.config.max_paper_length,
            max_extraction_chars_per_paper=self.config.max_extraction_chars_per_paper,
        )
        batch = await harvester.harvest_async(
            wave,
            max_results_per_task=self.config.papers_per_query,
            per_wave_cap=cap,
            remaining_paper_budget=self.config.max_papers - self.paper_count,
        )
        if (
            batch.unattempted_tasks
            and self.search_frontier.persistent
            and not batch.fatal_error
        ):
            self.search_frontier.requeue_front(batch.unattempted_tasks)
        if batch.fatal_error:
            self.search_provider_error = batch.fatal_error
            print(f"  Search provider stopped the wave: {batch.fatal_error}")

        self.search_frontier.record(batch.outcomes)
        self.last_search_batch = batch
        self.search_outcomes.extend(batch.outcome_dicts())
        self.queries_used.extend(outcome.query for outcome in batch.outcomes)
        self.paper_count += len(batch.papers)
        self._record_goal_discovery_sources(batch.papers)
        self._refresh_search_memory()
        return batch.papers

    async def _source_relevance_decision(
        self,
        task: SearchTask,
        result: Dict[str, Any],
        text: str,
    ):
        if not self._should_gate_source(task):
            return None

        try:
            assessment = await strategy.assess_source_relevance(
                self.llm,
                self.config.question,
                task=task.to_dict(),
                result=self._compact_search_result(result),
                text=text,
            )
        except Exception as exc:  # noqa: BLE001 - relevance gating should not drop evidence on LLM failure
            from .search import SourceRelevanceDecision

            return SourceRelevanceDecision(
                accept=True,
                reason=f"relevance check failed open: {exc}",
                confidence=0.0,
                metadata={"error": str(exc)},
            )

        from .search import SourceRelevanceDecision

        return SourceRelevanceDecision(
            accept=bool(assessment.get("accept")),
            reason=str(assessment.get("reason") or ""),
            confidence=float(assessment.get("confidence") or 0.0),
            metadata={
                "matched_needs": assessment.get("matched_needs") or [],
                "missing_needs": assessment.get("missing_needs") or [],
            },
        )

    def _should_gate_source(self, task: SearchTask) -> bool:
        mode = self.config.source_relevance_mode
        if mode == "off":
            return False
        if mode == "all":
            return True
        return task.topic in {"target_deficit", "table_gap"}

    @staticmethod
    def _compact_search_result(result: Dict[str, Any]) -> Dict[str, Any]:
        compact: Dict[str, Any] = {}
        for key in ("title", "url", "description", "snippet", "source", "publishedDate"):
            value = result.get(key)
            if value:
                compact[key] = value
        for key, value in result.items():
            if key in compact or key in {"content", "markdown", "html", "rawHtml"}:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                compact[key] = value
            elif isinstance(value, dict):
                compact[key] = {
                    nested_key: nested_value
                    for nested_key, nested_value in value.items()
                    if isinstance(nested_value, (str, int, float, bool))
                    and len(str(nested_value)) <= 500
                }
        return compact

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
                max_review_rounds=self.config.schema_review_rounds,
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
        return await asyncio.to_thread(
            self._gasl_runner,
            graph if graph is not None else self.graph,
            metadata,
            state_file,
        )

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    async def _ingest_papers(self, papers: List[Dict[str, Any]]) -> int:
        added = 0
        for paper in papers:
            entities, relationships = await extract_from_text(
                self.extractor,
                paper["text"],
                paper["id"],
                chunk_size=self.config.chunk_size,
                overlap=self.config.chunk_overlap,
                concurrency=self.config.extraction_concurrency,
                timeout=self.config.extraction_timeout_sec,
            )
            if not entities:
                continue
            self.graph = enrich_graph(
                self.graph,
                entities,
                relationships,
                paper["id"],
                similarity_threshold=self.config.similarity_threshold,
                auto_merge=self.config.auto_merge_entities,
            )
            added += 1
        return added

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

        nodes = self._source_neighborhood_nodes(
            source_ids,
            hops=self.config.gasl_new_source_hops,
        )
        if not nodes:
            return self.graph
        return self.graph.subgraph(nodes).copy()

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

    def _export_gasl_tables(
        self, round_idx: int | str, gasl_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        if self.config.answer_mode != "table":
            return []

        final_state = gasl_result.get("final_state") or {}
        exports: List[Dict[str, Any]] = []
        rows_by_name = self._compiled_answer_view_tables(final_state)
        raw_rows_by_name = self._raw_gasl_table_variables(final_state)
        for name, rows in raw_rows_by_name.items():
            rows_by_name.setdefault(name, rows)

        current_rows = {
            name: self._table_export_rows(name, rows)
            for name, rows in rows_by_name.items()
            if isinstance(rows, list)
        }
        merged_rows = merge_rows_by_table(
            self.seed_tables.rows_by_name,
            current_rows,
        )
        exports = self._write_table_exports(
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

    def _export_seed_tables(
        self, round_idx: int | str = "seed",
    ) -> List[Dict[str, Any]]:
        if self.config.answer_mode != "table":
            return []
        if not self.seed_tables.rows_by_name:
            return []

        return self._write_table_exports(
            round_idx,
            self.seed_tables.rows_by_name,
            seed_row_counts={
                name: len(rows)
                for name, rows in self.seed_tables.rows_by_name.items()
            },
            new_row_counts={},
        )

    def _write_table_exports(
        self,
        round_idx: int | str,
        rows_by_name: Dict[str, List[Dict[str, Any]]],
        *,
        seed_row_counts: Dict[str, int],
        new_row_counts: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        exports: List[Dict[str, Any]] = []
        table_names = self.config.table_variables or sorted(rows_by_name)
        for name in table_names:
            items = rows_by_name.get(name)
            if not isinstance(items, list):
                continue

            self.tables_dir.mkdir(parents=True, exist_ok=True)
            json_path = self.tables_dir / f"round_{round_idx}_{name}.json"
            csv_path = self.tables_dir / f"round_{round_idx}_{name}.csv"
            json_path.write_text(
                json.dumps(items, indent=2, default=str), encoding="utf-8"
            )

            csv_written = False
            if all(isinstance(item, dict) for item in items):
                self._write_table_csv(csv_path, items, table_name=name)
                csv_written = True

            record = {
                "round": round_idx,
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
            manifest_path = self.tables_dir / f"round_{round_idx}_manifest.json"
            manifest_path.write_text(
                json.dumps(exports, indent=2, default=str), encoding="utf-8"
            )

        self.last_derived_table_exports = self._write_numeric_candidate_exports(
            round_idx,
            rows_by_name,
        )
        return exports

    def _write_numeric_candidate_exports(
        self,
        round_idx: int | str,
        rows_by_name: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        if self.config.answer_mode != "table":
            return []
        if self.config.numeric_candidate_mode == "off":
            return []

        rows = numeric_candidates_from_tables(
            rows_by_name,
            mode=self.config.numeric_candidate_mode,
        )
        self.derived_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.derived_dir / f"round_{round_idx}_numeric_candidates.json"
        csv_path = self.derived_dir / f"round_{round_idx}_numeric_candidates.csv"
        manifest_path = self.derived_dir / f"round_{round_idx}_manifest.json"
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
            "round": round_idx,
            "variable": "numeric_candidates",
            "mode": self.config.numeric_candidate_mode,
            "rows": len(rows),
            "json_path": str(json_path),
            "csv_path": str(csv_path),
        }
        manifest_path.write_text(
            json.dumps([record], indent=2, default=str),
            encoding="utf-8",
        )
        self.derived_table_exports.append(record)
        return [record]

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
            table_name = view.payload.get("table_name")
            rows = view.payload.get("rows")
            if table_name and isinstance(rows, list):
                tables[table_name] = rows
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
    def _table_export_rows(cls, name: str, rows: List[Any]) -> List[Any]:
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
                            )
                        )
                    continue

            export_rows.append(cls._with_required_table_columns(name, row))

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
        return cls._with_required_table_columns(name, row)

    @classmethod
    def _with_required_table_columns(
        cls,
        name: str,
        row: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            **{
                column: row.get(column, "")
                for column in TABLE_REQUIRED_COLUMNS.get(name, [])
            },
            **row,
        }

    @classmethod
    def _validate_table(cls, name: str, rows: List[Any]) -> Dict[str, Any]:
        required = TABLE_REQUIRED_COLUMNS.get(name, [])
        completeness_columns = TABLE_COMPLETENESS_COLUMNS.get(name, [])
        row_dicts = [row for row in rows if isinstance(row, dict)]
        missing_by_column = {
            column: sum(
                1 for row in row_dicts if cls._is_missing(row.get(column))
            )
            for column in completeness_columns
        }
        if any("completeness" in row for row in row_dicts):
            complete_rows = sum(
                1 for row in row_dicts if row.get("completeness") == "complete"
            )
        else:
            complete_rows = sum(
                1
                for row in row_dicts
                if all(
                    not cls._is_missing(row.get(column))
                    for column in completeness_columns or required
                )
            )
        return {
            "required_columns": required,
            "rows": len(rows),
            "dict_rows": len(row_dicts),
            "complete_rows": complete_rows,
            "partial_rows": max(0, len(row_dicts) - complete_rows),
            "missing_by_column": {
                column: missing
                for column, missing in missing_by_column.items()
                if missing
            },
        }

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
        if value is None or value == "":
            return True
        if isinstance(value, (list, tuple, set, dict)) and not value:
            return True
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        return normalized in {
            "n/a",
            "na",
            "none",
            "not applicable",
            "not specified",
            "not specified in current evidence",
            "null",
            "unknown",
        }

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

            missing = validation.get("missing_by_column") or {}
            rows = validation.get("dict_rows") or validation.get("rows") or 0
            for column, count in sorted(missing.items(), key=lambda item: -item[1])[:5]:
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
        return [*outcome_records, *synthetic_outcomes]

    async def _estimate_task_goal_universe(
        self,
        round_idx: int | str,
        table_rows: Dict[str, List[Dict[str, Any]]],
        gaps: List[str],
    ) -> Dict[str, Any]:
        if self.goal_tracker is None:
            return self.goal_universe_estimate
        if not self.goal_discovery_sources:
            self.goal_universe_estimate = normalize_universe_estimate(
                self.goal_universe_estimate,
                table_rows=table_rows,
            )
            return self.goal_universe_estimate

        estimate = await strategy.estimate_coverage_universe(
            self.llm,
            self.config.question,
            goal_context=self.goal_tracker.prompt_context(
                table_rows,
                gaps,
                self.goal_universe_estimate,
            ),
            discovery_sources=self.goal_discovery_sources,
            previous_estimate=self.goal_universe_estimate,
        )
        self.goal_universe_estimate = merge_universe_estimates(
            self.goal_universe_estimate,
            estimate,
            table_rows=table_rows,
        )
        self.goals_dir.mkdir(parents=True, exist_ok=True)
        path = self.goals_dir / f"round_{round_idx}_universe_estimate.json"
        path.write_text(
            json.dumps(estimate, indent=2, default=str),
            encoding="utf-8",
        )
        return estimate

    async def _enqueue_catalog_searches(
        self,
        round_idx: int,
        table_rows: Dict[str, List[Dict[str, Any]]],
        gaps: List[str],
    ) -> List[Dict[str, Any]]:
        if self.goal_tracker is None:
            return []
        if self.config.task_goal_search_tasks <= 0:
            return []
        if self.search_provider_error:
            print(
                "  Catalog search paused after provider error: "
                f"{self.search_provider_error}"
            )
            return []
        if not self._paper_budget_available():
            return []

        operator_plan = plan_catalog_operator(self.search_outcomes)
        if operator_plan.get("exhausted"):
            print("  Catalog search operators exhausted for current goal state.")
            return []

        queries = await strategy.catalog_queries(
            self.llm,
            self.config.question,
            goal_context=self.goal_tracker.prompt_context(
                table_rows,
                gaps,
                self.goal_universe_estimate,
            ),
            operator_plan=operator_plan,
            universe_estimate=self.goal_universe_estimate,
            search_outcomes=[
                outcome
                for outcome in self.search_outcomes[-20:]
                if outcome.get("topic") == "goal_catalog"
            ],
            n=self.config.task_goal_search_tasks,
        )
        for query in self.goal_universe_estimate.get("suggested_queries") or []:
            if isinstance(query, str) and query.strip():
                queries.append(query)
        tasks = [
            SearchTask(
                query=query,
                topic="goal_catalog",
                expansion_op="llm_goal_catalog",
                round_index=round_idx,
                metadata={
                    "goal_mode": self.config.task_goal_mode,
                    "goal_search_tasks": self.config.task_goal_search_tasks,
                    **self._catalog_baseline_metadata(),
                    **_operator_metadata(operator_plan),
                },
            )
            for query in queries
        ]
        accepted = self.search_frontier.enqueue(tasks)
        if accepted:
            print(
                f"  Queued {len(accepted)} catalog searches "
                f"for round {round_idx}"
            )
        return [task.to_dict() for task in accepted]

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

        planned = await strategy.target_deficit_queries(
            self.llm,
            self.config.question,
            goal_context=self.goal_tracker.prompt_context(
                table_rows,
                [],
                self.goal_universe_estimate,
            ),
            deficits=deficits,
            n=max(
                self.config.task_goal_search_tasks,
                min(len(deficits), self.config.task_goal_search_tasks * 2),
            ),
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
            task = self._target_deficit_search_task(
                query=item["query"],
                target=target,
                round_idx=round_idx,
                rationale=item.get("rationale", ""),
                operator_plan=target.get("operator_plan") or {},
                strategy_origin="llm",
            )
            self._record_strategy_baseline(task)
            tasks.append(task)

        accepted = self.search_frontier.enqueue(tasks)
        covered_target_ids = {
            str(task.metadata.get("fill_deficit_id") or "")
            for task in accepted
        }
        fallback_tasks = []
        for target in deficits:
            deficit_id = str(target.get("id") or "")
            if deficit_id in covered_target_ids:
                continue
            fallback_query = self._fallback_target_deficit_query(target)
            if not fallback_query:
                continue
            task = self._target_deficit_search_task(
                query=fallback_query,
                target=target,
                round_idx=round_idx,
                rationale="Fallback strategy for a target omitted by the planner.",
                operator_plan=target.get("operator_plan") or {},
                strategy_origin="fallback",
            )
            self._record_strategy_baseline(task)
            fallback_tasks.append(task)
        if fallback_tasks:
            accepted.extend(self.search_frontier.enqueue(fallback_tasks))
        if accepted:
            print(
                f"  Queued {len(accepted)} target-deficit searches "
                f"for round {round_idx}"
            )
        return [task.to_dict() for task in accepted]

    @staticmethod
    def _target_deficit_search_task(
        *,
        query: str,
        target: Dict[str, Any],
        round_idx: int,
        rationale: str,
        operator_plan: Dict[str, Any],
        strategy_origin: str,
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
            },
        )

    def _record_strategy_baseline(self, task: SearchTask) -> None:
        task.metadata["baseline_graph_nodes"] = self.graph.number_of_nodes()
        task.metadata["baseline_graph_edges"] = self.graph.number_of_edges()

    def _catalog_baseline_metadata(self) -> Dict[str, Any]:
        return _catalog_snapshot_metadata(
            "baseline_catalog",
            self._catalog_progress_snapshot(self.goal_universe_estimate),
        )

    @staticmethod
    def _fallback_target_deficit_query(target: Dict[str, Any]) -> str:
        return fallback_query_for_operator(target)

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
                    str(attempt.get("query") or ""),
                ),
            )
            enriched_target = {
                **target,
                "strategy_history": attempts[-8:],
                "strategy_memory": memory_records,
            }
            enriched_target["operator_plan"] = plan_target_operator(enriched_target)
            enriched.append(enriched_target)
        return enriched

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

    def _annotate_recent_target_outcomes(
        self,
        goal_state: Optional[FillGoalState],
    ) -> None:
        if goal_state is None:
            return

        targets = (
            goal_state.target_catalog.get("fill_deficits")
            or goal_state.target_estimate.get("count_targets")
            or []
        )
        if not self.last_search_batch.outcomes:
            return

        metadata_updates: Dict[str, Dict[str, Any]] = {}
        for outcome in self.last_search_batch.outcomes:
            metadata = outcome.metadata
            if outcome.topic != "target_deficit":
                continue
            if not isinstance(metadata, dict):
                continue
            update = {
                "search_yield": self._search_yield_summary(outcome.to_dict()),
            }
            target = self._target_for_outcome_metadata(metadata, targets)
            if target is not None:
                previous_count = int(metadata.get("observed_count") or 0)
                observed_count = int(target.get("observed_count") or 0)
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
                        "post_round_observed_delta": observed_count - previous_count,
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

    def _annotate_recent_catalog_outcomes(self) -> None:
        if not self.last_search_batch.outcomes:
            return

        post = self._catalog_progress_snapshot(self.goal_universe_estimate)
        post_metadata = _catalog_snapshot_metadata("post_catalog", post)
        metadata_updates: Dict[str, Dict[str, Any]] = {}
        for outcome in self.last_search_batch.outcomes:
            if outcome.topic != "goal_catalog":
                continue
            metadata = outcome.metadata
            if not isinstance(metadata, dict):
                continue
            baseline = _catalog_snapshot_from_metadata(metadata)
            update = {
                **post_metadata,
                **_catalog_progress_delta_metadata(baseline, post),
                "search_yield": self._search_yield_summary(outcome.to_dict()),
            }
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
            "status_rank": _CATALOG_STATUS_RANK.get(status, 0),
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

    def _record_task_goal(
        self,
        round_idx: int | str,
        table_exports: List[Dict[str, Any]],
        *,
        gap_search_tasks: List[Dict[str, Any]],
        goal_search_tasks: List[Dict[str, Any]],
        update_history: bool = True,
    ) -> Optional[FillGoalState]:
        if self.goal_tracker is None:
            return None

        rows_by_variable = self._table_rows_by_variable(table_exports)
        state = self.goal_tracker.evaluate(
            round_idx=round_idx,
            table_rows=rows_by_variable,
            universe_estimate=self.goal_universe_estimate,
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
        path = self.goals_dir / f"round_{round_idx}_stop_criteria.json"
        payload = state.to_dict()
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        entry = {**payload, "json_path": str(path)}
        self.goal_states = [
            previous
            for previous in self.goal_states
            if previous.get("round") != round_idx
        ]
        self.goal_states.append(entry)
        return state

    async def _bootstrap_task_goal(self) -> List[Dict[str, Any]]:
        if self.goal_tracker is None:
            return []

        seed_exports = self._export_seed_tables()
        seed_table_rows = self._table_rows_by_variable(seed_exports)
        bootstrap_round_idx = self._round_label(0)
        bootstrap_idx = 0

        while (
            self._paper_budget_available()
            and not self._universe_estimate_actionable()
        ):
            source_count_before = len(self.goal_discovery_sources)
            catalog_tasks = await self._enqueue_catalog_searches(
                bootstrap_round_idx,
                seed_table_rows,
                [],
            )
            if self.search_frontier.pending_count <= 0:
                break

            wave_papers = await self._fetch_papers(
                [],
                cap=self.config.papers_per_round,
                round_idx=bootstrap_round_idx,
                topic="goal_catalog",
                expansion_op="llm_goal_bootstrap",
            )
            print(
                "  Fetched "
                f"{len(wave_papers)} catalog papers "
                f"in bootstrap wave {bootstrap_idx}"
            )

            await self._estimate_task_goal_universe(
                f"bootstrap_{bootstrap_round_idx}_{bootstrap_idx}",
                seed_table_rows,
                [],
            )
            self._record_task_goal(
                f"bootstrap_{bootstrap_round_idx}_{bootstrap_idx}",
                seed_exports,
                gap_search_tasks=[],
                goal_search_tasks=catalog_tasks,
            )
            self._annotate_recent_catalog_outcomes()
            bootstrap_idx += 1

            if not wave_papers and not catalog_tasks:
                break
            if (
                len(self.goal_discovery_sources) == source_count_before
                and self._universe_estimate_actionable()
            ):
                break

        if bootstrap_idx == 0:
            self._record_task_goal(
                f"bootstrap_{bootstrap_round_idx}",
                seed_exports,
                gap_search_tasks=[],
                goal_search_tasks=[],
            )

        return seed_exports

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
        target_deficit_tasks = await self._enqueue_target_deficit_searches(
            round_idx,
            table_rows,
            goal_state,
        )
        return table_gap_tasks, target_deficit_tasks

    def _universe_estimate_ready(self) -> bool:
        return (
            self.goal_universe_estimate.get("status") == "estimated"
            and bool(self.goal_universe_estimate.get("count_targets"))
        )

    def _universe_estimate_actionable(self) -> bool:
        return self._universe_estimate_ready()

    def _table_rows_by_variable(
        self,
        exports: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        table_names = self.config.table_variables or [
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

    @staticmethod
    def _write_table_csv(
        path: Path,
        rows: List[Dict[str, Any]],
        *,
        table_name: str = "",
    ) -> None:
        fieldnames: List[str] = list(TABLE_REQUIRED_COLUMNS.get(table_name, []))
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
            seed_papers: List[Dict[str, Any]] = []
            queries: List[str] = []
            await self._resolve_schema([])
        else:
            self._ensure_search_ready()

            # Round 0 search seeds both the schema and the graph.
            print(
                f"Round {self._round_label(0)}: "
                "seeding search from the question..."
            )
            schema_hint = cfg.schema_name or ""
            queries = await strategy.initial_queries(
                self.llm, cfg.question, n=cfg.queries_per_round, schema_hint=schema_hint
            )
            print(f"  Initial queries: {queries}")
            seed_papers = await self._fetch_papers(
                queries,
                cap=cfg.papers_per_round,
                round_idx=self._round_label(0),
                topic="initial",
                expansion_op="llm_initial",
            )
            print(f"  Fetched {len(seed_papers)} seed papers")

            await self._resolve_schema(seed_papers[:2])

        gaps: List[str] = []
        last_answer = ""
        final_assessment: Dict[str, Any] = {}
        if self.goal_tracker is not None:
            print("  Bootstrapping task-level goal from current tables...")
            seed_exports = await self._bootstrap_task_goal()
            if not self._universe_estimate_actionable():
                final_assessment = {
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
                return self._finalize(last_answer, final_assessment)
            bootstrap_goal_state = self._record_task_goal(
                f"bootstrap_deficit_{self._round_label(0)}",
                seed_exports,
                gap_search_tasks=[],
                goal_search_tasks=[],
            )
            gap_search_tasks, goal_search_tasks = await self._enqueue_deficit_searches(
                self._round_label(0),
                seed_exports,
                bootstrap_goal_state,
            )
            if gap_search_tasks or goal_search_tasks:
                self._record_task_goal(
                    f"bootstrap_deficit_{self._round_label(0)}",
                    seed_exports,
                    gap_search_tasks=gap_search_tasks,
                    goal_search_tasks=goal_search_tasks,
                    update_history=False,
                )

        for local_round_idx in range(cfg.max_rounds):
            round_idx = self._round_label(local_round_idx)
            print(f"\n{'#'*70}\nROUND {round_idx}\n{'#'*70}")

            if local_round_idx == 0 and seeded_from_graph:
                if self.search_frontier.pending_count > 0:
                    queries = []
                    round_papers = await self._fetch_papers(
                        queries,
                        cap=cfg.papers_per_round,
                        round_idx=round_idx,
                        topic="queued",
                        expansion_op="task_frontier",
                    )
                    print(f"  Fetched {len(round_papers)} queued papers")
                else:
                    round_papers = []
                    print("  Reusing seed graph for GASL.")
            elif local_round_idx == 0:
                round_papers = seed_papers
            else:
                if (
                    self.goal_tracker is not None
                    and self.search_frontier.pending_count > 0
                    and self._paper_budget_available()
                ):
                    queries = []
                    round_papers = await self._fetch_papers(
                        queries,
                        cap=cfg.papers_per_round,
                        round_idx=round_idx,
                        topic="queued",
                        expansion_op="task_frontier",
                    )
                    print(f"  Fetched {len(round_papers)} queued papers")
                elif self.goal_tracker is not None:
                    queries = []
                    round_papers = []
                    print("  No queued table-fill searches.")
                    break
                elif self._search_budget_available():
                    self._ensure_search_ready()
                    queries = await strategy.followup_queries(
                        self.llm,
                        cfg.question,
                        current_answer=last_answer,
                        gaps=gaps,
                        top_entities=self._top_entities(),
                        n=cfg.queries_per_round,
                    )
                    print(f"  Follow-up queries: {queries}")
                    round_papers = await self._fetch_papers(
                        queries,
                        cap=cfg.papers_per_round,
                        round_idx=round_idx,
                        topic="followup",
                        expansion_op="llm_followup",
                    )
                    print(f"  Fetched {len(round_papers)} papers")
                else:
                    queries = []
                    round_papers = []
                    print("  No search budget available.")

            if round_papers:
                ingested = await self._ingest_papers(round_papers)
                print(f"  Ingested {ingested} papers -> {self._graph_summary()}")
            elif local_round_idx > 0:
                print("  No new papers this round; stopping search.")

            if (
                self.goal_tracker is not None
                and seeded_from_graph
                and not round_papers
                and self.seed_tables.row_count
            ):
                print(
                    "  No new papers accepted; recording current tables "
                    "without rerunning GASL."
                )
                table_exports = self._write_table_exports(
                    round_idx,
                    self.seed_tables.rows_by_name,
                    seed_row_counts={
                        name: len(rows)
                        for name, rows in self.seed_tables.rows_by_name.items()
                    },
                    new_row_counts={},
                )
                gaps = self._table_gaps(table_exports)
                assessment = {
                    "sufficient": False,
                    "confidence": 0.0,
                    "gaps": gaps,
                    "rationale": (
                        "Table-fill mode controls stopping through exported "
                        "table coverage and task-level stop criteria."
                    ),
                }
                final_assessment = assessment
                await self._estimate_task_goal_universe(
                    round_idx,
                    self._table_rows_by_variable(table_exports),
                    gaps,
                )
                goal_state = self._record_task_goal(
                    round_idx,
                    table_exports,
                    gap_search_tasks=[],
                    goal_search_tasks=[],
                )
                self._annotate_recent_target_outcomes(goal_state)
                round_record = {
                    "round": round_idx,
                    "queries": queries,
                    "papers_ingested": 0,
                    "graph_nodes": self.graph.number_of_nodes(),
                    "graph_edges": self.graph.number_of_edges(),
                    "answer": last_answer,
                    "assessment": assessment,
                    "gasl_iterations": 0,
                    "search_outcomes": self.last_search_batch.outcome_dicts(),
                    "table_exports": table_exports,
                    "derived_table_exports": self.last_derived_table_exports,
                    "gap_search_tasks": [],
                    "goal_search_tasks": [],
                    "task_goal": goal_state.to_dict() if goal_state else None,
                    "skipped_gasl": True,
                    "skip_reason": "no_new_papers",
                }
                self.rounds.append(round_record)
                (self.answers_dir / f"round_{round_idx}.json").write_text(
                    json.dumps(round_record, indent=2, default=str),
                    encoding="utf-8",
                )
                if goal_state is not None:
                    print(
                        "  Task goal: "
                        f"fulfilled={goal_state.fulfilled} "
                        f"targets={len(goal_state.target_estimate.get('count_targets') or [])} "
                        f"unmet={len(goal_state.target_catalog.get('unmet_count_targets') or [])} "
                        f"pending={goal_state.search_frontier['pending_tasks']}"
                    )
                if goal_state is not None and goal_state.fulfilled:
                    print("\n  Task-level stop criteria fulfilled; stopping.")
                    break
                if self.search_frontier.pending_count <= 0:
                    print("\n  Search frontier exhausted; stopping.")
                    break
                continue

            if self.graph.number_of_nodes() == 0:
                print("  Graph is still empty; cannot answer yet.")
                self.rounds.append({"round": round_idx, "papers": len(round_papers), "answer": None})
                if not round_papers:
                    break
                continue

            self._save_graph(round_idx)
            metadata = self._write_metadata()

            print("  Running GASL traversal...")
            gasl_graph = self._gasl_graph_for_round(round_papers)
            if gasl_graph is not self.graph:
                print(
                    "  GASL graph scope: "
                    f"{gasl_graph.number_of_nodes()} nodes, "
                    f"{gasl_graph.number_of_edges()} edges"
                )
            gasl_result = await self._run_gasl(round_idx, metadata, graph=gasl_graph)
            table_exports = self._export_gasl_tables(round_idx, gasl_result)
            last_answer = gasl_result.get("final_answer", "") or ""
            if self.goal_tracker is not None:
                print(
                    "  GASL materialized "
                    f"{len(table_exports)} table export(s) "
                    f"({len(last_answer)} chars of summary text)"
                )
                gaps = self._table_gaps(table_exports)
                assessment = {
                    "sufficient": False,
                    "confidence": 0.0,
                    "gaps": gaps,
                    "rationale": (
                        "Table-fill mode controls stopping through exported "
                        "table coverage and task-level stop criteria."
                    ),
                }
                print(f"  Table gaps: {len(gaps)}")
            else:
                print(f"  Answer ({len(last_answer)} chars): {last_answer[:300]}")
                assessment = await strategy.assess_answer(
                    self.llm,
                    cfg.question,
                    answer=last_answer,
                    graph_summary=self._graph_summary(),
                )
                gaps = [
                    *(assessment.get("gaps", []) or []),
                    *self._table_gaps(table_exports),
                ]
                print(
                    f"  Assessment: sufficient={assessment.get('sufficient')} "
                    f"confidence={assessment.get('confidence')} | gaps={len(gaps)}"
                )
            final_assessment = assessment

            sufficient = bool(assessment.get("sufficient"))
            confident = float(assessment.get("confidence", 0.0) or 0.0) >= cfg.target_confidence
            gap_search_tasks: List[Dict[str, Any]] = []
            goal_search_tasks: List[Dict[str, Any]] = []
            await self._estimate_task_goal_universe(
                round_idx,
                self._table_rows_by_variable(table_exports),
                gaps,
            )
            goal_state = self._record_task_goal(
                round_idx,
                table_exports,
                gap_search_tasks=gap_search_tasks,
                goal_search_tasks=goal_search_tasks,
            )
            self._annotate_recent_target_outcomes(goal_state)

            should_expand_for_goal = (
                goal_state is not None and not goal_state.fulfilled
            )
            should_expand_for_answer = (
                goal_state is None and not (sufficient and confident)
            )
            if self._paper_budget_available() and (
                should_expand_for_goal or should_expand_for_answer
            ):
                table_gap_tasks, target_deficit_tasks = (
                    await self._enqueue_deficit_searches(
                        self._round_label(local_round_idx + 1),
                        table_exports,
                        goal_state,
                    )
                )
                gap_search_tasks.extend(table_gap_tasks)
                goal_search_tasks.extend(target_deficit_tasks)
                if should_expand_for_goal:
                    goal_state = self._record_task_goal(
                        round_idx,
                        table_exports,
                        gap_search_tasks=gap_search_tasks,
                        goal_search_tasks=goal_search_tasks,
                        update_history=False,
                    )

            round_record = {
                "round": round_idx,
                "queries": queries,
                "papers_ingested": len(round_papers),
                "graph_nodes": self.graph.number_of_nodes(),
                "graph_edges": self.graph.number_of_edges(),
                "answer": last_answer,
                "assessment": assessment,
                "gasl_iterations": gasl_result.get("iterations"),
                "search_outcomes": self.last_search_batch.outcome_dicts(),
                "table_exports": table_exports,
                "derived_table_exports": self.last_derived_table_exports,
                "gap_search_tasks": gap_search_tasks,
                "goal_search_tasks": goal_search_tasks,
                "task_goal": goal_state.to_dict() if goal_state else None,
            }
            self.rounds.append(round_record)
            (self.answers_dir / f"round_{round_idx}.json").write_text(
                json.dumps(round_record, indent=2, default=str), encoding="utf-8"
            )

            if goal_state is not None:
                print(
                    "  Task goal: "
                    f"fulfilled={goal_state.fulfilled} "
                    f"targets={len(goal_state.target_estimate.get('count_targets') or [])} "
                    f"unmet={len(goal_state.target_catalog.get('unmet_count_targets') or [])} "
                    f"pending={goal_state.search_frontier['pending_tasks']}"
                )
            if goal_state is not None and goal_state.fulfilled:
                print("\n  Task-level stop criteria fulfilled; stopping.")
                break
            if goal_state is None and sufficient and confident:
                print("\n  Answer is sufficient and confident; stopping.")
                break
            if self.paper_count >= cfg.max_papers:
                print("\n  Reached paper budget; stopping.")
                break

        return self._finalize(last_answer, final_assessment)

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _save_graph(self, round_idx: int) -> None:
        save_graph(self.graphs_dir / f"round_{round_idx}.graphml", self.graph)
        save_graph(self.graphs_dir / "current_graph.graphml", self.graph)

    def _finalize(self, answer: str, assessment: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "question": self.config.question,
            "final_answer": answer,
            "assessment": assessment,
            "rounds": len(self.rounds),
            "papers_fetched": self.paper_count,
            "graph_nodes": self.graph.number_of_nodes(),
            "graph_edges": self.graph.number_of_edges(),
            "schema": self.schema.domain_name if self.schema else None,
            "graph_path": str(self.graphs_dir / "current_graph.graphml"),
            "answer_mode": self.config.answer_mode,
            "table_exports": self.table_exports,
            "derived_table_exports": self.derived_table_exports,
            "search_frontier": self.search_frontier.to_dict(),
            "search_outcomes": self.search_outcomes,
            "search_memory": self.search_memory.to_dict(),
            "task_goals": self.goal_states,
            "goal_universe_estimate": self.goal_universe_estimate,
            "goal_discovery_sources": self.goal_discovery_sources,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "config": self.config.to_dict(),
        }
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
