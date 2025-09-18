# Analytical Retriever for nano-graphrag

A flexible, systematic approach to querying knowledge graphs that adapts the cognee analytical retriever pattern for nano-graphrag. This system provides much more comprehensive and accurate results than the standard query modes.

## Key Features

- **Query Decomposition**: Uses LLM to break complex queries into systematic steps
- **Direct Graph Querying**: Bypasses query modes to directly access graph data
- **Multi-Backend Support**: Works with both NetworkX and Neo4j backends
- **Systematic Processing**: Processes results based on query intent
- **Flexible Output**: Generates structured answers with Mermaid diagrams

## Why This Approach is Better

### **Standard Query Modes (Limited)**
- **LOCAL**: Finds direct relationships mentioned in text
- **GLOBAL**: Uses community detection algorithms
- **NAIVE**: Simple text search

### **Analytical Retriever (Comprehensive)**
- **Direct Data Access**: Queries the actual graph database
- **Systematic Decomposition**: Breaks complex queries into manageable steps
- **Complete Coverage**: Gets ALL relevant data, not just what query modes find
- **Flexible Processing**: Handles any type of analytical query

## Files Created

1. **`analytical_retriever.py`** - Main analytical retriever implementation
2. **`test_analytical_retriever.py`** - Test script for the analytical retriever
3. **`run_analytical_retriever.py`** - Integration script with Argo Bridge API
4. **`ANALYTICAL_RETRIEVER_README.md`** - This documentation

## Usage

### Basic Usage

```python
from analytical_retriever import AnalyticalRetriever
from nano_graphrag import GraphRAG

# Initialize GraphRAG
rag = GraphRAG(working_dir="your_working_dir")

# Create analytical retriever
analytical_retriever = AnalyticalRetriever(
    graph_storage=rag.knowledge_graph_inst,
    llm_func=rag.best_model_func
)

# Query the knowledge graph
context = await analytical_retriever.get_context("Find all authors and their co-authorship relationships")
completion = await analytical_retriever.get_completion("Find all authors and their co-authorship relationships", context)
```

### With Argo Bridge API

```bash
# Set environment variables
export LLM_API_KEY="api+key"
export EMBEDDING_API_KEY="api+key"
export LLM_MODEL="gpt41"
export LLM_ENDPOINT="https://argo-bridge.cels.anl.gov/v1"
export EMBEDDING_ENDPOINT="https://argo-bridge.cels.anl.gov/v1"

# Run the analytical retriever
python run_analytical_retriever.py --working-dir "/path/to/your/knowledge/graph" --query "Make me a graph representation of authors connected by co-authorship" --verbose
```

### Test the System

```bash
python test_analytical_retriever.py /path/to/your/knowledge/graph "Find all authors and their co-authorship relationships"
```

## How It Works

### 1. Query Decomposition
The LLM analyzes your query and breaks it down into systematic steps:

```json
[
  {
    "step_number": 1,
    "description": "Find all entities with type 'Entity'",
    "query_type": "neo4j",
    "query": "MATCH (n:`namespace`) WHERE n.entity_type = 'Entity' RETURN n",
    "expected_output_type": "entity_list",
    "depends_on": []
  },
  {
    "step_number": 2,
    "description": "Filter for author entities",
    "query_type": "neo4j", 
    "query": "MATCH (n:`namespace`) WHERE n.entity_type = 'Entity' AND n.description CONTAINS 'Researcher' RETURN n",
    "expected_output_type": "coauthorship_network",
    "depends_on": [1]
  }
]
```

### 2. Step Execution
Each step is executed systematically:
- **Neo4j**: Executes Cypher queries directly
- **NetworkX**: Performs Python operations on the graph
- **Hybrid**: Tries both approaches

### 3. Result Processing
Results are processed based on the expected output type:
- **entity_list**: Extracts and counts entities
- **coauthorship_network**: Identifies authors and their relationships
- **relationship_analysis**: Analyzes relationship patterns
- **aggregation**: Computes statistics and counts

### 4. Final Answer Generation
The LLM generates a comprehensive answer using all retrieved data.

## Example: Co-Authorship Analysis

### Query
"Make me a graph representation of authors connected by co-authorship"

### Steps Generated
1. **Find all entities** with type 'Entity'
2. **Filter for authors** using description keywords
3. **Find relationships** between author entities
4. **Build co-authorship network** from the data
5. **Generate Mermaid diagram** for visualization

### Output
- Complete list of all authors found
- All co-authorship relationships
- Mermaid diagram for visualization
- Comprehensive analysis of the network

## Advantages Over Query Modes

| Aspect | Query Modes | Analytical Retriever |
|--------|-------------|---------------------|
| **Data Coverage** | Limited to what modes find | Complete data extraction |
| **Accuracy** | Depends on mode interpretation | Direct database access |
| **Flexibility** | Fixed query types | Any analytical query |
| **Systematic** | Single-step process | Multi-step decomposition |
| **Comprehensive** | Partial results | Complete results |

## Customization

### Adding New Query Types
Extend the `_process_step_result` method to handle new output types:

```python
def _process_step_result(self, step: QueryStep, raw_result: List[Dict], 
                         step_outputs: Dict[int, Any]) -> Any:
    if step.expected_output_type == "your_new_type":
        return self._process_your_new_type(raw_result)
    # ... existing code
```

### Adding New Backends
Extend the `_execute_steps` method to support new graph databases:

```python
async def _execute_steps(self, steps: List[QueryStep]) -> Dict[str, Any]:
    # Add new backend support
    if step.query_type == "your_backend":
        raw_result = await self._execute_your_backend_query(step.query)
    # ... existing code
```

## Troubleshooting

### Common Issues

1. **"No authors found"**: Check if the knowledge graph contains author entities
2. **"Query decomposition failed"**: The LLM might need a more specific prompt
3. **"Step execution failed"**: Check the query syntax for your backend

### Debug Mode
Use the `--verbose` flag to see detailed step-by-step execution:

```bash
python run_analytical_retriever.py --working-dir "/path/to/graph" --query "your query" --verbose
```

## Integration with Existing Code

The analytical retriever can be easily integrated into your existing nano-graphrag workflow:

```python
# Replace this:
result = rag.query("your query", param=QueryParam(mode="local"))

# With this:
analytical_retriever = AnalyticalRetriever(graph_storage=rag.knowledge_graph_inst, llm_func=rag.best_model_func)
context = await analytical_retriever.get_context("your query")
result = await analytical_retriever.get_completion("your query", context)
```

This provides much more comprehensive and accurate results for complex analytical queries.
