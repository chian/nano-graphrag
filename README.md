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

This is upstream of any querying — without comprehensive seeding,
GASL/RAG can only answer about the literature we happened to feed it.
The whole point of the strategy is to **let Firecrawl do the heavy
lifting**. Don't roll your own PRISMA review across PubMed + Web of
Science + Scopus + Crossref + Semantic Scholar; aim a few well-shaped
Firecrawl calls at the open web and let it scrape, render, follow
links, and return clean markdown.

### What Firecrawl gives us (the four primitives we actually use)

| Endpoint | What it does | When to use it for HAIQU seeding |
|---|---|---|
| **`/search`** (already wired in `firecrawl_client.search_papers`) | Web search + content fetch in one call. Each result comes back already scraped to markdown. Supports `tbs` time filters (`qdr:m`, `qdr:y`) and standard Google operators (`site:`, `intitle:`, `OR`). | Topic searches per subdomain, time-bounded preprint passes, site-scoped queries. |
| **`/scrape`** (already wired in `firecrawl_client.download_paper_content`) | One URL → clean markdown / HTML / structured JSON. Renders JS, optionally only-main-content. | Pull a known paper's full text from a DOI or PubMed URL when /search returned only metadata. |
| **`/crawl`** | Recursively fetch every page reachable from a starting URL, with include/exclude path patterns and depth caps. | Scrape an author's institutional publications page, a journal's TOC archive, a funder's awardee list, or a preprint server's subject feed — without writing a custom scraper for each. |
| **`/extract`** | URL(s) + JSON schema → structured data extracted by an LLM. Returns title/authors/DOI/abstract/key-claims as a typed object. | Skip writing per-publisher HTML parsers; feed paper landing pages and a paper-metadata schema and let Firecrawl + the LLM populate it. |
| **`/batch-scrape`** | A list of URLs scraped in one job. | Forward citation chasing — feed in a list of DOI URLs, get markdown back en masse. |

The repo currently uses only `/search` and `/scrape`. The other three
endpoints unlock the rest of this strategy without writing more
infrastructure.

### Quick mechanics

- `FIRECRAWL_API_KEY` env var, or `--firecrawl-api-key` flag to
  `run_haiqu_iterative_pipeline.py`.
- `paper_fetching/firecrawl_client.py` already filters results to a
  scientific-domain allowlist (PubMed, PMC, bioRxiv, medRxiv, Nature,
  Science, Cell, PLOS, Frontiers, Springer, Wiley, ACS, arXiv) and
  blocks news/blog noise (Wikipedia, Medscape, WebMD, Reddit, etc.).
  Edit those two lists when a domain you trust is being filtered out.
- All Firecrawl calls return tokens of usage in their JSON; track for
  cost.

### Patterns for HAIQU seeding, ordered roughly by laziness

#### Pattern 1 — `/search` topic queries (lazy default)

The cheapest pass. Aim each query at one HAIQU subdomain. Firecrawl's
search supports Google operators, so use `site:` to restrict to the
publishers you trust:

```
microfluidic droplet CRISPR airborne pathogen detection
  site:pubmed.ncbi.nlm.nih.gov OR site:biorxiv.org OR site:medrxiv.org

bioaerosol sampler hospital ICU
  site:ncbi.nlm.nih.gov OR site:nature.com OR site:cell.com

agent-based model nosocomial transmission
  site:plos.org OR site:springer.com OR site:nature.com

ASHRAE 170 healthcare ventilation infection control
  site:cdc.gov OR site:ashrae.org OR site:who.int
```

The iterative pipeline already runs queries in this shape; the upgrade
is to *write better queries*, not to add infrastructure.

#### Pattern 2 — time-bounded `/search` for the live frontier

Firecrawl's search accepts `tbs` (Google's `qdr:` time filter). Pass
`tbs=qdr:m` to restrict results to the last month, `qdr:y` for the last
year. Run the same topic queries from Pattern 1 with `qdr:m` on a
weekly cron — that's your "living review" continuous feed, no RSS
plumbing required.

#### Pattern 3 — `/crawl` author / funder / journal pages

Instead of "find the right paper one query at a time," point Firecrawl
at a page that *lists* papers and let it follow:

- Author publications: `/crawl https://pubmed.ncbi.nlm.nih.gov/?term=Chang+CC+Mayo+Clinic` with `includePaths: ["/article/.*"]` and `maxDepth: 2` pulls every paper page that user clicks through to.
- Funder awardees: `/crawl https://arpa-h.gov/explore-funding/programs/breathe`.
- Journal subject feed: `/crawl https://www.biorxiv.org/collection/microbiology` with `tbs=qdr:y` semantics implemented via include patterns on date.
- A specific bibliography: pass an HTML reference list URL with
  `includePaths` matching DOI patterns.

This is the lazy substitute for "build a per-publisher scraper to chase
citations and author corpora." You define the *starting page* and the
*url-pattern filter*; Firecrawl handles the rest.

#### Pattern 4 — `/extract` with a schema for structured ingestion

For each paper landing page, ask Firecrawl + an LLM to populate a
schema like:

```json
{
  "title": "string",
  "authors": ["string"],
  "doi": "string",
  "abstract": "string",
  "publication_date": "string",
  "journal": "string",
  "key_entities": [
    {"type": "PATHOGEN|METHOD|DEVICE|MODEL", "name": "string"}
  ],
  "cited_dois": ["string"]
}
```

This collapses three steps (scrape → parse HTML → entity-extract) into
one Firecrawl call. The `cited_dois` field then feeds Pattern 5.

#### Pattern 5 — `/batch-scrape` for forward/backward citation chasing

Once Pattern 4 has a list of cited DOIs, fire them all into
`/batch-scrape` with the same paper-metadata schema. That's
citation-chasing in two API calls per round, no Crossref / OpenCitations
/ Semantic Scholar account required.

For *forward* citation chasing (papers that cite a given paper), the
laziest move is `/search "intitle:<paper title>"` with `tbs=qdr:y` and
let Google's index find later citing work; or `/crawl` the paper's
Semantic Scholar page directly.

#### Pattern 6 — grey-lit PDFs as direct `/scrape` calls

ASHRAE 170, CDC HICPAC guidelines, WHO IPC, OSHA standards: most are
PDFs at known URLs. `/scrape` returns clean markdown from a PDF with
`formats: ["markdown"]`. No special PDF handling on our side.

### Quality gates (these stay regardless of source)

These aren't Firecrawl features; they're the part you have to keep
discipline on:

1. **Inclusion / exclusion criteria, written down before searching.**
   For HAIQU, a starting point: indoor/hospital airborne pathogen
   detection, transmission modelling, engineering controls. Exclude
   outdoor air, occupational dust, non-airborne HAIs, animal-only
   work without translational claims. Date ≥2010 (≥2020 for surveys).
2. **LLM inclusion gate before entity extraction.** For every
   `/search` result and every paper from a `/crawl`, run a small LLM
   call over title + abstract: `does this match the criteria, yes/no,
   one-sentence reason`. Reject before paying full-text entity
   extraction. Log decisions for audit.
3. **Convergence + rebalancing.** `iterative_search/convergence.py`
   already tracks novel entities per round. Every ~100 papers
   ingested, eyeball the entity-type distribution against
   `domain_schemas/`. If one subdomain is 90% of nodes, queue a
   fresh `/search` pass focused on the under-represented one.
4. **Provenance.** Log every Firecrawl call: endpoint, query / URL /
   schema, result count, the gate decisions, the graph snapshot. When
   a reviewer asks why an answer changed, diff corpus versions and
   point at the new papers.

### Operational notes

1. **Run on the high-bandwidth host.** Firecrawl calls are network-
   bound, the entity-extraction LLM calls are compute-bound; both want
   the Argo-bandwidth machine. Ship the resulting `.graphml` to the UI
   host.
2. **`domain_schemas/` to constrain types.** Tighter typed vocab makes
   GASL plans dramatically more precise and makes the rebalancing
   check meaningful.
3. **Snapshot between iterations** via `gasl/graph_versioning.py`.
4. **Don't let the HAIQU PDF dominate.** Treat it as one anchor, not
   the centre of the universe. Each Pattern-1 query should pull from a
   neighbourhood the seed PDF doesn't cover.
5. **Edit the domain allow/block lists in `firecrawl_client.py`** when
   you need to ingest from a new publisher — they're at the top of the
   file (`SCIENTIFIC_DOMAINS`, `EXCLUDED_DOMAINS`).

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
