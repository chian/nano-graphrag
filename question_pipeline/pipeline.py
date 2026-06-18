"""Question-driven iterative GraphRAG pipeline orchestrator.

One question in; one well-supported answer out. Each round searches the web,
extends a typed knowledge graph, answers the question with GASL, and uses the
identified gaps to steer the next search.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import uuid
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
from gasl.llm import ArgoBridgeLLM
from graph_metadata import build_metadata, save_graph_metadata
from hpc.common import save_graph
from nano_graphrag.entity_extraction.typed_module import (
    create_domain_extractor_from_schema,
)
from paper_fetching.firecrawl_client import (
    extract_text_from_result,
    search_papers,
)

from . import schema_synthesis, strategy
from .extraction import enrich_graph, extract_from_text


@dataclass
class PipelineConfig:
    question: str
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

    # Extraction / merge
    chunk_size: int = 2000
    chunk_overlap: int = 200
    extraction_concurrency: int = 1
    similarity_threshold: float = 0.85
    auto_merge_entities: bool = True
    self_refine: bool = False

    # GASL
    max_gasl_iterations: int = 8
    answer_mode: str = "natural"
    table_variables: List[str] = field(
        default_factory=lambda: [
            "disease_id50_r0_table",
            "country_r0_table",
        ]
    )

    # Stopping
    target_confidence: float = 0.75

    # LLM
    model: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


TABLE_ANSWER_INSTRUCTIONS = """
Materialize normalized tables instead of treating prose as the deliverable.

Produce these exact LIST variables:

1. disease_id50_r0_table
   One row per disease/pathogen with any infectious-dose-like evidence and any
   R0, Rt, or Re evidence connected through disease, pathogen, strain, host,
   exposure route, country, source, or comparison paths.

   Required columns: disease, pathogen, strain_or_variant,
   infectious_dose_measure, infectious_dose_value, infectious_dose_unit,
   infectious_dose_route, infectious_dose_host, reproduction_measure_type,
   r0_value, r0_range, country, time_period, relationship, source_refs,
   source_chunks, evidence_gap.

2. country_r0_table
   One row per country-specific reproduction-number record.

   Required columns: disease, pathogen, country, reproduction_measure_type,
   r0_value, r0_range, time_period, model_or_method,
   intervention_context, behavioral_or_condition_factor, source_refs,
   source_chunks, evidence_gap.

Use FIND, GRAPHWALK, PROJECT, COLLAPSE, and PROCESS to produce only those exact
table variables. Do not declare or PROCESS schema-contract, summary-count, or
bookkeeping variables; the runner validates and exports these tables directly.
When a path table needs multiple relationship types, issue one GRAPHWALK whose
follow clause joins all needed edge labels with |. Do not issue multiple
GRAPHWALK commands AS the same variable; AS replaces rather than appends.
Normalize table rows directly into disease_id50_r0_table and country_r0_table;
every PROCESS that creates or updates either final table must end with
AS disease_id50_r0_table or AS country_r0_table in the GASL command itself.
Do not SELECT into current_output_symbol or COLLAPSE a scratch variable into a
final table, because that discards the normalized required columns.
Preserve source_refs and source_chunks. Keep rows even when a numeric field is
missing, and explain the missing field in evidence_gap. Before any COLLAPSE BY
a deduplication key, create a non-empty deduplication key on every candidate
row; otherwise collapse only after required columns exist. Once both tables are
materialized, run SHOW on each table only. The final answer should be a short
summary of how many complete and partial rows were materialized.
""".strip()


TABLE_REQUIRED_COLUMNS = {
    "disease_id50_r0_table": [
        "disease",
        "pathogen",
        "strain_or_variant",
        "infectious_dose_measure",
        "infectious_dose_value",
        "infectious_dose_unit",
        "infectious_dose_route",
        "infectious_dose_host",
        "reproduction_measure_type",
        "r0_value",
        "r0_range",
        "country",
        "time_period",
        "relationship",
        "source_refs",
        "source_chunks",
        "evidence_gap",
    ],
    "country_r0_table": [
        "disease",
        "pathogen",
        "country",
        "reproduction_measure_type",
        "r0_value",
        "r0_range",
        "time_period",
        "model_or_method",
        "intervention_context",
        "behavioral_or_condition_factor",
        "source_refs",
        "source_chunks",
        "evidence_gap",
    ],
}


class QuestionPipeline:
    """Iterative search + KG build + GASL answer loop for one question."""

    def __init__(
        self,
        config: PipelineConfig,
        *,
        llm=None,
        search_fn: Optional[Callable[[str, int], List[Dict[str, Any]]]] = None,
        extractor_factory: Optional[Callable[[DomainSchema], Any]] = None,
        gasl_runner: Optional[Callable[[nx.DiGraph, Dict[str, Any], str], Dict[str, Any]]] = None,
    ):
        self.config = config
        if llm is not None:
            self.llm = llm
        elif config.model:
            self.llm = ArgoBridgeLLM(model=config.model)
        else:
            self.llm = ArgoBridgeLLM()
        self._search_fn = search_fn or self._default_search_fn
        self._uses_default_search = search_fn is None
        self._extractor_factory = extractor_factory or self._default_extractor_factory
        self._gasl_runner = gasl_runner or self._default_gasl_runner

        self.out = Path(config.output_dir)
        self.graphs_dir = self.out / "graphs"
        self.papers_dir = self.out / "fetched_papers"
        self.answers_dir = self.out / "answers"
        self.tables_dir = self.answers_dir / "tables"
        for d in (self.graphs_dir, self.papers_dir, self.answers_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.graph = nx.DiGraph()
        self.schema: Optional[DomainSchema] = None
        self.extractor = None
        self.seen_urls: set[str] = set()
        self.queries_used: List[str] = []
        self.paper_count = 0
        self.rounds: List[Dict[str, Any]] = []
        self.table_exports: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Default real dependencies (swappable for tests)
    # ------------------------------------------------------------------ #
    def _default_search_fn(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        api_key = self.config.firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY")
        if not api_key:
            raise RuntimeError(
                "No Firecrawl API key. Set --firecrawl-api-key or FIRECRAWL_API_KEY."
            )
        return search_papers(query=query, api_key=api_key, max_results=max_results)

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
        return f"{self.config.question}\n\nTABLE ANSWER MODE:\n{TABLE_ANSWER_INSTRUCTIONS}"

    def _search_budget_available(self) -> bool:
        return (
            self.paper_count < self.config.max_papers
            and self.config.papers_per_round > 0
            and self.config.papers_per_query > 0
            and self.config.queries_per_round > 0
        )

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
    def _fetch_papers(self, queries: List[str], cap: int) -> List[Dict[str, Any]]:
        """Search each query, dedup by URL, save text, respect global cap."""
        fetched: List[Dict[str, Any]] = []
        for query in queries:
            if len(fetched) >= cap or self.paper_count >= self.config.max_papers:
                break
            self.queries_used.append(query)
            try:
                results = self._search_fn(query, self.config.papers_per_query)
            except Exception as exc:  # noqa: BLE001
                print(f"    [search] '{query}' failed: {exc}")
                continue
            for result in results:
                if len(fetched) >= cap or self.paper_count >= self.config.max_papers:
                    break
                url = result.get("url", "")
                if url and url in self.seen_urls:
                    continue
                text = extract_text_from_result(result)
                if len(text) < self.config.min_paper_length:
                    continue
                if (
                    self.config.max_paper_length is not None
                    and len(text) > self.config.max_paper_length
                ):
                    continue
                if url:
                    self.seen_urls.add(url)
                paper_id = str(uuid.uuid4())
                (self.papers_dir / f"{paper_id}.txt").write_text(text, encoding="utf-8")
                self.paper_count += 1
                fetched.append(
                    {
                        "id": paper_id,
                        "text": text,
                        "url": url,
                        "title": result.get("title", ""),
                        "source_query": query,
                    }
                )
        return fetched

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

    async def _run_gasl(self, round_idx: int, metadata: Dict[str, Any]) -> Dict[str, Any]:
        state_file = str(self.answers_dir / f"round_{round_idx}_gasl_state.json")
        # GASL is synchronous and chatty; run it off the event loop.
        return await asyncio.to_thread(
            self._gasl_runner, self.graph, metadata, state_file
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

    def _export_gasl_tables(
        self, round_idx: int, gasl_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        if self.config.answer_mode != "table":
            return []

        final_state = gasl_result.get("final_state") or {}
        variables = final_state.get("variables") or {}
        table_names = set(self.config.table_variables)
        exports: List[Dict[str, Any]] = []

        for name, variable in variables.items():
            if not (
                isinstance(variable, dict)
                and variable.get("_meta", {}).get("type") == "LIST"
                and (name in table_names or name.endswith("_table"))
            ):
                continue

            raw_items = variable.get("items") or []
            if not isinstance(raw_items, list):
                continue
            items = self._table_export_rows(name, raw_items)

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
                "json_path": str(json_path),
                "csv_path": str(csv_path) if csv_written else None,
                "validation": self._validate_table(name, items),
            }
            exports.append(record)
            self.table_exports.append(record)

        if exports:
            manifest_path = self.tables_dir / f"round_{round_idx}_manifest.json"
            manifest_path.write_text(
                json.dumps(exports, indent=2, default=str), encoding="utf-8"
            )

        return exports

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
            **{column: row.get(column, "") for column in TABLE_REQUIRED_COLUMNS.get(name, [])},
            **row,
        }

    @classmethod
    def _validate_table(cls, name: str, rows: List[Any]) -> Dict[str, Any]:
        required = TABLE_REQUIRED_COLUMNS.get(name, [])
        row_dicts = [row for row in rows if isinstance(row, dict)]
        missing_by_column = {
            column: sum(1 for row in row_dicts if cls._is_missing(row.get(column)))
            for column in required
        }
        complete_rows = sum(
            1
            for row in row_dicts
            if all(not cls._is_missing(row.get(column)) for column in required)
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
        for table_name in self.config.table_variables:
            export = by_variable.get(table_name)
            if export is None:
                gaps.append(f"{table_name} was not materialized.")
                continue

            validation = export.get("validation") or {}
            if not validation.get("rows"):
                gaps.append(f"{table_name} was materialized with zero rows.")

            missing = validation.get("missing_by_column") or {}
            rows = validation.get("dict_rows") or validation.get("rows") or 0
            for column, count in sorted(missing.items(), key=lambda item: -item[1])[:5]:
                gaps.append(f"{table_name} is missing {column} in {count}/{rows} rows.")

        return gaps

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

        seeded_from_graph = self._load_seed_graph()

        if seeded_from_graph:
            seed_papers: List[Dict[str, Any]] = []
            queries: List[str] = []
            await self._resolve_schema([])
        else:
            self._ensure_search_ready()

            # Round 0 search seeds both the schema and the graph.
            print("Round 0: seeding search from the question...")
            schema_hint = cfg.schema_name or ""
            queries = await strategy.initial_queries(
                self.llm, cfg.question, n=cfg.queries_per_round, schema_hint=schema_hint
            )
            print(f"  Initial queries: {queries}")
            seed_papers = self._fetch_papers(queries, cap=cfg.papers_per_round)
            print(f"  Fetched {len(seed_papers)} seed papers")

            await self._resolve_schema(seed_papers[:2])

        gaps: List[str] = []
        last_answer = ""
        final_assessment: Dict[str, Any] = {}

        for round_idx in range(cfg.max_rounds):
            print(f"\n{'#'*70}\nROUND {round_idx}\n{'#'*70}")

            if round_idx == 0 and seeded_from_graph:
                round_papers = []
                print("  Reusing seed graph; running GASL before new search.")
            elif round_idx == 0:
                round_papers = seed_papers
            else:
                if self._search_budget_available():
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
                    round_papers = self._fetch_papers(queries, cap=cfg.papers_per_round)
                    print(f"  Fetched {len(round_papers)} papers")
                else:
                    queries = []
                    round_papers = []
                    print("  No search budget available.")

            if round_papers:
                ingested = await self._ingest_papers(round_papers)
                print(f"  Ingested {ingested} papers -> {self._graph_summary()}")
            elif round_idx > 0:
                print("  No new papers this round; stopping search.")

            if self.graph.number_of_nodes() == 0:
                print("  Graph is still empty; cannot answer yet.")
                self.rounds.append({"round": round_idx, "papers": len(round_papers), "answer": None})
                if not round_papers:
                    break
                continue

            self._save_graph(round_idx)
            metadata = self._write_metadata()

            print("  Running GASL traversal...")
            gasl_result = await self._run_gasl(round_idx, metadata)
            table_exports = self._export_gasl_tables(round_idx, gasl_result)
            last_answer = gasl_result.get("final_answer", "") or ""
            print(f"  Answer ({len(last_answer)} chars): {last_answer[:300]}")

            assessment = await strategy.assess_answer(
                self.llm,
                cfg.question,
                answer=last_answer,
                graph_summary=self._graph_summary(),
            )
            gaps = assessment.get("gaps", []) or []
            gaps = [*gaps, *self._table_gaps(table_exports)]
            final_assessment = assessment
            print(
                f"  Assessment: sufficient={assessment.get('sufficient')} "
                f"confidence={assessment.get('confidence')} | gaps={len(gaps)}"
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
                "table_exports": table_exports,
            }
            self.rounds.append(round_record)
            (self.answers_dir / f"round_{round_idx}.json").write_text(
                json.dumps(round_record, indent=2, default=str), encoding="utf-8"
            )

            sufficient = bool(assessment.get("sufficient"))
            confident = float(assessment.get("confidence", 0.0) or 0.0) >= cfg.target_confidence
            if sufficient and confident:
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
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "config": self.config.to_dict(),
        }
        (self.out / "final_answer.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
        print(f"\n{'='*70}\nFINAL ANSWER\n{'='*70}\n{answer}\n")
        print(f"Saved: {self.out / 'final_answer.json'}")
        return result
