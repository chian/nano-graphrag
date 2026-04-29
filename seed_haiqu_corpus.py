#!/usr/bin/env python3
"""
HAIQU literature seeding -- Firecrawl-only search strategy.

Runs grouped Firecrawl /v1/search calls (with inline markdown scraping) to
populate a per-group paper corpus that the iterative-search KG pipeline can
then ingest.

Each group is aligned to one or more domain_schemas/* schemas so a graph
build can take a single group as a focused input rather than the whole
corpus at once.

Output layout:
    data/haiqu_corpus/
        corpus_index.json
        <group>/
            metadata.json          # queries used + per-paper records
            papers/
                <uuid>.md          # one paper per file (Firecrawl markdown)

Usage:
    export FIRECRAWL_API_KEY=...
    python seed_haiqu_corpus.py
    python seed_haiqu_corpus.py --groups crispr_microfluidic_diagnostics hvac_engineering_controls
    python seed_haiqu_corpus.py --max-per-query 20 --output-dir data/my_corpus
    python seed_haiqu_corpus.py --dry-run               # show queries, no API calls
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import requests

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

# Reuse the repo's domain allow/block lists and markdown extractor.
from paper_fetching.firecrawl_client import (  # noqa: E402
    SCIENTIFIC_DOMAINS,
    EXCLUDED_DOMAINS,
    extract_text_from_result,
)

FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v1/search"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SearchQuery:
    """One Firecrawl /search call within a group.

    `tbs` is Google's time-based filter and is passed straight through:
        qdr:m  -> past month
        qdr:y  -> past year
    """
    query: str
    tbs: Optional[str] = None
    notes: str = ""


@dataclass
class PaperGroup:
    """One HAIQU grant question class + its search queries + its schema."""
    name: str                    # folder-safe slug (also the schema name)
    question: str                # the specific HAIQU question this answers
    schema: str                  # exactly one domain_schema name
    queries: List[SearchQuery] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The HAIQU corpus definition
# ---------------------------------------------------------------------------

# `site:` operators restrict each query to publishers we trust. The
# firecrawl_client.SCIENTIFIC_DOMAINS / EXCLUDED_DOMAINS lists then re-filter
# results post-search. A few `tbs=qdr:y` queries serve as the live-frontier
# layer; flip to qdr:m for a weekly continuous-feed run.

GROUPS: List[PaperGroup] = [
    PaperGroup(
        name="haiqu_biosensor_detection",
        question=(
            "Can microfluidic droplet CRISPR biosensors detect pathogenic agents "
            "in hospital air, and at what limits?"
        ),
        schema="haiqu_biosensor_detection",
        queries=[
            SearchQuery(
                "microfluidic droplet CRISPR Cas13 airborne pathogen detection "
                "limit of detection site:pubmed.ncbi.nlm.nih.gov OR site:nature.com OR site:cell.com"
            ),
            SearchQuery(
                "SHERLOCK DETECTR CRISPR biosensor aerosol pathogen hospital "
                "site:pubmed.ncbi.nlm.nih.gov OR site:biorxiv.org",
                tbs="qdr:y",
            ),
            SearchQuery(
                "Cas13a Cas12a airborne virus detection sensitivity specificity "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com"
            ),
            SearchQuery(
                "digital droplet PCR airborne respiratory pathogen quantification "
                "hospital site:pubmed.ncbi.nlm.nih.gov OR site:plos.org"
            ),
            SearchQuery(
                "isothermal amplification RPA LAMP airborne pathogen point-of-care "
                "site:pubmed.ncbi.nlm.nih.gov OR site:biorxiv.org"
            ),
            SearchQuery(
                "biosensor validation aerosol spiked chamber clinical specimen "
                "respiratory pathogen site:pubmed.ncbi.nlm.nih.gov"
            ),
        ],
    ),
    PaperGroup(
        name="haiqu_aerosol_exposure",
        question=(
            "What pathogens are present in hospital air, at what concentrations, "
            "and under what environmental conditions?"
        ),
        schema="haiqu_aerosol_exposure",
        queries=[
            SearchQuery(
                "bioaerosol sampling hospital airborne pathogen concentration "
                "site:pubmed.ncbi.nlm.nih.gov OR site:ncbi.nlm.nih.gov/pmc"
            ),
            SearchQuery(
                "SARS-CoV-2 airborne concentration hospital sampling impactor cyclone "
                "site:pubmed.ncbi.nlm.nih.gov OR site:medrxiv.org OR site:biorxiv.org",
                tbs="qdr:y",
            ),
            SearchQuery(
                "aerosol viability respiratory pathogen relative humidity temperature "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com"
            ),
            SearchQuery(
                "particle size distribution respiratory aerosol droplet nucleus "
                "hospital infection site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "Mycobacterium tuberculosis Aspergillus airborne hospital sampling "
                "concentration CFU copies site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "influenza RSV MRSA airborne hospital environmental sampling "
                "site:pubmed.ncbi.nlm.nih.gov OR site:cdc.gov"
            ),
        ],
    ),
    PaperGroup(
        name="haiqu_hospital_environment",
        question=(
            "How does hospital room configuration and HVAC design affect "
            "airborne pathogen distribution?"
        ),
        schema="haiqu_hospital_environment",
        queries=[
            SearchQuery(
                "hospital HVAC design airborne pathogen distribution air changes "
                "site:pubmed.ncbi.nlm.nih.gov OR site:ashrae.org"
            ),
            SearchQuery(
                "negative pressure isolation room AIIR airborne infection control "
                "site:pubmed.ncbi.nlm.nih.gov OR site:cdc.gov"
            ),
            SearchQuery(
                "operating room ventilation airflow pathogen contamination "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "tracer gas air distribution hospital ward CFD airflow "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com"
            ),
            SearchQuery(
                "hospital room configuration recirculation dead zone infection "
                "site:pubmed.ncbi.nlm.nih.gov",
                tbs="qdr:y",
            ),
            SearchQuery(
                "ASHRAE 170 ventilation healthcare facility infection control "
                "site:ashrae.org OR site:pubmed.ncbi.nlm.nih.gov"
            ),
        ],
    ),
    PaperGroup(
        name="haiqu_engineering_controls",
        question=(
            "Which engineering controls reduce airborne pathogen exposure "
            "and by how much?"
        ),
        schema="haiqu_engineering_controls",
        queries=[
            SearchQuery(
                "upper room UV-C UVGI airborne tuberculosis disinfection efficacy "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "HEPA portable air cleaner hospital airborne pathogen reduction "
                "site:pubmed.ncbi.nlm.nih.gov OR site:biorxiv.org",
                tbs="qdr:y",
            ),
            SearchQuery(
                "engineering control airborne infection reduction hospital "
                "log reduction effectiveness site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "increased ventilation ACH airborne infection risk reduction "
                "site:pubmed.ncbi.nlm.nih.gov OR site:plos.org"
            ),
            SearchQuery(
                "source control masking N95 respirator airborne hospital "
                "site:pubmed.ncbi.nlm.nih.gov OR site:cdc.gov"
            ),
            SearchQuery(
                "UV-C HEPA ventilation combined effectiveness hospital "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
        ],
    ),
    PaperGroup(
        name="haiqu_transmission_risk",
        question=(
            "What models predict real-time disease transmission risk from "
            "environmental measurements?"
        ),
        schema="haiqu_transmission_risk",
        queries=[
            SearchQuery(
                "Wells-Riley airborne infection risk model hospital real-time "
                "site:pubmed.ncbi.nlm.nih.gov OR site:plos.org"
            ),
            SearchQuery(
                "quantitative microbial risk assessment QMRA airborne hospital "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "agent-based model nosocomial airborne transmission hospital simulation "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com"
            ),
            SearchQuery(
                "digital twin hospital airborne transmission risk prediction "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com",
                tbs="qdr:y",
            ),
            SearchQuery(
                "CO2 rebreathed air fraction proxy infection risk indoor "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "dose-response model airborne pathogen infection probability "
                "site:pubmed.ncbi.nlm.nih.gov OR site:plos.org"
            ),
        ],
    ),
    PaperGroup(
        name="haiqu_cognitive_impact",
        question=(
            "How do respiratory infections affect cognitive function in "
            "healthcare workers?"
        ),
        schema="haiqu_cognitive_impact",
        queries=[
            SearchQuery(
                "post-COVID cognitive impairment healthcare worker "
                "neuropsychological assessment site:pubmed.ncbi.nlm.nih.gov OR site:nature.com"
            ),
            SearchQuery(
                "long COVID cognitive function executive memory processing speed "
                "longitudinal site:pubmed.ncbi.nlm.nih.gov OR site:medrxiv.org",
                tbs="qdr:y",
            ),
            SearchQuery(
                "respiratory infection cognitive deficit attention working memory "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "neuropsychological test healthcare worker respiratory infection "
                "cognitive outcome site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "ICU healthcare worker cognitive sequelae occupational exposure "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_search(api_key: str, q: SearchQuery, max_results: int) -> List[dict]:
    """POST /v1/search; return scientific-domain results (with inline markdown)."""
    payload: dict = {
        "query": q.query,
        "limit": max_results,
        "scrapeOptions": {"formats": ["markdown"]},
    }
    if q.tbs:
        payload["tbs"] = q.tbs
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(FIRECRAWL_SEARCH_URL, headers=headers,
                          json=payload, timeout=180)
        r.raise_for_status()
        data = r.json().get("data", [])
    except requests.exceptions.RequestException as e:
        print(f"     ! Firecrawl error: {e}")
        return []

    out = []
    for hit in data:
        url = (hit.get("url") or "").lower()
        if any(d in url for d in EXCLUDED_DOMAINS):
            continue
        if not any(d in url for d in SCIENTIFIC_DOMAINS):
            continue
        out.append(hit)
    return out


def save_paper(result: dict, dest_dir: Path,
               source_query: str, tbs: Optional[str]) -> dict:
    """Save the paper's markdown body; return its metadata record."""
    paper_uuid = str(uuid.uuid4())
    body = extract_text_from_result(result, format="markdown")
    out_path = dest_dir / f"{paper_uuid}.md"
    out_path.write_text(body, encoding="utf-8")
    md = result.get("metadata") or {}
    return {
        "uuid": paper_uuid,
        "title": md.get("title") or result.get("title", "(unknown)"),
        "url": result.get("url", ""),
        "description": md.get("description", ""),
        "language": md.get("language", ""),
        "source_query": source_query,
        "tbs": tbs,
        "downloaded_at": datetime.utcnow().isoformat() + "Z",
        "content_file": out_path.name,
        "content_chars": len(body),
    }


def run_group(g: PaperGroup, api_key: Optional[str], root: Path,
              max_per_query: int, dry_run: bool) -> dict:
    print(f"\n=== {g.name} ===")
    print(f"  Q: {g.question}")
    print(f"  schema: {g.schema}")
    print(f"  queries: {len(g.queries)}")

    if dry_run:
        for i, q in enumerate(g.queries, 1):
            tag = f" [tbs={q.tbs}]" if q.tbs else ""
            print(f"    {i:>2}.{tag} {q.query}")
        return {"group": g.name, "dry_run": True}

    group_dir = root / g.name
    papers_dir = group_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    seen_urls: set = set()
    saved: List[dict] = []
    queries_log: List[dict] = []

    for i, q in enumerate(g.queries, 1):
        head = q.query[:80] + ("..." if len(q.query) > 80 else "")
        print(f"  [{i}/{len(g.queries)}] {head}")
        hits = run_search(api_key, q, max_per_query)
        kept = 0
        for h in hits:
            u = (h.get("url") or "").strip()
            if not u or u in seen_urls:
                continue
            seen_urls.add(u)
            saved.append(save_paper(h, papers_dir, q.query, q.tbs))
            kept += 1
        queries_log.append({
            "query": q.query,
            "tbs": q.tbs,
            "notes": q.notes,
            "raw_hits": len(hits),
            "saved_unique": kept,
        })
        print(f"     hits={len(hits)}  saved_new={kept}  "
              f"running_total={len(saved)}")
        time.sleep(1)  # gentle to the API

    metadata = {
        "group": g.name,
        "question": g.question,
        "schema": g.schema,
        "ran_at": datetime.utcnow().isoformat() + "Z",
        "max_per_query": max_per_query,
        "queries": queries_log,
        "paper_count": len(saved),
        "papers": saved,
    }
    (group_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"  -> {group_dir/'metadata.json'} ({len(saved)} unique papers)")
    return {"group": g.name, "paper_count": len(saved)}


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--api-key", default=os.getenv("FIRECRAWL_API_KEY"),
                   help="Firecrawl API key (or set FIRECRAWL_API_KEY)")
    p.add_argument("--output-dir", default="data/haiqu_corpus",
                   help="Root output directory (default: data/haiqu_corpus)")
    p.add_argument("--max-per-query", type=int, default=10,
                   help="Max results per query (default 10)")
    p.add_argument("--groups", nargs="*",
                   help="Only run these group names (default: all)")
    p.add_argument("--list-groups", action="store_true",
                   help="List the available groups and exit")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the queries but make no API calls")
    args = p.parse_args()

    if args.list_groups:
        for g in GROUPS:
            print(f"{g.name:<32} schema: {g.schema:<32} {len(g.queries)} queries")
            print(f"  Q: {g.question}")
        return

    if not args.dry_run and not args.api_key:
        sys.exit("ERROR: FIRECRAWL_API_KEY not set and --api-key not provided")

    selected = GROUPS
    if args.groups:
        wanted = set(args.groups)
        selected = [g for g in GROUPS if g.name in wanted]
        unknown = wanted - {g.name for g in GROUPS}
        if unknown:
            sys.exit(f"unknown group(s): {sorted(unknown)}")

    root = Path(args.output_dir)
    if not args.dry_run:
        root.mkdir(parents=True, exist_ok=True)

    print(f"output:    {root}")
    print(f"groups:    {[g.name for g in selected]}")
    print(f"max/query: {args.max_per_query}")
    print(f"dry-run:   {args.dry_run}")

    summaries = [run_group(g, args.api_key, root,
                           args.max_per_query, args.dry_run)
                 for g in selected]

    if not args.dry_run:
        index = {
            "ran_at": datetime.utcnow().isoformat() + "Z",
            "output_dir": str(root),
            "max_per_query": args.max_per_query,
            "groups": summaries,
        }
        (root / "corpus_index.json").write_text(
            json.dumps(index, indent=2), encoding="utf-8")
        print(f"\n-> top-level index: {root/'corpus_index.json'}")


if __name__ == "__main__":
    main()
