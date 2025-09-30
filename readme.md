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









😭 [GraphRAG](https://arxiv.org/pdf/2404.16130) is good and powerful, but the official [implementation](https://github.com/microsoft/graphrag/tree/main) is difficult/painful to **read or hack**.

😊 This project provides a **smaller, faster, cleaner GraphRAG**, while remaining the core functionality(see [benchmark](#benchmark) and [issues](#Issues) ).

🎁 Excluding `tests` and prompts,  `nano-graphrag` is about **1100 lines of code**.

👌 Small yet [**portable**](#Components)(faiss, neo4j, ollama...), [**asynchronous**](#Async) and fully typed.



> If you're looking for a multi-user RAG solution for long-term user memory, have a look at this project: [memobase](https://github.com/memodb-io/memobase) :)

## Install

**Install from source** (recommend)

```shell
# clone this repo first
cd nano-graphrag
pip install -e .
```

**Install from PyPi**

```shell
pip install nano-graphrag
```



## Quick Start

> [!TIP]
>
> **Please set OpenAI API key in environment: `export OPENAI_API_KEY="sk-..."`.** 

> [!TIP]
> If you're using Azure OpenAI API, refer to the [.env.example](./.env.example.azure) to set your azure openai. Then pass `GraphRAG(...,using_azure_openai=True,...)` to enable.

> [!TIP]
> If you're using Amazon Bedrock API, please ensure your credentials are properly set through commands like `aws configure`. Then enable it by configuring like this: `GraphRAG(...,using_amazon_bedrock=True, best_model_id="us.anthropic.claude-3-sonnet-20240229-v1:0", cheap_model_id="us.anthropic.claude-3-haiku-20240307-v1:0",...)`. Refer to an [example script](./examples/using_amazon_bedrock.py).

> [!TIP]
>
> If you don't have any key, check out this [example](./examples/no_openai_key_at_all.py) that using `transformers` and `ollama` . If you like to use another LLM or Embedding Model, check [Advances](#Advances).

download a copy of A Christmas Carol by Charles Dickens:

```shell
curl https://raw.githubusercontent.com/gusye1234/nano-graphrag/main/tests/mock_data.txt > ./book.txt
```

Use the below python snippet:

```python
from nano_graphrag import GraphRAG, QueryParam

graph_func = GraphRAG(working_dir="./dickens")

with open("./book.txt") as f:
    graph_func.insert(f.read())

# Perform global graphrag search
print(graph_func.query("What are the top themes in this story?"))

# Perform local graphrag search (I think is better and more scalable one)
print(graph_func.query("What are the top themes in this story?", param=QueryParam(mode="local")))
```

Next time you initialize a `GraphRAG` from the same `working_dir`, it will reload all the contexts automatically.

#### Batch Insert

```python
graph_func.insert(["TEXT1", "TEXT2",...])
```

<details>
<summary> Incremental Insert</summary>

`nano-graphrag` supports incremental insert, no duplicated computation or data will be added:

```python
with open("./book.txt") as f:
    book = f.read()
    half_len = len(book) // 2
    graph_func.insert(book[:half_len])
    graph_func.insert(book[half_len:])
```

> `nano-graphrag` use md5-hash of the content as the key, so there is no duplicated chunk.
>
> However, each time you insert, the communities of graph will be re-computed and the community reports will be re-generated

</details>

<details>
<summary> Naive RAG</summary>

`nano-graphrag` supports naive RAG insert and query as well:

```python
graph_func = GraphRAG(working_dir="./dickens", enable_naive_rag=True)
...
# Query
print(rag.query(
      "What are the top themes in this story?",
      param=QueryParam(mode="naive")
)
```
</details>


### Async

For each method `NAME(...)` , there is a corresponding async method `aNAME(...)`

```python
await graph_func.ainsert(...)
await graph_func.aquery(...)
...
```

### Available Parameters

`GraphRAG` and `QueryParam` are `dataclass` in Python. Use `help(GraphRAG)` and `help(QueryParam)` to see all available parameters!  Or check out the [Advances](#Advances) section to see some options.



## Components

Below are the components you can use:

| Type            |                             What                             |                       Where                       |
| :-------------- | :----------------------------------------------------------: | :-----------------------------------------------: |
| LLM             |                            OpenAI                            |                     Built-in                      |
|                 |                        Amazon Bedrock                        |                     Built-in                      |
|                 |                           DeepSeek                           |              [examples](./examples)               |
|                 |                           `ollama`                           |              [examples](./examples)               |
| Embedding       |                            OpenAI                            |                     Built-in                      |
|                 |                        Amazon Bedrock                        |                     Built-in                      |
|                 |                    Sentence-transformers                     |              [examples](./examples)               |
| Vector DataBase | [`nano-vectordb`](https://github.com/gusye1234/nano-vectordb) |                     Built-in                      |
|                 |        [`hnswlib`](https://github.com/nmslib/hnswlib)        |         Built-in, [examples](./examples)          |
|                 |  [`milvus-lite`](https://github.com/milvus-io/milvus-lite)   |              [examples](./examples)               |
|                 | [faiss](https://github.com/facebookresearch/faiss?tab=readme-ov-file) |              [examples](./examples)               |
| Graph Storage   | [`networkx`](https://networkx.org/documentation/stable/index.html) |                     Built-in                      |
|                 |                [`neo4j`](https://neo4j.com/)                 | Built-in([doc](./docs/use_neo4j_for_graphrag.md)) |
| Visualization   |                           graphml                            |              [examples](./examples)               |
| Chunking        |                        by token size                         |                     Built-in                      |
|                 |                       by text splitter                       |                     Built-in                      |

- `Built-in` means we have that implementation inside `nano-graphrag`. `examples` means we have that implementation inside an tutorial under [examples](./examples) folder.

- Check [examples/benchmarks](./examples/benchmarks) to see few comparisons between components.
- **Always welcome to contribute more components.**

### Additional Features

- **QA Generation**: Built-in scripts for generating complex reasoning question-answer pairs from knowledge graphs (see [Question-Answer Generation](#question-answer-generation) section)
- **Dynamic Entity Type Generation**: Automatically generates relevant entity types based on user queries and document content
- **Query-Aware Processing**: All prompts and processing are optimized based on the specific user query
- **Analytical Retriever**: Advanced query decomposition and systematic graph analysis (see [Analytical Retriever](./ANALYTICAL_RETRIEVER_README.md))

## Advances



<details>
<summary>Some setup options</summary>

- `GraphRAG(...,always_create_working_dir=False,...)` will skip the dir-creating step. Use it if you switch all your components to non-file storages.

</details>



<details>
<summary>Only query the related context</summary>

`graph_func.query` return the final answer without streaming. 

If you like to interagte `nano-graphrag` in your project, you can use `param=QueryParam(..., only_need_context=True,...)`, which will only return the retrieved context from graph, something like:

````
# Local mode
-----Reports-----
```csv
id,	content
0,	# FOX News and Key Figures in Media and Politics...
1, ...
```
...

# Global mode
----Analyst 3----
Importance Score: 100
Donald J. Trump: Frequently discussed in relation to his political activities...
...
````

You can integrate that context into your customized prompt.

</details>

<details>
<summary>Prompt System</summary>

`nano-graphrag` uses a query-aware prompt system that dynamically optimizes prompts based on user queries. The system loads prompts from the `prompts/` directory and can optimize them using LLM intelligence.

**Key Features:**
- **Query-Aware Optimization**: Prompts are automatically optimized for specific user queries
- **File-Based Prompts**: Prompts are stored as individual files in the `prompts/` directory
- **Backward Compatibility**: The old `PROMPTS` dictionary interface is still supported
- **Caching**: Optimized prompts are cached for performance

**Important Prompts:**

- `entity_extraction` - Extract entities and relations from text chunks
- `entity_type_generation` - Generate entity types dynamically based on user queries
- `community_report` - Organize and summarize graph cluster descriptions
- `local_rag_response` - System prompt for local search generation
- `global_reduce_rag_response` - System prompt for global search generation
- `plan_generation` - Generate execution plans for complex queries
- `process_batch` - Process batches of data with LLM
- `classify_batch` - Classify batches of data with LLM

**Usage:**
```python
from nano_graphrag.prompt_system import QueryAwarePromptSystem, set_prompt_system

# Create a query-aware prompt system
prompt_system = QueryAwarePromptSystem(llm_func=your_llm_func)
set_prompt_system(prompt_system)

# Get optimized prompts
prompt = prompt_system.get_prompt("entity_extraction", user_query="your query", optimize=True)
```

</details>

<details>
<summary>Customize Chunking</summary>


`nano-graphrag` allow you to customize your own chunking method, check out the [example](./examples/using_custom_chunking_method.py).

Switch to the built-in text splitter chunking method:

```python
from nano_graphrag._op import chunking_by_seperators

GraphRAG(...,chunk_func=chunking_by_seperators,...)
```

</details>

<details>
<summary>Dynamic Entity Type Generation</summary>

`nano-graphrag` includes a dynamic entity type generation system that automatically determines relevant entity types based on your specific query and document content, rather than using a fixed set of entity types.

**Key Features:**
- **Query-Aware**: Entity types are generated based on the user's specific query
- **Content-Adaptive**: Types are tailored to the actual content being processed
- **Frequency-Based Filtering**: Only entity types that appear frequently across chunks are selected
- **Fallback Support**: Falls back to top-N most frequent types if no types meet the frequency threshold

**How It Works:**
1. The system analyzes your query to understand what types of entities are relevant
2. For each text chunk, it generates potential entity types using LLM
3. It aggregates entity types across all chunks and filters by frequency
4. Only entity types that appear in 2+ chunks (or top 12 if none meet threshold) are used

**Usage:**
```python
from nano_graphrag.entity_type_generator import generate_entity_types_for_chunks

# Generate entity types for your specific task
entity_types = await generate_entity_types_for_chunks(
    task="Find all authors and their collaborations",
    chunks=your_chunks,
    llm_func=your_llm_func,
    per_chunk=True
)
```

This ensures that entity extraction is always relevant to your specific use case and document content.

</details>

<details>
<summary>LLM Function</summary>

In `nano-graphrag`, we requires two types of LLM, a great one and a cheap one. The former is used to plan and respond, the latter is used to summary. By default, the great one is `gpt-4o` and the cheap one is `gpt-4o-mini`

You can implement your own LLM function (refer to `_llm.gpt_4o_complete`):

```python
async def my_llm_complete(
    prompt, system_prompt=None, history_messages=[], **kwargs
) -> str:
  # pop cache KV database if any
  hashing_kv: BaseKVStorage = kwargs.pop("hashing_kv", None)
  # the rest kwargs are for calling LLM, for example, `max_tokens=xxx`
	...
  # YOUR LLM calling
  response = await call_your_LLM(messages, **kwargs)
  return response
```

Replace the default one with:

```python
# Adjust the max token size or the max async requests if needed
GraphRAG(best_model_func=my_llm_complete, best_model_max_token_size=..., best_model_max_async=...)
GraphRAG(cheap_model_func=my_llm_complete, cheap_model_max_token_size=..., cheap_model_max_async=...)
```

You can refer to this [example](./examples/using_deepseek_as_llm.py) that use [`deepseek-chat`](https://platform.deepseek.com/api-docs/) as the LLM model

You can refer to this [example](./examples/using_ollama_as_llm.py) that use [`ollama`](https://github.com/ollama/ollama) as the LLM model

#### Json Output

`nano-graphrag` will use `best_model_func` to output JSON with params `"response_format": {"type": "json_object"}`. However there are some open-source model maybe produce unstable JSON. 

`nano-graphrag` introduces a post-process interface for you to convert the response to JSON. This func's signature is below:

```python
def YOUR_STRING_TO_JSON_FUNC(response: str) -> dict:
  "Convert the string response to JSON"
  ...
```

And pass your own func by `GraphRAG(...convert_response_to_json_func=YOUR_STRING_TO_JSON_FUNC,...)`.

For example, you can refer to [json_repair](https://github.com/mangiucugna/json_repair) to repair the JSON string returned by LLM. 
</details>



<details>
<summary>Embedding Function</summary>

You can replace the default embedding functions with any `_utils.EmbedddingFunc` instance.

For example, the default one is using OpenAI embedding API:

```python
@wrap_embedding_func_with_attrs(embedding_dim=1536, max_token_size=8192)
async def openai_embedding(texts: list[str]) -> np.ndarray:
    openai_async_client = AsyncOpenAI()
    response = await openai_async_client.embeddings.create(
        model="text-embedding-3-small", input=texts, encoding_format="float"
    )
    return np.array([dp.embedding for dp in response.data])
```

Replace default embedding function with:

```python
GraphRAG(embedding_func=your_embed_func, embedding_batch_num=..., embedding_func_max_async=...)
```

You can refer to an [example](./examples/using_local_embedding_model.py) that use `sentence-transformer` to locally compute embeddings.
</details>


<details>
<summary>Storage Component</summary>

You can replace all storage-related components to your own implementation, `nano-graphrag` mainly uses three kinds of storage:

**`base.BaseKVStorage` for storing key-json pairs of data** 

- By default we use disk file storage as the backend. 
- `GraphRAG(.., key_string_value_json_storage_cls=YOURS,...)`

**`base.BaseVectorStorage` for indexing embeddings**

- By default we use [`nano-vectordb`](https://github.com/gusye1234/nano-vectordb) as the backend.
- We have a built-in [`hnswlib`](https://github.com/nmslib/hnswlib) storage also, check out this [example](./examples/using_hnsw_as_vectorDB.py).
- Check out this [example](./examples/using_milvus_as_vectorDB.py) that implements [`milvus-lite`](https://github.com/milvus-io/milvus-lite) as the backend (not available in Windows).
- `GraphRAG(.., vector_db_storage_cls=YOURS,...)`

**`base.BaseGraphStorage` for storing knowledge graph**

- By default we use [`networkx`](https://github.com/networkx/networkx) as the backend.
- We have a built-in `Neo4jStorage` for graph, check out this [tutorial](./docs/use_neo4j_for_graphrag.md).
- `GraphRAG(.., graph_storage_cls=YOURS,...)`

You can refer to `nano_graphrag.base` to see detailed interfaces for each components.
</details>



## FQA

Check [FQA](./docs/FAQ.md).



## Roadmap

See [ROADMAP.md](./docs/ROADMAP.md)



## Contribute

`nano-graphrag` is open to any kind of contribution. Read [this](./docs/CONTRIBUTING.md) before you contribute.




## Benchmark

- [benchmark for English](./docs/benchmark-en.md)
- [benchmark for Chinese](./docs/benchmark-zh.md)
- [An evaluation](./examples/benchmarks/eval_naive_graphrag_on_multi_hop.ipynb) notebook on a [multi-hop RAG task](https://github.com/yixuantt/MultiHop-RAG)



## Projects that used `nano-graphrag`

- [Medical Graph RAG](https://github.com/MedicineToken/Medical-Graph-RAG): Graph RAG for the Medical Data
- [LightRAG](https://github.com/HKUDS/LightRAG): Simple and Fast Retrieval-Augmented Generation
- [fast-graphrag](https://github.com/circlemind-ai/fast-graphrag): RAG that intelligently adapts to your use case, data, and queries
- [HiRAG](https://github.com/hhy-huang/HiRAG): Retrieval-Augmented Generation with Hierarchical Knowledge

> Welcome to pull requests if your project uses `nano-graphrag`, it will help others to trust this repo❤️



## Question-Answer Generation

`nano-graphrag` includes powerful scripts for generating complex reasoning question-answer pairs from knowledge graphs, perfect for creating training data that requires `<think>` tokens.

### QA Generation Scripts

#### **Multi-Hop Reasoning Questions** (`generate_multihop_qa.py`)
Generates questions that require chaining facts across multiple hops in the knowledge graph:

```bash
python generate_multihop_qa.py --working-dir /path/to/your/graph --num-questions 10 --path-length 2
```

**Features:**
- Finds random paths of specified length in the graph
- Generates questions requiring multi-step reasoning
- Creates detailed answers with step-by-step explanations
- Perfect for training models on complex reasoning tasks

#### **Synthesis Questions** (`generate_synthesis_qa.py`)
Generates "why" and "how" questions that require synthesizing information from entity contexts:

```bash
python generate_synthesis_qa.py --working-dir /path/to/your/graph --num-questions 10
```

**Features:**
- Identifies central nodes with high connectivity
- Aggregates rich context from entities and their relationships
- Generates synthesis questions requiring deep understanding
- Creates comprehensive answers showing information synthesis

### Example Output

**Multi-Hop Question:**
- **Q:** "How might the use of prescription opioids among older adults be indirectly connected to the risk of heroin overdose in this population?"
- **A:** Detailed step-by-step reasoning connecting prescription opioids → dependence → heroin use → overdose risk

**Synthesis Question:**
- **Q:** "How does the CDC integrate data from diverse surveillance systems to identify emerging public health threats?"
- **A:** Comprehensive analysis synthesizing surveillance systems, reporting mechanisms, collaborations, and response strategies

### Use Cases

- **Training Data Generation**: Create high-quality QA pairs for fine-tuning language models
- **Reasoning Evaluation**: Test model capabilities on complex multi-hop and synthesis tasks
- **Educational Content**: Generate challenging questions for learning and assessment
- **Research Applications**: Create datasets for reasoning research and evaluation

## GASL (Graph Analysis and Scripting Language)

`nano-graphrag` includes GASL, a domain-specific language for querying and manipulating knowledge graphs. GASL provides a comprehensive set of commands for graph analysis, data transformation, and field creation.

### Core Commands

#### **Discovery & Data Retrieval**
- `DECLARE` - Create variables (DICT, LIST, COUNTER) with descriptions
- `FIND` - Discover nodes/edges/paths with filtering criteria
- `SET` - Set variable values
- `SELECT` - Select specific fields from data

#### **Data Processing**
- `PROCESS` - Transform individual items using LLM intelligence
- `CLASSIFY` - Categorize items using LLM
- `TRANSFORM` - Transform data using LLM intelligence
- `UPDATE` - Update state variables with data transformations

#### **Graph Navigation**
- `GRAPHWALK` - Walk through graph following relationships
- `GRAPHCONNECT` - Find connections between node sets
- `SUBGRAPH` - Extract subgraph around specific nodes
- `GRAPHPATTERN` - Find specific patterns in the graph

#### **Data Analysis**
- `COUNT` - Count frequencies and unique values with grouping
- `AGGREGATE` - Mathematical aggregations (sum, avg, min, max, count)
- `ANALYZE` - Perform analysis on data
- `CLUSTER` - Cluster similar items using LLM
- `DETECT` - Detect patterns in data

#### **Data Combination**
- `JOIN` - Combine variables on matching fields
- `MERGE` - Combine multiple variables
- `COMPARE` - Compare variables on specific fields
- `PIVOT` - Create pivot tables from data

#### **Field Operations**
- `CALCULATE` - Add calculated fields to data
- `SCORE` - Score items using LLM evaluation
- `RANK` - Rank items by a field
- `WEIGHT` - Assign weights to items using LLM

#### **Object Creation**
- `CREATE` - Create new graph objects (nodes, edges, summaries)
- `GENERATE` - Generate new content using LLM
- `RESHAPE` - Change data structure format

#### **Control Flow**
- `REQUIRE` - Require conditions to be met
- `ASSERT` - Assert conditions (stops execution if false)
- `ON` - Conditional execution based on status
- `TRY/CATCH/FINALLY` - Error handling
- `CANCEL` - Cancel execution

### Field Management

GASL automatically manages field metadata with descriptions:
- Fields are auto-generated when conflicts occur (`field_name_1`, `field_name_2`)
- Each field includes a description of its purpose and source
- The LLM can always see available fields and their descriptions

### Example Workflows

#### **Author Frequency Analysis**
```
FIND nodes with entity_type=PERSON AS person_nodes
PROCESS person_nodes with instruction: "Extract author names from description" AS author_names
ADD_FIELD person_nodes field: author_name = author_names
COUNT person_nodes field author_name unique AS author_frequency
```

#### **Multi-Dataset Analysis**
```
FIND nodes with entity_type=PERSON AS person_nodes
FIND nodes with entity_type=EVENT AS event_nodes
PROCESS person_nodes with instruction: "Extract author names" AS person_authors
PROCESS event_nodes with instruction: "Extract author names" AS event_authors
ADD_FIELD person_nodes field: author_name = person_authors
ADD_FIELD event_nodes field: author_name = event_authors
JOIN person_nodes with event_nodes on author_name AS combined_authors
```

### Usage

#### Run GASL Analysis

```bash
# Run a GASL query on your papers directory
python gasl_main.py --working-dir /path/to/your/papers --query "create a histogram of how often author names appear" --max-iterations 3

# Test individual commands
python test_commands.py "FIND nodes with entity_type=PERSON" --working-dir /path/to/your/papers
```

#### Working Directory Structure

Your papers directory will contain:
- Your original paper files (PDFs, text files, etc.)
- `graph_chunk_entity_relation.graphml` - Generated knowledge graph (auto-created by nano-graphrag)
- `gasl_state.json` - GASL state file (auto-created)
- `test_state.json` - Test command state file (auto-created)
- Other nano-graphrag cache files (auto-created)

All files are stored in your papers directory to keep everything organized and avoid conflicts between different projects.

## Issues

- `nano-graphrag` didn't implement the `covariates` feature of `GraphRAG`
- `nano-graphrag` implements the global search different from the original. The original use a map-reduce-like style to fill all the communities into context, while `nano-graphrag` only use the top-K important and central communites (use `QueryParam.global_max_consider_community` to control, default to 512 communities).

