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

## Suggested literature-search strategy for HAIQU

The iterative pipeline's quality is gated by how well-seeded its search
terms are. For HAIQU specifically, here's what's worth feeding in beyond
the seed PDF:

### Domains to search

| Topic | Why it matters for HAIQU | Example seed terms |
|---|---|---|
| **CRISPR-based pathogen detection** | Core biosensor mechanism | SHERLOCK, DETECTR, Cas13a, Cas12a, isothermal amplification, microfluidic CRISPR |
| **Microfluidic droplet platforms** | The biosensor substrate | digital droplet PCR, droplet microfluidics, droplet biosensor, single-cell partitioning |
| **Bioaerosol sampling & detection** | Getting pathogens *into* the biosensor | bioaerosol sampler, impactor, cyclone sampler, electrostatic precipitation, BioSpot, BC-251 |
| **Airborne pathogen viability** | What the signal means clinically | viral aerosol decay, Wells-Riley, RH effects on aerosol, particle size distribution of respiratory droplets |
| **Hospital-acquired infections** | Outcomes the project intervenes on | nosocomial transmission, HAI, healthcare-associated infections, *M. tuberculosis*, MRSA, VRE, *C. difficile*, SARS-CoV-2 nosocomial, RSV, *Aspergillus* |
| **HVAC & engineering controls** | The deployment environment | hospital ventilation, ACH, HEPA, UV-C upper-room, isolation room negative pressure, ASHRAE 170 |
| **Agent-based & digital-twin models** | Project's modelling deliverable | agent-based hospital models, digital twin healthcare, FRED, COMOKIT, indoor microbiome dispersion |
| **Risk-assessment frameworks** | How to compose detections into a risk score | quantitative microbial risk assessment (QMRA), Wells-Riley, real-time exposure modelling |

### Where to point the fetchers

- **PubMed / Europe PMC** for the biology and clinical literature
  (`paper_fetching` already supports PMID-based lookups).
- **bioRxiv + medRxiv** for current-year preprints — HAIQU's frontier is
  preprint-heavy, especially on aerosol biology and CRISPR diagnostics.
- **arXiv `cs.LG` / `q-bio.PE`** for the agent-based-model side.
- **CDC, WHO, ASHRAE** publications for guideline anchors (these often
  serve as nucleation points whose neighbours in the graph then point at
  the primary literature).
- **Mayo Clinic faculty publications**, including Connie Chang's prior
  work on droplet CRISPR — often the most context-rich entry points.

### Practical tips

1. **Start narrow, expand**. Run the pipeline first with a tight set
   of biosensor-CRISPR seeds, build a small graph, look at it in the UI,
   then re-seed with whatever entity types are sparsest.
2. **Use domain schemas**. `domain_schemas/` lets you constrain
   extraction to a typed vocabulary (PATHOGEN, BIOSENSOR_METHOD,
   HVAC_CONTROL, …). Tighter types make GASL queries dramatically more
   precise.
3. **Run inference on the bigger pipe**. Iterative graph build is LLM-
   heavy. Run that on a host with Argo access (high bandwidth, low cost)
   and copy the resulting `.graphml` to the UI host.
4. **Snapshot and version**. The pipeline writes intermediate GraphML
   files between iterations; commit those snapshots somewhere (or use
   `gasl/graph_versioning.py`) so you can compare "what did the graph
   know last week vs today" — useful when reviewers ask why an answer
   changed.

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
