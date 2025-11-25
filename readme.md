<div align="center">
  <a href="https://github.com/gusye1234/nano-graphrag">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://assets.memodb.io/nano-graphrag-dark.png">
      <img alt="Shows the MemoDB logo" src="https://assets.memodb.io/nano-graphrag.png" width="512">
    </picture>
  </a>
  <p><strong>A simple, easy-to-hack GraphRAG implementation</strong></p>
  <p>
    <img src="https://img.shields.io/badge/python->=3.9.11-blue">
    <a href="https://pypi.org/project/nano-graphrag/">
      <img src="https://img.shields.io/pypi/v/nano-graphrag.svg">
    </a>
    <a href="https://codecov.io/github/gusye1234/nano-graphrag" >
     <img src="https://codecov.io/github/gusye1234/nano-graphrag/graph/badge.svg?token=YFPMj9uQo7"/>
		</a>
    <a href="https://pepy.tech/project/nano-graphrag">
      <img src="https://static.pepy.tech/badge/nano-graphrag/month">
    </a>
  </p>
  <p>
  	<a href="https://discord.gg/sqCVzAhUY6">
      <img src="https://dcbadge.limes.pink/api/server/sqCVzAhUY6?style=flat">
    </a>
    <a href="https://github.com/gusye1234/nano-graphrag/issues/8">
       <img src="https://img.shields.io/badge/群聊-wechat-green">
    </a>
  </p>
</div>

---

## Why nano-graphrag?

😭 [GraphRAG](https://arxiv.org/pdf/2404.16130) is good and powerful, but the official [implementation](https://github.com/microsoft/graphrag/tree/main) is difficult/painful to **read or hack**.

😊 This project provides a **smaller, faster, cleaner GraphRAG**, while maintaining the core functionality ([benchmark](#benchmark)).

🎁 **~1100 lines of code** (excluding tests and prompts)

👌 Small yet **[portable](#components)** (faiss, neo4j, ollama...), **[asynchronous](#async)**, and fully typed

🚀 **Advanced features**: [GASL](#gasl) for graph queries, [QA generation](#qa-generation) for training data, query-aware prompts

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Core Features](#core-features)
- [Components & Extensions](#components--extensions)
- [Advanced Features](#advanced-features)
  - [GASL (Graph Analysis & Scripting Language)](#gasl-graph-analysis--scripting-language)
  - [QA Generation](#qa-generation)
  - [Query-Aware Processing](#query-aware-processing)
- [Documentation](#documentation)
- [Projects Using nano-graphrag](#projects-using-nano-graphrag)
- [Contributing](#contributing)

---

## Installation

### From PyPI (Stable)

```bash
pip install nano-graphrag
```

### From Source (Latest)

```bash
git clone https://github.com/gusye1234/nano-graphrag
cd nano-graphrag
pip install -e .
```

### Requirements

- Python >= 3.9.11
- OpenAI API key (or use [alternative LLMs](#llm-providers))

---

## Quick Start

### Basic Usage

**Set up your API key:**
```bash
export OPENAI_API_KEY="sk-..."
```

**Download sample data:**
```bash
curl https://raw.githubusercontent.com/gusye1234/nano-graphrag/main/tests/mock_data.txt > ./book.txt
```

**Build and query a knowledge graph:**
```python
from nano_graphrag import GraphRAG, QueryParam

# Initialize GraphRAG
graph_func = GraphRAG(working_dir="./dickens")

# Insert documents (builds knowledge graph)
with open("./book.txt") as f:
    graph_func.insert(f.read())

# Query using local mode (entity-focused, fast)
answer = graph_func.query(
    "What are the top themes in this story?",
    param=QueryParam(mode="local")
)
print(answer)

# Query using global mode (comprehensive, slower)
answer = graph_func.query(
    "What are the top themes in this story?",
    param=QueryParam(mode="global")
)
print(answer)
```

**Next run:** GraphRAG automatically reloads from `working_dir`—no need to rebuild!

### Async Support

```python
# All methods have async versions
await graph_func.ainsert(documents)
await graph_func.aquery(query)
```

### Batch Operations

```python
# Insert multiple documents at once
graph_func.insert(["TEXT1", "TEXT2", "TEXT3"])

# Incremental insert (no duplicates, uses MD5 hash)
with open("./book.txt") as f:
    book = f.read()
    half = len(book) // 2
    graph_func.insert(book[:half])
    graph_func.insert(book[half:])  # No duplication!
```

---

## Core Features

### 1. Knowledge Graph Construction

- **Entity Extraction**: LLM-powered entity and relationship extraction
- **Dynamic Entity Types**: Query-aware entity type generation
- **Community Detection**: Leiden/Louvain algorithms for graph clustering
- **Incremental Updates**: MD5-based deduplication for efficient updates

### 2. Three Query Modes

| Mode | Speed | Accuracy | Best For |
|------|-------|----------|----------|
| **Local** | Fast | High | Specific entities, relationships |
| **Global** | Slow | Highest | Broad themes, comprehensive analysis |
| **Naive** | Fastest | Medium | Simple facts, baseline comparison |

**Local Mode**: Vector search → graph traversal → context assembly → LLM generation
**Global Mode**: Community detection → community reports → map-reduce synthesis
**Naive Mode**: Simple vector similarity search (no graph)

### 3. Query-Aware Processing

- **Dynamic Prompts**: Automatically optimize prompts for specific queries
- **Content-Adaptive**: Entity types adapt to document content
- **Smart Chunking**: Token-based or semantic splitting

### 4. Pluggable Architecture

Replace any component with your own implementation:
- **LLM**: OpenAI, Azure, Bedrock, Ollama, DeepSeek, or custom
- **Embeddings**: OpenAI, Bedrock, sentence-transformers, or custom
- **Vector DB**: NanoVectorDB, HNSW, Milvus, FAISS
- **Graph DB**: NetworkX, Neo4j

---

## Components & Extensions

### LLM Providers

| Provider | Status | Documentation |
|----------|--------|---------------|
| OpenAI | ✅ Built-in | Default (`gpt-4o`, `gpt-4o-mini`) |
| Azure OpenAI | ✅ Built-in | [.env.example.azure](./.env.example.azure) |
| Amazon Bedrock | ✅ Built-in | [Example](./examples/using_amazon_bedrock.py) |
| DeepSeek | 📘 Example | [Example](./examples/using_deepseek_as_llm.py) |
| Ollama | 📘 Example | [Example](./examples/using_ollama_as_llm.py) |
| Custom | ✅ Supported | [Guide](./docs/ARCHITECTURE.md#extension-points) |

### Embedding Models

| Model | Status | Documentation |
|-------|--------|---------------|
| OpenAI | ✅ Built-in | Default (`text-embedding-3-small`) |
| Amazon Bedrock | ✅ Built-in | [Example](./examples/using_amazon_bedrock.py) |
| Sentence-transformers | 📘 Example | [Example](./examples/using_local_embedding_model.py) |
| Custom | ✅ Supported | [Guide](./docs/ARCHITECTURE.md#2-custom-embedding-function) |

### Vector Databases

| Database | Status | Documentation |
|----------|--------|---------------|
| NanoVectorDB | ✅ Built-in | Default (lightweight) |
| HNSW | ✅ Built-in | [Example](./examples/using_hnsw_as_vectorDB.py) |
| Milvus Lite | 📘 Example | [Example](./examples/using_milvus_as_vectorDB.py) |
| FAISS | 📘 Example | [Example](./examples/using_faiss_as_vectorDB.py) |
| Qdrant | 📘 Example | [Example](./examples/using_qdrant_as_vectorDB.py) |

### Graph Storage

| Storage | Status | Documentation |
|---------|--------|---------------|
| NetworkX | ✅ Built-in | Default (in-memory + GraphML) |
| Neo4j | ✅ Built-in | [Guide](./docs/use_neo4j_for_graphrag.md) |

---

## Advanced Features

### GASL (Graph Analysis & Scripting Language)

**GASL** is a domain-specific language for LLM-driven graph analysis with **hypothesis-driven traversal (HDT)**.

#### Why GASL?

Traditional RAG: `Query → Vector Search → Context → Answer` (limited coverage, no exploration)

GASL: `Query → Hypothesis → Plan → Execute → Evaluate → Refine → Answer` (complete coverage, systematic)

#### Key Features

- 🧠 **LLM-Driven Planning**: Natural language queries → executable graph operations
- 🔄 **Hypothesis-Driven Traversal**: Iterative exploration with refinement
- 📊 **Rich Command Set**: 30+ commands for graph analysis
- 💾 **State Management**: Persistent state across commands
- 🔍 **Provenance Tracking**: Trace results to source documents

#### Quick Example

```bash
python gasl_main.py \
  --working-dir /path/to/graph \
  --query "Create a histogram of how often author names appear" \
  --max-iterations 5
```

**Generated Plan (by LLM)**:
```json
{
  "hypothesis": "Author names are in PERSON entity descriptions",
  "commands": [
    "FIND nodes with entity_type=PERSON AS authors",
    "PROCESS authors with instruction: Extract author name from description AS names",
    "ADD_FIELD authors field: author_name = names",
    "COUNT authors field author_name AS histogram"
  ]
}
```

#### Core GASL Commands

**Discovery**: `DECLARE`, `FIND`, `SELECT`, `SET`
**Processing**: `PROCESS`, `CLASSIFY`, `UPDATE`, `COUNT`
**Graph Navigation**: `GRAPHWALK`, `GRAPHCONNECT`, `SUBGRAPH`, `GRAPHPATTERN`
**Data Combination**: `JOIN`, `MERGE`, `COMPARE`
**Object Creation**: `CREATE_NODES`, `CREATE_EDGES`, `GENERATE`

👉 **[Full GASL Guide](./docs/GASL_GUIDE.md)**

---

### QA Generation

Generate high-quality reasoning questions from knowledge graphs for training data (e.g., models with `<think>` tokens).

#### Reasoning QA (Recommended)

Most sophisticated generator with diversity tracking and quality filtering:

```bash
python generate_reasoning_qa.py \
  --working-dir /path/to/graph/graphrag_cache \
  --num-questions 100 \
  --min-quality-score 7
```

**Features**:
- 🎯 **Topic Diversity**: Tracks last 20 topics, avoids repetition
- ⭐ **Quality Filtering**: Only questions scoring ≥7/10 pass
- 🧬 **Multiple Reasoning Types**: Mechanistic, comparative, causal, predictive
- 🔬 **Scientific Rigor**: Self-contained, no "the text" references

**Example Output**:
```json
{
  "question": "Which mechanism best explains how antibiotic resistance emerges?",
  "choices": {"A": "...", "B": "...", "C": "...", "D": "...", "E": "...", "F": "...", "G": "...", "H": "..."},
  "answer": "B",
  "reasoning_type": "mechanistic",
  "quality_score": 9
}
```

#### Other QA Types

**Multi-Hop QA**: Chain facts across graph paths
```bash
python generate_multihop_qa.py --working-dir /path/to/graph --num-questions 50 --path-length 2
```

**Synthesis QA**: Integrate information from multiple sources
```bash
python generate_synthesis_qa.py --working-dir /path/to/graph --num-questions 30
```

**Logic Puzzle QA**: Constraint satisfaction problems
```bash
python generate_logic_puzzle_qa.py --working-dir /path/to/graph --num-questions 20
```

👉 **[Full QA Generation Guide](./docs/QA_GENERATION.md)**

---

### Query-Aware Processing

All prompts and processing are optimized based on your specific query:

```python
from nano_graphrag.prompt_system import QueryAwarePromptSystem, set_prompt_system

# Set up query-aware prompts
prompt_system = QueryAwarePromptSystem(llm_func=your_llm)
set_prompt_system(prompt_system)

# Now entity types and extraction adapt to your queries!
```

**Features**:
- **Dynamic Entity Types**: Generated based on query + content
- **Optimized Prompts**: LLM optimizes prompts for specific queries
- **Content-Adaptive**: Processing tailored to document domain

---

## Documentation

### Core Documentation

- 📖 **[Architecture Guide](./docs/ARCHITECTURE.md)** - System design, components, data flow
- 🔧 **[GASL Guide](./docs/GASL_GUIDE.md)** - Complete GASL reference with examples
- 📝 **[QA Generation Guide](./docs/QA_GENERATION.md)** - Generate training data from graphs
- 🔌 **[Storage Backends](./docs/ARCHITECTURE.md#storage-system)** - Configure KV, vector, and graph storage
- 🌐 **[Neo4j Integration](./docs/use_neo4j_for_graphrag.md)** - Use Neo4j as graph backend

### Additional Resources

- ❓ **[FAQ](./docs/FAQ.md)** - Frequently asked questions
- 🗺️ **[Roadmap](./docs/ROADMAP.md)** - Future development plans
- 🤝 **[Contributing](./docs/CONTRIBUTING.md)** - Contribution guidelines
- 📊 **[Benchmarks](./docs/benchmark-en.md)** - Performance comparisons

---

## Configuration Examples

### Custom LLM

```python
async def my_llm_complete(prompt, system_prompt=None, history_messages=[], **kwargs) -> str:
    hashing_kv = kwargs.pop("hashing_kv", None)  # Optional cache
    response = await your_llm_api(prompt, **kwargs)
    return response

graph_func = GraphRAG(
    best_model_func=my_llm_complete,
    best_model_max_token_size=8192,
    best_model_max_async=16
)
```

### Custom Embedding

```python
from nano_graphrag._utils import wrap_embedding_func_with_attrs

@wrap_embedding_func_with_attrs(embedding_dim=384, max_token_size=512)
async def my_embedding(texts: list[str]) -> np.ndarray:
    return your_model.encode(texts)

graph_func = GraphRAG(
    embedding_func=my_embedding,
    embedding_batch_num=32
)
```

### Custom Storage

```python
from nano_graphrag.base import BaseVectorStorage

class MyVectorDB(BaseVectorStorage):
    async def upsert(self, data): ...
    async def query(self, query, top_k): ...

graph_func = GraphRAG(vector_db_storage_cls=MyVectorDB)
```

### Azure OpenAI

```python
# Set environment variables (see .env.example.azure)
graph_func = GraphRAG(
    working_dir="./cache",
    using_azure_openai=True
)
```

### Ollama (Local LLM)

```python
# See examples/using_ollama_as_llm.py
from examples.using_ollama_as_llm import ollama_model_complete, ollama_embedding

graph_func = GraphRAG(
    best_model_func=ollama_model_complete,
    cheap_model_func=ollama_model_complete,
    embedding_func=ollama_embedding
)
```

---

## Benchmark

- 📊 [English Benchmark](./docs/benchmark-en.md)
- 📊 [Chinese Benchmark](./docs/benchmark-zh.md)
- 📓 [Multi-Hop RAG Evaluation](./examples/benchmarks/eval_naive_graphrag_on_multi_hop.ipynb)

---

## Projects Using nano-graphrag

- [Medical Graph RAG](https://github.com/MedicineToken/Medical-Graph-RAG) - Graph RAG for Medical Data
- [LightRAG](https://github.com/HKUDS/LightRAG) - Simple and Fast Retrieval-Augmented Generation
- [fast-graphrag](https://github.com/circlemind-ai/fast-graphrag) - Adaptive RAG system
- [HiRAG](https://github.com/hhy-huang/HiRAG) - Hierarchical Knowledge RAG

> ❤️ Welcome PRs if your project uses `nano-graphrag`!

---

## Known Limitations

- `nano-graphrag` does not implement the `covariates` feature from the original GraphRAG
- Global search differs from original: uses top-K communities (default: 512) instead of map-reduce over all communities
  - Control with `QueryParam(global_max_consider_community=512)`

---

## Contributing

Contributions are welcome! Read the [Contributing Guide](./docs/CONTRIBUTING.md) before submitting PRs.

**Areas for contribution**:
- Additional storage backends (Pinecone, Weaviate, etc.)
- More LLM providers
- Performance optimizations
- Documentation improvements
- Bug fixes and tests

---

## Citation

If you use nano-graphrag in your research, please cite:

```bibtex
@software{nano-graphrag,
  title = {nano-graphrag: A Simple, Easy-to-Hack GraphRAG Implementation},
  author = {Gusye},
  year = {2024},
  url = {https://github.com/gusye1234/nano-graphrag}
}
```

---

## License

MIT License - see [LICENSE](./LICENSE) for details

---

## Community

- 💬 [Discord](https://discord.gg/sqCVzAhUY6)
- 💬 [WeChat](https://github.com/gusye1234/nano-graphrag/issues/8)
- 🐛 [Issues](https://github.com/gusye1234/nano-graphrag/issues)
- 📢 [Discussions](https://github.com/gusye1234/nano-graphrag/discussions)

---

<div align="center">
  <p><strong>⭐ Star this repo if you find it useful!</strong></p>
  <p>Looking for a multi-user RAG solution? Check out <a href="https://github.com/memodb-io/memobase">memobase</a></p>
</div>
