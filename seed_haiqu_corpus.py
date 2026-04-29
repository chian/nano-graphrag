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
    """A topic-cohesive group of queries + a destination folder name."""
    name: str                           # folder-safe slug
    description: str
    schema_alignment: List[str]         # which domain_schemas/* this feeds
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
        name="bioaerosols_and_air_sampling",
        description=(
            "Bioaerosol sampling instrumentation, airborne pathogen detection in "
            "indoor / hospital air, particle size + viability biology."
        ),
        schema_alignment=["air_quality_exposure", "infectious_disease"],
        queries=[
            SearchQuery(
                "bioaerosol sampler hospital airborne pathogen detection "
                "site:pubmed.ncbi.nlm.nih.gov OR site:ncbi.nlm.nih.gov/pmc "
                "OR site:nature.com"
            ),
            SearchQuery(
                "cyclone impactor air sampling SARS-CoV-2 hospital "
                "site:biorxiv.org OR site:medrxiv.org "
                "OR site:pubmed.ncbi.nlm.nih.gov",
                tbs="qdr:y",
                notes="time-windowed past-year preprints+pubs",
            ),
            SearchQuery(
                "aerosol viability respiratory virus relative humidity decay "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com OR site:cell.com"
            ),
            SearchQuery(
                "particle size distribution respiratory droplets aerosol indoor "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com"
            ),
            SearchQuery(
                "airborne tuberculosis Mycobacterium tuberculosis aerosol detection "
                "site:pubmed.ncbi.nlm.nih.gov OR site:plos.org"
            ),
            SearchQuery(
                "Aspergillus airborne hospital sampling environmental "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com"
            ),
        ],
    ),
    PaperGroup(
        name="crispr_microfluidic_diagnostics",
        description=(
            "CRISPR-based pathogen detection (Cas13/Cas12, SHERLOCK, DETECTR), "
            "microfluidic droplet platforms, isothermal amplification."
        ),
        schema_alignment=[
            "biosensor_measurement", "molecular_biology", "clinical_microbiology",
        ],
        queries=[
            SearchQuery(
                "microfluidic droplet CRISPR Cas13 pathogen detection "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com OR site:cell.com"
            ),
            SearchQuery(
                "SHERLOCK DETECTR isothermal amplification airborne virus "
                "site:pubmed.ncbi.nlm.nih.gov OR site:biorxiv.org",
                tbs="qdr:y",
            ),
            SearchQuery(
                "Cas12a Cas13a pathogen diagnostic limit of detection clinical "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com"
            ),
            SearchQuery(
                "digital droplet PCR ddPCR airborne respiratory virus quantification "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com OR site:plos.org"
            ),
            SearchQuery(
                "point-of-care rapid pathogen detection microfluidic clinical validation "
                "site:pubmed.ncbi.nlm.nih.gov OR site:cell.com"
            ),
            SearchQuery(
                "droplet microfluidics single-molecule pathogen amplification "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com"
            ),
        ],
    ),
    PaperGroup(
        name="hvac_engineering_controls",
        description=(
            "HVAC, ventilation rates (ACH), HEPA filtration, upper-room UV-C, "
            "isolation pressure, and other engineering controls in healthcare "
            "facilities."
        ),
        schema_alignment=["built_environment", "engineering_control"],
        queries=[
            SearchQuery(
                "hospital ventilation airborne infection control air changes per hour "
                "site:pubmed.ncbi.nlm.nih.gov OR site:ashrae.org"
            ),
            SearchQuery(
                "upper room UV-C tuberculosis disinfection healthcare clinical "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "HEPA filtration portable air cleaner hospital SARS-CoV-2 "
                "site:pubmed.ncbi.nlm.nih.gov OR site:biorxiv.org",
                tbs="qdr:y",
            ),
            SearchQuery(
                "negative pressure airborne infection isolation room AIIR ventilation "
                "site:pubmed.ncbi.nlm.nih.gov OR site:cdc.gov"
            ),
            SearchQuery(
                "ASHRAE 170 healthcare ventilation infection control standard "
                "site:ashrae.org OR site:cdc.gov OR site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "operating room ventilation surgical site infection airflow "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
        ],
    ),
    PaperGroup(
        name="transmission_modeling",
        description=(
            "Risk models for airborne transmission in healthcare: Wells-Riley + "
            "extensions, QMRA, agent-based hospital simulations, digital twins."
        ),
        schema_alignment=["transmission_risk_model", "epidemiology"],
        queries=[
            SearchQuery(
                "Wells-Riley airborne infection risk hospital indoor "
                "site:pubmed.ncbi.nlm.nih.gov OR site:plos.org"
            ),
            SearchQuery(
                "quantitative microbial risk assessment QMRA airborne hospital "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "agent-based model nosocomial transmission hospital simulation "
                "site:pubmed.ncbi.nlm.nih.gov OR site:plos.org OR site:nature.com"
            ),
            SearchQuery(
                "digital twin hospital indoor air transmission CFD "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com",
                tbs="qdr:y",
            ),
            SearchQuery(
                "rebreathed fraction CO2 indoor airborne infection Rudnick Milton "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "compartmental SEIR hospital nosocomial outbreak healthcare workers "
                "site:pubmed.ncbi.nlm.nih.gov OR site:plos.org"
            ),
        ],
    ),
    PaperGroup(
        name="hospital_acquired_infections",
        description=(
            "Nosocomial / hospital-acquired airborne infections, transmission "
            "outbreaks, healthcare-associated infection epidemiology."
        ),
        schema_alignment=[
            "epidemiology", "infectious_disease", "clinical_microbiology",
        ],
        queries=[
            SearchQuery(
                "nosocomial airborne SARS-CoV-2 transmission hospital outbreak "
                "site:pubmed.ncbi.nlm.nih.gov OR site:cdc.gov",
                tbs="qdr:y",
            ),
            SearchQuery(
                "healthcare-associated infection HAI airborne pathogen outbreak "
                "site:pubmed.ncbi.nlm.nih.gov OR site:cdc.gov"
            ),
            SearchQuery(
                "Aspergillus hospital airborne nosocomial transplant patient "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "MRSA airborne dispersion hospital ward shedding "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "tuberculosis healthcare worker exposure hospital transmission "
                "site:pubmed.ncbi.nlm.nih.gov OR site:cdc.gov"
            ),
            SearchQuery(
                "RSV influenza nosocomial transmission ward outbreak "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
        ],
    ),
    PaperGroup(
        name="cognitive_effects_respiratory",
        description=(
            "Cognitive effects of respiratory infections in healthcare workers "
            "and patients (the HAIQU project's Cognitive-Tests-for-HAIQU angle)."
        ),
        schema_alignment=["respiratory_disease_cognition", "disease_study"],
        queries=[
            SearchQuery(
                "post-COVID cognitive impairment healthcare worker neuropsychological "
                "site:pubmed.ncbi.nlm.nih.gov OR site:nature.com OR site:cell.com"
            ),
            SearchQuery(
                "long COVID cognitive function executive memory longitudinal cohort "
                "site:pubmed.ncbi.nlm.nih.gov OR site:medrxiv.org",
                tbs="qdr:y",
            ),
            SearchQuery(
                "respiratory infection cognitive dysfunction processing speed attention "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "neuropsychological test battery healthcare worker respiratory infection "
                "site:pubmed.ncbi.nlm.nih.gov"
            ),
            SearchQuery(
                "ICU delirium cognitive sequelae critical illness "
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
    print(f"  {g.description}")
    print(f"  schemas: {', '.join(g.schema_alignment)}")
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
        "description": g.description,
        "schema_alignment": g.schema_alignment,
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
            print(f"{g.name:<36} {len(g.queries)} queries  "
                  f"-> schemas: {', '.join(g.schema_alignment)}")
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
