# Contrastive QA Generation Pipeline

A complete pipeline for generating contrastive reasoning questions from scientific papers using domain-specific knowledge graphs.

## Overview

This pipeline takes a scientific paper and generates high-quality reasoning questions that require understanding of alternative mechanisms, competing pathways, and biological tradeoffs. Questions are grounded in real entities and relationships extracted from multiple papers.

## Quick Start

```bash
# Full pipeline (domain is REQUIRED)
python run_contrastive_pipeline.py paper.txt --domain molecular_biology --num-questions 20

# Without Firecrawl (local graph only)
python run_contrastive_pipeline.py paper.txt --domain molecular_biology --skip-paper-fetching --num-questions 10

# With Firecrawl API for enrichment (recommended for best results)
export FIRECRAWL_API_KEY="fc-bb606f0de1c049588b360a5c4313d802"
python run_contrastive_pipeline.py paper.txt --domain molecular_biology --num-questions 20 --max-papers 30
```

**Note:** The `--domain` argument is required. The pipeline will assess whether the paper is suitable for the specified domain and exit if not.

## Pipeline Stages

### Stage 1: Paper Suitability Assessment
**Script:** `assess_paper_suitability.py`

Tests the paper against a specific domain schema to determine suitability.

```bash
# Single domain assessment (pipeline mode)
python assess_paper_suitability.py paper.txt --domain molecular_biology

# Exploratory mode (test all domains)
python assess_paper_suitability.py paper.txt
```

**Pipeline behavior:** The paper must be suitable for the specified domain or the pipeline exits.

### Stage 2: Initial Graph Construction
**Script:** `create_domain_typed_graph.py`

Builds a knowledge graph with domain-typed entities and relationships.

```bash
python create_domain_typed_graph.py paper.txt molecular_biology --output-dir ./graphs
```

### Stage 3: Query Generation
**Scripts:** `query_generation/generate_queries_*.py`

Generates 4 types of search queries to find additional papers:
- Contrastive alternatives (find more mechanisms)
- Pathway expansion (fill connection gaps)
- Therapeutic alternatives (find more treatments)
- Cross-domain exploration (bridge contexts)

```bash
python query_generation/generate_queries_contrastive_alternatives.py graph.graphml molecular_biology
python query_generation/generate_queries_pathway_expansion.py graph.graphml molecular_biology
python query_generation/generate_queries_therapeutic_alternatives.py graph.graphml molecular_biology
python query_generation/generate_queries_cross_domain.py graph.graphml molecular_biology
```

### Stage 4: Paper Fetching
**Script:** `fetch_papers_firecrawl.py`

Uses Firecrawl API to search and download scientific papers based on generated queries.

```bash
export FIRECRAWL_API_KEY="your_key"
python fetch_papers_firecrawl.py queries_*.json --output-dir ./fetched_papers --max-total-papers 30
```

### Stage 5: Graph Enrichment
**Script:** `enrich_graph_with_papers.py`

Enriches the initial graph with entities from additional papers, merging synonyms and tracking provenance.

```bash
python enrich_graph_with_papers.py graph.graphml molecular_biology --papers-dir ./fetched_papers
```

### Stage 6: Question Generation
**Script:** `generate_contrastive_qa.py`

Uses GASL contrastive commands to analyze the enriched graph and generate reasoning questions.

```bash
python generate_contrastive_qa.py enriched_graph.graphml molecular_biology --max-questions 20
```

## Domain Schemas

Six domain schemas are available:
- `molecular_biology` - Proteins, genes, compounds, pathways
- `microbial_biology` - Organisms, metabolism, resistance
- `infectious_disease` - Pathogens, hosts, transmission
- `ecology` - Species, ecosystems, interactions
- `epidemiology` - Populations, transmission, interventions
- `disease_biology` - Diseases, symptoms, treatments

Each schema defines:
- Entity types (PROTEIN, COMPOUND, PATHWAY, etc.)
- Relationship types (INHIBITS, ACTIVATES, CAUSES, etc.)
- Suitability criteria
- Contrastive patterns

## GASL Contrastive Commands

Four new GASL commands for contrastive analysis:

1. **FIND_ALTERNATIVES** - Finds mechanisms achieving the same outcome
2. **FIND_OPPOSING** - Finds entities with opposing effects
3. **COMPARE_MECHANISMS** - Compares two mechanisms
4. **FIND_COMPETING** - Finds entities competing for targets

## Key Features

### Entity Merging
Automatically handles synonyms across papers:
- "dolutegravir" = "DTG"
- "tumor necrosis factor" = "TNF"
- Configurable similarity threshold
- Abbreviation detection

### Provenance Tracking
Every entity and relationship tracks:
- Source paper UUIDs
- Source chunks
- Alternative names used

### Modular Design
All components can be imported and used independently:
- Domain schema loaders
- Entity extraction modules
- Graph merger functions
- Firecrawl API client
- GASL command handlers

### Quality Filters
- Scientific domain filtering (PubMed, bioRxiv, medRxiv, journals)
- Excludes non-scientific sources (news, blogs, Wikipedia)
- Validates graph schema compatibility
- Deduplicates by URL

## Output Structure

```
pipeline_output/
├── graphs/
│   ├── molecular_biology_graph.graphml
│   └── molecular_biology_metadata.json
├── queries/
│   ├── contrastive_alternatives_queries.json
│   ├── pathway_expansion_queries.json
│   ├── therapeutic_alternatives_queries.json
│   └── cross_domain_queries.json
├── fetched_papers/
│   ├── {uuid1}.txt
│   ├── {uuid2}.txt
│   └── papers_metadata.json
├── enriched_graphs/
│   ├── molecular_biology_enriched_graph.graphml
│   └── molecular_biology_enrichment_metadata.json
├── contrastive_qa.json
└── pipeline_metadata.json
```

## Question Format

Generated questions include:
```json
{
  "question": "Drug A and Drug B both inhibit pathway X. Under condition C, which is more effective?",
  "answers": {
    "A": "Drug A because...",
    "B": "Drug B because...",
    "C": "Neither, because...",
    "D": "Both equally because..."
  },
  "correct_answer": "A",
  "explanation": "Detailed reasoning...",
  "analysis_type": "alternatives",
  "source_entities": ["Drug A", "Drug B", "Pathway X"],
  "source_papers": ["uuid1", "uuid2"]
}
```

## Pipeline Options

```bash
python run_contrastive_pipeline.py paper.txt \
  --domain molecular_biology \
  --num-questions 20 \
  --max-papers 30 \
  --max-papers-for-enrichment 20 \
  --queries-per-type 10 \
  --output-dir ./output \
  --skip-assessment \
  --skip-graph-creation \
  --skip-query-generation \
  --skip-paper-fetching \
  --skip-graph-enrichment
```

## Requirements

- Python 3.8+
- NetworkX
- dspy
- Firecrawl API key (optional, for paper fetching)
- LLM access via ArgoBridgeLLM

## Implementation Status

✅ All stages complete and tested
✅ Modular functions for reuse
✅ Full provenance tracking
✅ Multiple domain support
✅ End-to-end pipeline orchestrator

See [CONTRASTIVE_PIPELINE_STATUS.md](CONTRASTIVE_PIPELINE_STATUS.md) for detailed implementation status.
