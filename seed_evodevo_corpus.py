#!/usr/bin/env python3
"""
Evo-devo literature seeding -- Firecrawl-only search strategy.

Populates a per-group paper corpus for 10 knowledge-graph topics covering
evolutionary developmental biology, body-plan innovation, and related
mechanistic/theoretical frameworks.

Output layout:
    data/evo_devo_corpus/
        corpus_index.json
        <group>/
            metadata.json
            papers/
                <uuid>.md

Usage:
    export FIRECRAWL_API_KEY=...
    python seed_evodevo_corpus.py
    python seed_evodevo_corpus.py --groups kg_symmetry_locomotion_manoeuvrability
    python seed_evodevo_corpus.py --max-per-query 1000 --output-dir data/evo_devo_corpus
    python seed_evodevo_corpus.py --dry-run
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

from paper_fetching.firecrawl_client import (
    SCIENTIFIC_DOMAINS,
    EXCLUDED_DOMAINS,
    extract_text_from_result,
)

FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v1/search"

_SITES = (
    "site:pubmed.ncbi.nlm.nih.gov OR site:ncbi.nlm.nih.gov/pmc OR "
    "site:nature.com OR site:cell.com OR site:science.org OR "
    "site:biorxiv.org OR site:elifesciences.org OR site:plos.org"
)


@dataclass
class SearchQuery:
    query: str
    tbs: Optional[str] = None
    notes: str = ""


@dataclass
class PaperGroup:
    name: str
    question: str
    schema: str
    queries: List[SearchQuery] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Group definitions
# ---------------------------------------------------------------------------

GROUPS: List[PaperGroup] = [

    PaperGroup(
        name="kg_symmetry_locomotion_manoeuvrability",
        question=(
            "What is the relationship between body symmetry and locomotor performance, "
            "manoeuvrability, and hydrodynamic efficiency across animal taxa?"
        ),
        schema="kg_symmetry_locomotion_manoeuvrability",
        queries=[
            SearchQuery(
                query=(
                    f"bilateral symmetry aquatic locomotion hydrodynamic performance "
                    f"manoeuvrability fish swimming efficiency {_SITES}"
                ),
                notes="Core symmetry-locomotion link",
            ),
            SearchQuery(
                query=(
                    f"radial symmetry bilateral symmetry body plan evolutionary "
                    f"advantages locomotion animal movement {_SITES}"
                ),
                notes="Radial vs bilateral body plan comparison",
            ),
            SearchQuery(
                query=(
                    f"asymmetry fluctuating asymmetry locomotor performance fitness "
                    f"animal body plan evolution {_SITES}"
                ),
                notes="Asymmetry costs and locomotion",
            ),
            SearchQuery(
                query=(
                    f"evolutionary maintenance bilateral symmetry developmental "
                    f"constraint selection pressure body form {_SITES}"
                ),
                notes="Why symmetry is maintained evolutionarily",
                tbs="qdr:y",
            ),
        ],
    ),

    PaperGroup(
        name="kg_radial_vs_bilateral_signaling_geometry",
        question=(
            "How does body geometry (radial vs bilateral) constrain or enable "
            "morphogen gradient formation, positional information, and long-range "
            "developmental signaling?"
        ),
        schema="kg_radial_vs_bilateral_signaling_geometry",
        queries=[
            SearchQuery(
                query=(
                    f"morphogen gradient diffusion geometry radial symmetry "
                    f"bilateral symmetry positional information patterning {_SITES}"
                ),
                notes="Geometry-gradient interaction",
            ),
            SearchQuery(
                query=(
                    f"reaction diffusion patterning body plan geometry rotational "
                    f"symmetry synchronization developmental biology {_SITES}"
                ),
                notes="Reaction-diffusion in radial/bilateral contexts",
            ),
            SearchQuery(
                query=(
                    f"early animal embryo signaling coordination axis formation "
                    f"radial bilateral body plan evolution cnidaria {_SITES}"
                ),
                notes="Early animal signaling in radial organisms",
            ),
            SearchQuery(
                query=(
                    f"BMP Wnt gradient long range signaling tissue geometry "
                    f"body axis patterning invertebrate {_SITES}"
                ),
                notes="Specific morphogen gradients in body plan context",
                tbs="qdr:y",
            ),
        ],
    ),

    PaperGroup(
        name="kg_robustness_canalization_innovation",
        question=(
            "Do robust, canalized developmental networks constrain morphological "
            "innovation and ecological niche expansion, or do they enable it?"
        ),
        schema="kg_robustness_canalization_innovation",
        queries=[
            SearchQuery(
                query=(
                    f"developmental robustness canalization phenotypic innovation "
                    f"morphological novelty evolvability constraint {_SITES}"
                ),
                notes="Core robustness-innovation tension",
            ),
            SearchQuery(
                query=(
                    f"conserved developmental regulatory circuit evolvability "
                    f"phenotypic diversification developmental constraint {_SITES}"
                ),
                notes="Conserved circuits and diversification",
            ),
            SearchQuery(
                query=(
                    f"Waddington canalization genetic assimilation developmental "
                    f"buffering phenotypic variation evolution {_SITES}"
                ),
                notes="Waddington framework and empirical tests",
            ),
            SearchQuery(
                query=(
                    f"robustness evolvability trade-off gene regulatory network "
                    f"body plan innovation ecological niche {_SITES}"
                ),
                notes="Empirical robustness-evolvability trade-off",
                tbs="qdr:y",
            ),
        ],
    ),

    PaperGroup(
        name="kg_reaction_diffusion_body_plan_innovation",
        question=(
            "How do reaction-diffusion and Turing patterning mechanisms contribute "
            "to periodic structures, segmentation, and early animal body-plan innovation?"
        ),
        schema="kg_reaction_diffusion_body_plan_innovation",
        queries=[
            SearchQuery(
                query=(
                    f"reaction diffusion Turing pattern segmentation appendage "
                    f"patterning animal body plan {_SITES}"
                ),
                notes="Core RD patterning in development",
            ),
            SearchQuery(
                query=(
                    f"Turing mechanism stripe spot periodic pattern embryo "
                    f"vertebrate invertebrate comparative {_SITES}"
                ),
                notes="Comparative Turing patterning",
            ),
            SearchQuery(
                query=(
                    f"Cambrian body plan innovation evo-devo developmental "
                    f"mechanism gene duplication heterochrony ecological trigger {_SITES}"
                ),
                notes="Cambrian innovation mechanisms contrasted",
            ),
            SearchQuery(
                query=(
                    f"reaction diffusion vs gene regulatory network body plan "
                    f"segmentation growth dynamics alternative mechanisms {_SITES}"
                ),
                notes="RD vs alternative mechanisms",
                tbs="qdr:y",
            ),
        ],
    ),

    PaperGroup(
        name="kg_plasticity_modularity_gene_reuse",
        question=(
            "How do phenotypic plasticity, modularity, and gene reuse interact "
            "in the context-dependent morphology of marine invertebrates and "
            "other systems with environmentally variable development?"
        ),
        schema="kg_plasticity_modularity_gene_reuse",
        queries=[
            SearchQuery(
                query=(
                    f"phenotypic plasticity modularity developmental co-option "
                    f"gene reuse marine invertebrate morphology {_SITES}"
                ),
                notes="Core plasticity-modularity-reuse link",
            ),
            SearchQuery(
                query=(
                    f"developmental plasticity adaptive benefit environment "
                    f"context dependent morphology circuit reuse {_SITES}"
                ),
                notes="Plasticity vs adaptive benefit distinction",
            ),
            SearchQuery(
                query=(
                    f"modular gene regulatory network co-option novel trait "
                    f"evolution body plan diversification {_SITES}"
                ),
                notes="Modularity enabling co-option",
            ),
            SearchQuery(
                query=(
                    f"toolkit gene reuse deep homology convergent evolution "
                    f"morphological novelty invertebrate {_SITES}"
                ),
                notes="Gene reuse and deep homology",
                tbs="qdr:y",
            ),
        ],
    ),

    PaperGroup(
        name="kg_chromatin_accessibility_segment_identity",
        question=(
            "Does chromatin state constrain Hox binding and segment identity, "
            "or does Hox binding reshape chromatin — and what is the causal "
            "direction and timing?"
        ),
        schema="kg_chromatin_accessibility_segment_identity",
        queries=[
            SearchQuery(
                query=(
                    f"chromatin accessibility Hox binding segment identity "
                    f"embryonic patterning causal direction {_SITES}"
                ),
                notes="Core chromatin-Hox causality question",
            ),
            SearchQuery(
                query=(
                    f"chromatin remodeling Hox gene regulation ATAC-seq "
                    f"ChIP-seq embryo segmentation timing {_SITES}"
                ),
                notes="Perturbation/timing experiments",
            ),
            SearchQuery(
                query=(
                    f"pioneer transcription factor chromatin opening Hox "
                    f"homeodomain early development constraint {_SITES}"
                ),
                notes="Pioneer factor context",
            ),
            SearchQuery(
                query=(
                    f"Polycomb chromatin state Hox cluster regulation "
                    f"segment identity reprogramming perturbation {_SITES}"
                ),
                notes="Polycomb-Hox chromatin regulation",
                tbs="qdr:y",
            ),
        ],
    ),

    PaperGroup(
        name="kg_morphogen_gradients_organized_growth",
        question=(
            "How do morphogen gradients (SHH, FGF, BMP, Notch) separately "
            "control proliferation, differentiation, migration, and apoptosis "
            "to organize tissue architecture in neural and limb patterning?"
        ),
        schema="kg_morphogen_gradients_organized_growth",
        queries=[
            SearchQuery(
                query=(
                    f"morphogen gradient Sonic hedgehog FGF BMP proliferation "
                    f"differentiation tissue organization limb patterning {_SITES}"
                ),
                notes="Core morphogen gradient studies",
            ),
            SearchQuery(
                query=(
                    f"Notch signaling neural patterning proliferation zone "
                    f"tissue architecture organized growth {_SITES}"
                ),
                notes="Notch and neural organization",
            ),
            SearchQuery(
                query=(
                    f"morphogen gradient concentration threshold cell fate "
                    f"apoptosis migration separate roles tissue patterning {_SITES}"
                ),
                notes="Separating proliferation/diff/apoptosis/migration",
            ),
            SearchQuery(
                query=(
                    f"BMP gradient dorsal ventral patterning cell proliferation "
                    f"apoptosis embryo quantitative {_SITES}"
                ),
                notes="BMP gradient quantitative dissection",
                tbs="qdr:y",
            ),
        ],
    ),

    PaperGroup(
        name="kg_non_hox_novelty_sweep",
        question=(
            "What non-Hox mechanisms — biomechanics, ECM remodeling, planar cell "
            "polarity, Hippo, Notch, retinoic acid, heterochrony, metabolic "
            "constraints, and ecological selection — drive body-plan innovation?"
        ),
        schema="kg_non_hox_novelty_sweep",
        queries=[
            SearchQuery(
                query=(
                    f"body plan innovation non-Hox mechanism biomechanics "
                    f"extracellular matrix cell adhesion planar cell polarity {_SITES}"
                ),
                notes="Non-Hox structural mechanisms",
            ),
            SearchQuery(
                query=(
                    f"Hippo signaling Notch retinoic acid heterochrony body plan "
                    f"evolution morphological novelty {_SITES}"
                ),
                notes="Non-Hox signaling pathways",
            ),
            SearchQuery(
                query=(
                    f"metabolic constraint developmental timing ecological selection "
                    f"morphological innovation body plan evo-devo {_SITES}"
                ),
                notes="Metabolic and ecological drivers",
            ),
            SearchQuery(
                query=(
                    f"ECM remodeling tissue mechanics morphogenesis cell "
                    f"rearrangement body plan novelty evolution {_SITES}"
                ),
                notes="Mechanical and matrix contributions",
                tbs="qdr:y",
            ),
        ],
    ),

    PaperGroup(
        name="kg_contradictions_and_null_results",
        question=(
            "Where do dominant developmental and evolutionary explanations of "
            "body-plan innovation fail, produce null results, or face credible "
            "alternative interpretations?"
        ),
        schema="kg_contradictions_and_null_results",
        queries=[
            SearchQuery(
                query=(
                    f"null result rebuttal alternative mechanism developmental "
                    f"biology body plan evolution insufficient downstream {_SITES}"
                ),
                notes="Null results and rebuttals",
            ),
            SearchQuery(
                query=(
                    f"contradictory evidence evo-devo developmental mechanism "
                    f"context limited insufficient explanation review {_SITES}"
                ),
                notes="Contradictions and context limits",
            ),
            SearchQuery(
                query=(
                    f"failure dominant model morphogen Hox segmentation "
                    f"alternative explanation empirical challenge {_SITES}"
                ),
                notes="Challenges to dominant models",
            ),
            SearchQuery(
                query=(
                    f"replication failure inconsistent result developmental "
                    f"biology evolutionary mechanism critique {_SITES}"
                ),
                notes="Reproducibility and consistency issues",
                tbs="qdr:y",
            ),
        ],
    ),

    PaperGroup(
        name="kg_evidence_to_prediction",
        question=(
            "Which developmental biology papers specify explicit predictions, "
            "discriminating experiments, or measurable signatures that would "
            "distinguish mechanism A from mechanism B?"
        ),
        schema="kg_evidence_to_prediction",
        queries=[
            SearchQuery(
                query=(
                    f"developmental mechanism prediction discriminating experiment "
                    f"perturbation logic measurable outcome body plan {_SITES}"
                ),
                notes="Discriminating experiments",
            ),
            SearchQuery(
                query=(
                    f"comparative signature developmental biology mechanism test "
                    f"quantitative prediction evo-devo body plan {_SITES}"
                ),
                notes="Comparative and quantitative predictions",
            ),
            SearchQuery(
                query=(
                    f"falsifiable prediction developmental constraint body plan "
                    f"innovation mechanistic test alternative hypothesis {_SITES}"
                ),
                notes="Falsifiability and hypothesis testing",
            ),
            SearchQuery(
                query=(
                    f"perturbation experiment knockout rescue developmental "
                    f"mechanism causal test morphogenesis body plan {_SITES}"
                ),
                notes="Perturbation-based causal tests",
                tbs="qdr:y",
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Runner (mirrors seed_haiqu_corpus.py)
# ---------------------------------------------------------------------------

def run_search(api_key: str, q: SearchQuery, max_results: int) -> list[dict]:
    payload: dict = {
        "query": q.query,
        "limit": max_results,
        "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True},
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
            print(f"    {i:>2}.{tag} {q.query[:100]}...")
        return {"group": g.name, "dry_run": True}

    group_dir = root / g.name
    papers_dir = group_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    seen_urls: set = set()
    saved: list[dict] = []
    queries_log: list[dict] = []

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
        time.sleep(1)

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
    print(f"  -> {group_dir / 'metadata.json'} ({len(saved)} unique papers)")
    return {"group": g.name, "paper_count": len(saved)}


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--api-key", default=os.getenv("FIRECRAWL_API_KEY"),
                   help="Firecrawl API key (or set FIRECRAWL_API_KEY)")
    p.add_argument("--output-dir", default="data/evo_devo_corpus",
                   help="Root output directory (default: data/evo_devo_corpus)")
    p.add_argument("--max-per-query", type=int, default=100,
                   help="Max results per Firecrawl query (default: 100; Firecrawl API hard-cap is 100)")
    p.add_argument("--groups", nargs="*",
                   help="Only run these group names (default: all)")
    p.add_argument("--list-groups", action="store_true",
                   help="List available groups and exit")
    p.add_argument("--dry-run", action="store_true",
                   help="Print queries without making API calls")
    args = p.parse_args()

    if args.list_groups:
        for g in GROUPS:
            print(f"  {g.name}")
            print(f"    Q: {g.question}")
        return

    groups_to_run = GROUPS
    if args.groups:
        names = set(args.groups)
        groups_to_run = [g for g in GROUPS if g.name in names]
        if not groups_to_run:
            sys.exit(f"ERROR: no groups matched: {args.groups}")

    if not args.dry_run:
        if not args.api_key:
            sys.exit("ERROR: FIRECRAWL_API_KEY not set and --api-key not provided")

    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)

    print(f"output_dir   : {root}")
    print(f"max/query    : {args.max_per_query}")
    print(f"groups       : {len(groups_to_run)}")
    print(f"dry_run      : {args.dry_run}")

    results = []
    for g in groups_to_run:
        r = run_group(g, args.api_key, root, args.max_per_query, args.dry_run)
        results.append(r)

    if not args.dry_run:
        index = {
            "ran_at": datetime.utcnow().isoformat() + "Z",
            "output_dir": str(root),
            "max_per_query": args.max_per_query,
            "groups": [
                {"group": r["group"], "paper_count": r.get("paper_count", 0)}
                for r in results
            ],
        }
        (root / "corpus_index.json").write_text(
            json.dumps(index, indent=2), encoding="utf-8")
        total = sum(r.get("paper_count", 0) for r in results)
        print(f"\nDone. {total} papers across {len(results)} groups.")
        print(f"Index: {root / 'corpus_index.json'}")


if __name__ == "__main__":
    main()
