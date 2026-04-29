# HAIQU Knowledge-Graph Toolkit

A literature-to-knowledge-graph pipeline plus a browser UI for asking
questions about that graph in natural language. Built to help researchers
on the **HAIQU (Hospital Air QUality)** ARPA-H project move from "I think
the literature says X" to "show me the entities and citations that support
or contradict X" in seconds rather than weeks.

About HAIQU: *Hospital Air QUality: Breathing Life into Patient Care*,
$21M ARPA-H BREATHE-program award (Sept 29 2025), Mayo Clinic, PI Connie
Chang. The project develops microfluidic droplet CRISPR biosensors plus
agent-based and digital-twin models to assess and reduce airborne disease
transmission risk in clinical settings, validated at Mayo Clinic emergency
departments in Minnesota, Arizona, and Florida.
[Award page](https://arpa-h.gov/explore-funding/awards/3351).

This repo doesn't build the biosensors. It builds the **scientific
knowledge substrate** the team needs around them — what pathogens have
been air-detected with which methods, which HVAC interventions reduce
which transmission routes, which agent-based models have been validated
on real outbreak data, and so on. Then it lets the team query that
substrate without writing graph code.

---

## What's in this repository

Two cooperating systems plus glue:

1. **Knowledge-graph generation** (`iterative_search/`, `paper_fetching/`,
   `graph_enrichment/`, `nano_graphrag/`, `domain_schemas/`,
   `run_haiqu_iterative_pipeline.py`).
   Starting from a seed document (e.g. the HAIQU project PDF), the
   iterative pipeline extracts typed entities, prioritises the most
   informative ones, generates targeted literature search queries, fetches
   matching papers, and merges new entities and relations into a NetworkX
   graph. It converges when new searches stop adding novel nodes.

2. **GASL/RAG visualization UI** (`visualization/`, `gasl/`).
   A Flask + Socket.IO server that loads a GraphML graph and exposes:
   - **RAG mode** — TF-IDF + LLM-synthesized natural-language answers
     grounded in the most-relevant subgraph.
   - **GASL mode** — *Graph Action Specification Language*: an LLM
     generates a multi-step traversal plan (FIND, GRAPHWALK, AGGREGATE,
     PROCESS, …) that runs against the graph; intermediate state and
     command-by-command progress stream live to the browser.
   The UI is BYOK — each user pastes their own OpenAI key in the browser;
   the server never persists it.

3. **Inference backends** (`gasl/llm/argo_bridge.py`,
   `examples/using_custom_argo_bridge_api.py`,
   `run_with_argo_bridge.py`, `chia_test.sh`).
   The same LLM client speaks to either OpenAI's public API (default
   when a key is supplied at the call site) **or** Argonne's Argo gateway
   (default when reading env vars `LLM_API_KEY` / `LLM_ENDPOINT`). Argo
   is intended to run from a higher-bandwidth network node; the
   browser-facing UI server can stay user-key-only.

---

## Quick start

```bash
# 1. clone, venv, install
git clone https://github.com/chian/nano-graphrag.git
cd nano-graphrag
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt              # KG-gen pipeline deps
pip install flask flask-socketio scikit-learn # extra UI deps

# 2. run the visualization UI on a sample graph
./launch_viz.sh mmwr-test/graphrag_cache/graph_chunk_entity_relation.graphml
# open http://127.0.0.1:5050
# paste an OpenAI API key in the BYOK panel; pick a model; ask away.

# 3. (later) build a HAIQU graph end-to-end from the seed PDF — see below
```

For a Tailscale-served HTTPS deployment (no port forwarding, no public
exposure), bind to `0.0.0.0` and front with `tailscale serve`:

```bash
HOST=0.0.0.0 ./launch_viz.sh path/to/your.graphml
sudo ufw allow in on tailscale0 to any port 5050 proto tcp
tailscale serve --bg --https=443 http://localhost:5050
# https://<machine>.<tailnet>.ts.net is now serving the UI to your tailnet
```

---

## Building a HAIQU knowledge graph

The seed for HAIQU work is `haiqu/20260126 Cognitive Tests for HAIQU.pdf`.
Run the iterative pipeline to grow a typed graph from it:

```bash
export LLM_API_KEY=...                        # Argo or OpenAI
export LLM_ENDPOINT=...                       # only if using Argo
python run_haiqu_iterative_pipeline.py \
  --seed-pdf "haiqu/20260126 Cognitive Tests for HAIQU.pdf" \
  --output haiqu_graph/
```

The pipeline:
1. Chunks and extracts typed entities from the seed PDF.
2. Builds a `NetworkX` graph plus a per-entity priority queue
   (`iterative_search/entity_prioritizer.py`).
3. Generates search queries against the highest-priority entities
   (`iterative_search/iterative_query_generator.py`).
4. Fetches matching papers via Firecrawl
   (`paper_fetching/firecrawl_client.py`); requires a `FIRECRAWL_API_KEY`.
5. Re-extracts entities from new papers and merges
   (`graph_enrichment/graph_merger.py`).
6. Stops when convergence criteria are met
   (`iterative_search/convergence.py` — usually a moving-average drop in
   newly-added unique entities below a threshold).

Output is a GraphML file that drops straight into `launch_viz.sh`.

---

## Literature-search strategy for *seeding* the HAIQU knowledge graph

The goal of this section is **systematic discovery of every paper worth
ingesting** so the resulting graph represents the field, not just the
papers that happen to mention a few keywords. This is upstream of any
querying — without comprehensive seeding, GASL/RAG can only answer about
the literature we happened to feed it.

A PRISMA-flavoured pipeline, adapted to feed the iterative ingestion
engine.

### 1. Lock down inclusion / exclusion criteria first

Write these *before* running any searches; both the LLM inclusion gate
(step 7) and reviewers will need them. Suggested starting point — refine
with the HAIQU team's domain experts:

- **Topic:** indoor or hospital airborne pathogen detection, transmission
  modelling, or engineering controls. Include droplet/aerosol biology,
  bioaerosol sampling instrumentation, CRISPR-based diagnostics applied
  to aerosolised pathogens, HVAC/UV/filtration controls in healthcare,
  agent-based/digital-twin transmission models, QMRA/Wells-Riley risk
  frameworks.
- **Exclude** outdoor air pollution, occupational dust, non-airborne
  HAIs (catheter, surgical site), purely device-engineering papers with
  no biological readout, animal-only studies unless the model is
  explicitly translational.
- **Date window:** ≥2010 for primary research, ≥2020 for surveys; allow
  earlier for foundational methods cited from the seed.
- **Document types:** peer-reviewed primary research, peer-reviewed
  reviews, preprints (bioRxiv/medRxiv) flagged as such, agency guidance
  documents (ASHRAE/CDC/WHO/OSHA).
- **Languages:** English-language for now; flag others for translation.

### 2. Identify anchor reviews and seminal primary papers per subdomain

For each subdomain in the inclusion criteria, pick 3–5 recent (≤5 yr)
high-quality reviews and 3–5 most-cited primary papers. These become the
starting nodes for citation chasing in step 4 and provide the
*vocabulary* (MeSH terms, named methods, named instruments) that step 3
uses for Boolean searches. Ingest these manually, not via search.

### 3. Run reproducible Boolean searches against the major databases

Each search is recorded (database + query + date + result count) so the
corpus is reproducible. Concrete starter strings — adapt to the
HAIQU-specific framing:

**PubMed / Europe PMC (biomedical)**
```
("aerosol*"[Title/Abstract] OR "bioaerosol*"[Title/Abstract])
  AND ("hospital*"[Title/Abstract] OR "healthcare facilit*"[Title/Abstract])
  AND ("detection"[Title/Abstract] OR "sampling"[Title/Abstract]
        OR "monitoring"[Title/Abstract])
  AND ("2015/01/01"[PDAT] : "3000"[PDAT])
```
```
("CRISPR"[MeSH] OR "Cas13" OR "Cas12" OR "SHERLOCK" OR "DETECTR")
  AND ("droplet*"[Title/Abstract] OR "microfluidic*"[Title/Abstract])
  AND ("diagnostic*"[Title/Abstract] OR "detection"[Title/Abstract])
```
```
("nosocomial"[Title/Abstract] OR "healthcare-associated"[Title/Abstract])
  AND ("airborne"[Title/Abstract] OR "respiratory transmission"[Title/Abstract])
  AND ("model*"[Title/Abstract] OR "simulation"[Title/Abstract])
```

**Web of Science / Scopus** for cross-disciplinary work that PubMed
misses — specifically engineering-side papers on HVAC, UV-C disinfection,
aerosol physics, and digital-twin building modelling (try `WC=("Public,
Environmental & Occupational Health" OR "Construction & Building
Technology" OR "Engineering, Environmental")` plus the topical terms).

**arXiv** for the modelling side, esp. `q-bio.PE` (population +
ecology / epidemiology) and `eess.SY` (systems and control); search
`agent-based AND (hospital OR healthcare) AND (transmission OR
infection)`.

**bioRxiv + medRxiv** as the live frontier — query the same Boolean
strings as PubMed; many results show up there 6–18 months before
publication.

### 4. Citation chasing on every anchor

For each anchor (step 2) and each first-round Boolean hit (step 3),
expand both directions:

- **Backward** (references): pull cited papers via Crossref or
  the OpenCitations COCI dataset.
- **Forward** (citations): pull citing papers via the Semantic Scholar
  API (free, programmatic) or OpenAlex. Forward-citation chasing is
  where most novel-recent material comes from.

Iterate to depth 2 (anchor → its refs → their refs) before pruning;
hard-cap at depth 3.

### 5. Author-tracked corpora

Identify the most-active labs in each subdomain and ingest each PI's
full PubMed corpus filtered to relevant publications. A starter list to
*verify* with the HAIQU team rather than trust blindly:

- **Mayo Clinic / HAIQU PI lab**: Connie Chang — droplet microfluidics
  and pathogen detection.
- **Aerosol biology & transmission**: Linsey Marr (Virginia Tech),
  Don Milton (UMD), Lidia Morawska (QUT), Yuguo Li (HKU).
- **Hospital ventilation / engineering controls**: Edward Nardell
  (Harvard, upper-room UV-C), William Bahnfleth (Penn State, ASHRAE).
- **CRISPR diagnostics**: Pardis Sabeti (Broad, SHERLOCK lineage),
  Cameron Myhrvold (Princeton), Feng Zhang (Broad), Jennifer Doudna
  (UC Berkeley).
- **Bioaerosol sampling instrumentation**: groups associated with the
  AIHA, AAAR, and ISIAQ communities.

The HAIQU team should add and remove names. Ingest the *full* PubMed
output for each chosen PI — relevance is enforced at step 7, not here.

### 6. Funder-, conference-, and grey-literature passes

Sources that keyword search misses but that are highly enriched for
HAIQU-relevant content:

- **Funder programs**: ARPA-H BREATHE awardees and their pubs, NIH
  RADx-rad, NIH NIBIB, BARDA diagnostics contracts, CDC outbreak
  investigation reports. Track via NIH RePORTER, BARDA's portfolio page,
  and ARPA-H funded-projects pages.
- **Conferences**: Indoor Air (ISIAQ, biennial), AAAR Annual Meeting,
  ASHRAE Annual + Winter, IDWeek, SHEA Spring, APIC, AIHce. Many of
  these publish proceedings that PubMed doesn't index.
- **Standards & guidance**: ASHRAE Standard 170 (*Ventilation of Health
  Care Facilities*); CDC's *Guidelines for Environmental Infection
  Control in Health-Care Facilities* (HICPAC); WHO IPC technical
  guidance; OSHA respirator standards. These are PDFs — feed them into
  `extract_pdfs_to_text.py` directly.

### 7. LLM-gated inclusion before entity extraction

For every candidate paper from steps 3–6, run a small LLM call over
title + abstract that returns a yes/no plus a one-sentence reason
against the inclusion criteria from step 1. Reject before paying for
full-text entity extraction. Log the reasons so reviewers can audit
exclusions.

### 8. Continuous feeds (a "living review")

The HAIQU corpus is moving — bake in re-ingestion:

- bioRxiv + medRxiv RSS for the relevant subject areas, polled weekly.
- PubMed saved searches with email alerts for the step-3 strings.
- New publications by tracked authors (PubMed alerts per author).
- ARPA-H, NIH RePORTER, BARDA RSS / scrape for new awards and
  publications from funded teams.

Each new paper goes through the same inclusion gate (step 7) before
ingestion.

### 9. Convergence and rebalancing

After each ingestion round, the iterative pipeline already tracks novel
entities added (`iterative_search/convergence.py`). Layer in a manual
review every ~100 papers:

- Is one subdomain over-represented (e.g., CRISPR diagnostics is
  90% of nodes, HVAC controls is 2%)? Re-seed the underrepresented
  subdomain with a fresh round of searches focused on it.
- Are entity types balanced relative to the typed vocabulary in
  `domain_schemas/`? Sparse types usually mean sparse coverage.
- Are recent (last 12 mo) papers represented proportionally? If not,
  the corpus is aging; pull a fresh preprint pass.

### 10. Reproducibility and provenance

Every ingestion writes:
- The exact search strings, databases, date, and result counts.
- The inclusion-gate decisions per paper.
- A graph snapshot (`.graphml`) tagged with the corpus version.

So when a reviewer asks *"why does the GASL answer change between last
month and this month?"*, you can diff corpus versions and point at the
specific papers that joined the graph.

### Operational notes for running this

1. **Run inference on the high-bandwidth host.** Iterative graph build
   is LLM-heavy. Run it where Argo access is fast; ship the `.graphml`
   to the UI host.
2. **Use `domain_schemas/` to constrain entity types.** Tighter types
   make GASL plans dramatically more precise — and make step 9's
   imbalance check meaningful.
3. **Snapshot between iterations.** `gasl/graph_versioning.py` already
   supports this.
4. **Don't let the seed PDF dominate.** Treat the HAIQU project PDF as
   one anchor, not the centre of the universe. The graph should know
   about each anchor's neighbourhood independently.

---

## Querying the graph: GASL vs RAG

| | RAG | GASL |
|---|---|---|
| Latency | Seconds | Tens of seconds to minutes |
| LLM calls | 1 (synthesis) | Many (plan, execute, validate per iteration) |
| Best for | "Tell me what the literature says about X" | "Compute Y over the graph" — counts, intersections, multi-hop paths, comparisons |
| Output | Paragraph + 15 most-relevant nodes | Final answer + every intermediate state variable + a streaming command log |
| When it fails | Vague paragraphs that miss niche entities | Plans that don't converge inside `max_iterations` (currently 8) |

Pick RAG to brainstorm; pick GASL when the question has a real *operation*
in it ("how many", "which", "compare A and B", "find a path from
biosensor X to clinical outcome Y").

---

## Inference backends

The `ArgoBridgeLLM` class in `gasl/llm/argo_bridge.py` is a thin wrapper
over the OpenAI Python SDK. Two ways to point it:

- **OpenAI (default for the UI)** — pass `api_key=` and (optionally)
  `model=` at construction. The browser BYOK panel does this per-request,
  so a single UI server can serve many users on their own keys.

- **Argonne Argo (default for CLI / pipeline scripts)** — set
  `LLM_API_KEY`, `LLM_ENDPOINT`, `LLM_MODEL` env vars. The default
  endpoint targets `apps-dev.inside.anl.gov/argoapi/v1`; reachable only
  from inside ANL or via VPN. `chia_test.sh` shows the env block.

Different OpenAI models have different parameter rules. The bridge
handles them automatically:
- `o1`/`o3`/`o4` reasoning models use `max_completion_tokens` instead of
  `max_tokens`, and reject custom `temperature` (locked at default 1.0).
- GPT-5 reasoning variants (`gpt-5`, `gpt-5-mini`, `gpt-5-nano`,
  `gpt-5.5*`, any `*-chat-latest` alias) follow the same rules.
- GPT-5 non-reasoning (`gpt-5.4*`, `gpt-5.2`, `gpt-5.1`) and GPT-4.1 use
  `max_completion_tokens` but accept custom temperature.
- GPT-4 and earlier still use `max_tokens`.

We tested 26 models; `gpt-5.4-mini` is the current default — fastest
correct on a representative HAIQU-adjacent test query in 1 iteration.

---

## Repository layout

```
.
├── run_haiqu_iterative_pipeline.py   # KG-gen entry point for HAIQU
├── iterative_search/                 # iterative graph-build engine
├── paper_fetching/                   # Firecrawl + PMID/DOI fetchers
├── graph_enrichment/                 # merge new entities into existing graph
├── domain_schemas/                   # typed-entity vocabularies
├── nano_graphrag/                    # forked nano-graphrag core (entity extraction, etc.)
│
├── gasl/                             # GASL parser, executor, command handlers
│   ├── adapters/                     # NetworkX + Neo4j backends
│   ├── commands/                     # FIND, GRAPHWALK, AGGREGATE, …
│   └── llm/argo_bridge.py            # OpenAI/Argo client
├── visualization/                    # Flask + Socket.IO UI
│   ├── server.py                     # /api/query, /api/graph, /api/stats
│   ├── query_engine.py               # RagQueryEngine + GaslQueryEngine
│   ├── templates/viewer.html         # the BYOK + dropdown + graph viewer
│   └── examples/demo.py              # CLI launcher
│
├── analytical_retriever.py           # alternative LLM-driven decomposer
├── enrich_graph_with_papers.py       # add new papers to an existing graph
├── fetch_papers_firecrawl.py         # standalone paper-fetch CLI
├── extract_pdfs_to_text.py           # PDF → text preprocessor
├── inspect_graph.py                  # quick GraphML inspector
├── gasl_main.py                      # GASL CLI (no UI)
├── debug_gasl_queries.py             # run a single GASL plan and dump state
├── test_commands.py                  # parse-and-execute one GASL command
├── launch_viz.sh                     # UI launcher (uses .venv if present)
│
├── haiqu/                            # HAIQU project seed PDF
├── mmwr-test/                        # sample graph for demos
├── examples/                         # nano-graphrag usage examples
├── tests/
└── docs/                             # architecture, GASL guide, benchmarks
```

---

## Status, caveats, follow-ups

- **The visualization Flask server runs in debug mode.** Fine for a
  Tailscale-only deployment behind real TLS; do not put it on the public
  internet without putting a real WSGI server (gunicorn / uvicorn) in
  front and turning debug off.
- **GASL plan quality varies by model.** The smallest models bail early
  with confidently wrong answers; reasoning flagships sometimes
  over-iterate. `gpt-5.4-mini` and `gpt-4.1-mini` are the
  cost/quality sweet spots in our testing.
- **`max_iterations` is 8.** Tunable in
  `visualization/query_engine.py::GaslQueryEngine.run`.
- **`gpt-5-pro`, `gpt-5.5-pro`, `gpt-5.4-pro`, `gpt-5.2-pro`, and
  `o1-pro`** are not yet supported — they require OpenAI's Responses API
  rather than `v1/chat/completions`. Plumbing pending.
- **`gpt-3.5-turbo` is unusable** — the GASL plan prompt alone
  exceeds its 16k context window.

---

## License

See `LICENSE`. The `nano_graphrag/` directory is a fork of
[gusye1234/nano-graphrag](https://github.com/gusye1234/nano-graphrag)
with HAIQU-relevant additions; upstream license preserved.
