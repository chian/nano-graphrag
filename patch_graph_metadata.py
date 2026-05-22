"""
Retroactively write graph_metadata.json into all existing graph directories.

Run once from the repo root:
    python patch_graph_metadata.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from graph_metadata import (
    build_metadata,
    metadata_from_schema_and_corpus,
    save_graph_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _patch_haiqu(group: str, output_dirs: list[Path], *, version_override: str = None) -> None:
    """Patch all output dirs that contain a graph for this HAIQU group."""
    schema_path = REPO / "domain_schemas" / f"{group}.yaml"
    corpus_meta_path = REPO / "data" / "haiqu_corpus" / group / "metadata.json"

    if not schema_path.exists():
        print(f"  ✗ schema not found: {schema_path}")
        return
    if not corpus_meta_path.exists():
        print(f"  ✗ corpus metadata not found: {corpus_meta_path}")
        return

    # Load schema via DomainSchema loader
    from domain_schemas.schema_loader import SchemaLoader
    loader = SchemaLoader(str(schema_path.parent))
    schema = loader.get_schema(group)
    if schema is None:
        print(f"  ✗ could not load schema: {group}")
        return

    corpus_metadata = _load_json(corpus_meta_path)

    for out_dir in output_dirs:
        if not out_dir.exists():
            continue
        version = version_override or out_dir.parent.name
        gm = metadata_from_schema_and_corpus(
            kg_id=group,
            kg_version=version,
            schema=schema,
            corpus_metadata=corpus_metadata,
        )
        path = save_graph_metadata(out_dir, gm)
        print(f"  ✓ {path.relative_to(REPO)}")


def _patch_ldr(group: str, out_dir: Path, *, domain_name: str, domain_description: str,
               guiding_question: str, entity_types: list, relationship_types: list,
               search_queries: list, paper_count: int) -> None:
    """Patch an LDR group (schema YAMLs no longer in repo — use approximations)."""
    if not out_dir.exists():
        print(f"  ✗ dir not found: {out_dir}")
        return
    import re
    sources: list[str] = []
    for q in search_queries:
        for site in re.findall(r"site:([\w.\-]+)", q):
            if site not in sources:
                sources.append(site)
    if not sources:
        sources = ["pubmed.ncbi.nlm.nih.gov"]

    gm = build_metadata(
        kg_id=group,
        kg_version="v1",
        domain_name=domain_name,
        domain_description=domain_description,
        guiding_question=guiding_question,
        entity_types=entity_types,
        relationship_types=relationship_types,
        search_queries=search_queries,
        search_sources=sources,
        paper_count=paper_count,
        scope_in=[et["name"] + ": " + et["description"] for et in entity_types],
        scope_out=[
            "Vaccine efficacy or immunisation schedules",
            "High-dose radiation therapy (clinical radiotherapy)",
            "Non-radiation carcinogen exposures",
            "Epidemiological population-level cancer statistics unrelated to radiation",
        ],
        notes="Approximate metadata — original schema YAMLs not retained in repo.",
    )
    path = save_graph_metadata(out_dir, gm)
    print(f"  ✓ {path.relative_to(REPO)}")


def _patch_mmwr(out_dir: Path) -> None:
    """Patch the plain-GraphRAG MMWR graph (no typed schema)."""
    if not out_dir.exists():
        print(f"  ✗ dir not found: {out_dir}")
        return
    gm = build_metadata(
        kg_id="mmwr_injuries_65plus",
        kg_version="v1",
        domain_name="MMWR Injury Epidemiology — Adults 65+",
        domain_description=(
            "Knowledge graph built from the May 2021 MMWR report on emergency department "
            "visits and hospitalizations for nonfatal injuries among adults aged 65 and older."
        ),
        guiding_question=(
            "What are the patterns, causes, and risk factors for nonfatal injuries "
            "requiring emergency department visits or hospitalization in adults aged 65+?"
        ),
        entity_types=[
            {"name": "INJURY_TYPE", "description": "Category of nonfatal injury (e.g., falls, motor-vehicle crashes)"},
            {"name": "PATIENT_POPULATION", "description": "Demographic group of injured adults (age, sex)"},
            {"name": "CARE_SETTING", "description": "Emergency department or inpatient setting"},
            {"name": "OUTCOME", "description": "Hospitalization, ED discharge, or death"},
            {"name": "RISK_FACTOR", "description": "Factor associated with injury occurrence or severity"},
        ],
        relationship_types=[
            {"name": "CAUSES", "description": "An injury mechanism causes an outcome"},
            {"name": "AFFECTS", "description": "A risk factor affects a population group"},
            {"name": "TREATED_AT", "description": "An injury is treated at a care setting"},
        ],
        search_queries=["MMWR Weekly 2021 nonfatal injuries adults 65 emergency department"],
        search_sources=["cdc.gov"],
        paper_count=1,
        scope_in=[
            "Nonfatal injury types in adults 65+",
            "Emergency department utilisation patterns",
            "Hospitalisation rates by injury mechanism",
        ],
        scope_out=[
            "Fatal injuries or mortality statistics",
            "Paediatric or working-age adult injury patterns",
            "Disease epidemiology unrelated to injury",
            "COVID-19 or infectious disease",
        ],
        notes="Approximate metadata — graph built from a single MMWR report with plain GraphRAG (no typed schema).",
    )
    path = save_graph_metadata(out_dir, gm)
    print(f"  ✓ {path.relative_to(REPO)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    haiqu_base = REPO / "haiqu_graphs"
    ldr_base = REPO / "low-dose-radiation-cancer"

    # ── HAIQU v1 ────────────────────────────────────────────────────────────
    print("\n── HAIQU v1 ──")
    haiqu_groups_v1 = [
        "haiqu_aerosol_exposure",
        "haiqu_biosensor_detection",
        "haiqu_cognitive_impact",
        "haiqu_engineering_controls",
        "haiqu_hospital_environment",
    ]
    for group in haiqu_groups_v1:
        print(f"  {group}")
        _patch_haiqu(group, [haiqu_base / "v1" / group])

    # ── HAIQU v1_gpt51 ──────────────────────────────────────────────────────
    print("\n── HAIQU v1_gpt51 ──")
    for group in ["haiqu_aerosol_exposure", "haiqu_biosensor_detection"]:
        print(f"  {group}")
        _patch_haiqu(group, [haiqu_base / "v1_gpt51" / group])

    # ── HAIQU test_* model variants (engineering_controls only) ─────────────
    print("\n── HAIQU test_* model variants ──")
    test_dirs = sorted(haiqu_base.glob("test_*"))
    for test_dir in test_dirs:
        out_dir = test_dir  # graphml is directly in test_dir, not a subdir
        _patch_haiqu(
            "haiqu_engineering_controls",
            [out_dir],
            version_override=test_dir.name,
        )

    # ── Low-dose radiation ───────────────────────────────────────────────────
    print("\n── Low-dose radiation ──")

    _patch_ldr(
        group="ldr_carcinogenesis",
        out_dir=ldr_base / "ldr_carcinogenesis",
        domain_name="Radiation Carcinogenesis and Cancer Risk",
        domain_description=(
            "Entities and relationships capturing how low-dose ionising radiation causes cancer, "
            "dose-response relationships, and the accuracy of current risk models."
        ),
        guiding_question=(
            "How does low-dose radiation cause cancer, what are the dose-response relationships, "
            "and how well do current risk models predict outcomes?"
        ),
        entity_types=[
            {"name": "RADIATION_SOURCE", "description": "Source of ionising radiation exposure"},
            {"name": "DOSE", "description": "Quantitative radiation dose (Gy, mSv, cGy)"},
            {"name": "CANCER_TYPE", "description": "Specific cancer or tumour type induced"},
            {"name": "DOSE_RESPONSE_MODEL", "description": "Mathematical model relating dose to cancer risk (LNT, threshold, hormesis)"},
            {"name": "POPULATION", "description": "Exposed human or animal population studied"},
            {"name": "RISK_ESTIMATE", "description": "Excess relative or absolute cancer risk estimate"},
            {"name": "LATENCY", "description": "Time between exposure and tumour development"},
        ],
        relationship_types=[
            {"name": "INDUCES", "description": "Radiation dose induces a cancer type"},
            {"name": "MODELLED_BY", "description": "A dose-response relationship is described by a model"},
            {"name": "OBSERVED_IN", "description": "A risk estimate was observed in a population"},
            {"name": "PREDICTS", "description": "A model predicts risk for a population"},
        ],
        search_queries=[
            "low dose radiation cancer risk dose response site:pubmed.ncbi.nlm.nih.gov",
            "linear no-threshold model radiation carcinogenesis epidemiology site:pubmed.ncbi.nlm.nih.gov",
            "radiation hormesis low dose cancer incidence site:pubmed.ncbi.nlm.nih.gov OR site:ncbi.nlm.nih.gov/pmc",
        ],
        paper_count=229,
    )

    _patch_ldr(
        group="ldr_dna_repair",
        out_dir=ldr_base / "ldr_dna_repair",
        domain_name="Radiation-Induced DNA Damage and Repair",
        domain_description=(
            "Entities and relationships describing how low-dose ionising radiation damages DNA "
            "and the cellular mechanisms that detect, signal, and repair that damage."
        ),
        guiding_question=(
            "What DNA damage does low-dose radiation cause and how do cells repair it?"
        ),
        entity_types=[
            {"name": "DNA_LESION", "description": "Type of DNA damage (DSB, SSB, base oxidation, clustered damage)"},
            {"name": "REPAIR_PATHWAY", "description": "DNA repair mechanism (NHEJ, HR, BER, MMR)"},
            {"name": "REPAIR_PROTEIN", "description": "Protein involved in damage recognition or repair"},
            {"name": "DOSE_RATE", "description": "Rate at which dose is delivered (acute vs chronic)"},
            {"name": "CELL_TYPE", "description": "Cell or tissue type in which damage occurs"},
            {"name": "FIDELITY", "description": "Accuracy of repair (error-free vs error-prone)"},
        ],
        relationship_types=[
            {"name": "CAUSES", "description": "Radiation causes a DNA lesion type"},
            {"name": "REPAIRED_BY", "description": "A lesion is repaired by a pathway"},
            {"name": "REQUIRES", "description": "A repair pathway requires a specific protein"},
            {"name": "MODULATES", "description": "Dose rate modulates repair fidelity or pathway choice"},
        ],
        search_queries=[
            "low dose radiation DNA double strand break repair NHEJ HR site:pubmed.ncbi.nlm.nih.gov",
            "ionising radiation DNA damage response checkpoint ATM site:pubmed.ncbi.nlm.nih.gov",
        ],
        paper_count=150,
    )

    _patch_ldr(
        group="ldr_physics_biology",
        out_dir=ldr_base / "ldr_physics_biology",
        domain_name="Low-Dose Radiation Physics and Radiobiology",
        domain_description=(
            "Entities and relationships connecting the physical properties of low-dose ionising "
            "radiation to its biological effects at the cellular and tissue level."
        ),
        guiding_question=(
            "What are the physical mechanisms and radiobiological principles governing "
            "the effects of low-dose ionising radiation on living systems?"
        ),
        entity_types=[
            {"name": "RADIATION_TYPE", "description": "Type of ionising radiation (X-ray, gamma, alpha, neutron, beta)"},
            {"name": "LET", "description": "Linear energy transfer — energy deposited per unit track length"},
            {"name": "TRACK_STRUCTURE", "description": "Spatial pattern of ionisation events along a radiation track"},
            {"name": "BIOLOGICAL_EFFECT", "description": "Observable biological outcome (cell death, mutation, transformation)"},
            {"name": "RBE", "description": "Relative biological effectiveness of a radiation type"},
            {"name": "BYSTANDER_EFFECT", "description": "Radiation effects in cells not directly irradiated"},
        ],
        relationship_types=[
            {"name": "HAS_LET", "description": "A radiation type has a characteristic LET value"},
            {"name": "PRODUCES", "description": "A radiation track produces a biological effect"},
            {"name": "SCALES_WITH", "description": "RBE scales with LET or dose"},
            {"name": "TRIGGERS", "description": "Direct irradiation triggers bystander signalling"},
        ],
        search_queries=[
            "low LET ionising radiation radiobiology RBE cellular effects site:pubmed.ncbi.nlm.nih.gov",
            "radiation track structure Monte Carlo simulation low dose site:pubmed.ncbi.nlm.nih.gov",
        ],
        paper_count=120,
    )

    _patch_ldr(
        group="ldr_somatic_mutation",
        out_dir=ldr_base / "ldr_somatic_mutation",
        domain_name="Radiation-Induced Somatic Mutation",
        domain_description=(
            "Entities and relationships describing the somatic mutations produced by low-dose "
            "ionising radiation, their mutational signatures, and their role in clonal evolution."
        ),
        guiding_question=(
            "What somatic mutations does low-dose radiation induce and how do they contribute "
            "to clonal expansion and cancer initiation?"
        ),
        entity_types=[
            {"name": "MUTATION_TYPE", "description": "Class of somatic mutation (SNV, indel, SV, CNV)"},
            {"name": "MUTATIONAL_SIGNATURE", "description": "COSMIC or de novo signature associated with radiation"},
            {"name": "DRIVER_GENE", "description": "Gene whose mutation confers clonal fitness advantage"},
            {"name": "CLONE", "description": "Clonally expanded cell population carrying shared mutations"},
            {"name": "TISSUE", "description": "Tissue or organ in which somatic mutations accumulate"},
        ],
        relationship_types=[
            {"name": "INDUCES_SIGNATURE", "description": "Radiation induces a specific mutational signature"},
            {"name": "MUTATES", "description": "Radiation mutates a driver gene"},
            {"name": "EXPANDS", "description": "A driver mutation causes clonal expansion"},
            {"name": "ENRICHED_IN", "description": "A mutation type is enriched in a specific tissue after radiation"},
        ],
        search_queries=[
            "radiation induced somatic mutation clonal expansion COSMIC signature site:pubmed.ncbi.nlm.nih.gov",
            "ionising radiation mutational spectrum whole genome sequencing site:pubmed.ncbi.nlm.nih.gov OR site:nature.com",
        ],
        paper_count=180,
    )

    # ── MMWR test graph ──────────────────────────────────────────────────────
    print("\n── MMWR test graph ──")
    _patch_mmwr(REPO / "mmwr-test" / "graphrag_cache")

    print("\nDone.")


if __name__ == "__main__":
    main()
