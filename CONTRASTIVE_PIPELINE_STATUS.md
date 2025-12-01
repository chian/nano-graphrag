# Contrastive QA Generation Pipeline - Implementation Status

## Overview
Building a complete pipeline for generating contrastive reasoning questions from scientific papers using domain-specific knowledge graphs.

---

## ✅ COMPLETED Components

### 1. Domain Schema System
**Files:**
- `domain_schemas/molecular_biology.yaml`
- `domain_schemas/microbial_biology.yaml`
- `domain_schemas/infectious_disease.yaml`
- `domain_schemas/ecology.yaml`
- `domain_schemas/epidemiology.yaml`
- `domain_schemas/disease_biology.yaml`
- `domain_schemas/schema_loader.py`

**What it does:**
- Defines entity types (PROTEIN, COMPOUND, PATHWAY, etc.) for each domain
- Defines relationship types (INHIBITS, ACTIVATES, CAUSES, etc.) for each domain
- Provides suitability criteria for paper assessment
- Includes contrastive patterns to look for
- Includes question generation focus areas

### 2. Paper Suitability Assessment (Stage 1)
**File:** `assess_paper_suitability.py`

**What it does:**
- Takes a paper and tests it against a SINGLE specified domain schema (pipeline mode)
- OR tests against ALL domains (exploratory mode)
- For the domain(s), assesses:
  - How many entities/relationships could be extracted
  - Which entity/relationship types are present
  - Whether the paper fits the domain
- **Pipeline mode:** Exits if paper is not suitable for the specified domain
- **Exploratory mode:** Outputs which domain(s) the paper is suitable for

**Usage:**
```bash
# Pipeline mode (single domain)
python assess_paper_suitability.py paper.txt --domain molecular_biology
# Exits with code 0 if suitable for molecular_biology, code 1 if not

# Exploratory mode (all domains)
python assess_paper_suitability.py paper.txt
# Tests all domains, outputs suitable ones
```

### 3. Domain-Typed Entity/Relationship Extraction
**File:** `nano_graphrag/entity_extraction/typed_module.py`

**What it does:**
- Extends nano-graphrag's extraction to support:
  - Domain-specific entity types (not generic)
  - **Relationship types** (INHIBITS, CAUSES, etc. - not just free text)
- Uses dspy with self-refinement
- Factory function creates extractor from domain schema

### 4. Initial Graph Construction (Stage 2)
**File:** `create_domain_typed_graph.py`

**What it does:**
- Takes a paper + domain name
- Chunks the paper text
- Extracts entities and relationships using domain schema
- Builds NetworkX graph with:
  - Typed nodes (entity_type attribute)
  - Typed edges (relation_type attribute)
- Saves graph as GraphML
- Saves metadata JSON

**Usage:**
```bash
python create_domain_typed_graph.py paper.txt molecular_biology --output-dir ./graphs
```

---

### 5. Query Generation (Stage 3)
**Files:**
- `query_generation/graph_validator.py`
- `query_generation/generate_queries_contrastive_alternatives.py`
- `query_generation/generate_queries_pathway_expansion.py`
- `query_generation/generate_queries_therapeutic_alternatives.py`
- `query_generation/generate_queries_cross_domain.py`

**What it does:**
- Validates graphs have domain-typed nodes and edges
- Generates search queries to find NEW information from literature
- Four query strategies:
  1. **Contrastive Alternatives:** Finds nodes with multiple causal paths, generates queries for MORE alternative mechanisms
  2. **Pathway Expansion:** Finds indirect/missing connections, generates queries to fill gaps
  3. **Therapeutic Alternatives:** Finds diseases with few treatments, generates queries for more therapeutic options
  4. **Cross-Domain:** Finds entities bridging multiple contexts, generates queries to explore interactions
- All scripts validate graph compatibility before execution
- Outputs JSON files with search queries

**Usage:**
```bash
python query_generation/generate_queries_contrastive_alternatives.py molecular_biology_graph.graphml molecular_biology --output queries_alt.json
python query_generation/generate_queries_pathway_expansion.py molecular_biology_graph.graphml molecular_biology --output queries_path.json
python query_generation/generate_queries_therapeutic_alternatives.py molecular_biology_graph.graphml molecular_biology --output queries_ther.json
python query_generation/generate_queries_cross_domain.py molecular_biology_graph.graphml molecular_biology --output queries_cross.json
```

---

### 6. Firecrawl Paper Fetching (Stage 4)
**Files:**
- `paper_fetching/firecrawl_client.py` - Modular API functions
- `fetch_papers_firecrawl.py` - Main script

**What it does:**
- Takes query JSON files from Stage 3
- Uses Firecrawl API to search scientific publications
- Filters for scientific domains (PubMed, bioRxiv, medRxiv, journals)
- Excludes non-scientific sources (news, blogs, Wikipedia)
- Downloads full text content
- Assigns UUID to each paper
- Saves as `{uuid}.txt` files
- Maintains `papers_metadata.json` with UUID mappings
- Deduplicates by URL to avoid re-downloading
- Tracks source query and query type for each paper

**Modular functions (can be imported):**
- `search_papers()` - Search using Firecrawl API
- `download_paper_content()` - Scrape paper from URL
- `save_paper_with_uuid()` - Save with UUID and metadata
- `load_papers_metadata()` - Load existing metadata
- `save_papers_metadata()` - Save metadata to JSON
- `extract_text_from_result()` - Extract text from Firecrawl result
- `deduplicate_by_url()` - Remove duplicate URLs

**Usage:**
```bash
export FIRECRAWL_API_KEY="your_api_key"
python fetch_papers_firecrawl.py queries_alt.json queries_path.json --output-dir ./fetched_papers --max-total-papers 50
```

---

### 7. Graph Enrichment (Stage 5)
**Files:**
- `graph_enrichment/entity_merger.py` - Entity matching and merging
- `graph_enrichment/graph_merger.py` - Graph merging operations
- `enrich_graph_with_papers.py` - Main script

**What it does:**
- Loads base graph from Stage 2
- Loads fetched papers from Stage 4
- Extracts entities/relationships from each paper using domain schema
- Merges entities across papers (handles synonyms like "dolutegravir" = "DTG")
- Tracks source papers via UUIDs for each entity and relationship
- Adds new nodes/edges to graph
- Saves enriched graph with statistics

**Modular functions (can be imported):**
- `calculate_similarity()` - Calculate similarity between entity names
- `find_entity_matches()` - Find matching entities in existing graph
- `merge_entities()` - Merge entity data from multiple sources
- `add_entities_to_graph()` - Add entities with automatic merging
- `add_relationships_to_graph()` - Add relationships using name mapping
- `merge_graphs()` - Merge two complete graphs
- `get_enrichment_statistics()` - Calculate enrichment stats

**Features:**
- Known synonym dictionary for common biological entities
- Configurable similarity threshold for entity matching
- Abbreviation detection (e.g., "TNF" = "tumor necrosis factor")
- Alternative names tracking
- Source paper tracking for provenance

**Usage:**
```bash
python enrich_graph_with_papers.py molecular_biology_graph.graphml molecular_biology --papers-dir ./fetched_papers --output-dir ./enriched_graphs
```

---

## 🚧 IN PROGRESS

None currently.

---

### 8. GASL Contrastive Commands
**File:** `gasl/commands/contrastive.py`

**What it does:**
- Implements 4 contrastive analysis commands as GASL CommandHandlers
- Integrates with NetworkX adapter for graph queries
- Tracks provenance and source papers

**Commands implemented:**
- `FIND_ALTERNATIVES` - Finds different mechanisms achieving same outcome (multiple causal paths to target)
- `FIND_OPPOSING` - Finds entities with opposing effects (ACTIVATES vs INHIBITS, etc.)
- `COMPARE_MECHANISMS` - Compares two mechanisms by analyzing paths, targets, and similarity
- `FIND_COMPETING` - Finds entities competing for same target/resource

**Usage in GASL:**
```python
from gasl.commands.contrastive import FindAlternativesHandler
handler = FindAlternativesHandler(state_store, context_store, adapter, domain_name)
result = handler.execute(Command(command_type="FIND_ALTERNATIVES", args={...}))
```

---

### 9. Contrastive Question Generation (Stage 6)
**File:** `generate_contrastive_qa.py`

**What it does:**
- Loads enriched graph from Stage 5
- Uses GASL contrastive commands to analyze graph
- Generates reasoning questions using LLM (no dspy dependency)
- Uses quality filtering with 4-criteria scoring (threshold >= 4)
- Tracks source entities and papers for each question
- Outputs JSON with questions, answers, and explanations

**Question types:**
- Alternative mechanisms: Choose between different paths to same outcome
- Mechanism comparison: Compare effectiveness under specific conditions
- Competing entities: Reason about competition for targets

**Usage:**
```bash
python generate_contrastive_qa.py enriched_graph.graphml molecular_biology --max-questions 20 --output contrastive_qa.json
```

---

### 10. Pipeline Orchestrator
**File:** `run_contrastive_pipeline.py`

**What it does:**
- Runs all stages 1-6 sequentially
- Handles errors and provides clear progress output
- Supports skipping individual stages
- Saves intermediate outputs and pipeline metadata
- Automatically passes outputs between stages

**Features:**
- Optional stages can be skipped with flags
- Graceful handling when no Firecrawl API key is provided
- Uses initial graph if no papers fetched
- Tracks all outputs in pipeline_metadata.json

**Usage:**
```bash
# Full pipeline
python run_contrastive_pipeline.py paper.txt --domain molecular_biology --num-questions 20

# With Firecrawl API key (recommended for best results)
export FIRECRAWL_API_KEY="fc-bb606f0de1c049588b360a5c4313d802"
python run_contrastive_pipeline.py paper.txt --domain molecular_biology --num-questions 20 --max-papers 30

# Skip paper fetching (use initial graph only)
python run_contrastive_pipeline.py paper.txt --domain molecular_biology --skip-paper-fetching --num-questions 10
```

---

## 📋 TODO Components

None! All pipeline components are complete.

---

## Pipeline Flow

```
Input: paper.txt
    ↓
┌─────────────────────────────────────────────────┐
│ Stage 1: Assess Suitability                    │
│ assess_paper_suitability.py --domain X         │
│ Output: suitable=true/false for domain X       │
└─────────────────────────────────────────────────┘
    ↓ (Exit if not suitable for domain X)
    ↓
┌─────────────────────────────────────────────────┐
│ Stage 2: Build Initial Graph                   │
│ create_domain_typed_graph.py                   │
│ Output: molecular_biology_graph.graphml        │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│ Stage 3: Generate Search Queries               │
│ query_generation/generate_queries_*.py         │
│ Output: 4 query JSON files                     │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│ Stage 4: Fetch Additional Papers               │
│ fetch_papers_firecrawl.py                      │
│ Output: {uuid}.txt files, papers_metadata.json │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│ Stage 5: Enrich Graph                          │
│ enrich_graph_with_papers.py                    │
│ Output: enriched_graph.graphml                 │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│ Stage 6: Generate Contrastive Questions        │
│ generate_contrastive_qa.py                     │
│ Output: contrastive_qa.json                    │
└─────────────────────────────────────────────────┘
```

---

## Testing the Pipeline

The complete pipeline is ready for testing! To test with a single paper:

```bash
# Full pipeline with all stages
python run_contrastive_pipeline.py paper.txt --domain molecular_biology --num-questions 20 --max-papers 10

# Or test without Firecrawl (using initial graph only)
python run_contrastive_pipeline.py paper.txt --skip-paper-fetching --num-questions 10
```

Individual stages can be tested separately:
1. `python assess_paper_suitability.py paper.txt --domain molecular_biology`
2. `python create_domain_typed_graph.py paper.txt molecular_biology`
3. `python query_generation/generate_queries_*.py graph.graphml molecular_biology`
4. `python fetch_papers_firecrawl.py queries.json --max-total-papers 10`
5. `python enrich_graph_with_papers.py graph.graphml molecular_biology`
6. `python generate_contrastive_qa.py enriched_graph.graphml molecular_biology`

Once tested with one paper, scale up to batch processing multiple papers.

## Multi-Domain Processing

To process a paper for multiple domains, run the pipeline separately for each domain:

```bash
# Process for molecular_biology
python run_contrastive_pipeline.py paper.txt --domain molecular_biology --output-dir ./output_molbio

# Process for disease_biology
python run_contrastive_pipeline.py paper.txt --domain disease_biology --output-dir ./output_disease
```

Each run will:
- Assess suitability for that specific domain
- Build a domain-specific graph
- Generate domain-specific questions
