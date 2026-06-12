"""Question-driven iterative GraphRAG pipeline orchestrator.

One question in; one well-supported answer out. Each round searches the web,
extends a typed knowledge graph, answers the question with GASL, and uses the
identified gaps to steer the next search.
"""

from __future__ import annotations

import asyncio
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

    # Extraction / merge
    chunk_size: int = 2000
    chunk_overlap: int = 200
    similarity_threshold: float = 0.85
    auto_merge_entities: bool = True
    self_refine: bool = False

    # GASL
    max_gasl_iterations: int = 8

    # Stopping
    target_confidence: float = 0.75

    # LLM
    model: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


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
        for d in (self.graphs_dir, self.papers_dir, self.answers_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.graph = nx.DiGraph()
        self.schema: Optional[DomainSchema] = None
        self.extractor = None
        self.seen_urls: set[str] = set()
        self.queries_used: List[str] = []
        self.paper_count = 0
        self.rounds: List[Dict[str, Any]] = []

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
        executor = GASLExecutor(adapter, self.llm, state_file)
        return executor.run_hypothesis_driven_traversal(
            self.config.question, self.config.max_gasl_iterations
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

    async def run(self) -> Dict[str, Any]:
        cfg = self.config
        print(f"\n{'='*70}\nQuestion-driven pipeline\n{'='*70}")
        print(f"Question: {cfg.question}\nOutput:   {self.out}\n")

        if self._uses_default_search and not (
            cfg.firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY")
        ):
            raise RuntimeError(
                "No Firecrawl API key. This pipeline searches the web every round; "
                "set --firecrawl-api-key or the FIRECRAWL_API_KEY env var."
            )

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

            if round_idx == 0:
                round_papers = seed_papers
            else:
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
            last_answer = gasl_result.get("final_answer", "") or ""
            print(f"  Answer ({len(last_answer)} chars): {last_answer[:300]}")

            assessment = await strategy.assess_answer(
                self.llm,
                cfg.question,
                answer=last_answer,
                graph_summary=self._graph_summary(),
            )
            gaps = assessment.get("gaps", []) or []
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
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "config": self.config.to_dict(),
        }
        (self.out / "final_answer.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
        print(f"\n{'='*70}\nFINAL ANSWER\n{'='*70}\n{answer}\n")
        print(f"Saved: {self.out / 'final_answer.json'}")
        return result
