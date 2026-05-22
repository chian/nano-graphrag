"""
Graph metadata — captures the domain expertise, search strategy, and source coverage
of a knowledge graph so that empty query results can be interpreted correctly.

At build time: call save_graph_metadata(output_dir, metadata_dict).
At query time: the adapter loads it; _build_expertise_context() folds it in.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


METADATA_FILENAME = "graph_metadata.json"


def build_metadata(
    *,
    kg_id: str,
    kg_version: str,
    domain_name: str,
    domain_description: str,
    guiding_question: str,
    entity_types: List[Dict[str, str]],
    relationship_types: List[Dict[str, str]],
    search_queries: List[str],
    search_sources: List[str],
    paper_count: int,
    scope_in: List[str],
    scope_out: List[str],
    notes: str = "",
    built_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a metadata dict ready for serialisation."""
    return {
        "kg_id": kg_id,
        "kg_version": kg_version,
        "built_at": built_at or datetime.now(timezone.utc).isoformat(),
        "domain": {
            "name": domain_name,
            "description": domain_description,
            "guiding_question": guiding_question,
        },
        "schema": {
            "entity_types": entity_types,
            "relationship_types": relationship_types,
        },
        "search_strategy": {
            "queries": search_queries,
            "sources": search_sources,
        },
        "corpus_stats": {
            "paper_count": paper_count,
        },
        "scope": {
            "in_scope": scope_in,
            "out_of_scope": scope_out,
        },
        "notes": notes,
    }


def save_graph_metadata(output_dir: str | Path, metadata: Dict[str, Any]) -> Path:
    """Write metadata to <output_dir>/graph_metadata.json."""
    path = Path(output_dir) / METADATA_FILENAME
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
    return path


def load_graph_metadata(graph_dir: str | Path) -> Optional[Dict[str, Any]]:
    """Load graph_metadata.json from the directory containing a graph file.
    Returns None if the file does not exist.
    """
    path = Path(graph_dir) / METADATA_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def metadata_from_schema_and_corpus(
    *,
    kg_id: str,
    kg_version: str,
    schema,          # DomainSchema instance
    corpus_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Convenience builder that pulls directly from a DomainSchema + corpus metadata.json dict."""
    entity_types = [
        {"name": name, "description": et.description}
        for name, et in schema.entity_types.items()
    ]
    relationship_types = [
        {"name": name, "description": rt.description}
        for name, rt in schema.relationship_types.items()
    ]

    queries = [q.get("query", "") for q in corpus_metadata.get("queries", [])]
    # Derive unique source domains from query strings (site: filters)
    import re
    sources: list[str] = []
    for q in queries:
        for site in re.findall(r"site:([\w.\-]+)", q):
            if site not in sources:
                sources.append(site)
    if not sources:
        sources = ["pubmed.ncbi.nlm.nih.gov"]

    paper_count = corpus_metadata.get("paper_count", 0)
    guiding_question = corpus_metadata.get("question", "")

    # Build scope summaries from entity/relationship type names
    scope_in = [f"{et['name']}: {et['description']}" for et in entity_types]
    scope_out: list[str] = []  # caller can append domain-specific exclusions

    return build_metadata(
        kg_id=kg_id,
        kg_version=kg_version,
        domain_name=schema.domain_name,
        domain_description=schema.domain_description,
        guiding_question=guiding_question,
        entity_types=entity_types,
        relationship_types=relationship_types,
        search_queries=queries,
        search_sources=sources,
        paper_count=paper_count,
        scope_in=scope_in,
        scope_out=scope_out,
        notes="Generated automatically at build time from domain schema and corpus metadata.",
    )
