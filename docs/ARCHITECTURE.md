# nano-graphrag Architecture Guide

This document provides a comprehensive overview of the nano-graphrag architecture, component relationships, and data flow.

## Table of Contents

1. [System Overview](#system-overview)
2. [Core Package Structure](#core-package-structure)
3. [Key Components](#key-components)
4. [Data Flow](#data-flow)
5. [Storage System](#storage-system)
6. [Query Modes](#query-modes)
7. [Extension Points](#extension-points)

---

## System Overview

**nano-graphrag** is a lightweight (~1100 lines of core code), hackable implementation of GraphRAG that provides:

- **Knowledge Graph Construction**: Extracts entities and relationships from documents
- **Multiple Query Modes**: Local (entity-focused), Global (community-focused), and Naive (vector similarity)
- **Advanced Analytics**: GASL (Graph Analysis & Scripting Language) for systematic exploration
- **QA Generation**: Create high-quality reasoning questions for training data
- **Extensible Architecture**: Pluggable LLMs, embeddings, and storage backends

### Core Philosophy

1. **Keep it simple**: Minimal core code, easy to understand and modify
2. **Stay fast**: Efficient async operations, caching, and optimized algorithms
3. **Make it portable**: Support multiple backends (OpenAI, Ollama, Neo4j, etc.)
4. **Enable customization**: Dataclass-based configuration, pluggable components

---

## Core Package Structure

```
nano_graphrag/
├── __init__.py              # Public API (GraphRAG, QueryParam)
├── graphrag.py              # Main orchestrator class
├── base.py                  # Abstract base classes for storage
├── _llm.py                  # LLM integrations (OpenAI, Azure, Bedrock)
├── _op.py                   # Core operations (chunking, extraction, query)
├── _utils.py                # Utilities (hashing, async, logging)
├── _splitter.py             # Text splitting algorithms
├── prompt.py                # Legacy prompt constants
├── prompt_system.py         # Query-aware dynamic prompt system
├── entity_type_generator.py # Dynamic entity type generation
├── _storage/                # Storage backend implementations
│   ├── kv_json.py          # JSON key-value storage (default)
│   ├── vdb_nanovectordb.py # NanoVectorDB (default)
│   ├── vdb_hnswlib.py      # HNSW vector storage
│   ├── gdb_networkx.py     # NetworkX graph storage (default)
│   └── gdb_neo4j.py        # Neo4j graph storage
└── entity_extraction/       # Entity extraction subsystem
    ├── extract.py          # Extraction implementations
    ├── module.py           # DSPy extraction modules
    └── metric.py           # Quality metrics
```

---

## Key Components

### 1. GraphRAG Class (`graphrag.py`)

**Main Entry Point** - The orchestrator that coordinates all components.

```python
@dataclass
class GraphRAG:
    # Core configuration
    working_dir: str = "./nano_graphrag_cache_{timestamp}"
    enable_local: bool = True
    enable_naive_rag: bool = False

    # Text chunking
    tokenizer_type: str = "tiktoken"  # or 'huggingface'
    tiktoken_model_name: str = "gpt-4o"
    chunk_func: Callable = chunking_by_token_size
    chunk_token_size: int = 1200
    chunk_overlap_token_size: int = 100

    # Entity extraction
    entity_extract_max_gleaning: int = 1
    entity_summary_to_max_tokens: int = 500
    entity_extraction_func: callable = extract_entities

    # Graph clustering
    graph_cluster_algorithm: str = "leiden"
    max_graph_cluster_size: int = 10
    graph_cluster_seed: int = 0xDEADBEEF

    # Node embedding
    node_embedding_algorithm: str = "node2vec"
    node2vec_params: dict = {...}

    # LLM configuration
    using_azure_openai: bool = False
    using_amazon_bedrock: bool = False
    best_model_func: callable = gpt_4o_complete
    cheap_model_func: callable = gpt_4o_mini_complete
    best_model_max_token_size: int = 32768
    best_model_max_async: int = 16
    cheap_model_max_token_size: int = 32768
    cheap_model_max_async: int = 16

    # Embedding configuration
    embedding_func: EmbeddingFunc = openai_embedding
    embedding_batch_num: int = 32
    embedding_func_max_async: int = 16
    query_better_than_threshold: float = 0.2

    # Storage configuration
    key_string_value_json_storage_cls: Type[BaseKVStorage] = JsonKVStorage
    vector_db_storage_cls: Type[BaseVectorStorage] = NanoVectorDBStorage
    vector_db_storage_cls_kwargs: dict = {}
    graph_storage_cls: Type[BaseGraphStorage] = NetworkXStorage
    enable_llm_cache: bool = True

    # Extension
    always_create_working_dir: bool = True
    addon_params: dict = {}
    convert_response_to_json_func: callable = convert_response_to_json
```

**Key Methods**:

- `insert(string_or_strings)` - Ingest documents into knowledge graph
- `query(query, param=QueryParam())` - Query the knowledge graph
- `ainsert()` / `aquery()` - Async versions

**Initialization Process**:
1. Creates working directory structure
2. Initializes storage backends (KV, Vector, Graph)
3. Loads existing data if present
4. Sets up LLM and embedding functions

### 2. Operations Module (`_op.py`)

**Core processing pipeline** - Implements all major operations.

#### Chunking

```python
async def chunking_by_token_size(
    content: str,
    chunk_size: int = 1200,
    overlap_size: int = 100,
    tiktoken_model: str = "gpt-4o"
) -> List[TextChunk]
```

- Splits documents into overlapping chunks
- Uses tiktoken for accurate token counting
- Alternative: `chunking_by_seperators()` for semantic splitting

#### Entity Extraction

```python
async def extract_entities(
    chunks: List[TextChunk],
    knowledge_graph_inst: BaseGraphStorage,
    entity_vdb: BaseVectorStorage,
    relationships_vdb: BaseVectorStorage,
    global_config: dict
) -> None
```

**Process**:
1. For each chunk, call LLM to extract entities and relationships
2. Perform "gleaning" iterations to catch missed entities
3. Merge and deduplicate entities
4. Compute embeddings for entities
5. Store in graph and vector databases

**Key Sub-functions**:
- `_handle_single_entity_extraction()` - Extract entities from one chunk
- `_handle_single_relationship_extraction()` - Extract relationships
- `_handle_entity_relation_summary()` - Summarize entity descriptions

#### Query Functions

**Local Query** (`local_query()`):
```python
async def local_query(
    query: str,
    knowledge_graph_inst: BaseGraphStorage,
    entities_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage,
    param: QueryParam,
    global_config: dict
) -> str
```

**Process**:
1. Find similar entities via vector search
2. Get entity neighborhoods from graph (1-2 hops)
3. Retrieve source text chunks
4. Build context from entities + relationships + chunks
5. Generate answer using LLM

**Global Query** (`global_query()`):
```python
async def global_query(
    query: str,
    knowledge_graph_inst: BaseGraphStorage,
    entities_vdb: BaseVectorStorage,
    community_reports: BaseKVStorage,
    param: QueryParam,
    global_config: dict
) -> str
```

**Process**:
1. Detect communities in knowledge graph
2. Generate community reports (summaries of each cluster)
3. Find relevant communities for query
4. Map-reduce pattern: analyze each community, then synthesize

**Naive Query** (`naive_query()`):
```python
async def naive_query(
    query: str,
    chunks_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage,
    param: QueryParam,
    global_config: dict
) -> str
```

**Process**:
1. Find similar text chunks via vector search
2. Retrieve top-K chunks
3. Generate answer directly from chunks (no graph)

### 3. Storage System

**Three-tier storage architecture** for different data types.

#### BaseKVStorage - Key-Value Pairs

```python
class BaseKVStorage(ABC):
    @abstractmethod
    async def get_by_id(self, id: str) -> Union[dict, None]: ...

    @abstractmethod
    async def get_by_ids(self, ids: List[str]) -> List[Union[dict, None]]: ...

    @abstractmethod
    async def upsert(self, data: dict) -> None: ...

    @abstractmethod
    async def drop(self) -> None: ...
```

**Default: JsonKVStorage** (`_storage/kv_json.py`)
- File-based JSON storage
- One file per namespace
- Async file I/O

**Stores**:
- `full_docs` - Original documents
- `text_chunks` - Chunked text with metadata
- `llm_response_cache` - Cached LLM responses
- `community_reports` - Community summaries

#### BaseVectorStorage - Embeddings

```python
class BaseVectorStorage(ABC):
    @abstractmethod
    async def upsert(self, data: dict[str, dict]) -> None: ...

    @abstractmethod
    async def query(self, query: str, top_k: int) -> List[dict]: ...

    @abstractmethod
    def get_embeddings(self, queries: List[str]) -> np.ndarray: ...
```

**Default: NanoVectorDBStorage** (`_storage/vdb_nanovectordb.py`)
- Lightweight vector database
- Exact similarity search
- In-memory with disk persistence

**Alternatives**:
- `HNSWLibStorage` - Approximate nearest neighbors (faster)
- `MilvusLiteStorage` - Production-grade (see examples)
- `FaissStorage` - Facebook's vector search (see examples)

**Stores**:
- `entities_vdb` - Entity embeddings
- `relationships_vdb` - Relationship embeddings
- `chunks_vdb` - Text chunk embeddings

#### BaseGraphStorage - Knowledge Graph

```python
class BaseGraphStorage(ABC):
    @abstractmethod
    async def has_node(self, node_id: str) -> bool: ...

    @abstractmethod
    async def has_edge(self, source: str, target: str) -> bool: ...

    @abstractmethod
    async def get_node(self, node_id: str) -> Union[dict, None]: ...

    @abstractmethod
    async def upsert_node(self, node_id: str, node_data: dict) -> None: ...

    @abstractmethod
    async def upsert_edge(self, source: str, target: str, edge_data: dict) -> None: ...

    @abstractmethod
    def get_node_edges(self, source: str) -> List[tuple]: ...
```

**Default: NetworkXStorage** (`_storage/gdb_networkx.py`)
- In-memory graph using NetworkX
- Persists to GraphML file
- Community detection (Leiden/Louvain)

**Alternative: Neo4jStorage** (`_storage/gdb_neo4j.py`)
- Production graph database
- Cypher query support
- Scalable for large graphs

**Stores**:
- `chunk_entity_relation_graph` - Complete knowledge graph

### 4. LLM Integration (`_llm.py`)

**Supported Providers**:

1. **OpenAI**: `gpt_4o_complete()`, `gpt_4o_mini_complete()`
2. **Azure OpenAI**: Same functions with `using_azure_openai=True`
3. **Amazon Bedrock**: Claude models via Bedrock API

**LLM Function Signature**:
```python
async def llm_complete(
    prompt: str,
    system_prompt: str = None,
    history_messages: List[dict] = [],
    **kwargs
) -> str:
    """
    kwargs may include:
    - hashing_kv: Cache storage
    - max_tokens: Token limit
    - temperature: Sampling temperature
    - response_format: JSON mode
    """
```

**Features**:
- Async by default
- Built-in caching via `hashing_kv`
- Rate limiting via `limit_async_func_call()`
- JSON output support

**Embedding Function Signature**:
```python
@wrap_embedding_func_with_attrs(
    embedding_dim=1536,
    max_token_size=8192
)
async def embedding_func(texts: List[str]) -> np.ndarray:
    """Returns shape: (len(texts), embedding_dim)"""
```

### 5. Prompt System (`prompt_system.py`)

**Query-Aware Dynamic Prompts** - Optimizes prompts for specific queries.

```python
class QueryAwarePromptSystem:
    def get_prompt(
        self,
        prompt_name: str,
        user_query: str = None,
        optimize: bool = False,
        **kwargs
    ) -> str:
        """
        Load prompt from prompts/ directory and optionally optimize
        for the specific user query using LLM intelligence.
        """
```

**Key Prompts**:
- `entity_extraction` - Extract entities/relations from chunks
- `entity_type_generation` - Generate entity types dynamically
- `community_report` - Summarize graph communities
- `local_rag_response` - Local search response generation
- `global_reduce_rag_response` - Global search synthesis

**Features**:
- File-based prompt storage (`prompts/` directory)
- Template composition
- Query-aware optimization
- Caching of optimized prompts

### 6. Entity Type Generator (`entity_type_generator.py`)

**Dynamic Entity Type Generation** - Determines relevant entity types based on query and content.

```python
async def generate_entity_types_for_chunks(
    task: str,
    chunks: List[TextChunk],
    llm_func: callable,
    per_chunk: bool = True,
    min_frequency: int = 2,
    top_n_fallback: int = 12
) -> List[str]:
    """
    Generate entity types dynamically based on task and content.
    Returns types that appear in min_frequency chunks,
    or top_n_fallback most frequent types.
    """
```

**Process**:
1. For each chunk, ask LLM to suggest entity types for the task
2. Aggregate types across all chunks
3. Filter by frequency (default: must appear in 2+ chunks)
4. Fallback to top-N if none meet threshold

**Benefits**:
- Query-specific entity extraction
- Content-adaptive types
- No fixed ontology required

---

## Data Flow

### Document Ingestion Flow

```
Documents (str or List[str])
    ↓
[1. Chunking] (_op.chunking_by_token_size)
    ↓
Text Chunks (with metadata)
    ↓ (stored in text_chunks KV)
    ↓
[2. Entity Extraction] (_op.extract_entities)
    ↓
Entities + Relationships (JSON)
    ↓ (stored in graph + entities_vdb)
    ↓
[3. Graph Construction] (NetworkXStorage)
    ↓
Knowledge Graph (GraphML file)
    ↓
[4. Community Detection] (NetworkXStorage)
    ↓
Communities (graph clusters)
    ↓
[5. Community Reports] (_op.generate_community_reports)
    ↓
Community Summaries (stored in community_reports KV)
```

### Query Flow

#### Local Query Flow

```
User Query
    ↓
[1. Entity Search] (entities_vdb.query)
    ↓
Top-K Similar Entities
    ↓
[2. Graph Traversal] (get_node_edges)
    ↓
Entity Neighborhoods (1-2 hops)
    ↓
[3. Chunk Retrieval] (text_chunks_db.get_by_ids)
    ↓
Source Text Chunks
    ↓
[4. Context Assembly]
    ↓
Entities + Relationships + Chunks
    ↓
[5. LLM Generation] (best_model_func)
    ↓
Final Answer
```

#### Global Query Flow

```
User Query
    ↓
[1. Community Detection] (detect_communities)
    ↓
Graph Communities
    ↓
[2. Community Reports] (community_reports.get_by_ids)
    ↓
Community Summaries
    ↓
[3. Relevance Ranking] (vector similarity)
    ↓
Top-K Communities
    ↓
[4. Map Phase] (analyze each community)
    ↓
Individual Analyses
    ↓
[5. Reduce Phase] (synthesize)
    ↓
Final Answer
```

#### Naive Query Flow

```
User Query
    ↓
[1. Chunk Search] (chunks_vdb.query)
    ↓
Top-K Similar Chunks
    ↓
[2. Chunk Retrieval] (text_chunks_db.get_by_ids)
    ↓
Text Chunks
    ↓
[3. LLM Generation] (best_model_func)
    ↓
Final Answer
```

---

## Storage System Details

### Working Directory Structure

```
working_dir/
├── kv_store_full_docs.json           # Original documents
├── kv_store_text_chunks.json         # Chunked text
├── kv_store_llm_response_cache.json  # LLM cache
├── kv_store_community_reports.json   # Community summaries
├── vdb_entities.json                 # Entity vectors
├── vdb_relationships.json            # Relationship vectors
├── vdb_chunks.json                   # Chunk vectors
└── graph_chunk_entity_relation.graphml  # Knowledge graph
```

### Storage Lifecycle

**Initialization**:
```python
rag = GraphRAG(working_dir="./cache")
# Creates directory if missing
# Loads existing data if present
```

**Data Persistence**:
- KV storage: JSON files (auto-saved on upsert)
- Vector storage: Index files (auto-saved periodically)
- Graph storage: GraphML file (saved after modifications)

**Incremental Updates**:
- MD5 hash of content used as chunk ID
- Duplicate content automatically skipped
- Communities recomputed on each insert

---

## Query Modes

### Comparison

| Feature | Local | Global | Naive |
|---------|-------|--------|-------|
| **Speed** | Fast | Slow | Fastest |
| **Accuracy** | High | Highest | Medium |
| **Graph Used** | Yes (traversal) | Yes (communities) | No |
| **Best For** | Specific entities | Broad themes | Simple lookup |
| **Context Size** | Medium | Large | Small |

### When to Use Each Mode

**Local Mode** (`mode="local"`):
- Questions about specific entities or relationships
- "What is the relationship between X and Y?"
- "What are the properties of entity Z?"
- Requires focused, precise answers

**Global Mode** (`mode="global"`):
- Questions about overall themes or patterns
- "What are the main topics in this corpus?"
- "Summarize the key findings"
- Requires broad, comprehensive answers

**Naive Mode** (`mode="naive"`):
- Simple factual lookups
- When graph structure not needed
- Quick baseline comparisons
- Debugging/testing

### QueryParam Configuration

```python
@dataclass
class QueryParam:
    mode: Literal["local", "global", "naive"] = "global"  # Default: global
    only_need_context: bool = False  # Return context only
    response_type: str = "Multiple Paragraphs"
    level: int = 2
    top_k: int = 20  # Entities/chunks to retrieve

    # Naive mode params
    naive_max_token_for_text_unit: int = 12000

    # Local mode params
    local_max_token_for_text_unit: int = 4000
    local_max_token_for_local_context: int = 4800
    local_max_token_for_community_report: int = 3200
    local_community_single_one: bool = False

    # Global mode params
    global_min_community_rating: float = 0
    global_max_consider_community: float = 512
    global_max_token_for_community_report: int = 16384
    global_special_community_map_llm_kwargs: dict = field(
        default_factory=lambda: {"response_format": {"type": "json_object"}}
    )
```

---

## Extension Points

### 1. Custom LLM Provider

Implement async function matching signature:

```python
async def my_llm_complete(
    prompt: str,
    system_prompt: str = None,
    history_messages: List[dict] = [],
    **kwargs
) -> str:
    hashing_kv = kwargs.pop("hashing_kv", None)
    # Your LLM implementation
    response = await your_llm_api(prompt, **kwargs)
    return response

# Use it
rag = GraphRAG(
    best_model_func=my_llm_complete,
    best_model_max_token_size=8192,
    best_model_max_async=16
)
```

See: [examples/using_ollama_as_llm.py](../examples/using_ollama_as_llm.py)

### 2. Custom Embedding Function

```python
from nano_graphrag._utils import wrap_embedding_func_with_attrs

@wrap_embedding_func_with_attrs(
    embedding_dim=384,
    max_token_size=512
)
async def my_embedding(texts: List[str]) -> np.ndarray:
    # Your embedding implementation
    embeddings = your_model.encode(texts)
    return np.array(embeddings)

# Use it
rag = GraphRAG(
    embedding_func=my_embedding,
    embedding_batch_num=32,
    embedding_func_max_async=16
)
```

See: [examples/using_local_embedding_model.py](../examples/using_local_embedding_model.py)

### 3. Custom Storage Backend

Implement abstract base class:

```python
from nano_graphrag.base import BaseVectorStorage

class MyVectorStorage(BaseVectorStorage):
    async def upsert(self, data: dict[str, dict]) -> None:
        # Your implementation
        pass

    async def query(self, query: str, top_k: int) -> List[dict]:
        # Your implementation
        pass

    def get_embeddings(self, queries: List[str]) -> np.ndarray:
        # Your implementation
        pass

# Use it
rag = GraphRAG(vector_db_storage_cls=MyVectorStorage)
```

See: [examples/using_milvus_as_vectorDB.py](../examples/using_milvus_as_vectorDB.py)

### 4. Custom Chunking Method

```python
async def my_chunking(
    content: str,
    **kwargs
) -> List[dict]:
    # Your chunking logic
    chunks = custom_split(content)
    return [
        {"content": chunk, "metadata": {...}}
        for chunk in chunks
    ]

# Use it
rag = GraphRAG(chunk_func=my_chunking)
```

See: [examples/using_custom_chunking_method.py](../examples/using_custom_chunking_method.py)

---

## Performance Optimization

### Caching Strategies

1. **LLM Response Cache**: Stores LLM responses by prompt hash
2. **Embedding Cache**: Reuses embeddings for identical text
3. **Community Report Cache**: Avoids regenerating unchanged communities

### Async Concurrency

- `best_model_max_async` - Max concurrent calls to best LLM
- `cheap_model_max_async` - Max concurrent calls to cheap LLM
- `embedding_func_max_async` - Max concurrent embedding calls

### Batch Processing

- `embedding_batch_num` - Batch size for embeddings
- Entity extraction processes chunks in parallel
- Community detection batches similar operations

---

## Best Practices

### 1. Working Directory Management

- Use separate working directories for different projects
- Back up working directories before major changes
- Clean up old caches periodically

### 2. LLM Cost Optimization

- Use `cheap_model_func` for summarization tasks
- Enable caching with `hashing_kv`
- Adjust `entity_extract_max_gleaning` (default: 1)

### 3. Query Optimization

- Start with local mode for specific questions
- Use global mode only for broad themes
- Adjust `top_k` based on query complexity

### 4. Storage Selection

- Use NetworkX for development/small graphs
- Use Neo4j for production/large graphs
- Use HNSW for large-scale vector search

---

## Troubleshooting

### Common Issues

**1. Import Errors**
- Ensure conda environment activated: `conda activate py310`
- Check dependencies: `pip install -e .`

**2. Out of Memory**
- Reduce `best_model_max_async` and `cheap_model_max_async`
- Use HNSW instead of NanoVectorDB
- Process documents in smaller batches

**3. Slow Queries**
- Reduce `top_k` parameter
- Use local mode instead of global
- Enable caching
- Consider Neo4j for large graphs

**4. Poor Results**
- Increase `entity_extract_max_gleaning`
- Adjust `chunk_token_size` and `chunk_overlap_token_size`
- Try different query modes
- Use query-aware prompt optimization

---

## Next Steps

- [GASL Guide](./GASL_GUIDE.md) - Learn the Graph Analysis & Scripting Language
- [QA Generation](./QA_GENERATION.md) - Generate training data
- [Storage Backends](./STORAGE_BACKENDS.md) - Detailed storage configuration
- [API Reference](./API_REFERENCE.md) - Complete API documentation
