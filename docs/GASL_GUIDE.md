# GASL (Graph Analysis & Scripting Language) - Comprehensive Guide

GASL is a domain-specific language for LLM-driven graph analysis with hypothesis-driven traversal. It enables systematic exploration and analysis of knowledge graphs through natural language queries.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Core Concepts](#core-concepts)
4. [Command Reference](#command-reference)
5. [Execution Model](#execution-model)
6. [State Management](#state-management)
7. [Usage Examples](#usage-examples)
8. [Advanced Features](#advanced-features)
9. [Best Practices](#best-practices)

---

## Overview

### What is GASL?

GASL is a **hypothesis-driven graph analysis system** that uses LLM intelligence to:
- Translate natural language queries into systematic graph exploration plans
- Execute graph operations with state management
- Iteratively refine hypotheses based on results
- Generate comprehensive answers from accumulated evidence

### Key Features

- **LLM-Driven Planning**: Natural language queries → executable plans
- **Hypothesis-Driven Traversal (HDT)**: Iterative exploration with refinement
- **State Management**: Persistent state across commands
- **Field Management**: Automatic conflict resolution for field names
- **Graph Versioning**: Track graph modifications over time
- **Provenance Tracking**: Trace results back to source documents

### Design Philosophy

**Traditional Approach (RAG)**:
```
Query → Vector Search → Context → Answer
```
**Problems**: Limited coverage, no systematic exploration, single-shot

**GASL Approach (HDT)**:
```
Query → Hypothesis → Plan → Execute → Evaluate → Refine → Repeat → Answer
```
**Benefits**: Complete coverage, systematic exploration, iterative refinement

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────┐
│                    User Query                            │
└─────────────────┬───────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────┐
│              GASLExecutor                                │
│  - Hypothesis formation                                  │
│  - Plan generation (LLM)                                 │
│  - Execution coordination                                │
└─────────────┬────────────┬────────────┬─────────────────┘
              │            │            │
    ┌─────────▼──┐  ┌─────▼──────┐  ┌─▼──────────┐
    │  Parser    │  │   State    │  │  Adapter   │
    │            │  │  Manager   │  │            │
    └─────┬──────┘  └─────┬──────┘  └─┬──────────┘
          │               │            │
    ┌─────▼───────────────▼────────────▼──────────┐
    │         Command Handlers                     │
    │  FIND │ PROCESS │ COUNT │ JOIN │ ...        │
    └──────────────────┬───────────────────────────┘
                       │
              ┌────────▼─────────┐
              │   Graph Storage  │
              │  (NetworkX/Neo4j)│
              └──────────────────┘
```

### Directory Structure

```
gasl/
├── __init__.py           # Public API
├── executor.py           # Main execution engine
├── types.py              # Type definitions
├── errors.py             # Exception types
├── parser.py             # Command parsing
├── flexible_parser.py    # Flexible parsing strategies
├── state.py              # State management
├── state_manager.py      # Centralized state operations
├── graph_versioning.py   # Graph version control
├── validation.py         # Input validation
├── micro_actions.py      # LLM micro-operations
├── utils.py              # Utilities
├── commands/             # Command implementations
│   ├── base.py          # Base command handler
│   ├── find.py          # Graph search
│   ├── process.py       # LLM processing
│   ├── classify.py      # LLM classification
│   ├── count.py         # Counting/aggregation
│   ├── add_field.py     # Field manipulation
│   ├── graph_nav.py     # Graph navigation
│   ├── multi_var.py     # Multi-variable operations
│   ├── data_transform.py # Data transformations
│   └── ...
├── adapters/            # Graph backend adapters
│   ├── base.py         # Adapter interface
│   ├── networkx.py     # NetworkX implementation
│   └── neo4j.py        # Neo4j implementation
└── llm/                # LLM integration
    ├── client.py       # LLM client interface
    └── argo_bridge.py  # Argo Bridge implementation
```

---

## Core Concepts

### 1. Hypothesis-Driven Traversal (HDT)

HDT is the core execution model of GASL:

**Step 1: Hypothesis Formation**
```
User Query: "Create a histogram of author names"
    ↓
LLM Hypothesis: "To count authors, I need to:
  1. Find all nodes that might represent authors
  2. Extract author names from descriptions
  3. Count occurrences"
```

**Step 2: Plan Generation**
```json
{
  "plan_id": "plan_001",
  "hypothesis": "Find PERSON entities and extract author names",
  "commands": [
    {
      "command": "FIND nodes with entity_type=PERSON AS authors",
      "why": "Author information is stored in PERSON entities",
      "expected_count": "unknown"
    },
    {
      "command": "PROCESS authors with instruction: Extract author names from description AS author_names",
      "why": "Need to extract clean author names from node descriptions",
      "expected_format": "list of strings"
    },
    {
      "command": "COUNT author_names AS histogram",
      "why": "Create frequency histogram of author names",
      "expected_output": "dictionary with counts"
    }
  ]
}
```

**Step 3: Execution**
- Parser converts commands to executable form
- StateManager tracks variables and metadata
- Commands execute sequentially
- Results stored in state

**Step 4: Evaluation**
```
LLM evaluates:
- Did we get expected results?
- Are results complete/accurate?
- What's missing?
- Should we refine hypothesis?
```

**Step 5: Refinement (if needed)**
```
If incomplete:
  → Generate new hypothesis
  → Create refined plan
  → Execute again
  → Repeat until satisfied
```

**Step 6: Final Answer**
```
Synthesize all accumulated state into comprehensive answer
```

### 2. State Management

GASL uses a two-tier state system:

#### StateStore (Persistent)

Stores accumulated results that persist across commands:

```json
{
  "version": "0.1",
  "query": "Create histogram of author names",
  "variables": {
    "authors": {
      "_meta": {"type": "LIST", "description": "PERSON entities"},
      "items": [...],
      "fields": {
        "author_name": {
          "description": "Extracted author name",
          "source": "PROCESS command",
          "created_at": "2024-01-01T10:00:00"
        }
      }
    },
    "histogram": {
      "_meta": {"type": "DICT", "description": "Author frequency counts"},
      "John Smith": 5,
      "Jane Doe": 3,
      ...
    }
  },
  "history": [
    {
      "step": 1,
      "command": "FIND nodes with entity_type=PERSON",
      "why": "Find author entities",
      "summary": {"count": 100},
      "started_at": "...",
      "finished_at": "..."
    }
  ]
}
```

#### ContextStore (Ephemeral)

Stores temporary results within a single iteration:

```python
context.set("temp_results", data)
result = context.get("temp_results")
context.clear()  # Cleared after iteration
```

### 3. Field Management

GASL automatically manages field metadata with conflict resolution:

**Example: Adding Fields**
```
Initial data: [{"id": "1", "description": "..."}]

Command: ADD_FIELD authors field: name = extracted_names
Result: [{"id": "1", "description": "...", "name": "John"}]

Command: ADD_FIELD authors field: name = alternative_names
Result: [{"id": "1", "description": "...", "name": "John", "name_1": "J. Smith"}]
```

**Field Metadata**:
```json
{
  "fields": {
    "name": {
      "description": "Author name extracted from description",
      "source": "PROCESS with extract names",
      "created_at": "2024-01-01T10:00:00"
    },
    "name_1": {
      "description": "Alternative author name",
      "source": "PROCESS with alternative extraction",
      "created_at": "2024-01-01T10:05:00"
    }
  }
}
```

### 4. Graph Versioning

Tracks modifications to the graph over time:

```python
# Create version before modification
version_id = versioned_graph.create_version(
    operation="ADD_FIELD",
    description="Added author_name field to PERSON nodes"
)

# Modify graph
graph.nodes[node_id]["author_name"] = "John Smith"

# Version is automatically tracked
debugger = GraphVersionDebugger(versioned_graph)
debugger.show_versions()
# Output:
# v0: Initial graph (baseline)
# v1: ADD_FIELD - Added author_name field (3 nodes modified)
```

### 5. Adapters

Abstraction layer over different graph backends:

```python
class GraphAdapter(ABC):
    @abstractmethod
    def find_nodes(self, filters: Dict) -> List[Dict]:
        """Find nodes matching filters"""

    @abstractmethod
    def find_edges(self, filters: Dict) -> List[Dict]:
        """Find edges matching filters"""

    @abstractmethod
    def add_node(self, node_id: str, properties: Dict) -> None:
        """Add node to graph"""
```

**NetworkX Adapter**: In-memory graphs, GraphML persistence
**Neo4j Adapter**: Production database, Cypher queries

---

## Command Reference

### Discovery & Data Retrieval

#### DECLARE
Define state variables with types.

```gasl
DECLARE <variable_name> AS DICT|LIST|COUNTER [WITH_DESCRIPTION "description"]
```

**Examples**:
```gasl
DECLARE authors AS LIST WITH_DESCRIPTION "List of author entities"
DECLARE stats AS DICT WITH_DESCRIPTION "Statistical metrics"
DECLARE paper_count AS COUNTER WITH_DESCRIPTION "Total papers processed"
```

**Variable Types**:
- `LIST`: Ordered collection of items
- `DICT`: Key-value mappings
- `COUNTER`: Numeric accumulator

#### FIND
Search for nodes, edges, or paths in the graph.

```gasl
FIND nodes|edges|paths WITH <criteria> AS <result_var>
```

**Node Filters**:
```gasl
FIND nodes WITH entity_type=PERSON AS people
FIND nodes WITH entity_type=PERSON AND source_id=paper_123 AS paper_authors
FIND nodes WHERE description contains "gene" AS gene_entities
```

**Edge Filters**:
```gasl
FIND edges WITH relationship_name=COLLABORATION AS collaborations
FIND edges WITH source_node=author_1 AS author_relationships
```

**Path Filters**:
```gasl
FIND paths WITH source_filter entity_type=PERSON AS author_paths
FIND paths WITH target_filter entity_type=ORGANIZATION AS org_connections
```

**Supported Operators**:
- `=` - Exact match
- `!=` - Not equal
- `contains` - Substring match
- `AND`, `OR` - Logical operators

#### SELECT
Select specific fields from data.

```gasl
SELECT <variable> FIELDS <field1>,<field2>,... AS <result_var>
```

**Examples**:
```gasl
SELECT authors FIELDS id,name,affiliation AS author_summary
SELECT papers FIELDS title,year AS paper_metadata
```

#### SET
Set variable values directly.

```gasl
SET <variable> = <value>
```

**Examples**:
```gasl
SET threshold = 5
SET analysis_mode = "detailed"
```

### Data Processing

#### PROCESS
LLM-based data processing and transformation.

```gasl
PROCESS <variable> WITH instruction: <task> AS <result_var>
```

**Best For**:
- Text extraction and parsing
- Classification and categorization
- Complex logical reasoning
- Pattern recognition in text
- Semantic understanding

**Avoid For**:
- Numeric comparisons (use FILTER instead)
- Mathematical operations
- Simple field extraction

**Examples**:
```gasl
PROCESS authors WITH instruction: Extract author names from description AS names
PROCESS papers WITH instruction: Classify research field (genomics/proteomics/metabolomics) AS fields
PROCESS descriptions WITH instruction: Extract year if mentioned, otherwise return null AS years
PROCESS nodes WITH instruction: Identify if node represents a person or organization AS entity_types
```

**How It Works**:
1. Sends data + instruction to LLM
2. LLM processes each item individually
3. Returns structured results
4. Results stored in new variable

#### CLASSIFY
LLM-based categorization into predefined classes.

```gasl
CLASSIFY <variable> WITH instruction: <classification_task> AS <result_var>
```

**Examples**:
```gasl
CLASSIFY authors WITH instruction: human author vs cell line vs gene AS author_types
CLASSIFY papers WITH instruction: experimental vs review vs computational AS paper_types
CLASSIFY entities WITH instruction: person/organization/location AS entity_categories
```

**Difference from PROCESS**:
- CLASSIFY: Returns categorical labels
- PROCESS: Returns extracted/transformed data

#### UPDATE
Update state variables with transformations.

```gasl
UPDATE <variable> WITH <source> [operation: <op>] [where <condition>]
```

**Operations**:
- `replace` - Replace entire variable
- `filter` - Keep only matching items
- `delete` - Remove matching items
- `merge` - Combine with existing data
- `append` - Add to existing data

**Examples**:
```gasl
UPDATE authors WITH filtered_authors operation: replace
UPDATE stats WITH new_stats operation: merge
UPDATE papers WITH papers operation: filter where year > 2020
```

#### COUNT
Count occurrences with grouping and aggregation.

```gasl
COUNT [FIND <criteria>] [<variable>] field <field_name>
  [where <condition>]
  [group by <group_field>]
  [unique]
  AS <result_var>
```

**Examples**:
```gasl
# Simple count
COUNT authors field id AS author_count

# Count with filter
COUNT authors field id where affiliation="MIT" AS mit_count

# Count with grouping
COUNT papers field id group by year AS papers_per_year

# Count unique values
COUNT collaborations field author_id unique AS unique_authors

# Count with inline FIND
COUNT FIND nodes with entity_type=PERSON field source_id AS people_per_paper
```

**Group By Aggregation**:
```gasl
COUNT papers field citation_count group by year AS citations_by_year
# Result: {"2020": 150, "2021": 200, "2022": 175}
```

### Graph Navigation

#### GRAPHWALK
Walk through graph following relationships.

```gasl
GRAPHWALK from <start_var> follow <relationship> [depth <n>] AS <result_var>
```

**Examples**:
```gasl
GRAPHWALK from authors follow COLLABORATION depth 2 AS collaboration_network
GRAPHWALK from paper follow CITED_BY depth 1 AS citations
```

#### GRAPHCONNECT
Find connections between two sets of nodes.

```gasl
GRAPHCONNECT <var1> to <var2> via <relationship> AS <result_var>
```

**Examples**:
```gasl
GRAPHCONNECT authors to papers via AUTHORED AS authorship_links
GRAPHCONNECT institutions to authors via AFFILIATED_WITH AS affiliations
```

#### SUBGRAPH
Extract subgraph around specific nodes.

```gasl
SUBGRAPH around <center_var> radius <n> [include <types>] AS <result_var>
```

**Examples**:
```gasl
SUBGRAPH around key_authors radius 2 AS author_neighborhoods
SUBGRAPH around papers radius 1 include PERSON,ORGANIZATION AS paper_context
```

#### GRAPHPATTERN
Find specific patterns in the graph.

```gasl
GRAPHPATTERN find <pattern_description> in <variable> AS <result_var>
```

**Examples**:
```gasl
GRAPHPATTERN find triangular collaborations in authors AS collaboration_triangles
GRAPHPATTERN find citation chains in papers AS citation_chains
```

### Data Combination

#### JOIN
Join two variables on common fields.

```gasl
JOIN <var1> WITH <var2> ON <field> AS <result_var>
```

**Examples**:
```gasl
JOIN authors WITH papers ON author_id AS author_publications
JOIN person_nodes WITH event_nodes ON author_name AS combined_authors
```

**How It Works**:
```
authors = [{"id": "1", "name": "John"}, {"id": "2", "name": "Jane"}]
papers = [{"author_id": "1", "title": "Paper A"}, {"author_id": "1", "title": "Paper B"}]

JOIN authors WITH papers ON author_id/id
→ [
    {"id": "1", "name": "John", "title": "Paper A"},
    {"id": "1", "name": "John", "title": "Paper B"}
  ]
```

#### MERGE
Combine multiple variables into one.

```gasl
MERGE <var1>,<var2>,... AS <result_var>
```

**Examples**:
```gasl
MERGE authors,coauthors AS all_people
MERGE papers,reports,preprints AS all_publications
```

#### COMPARE
Compare two variables and find differences.

```gasl
COMPARE <var1> WITH <var2> ON <field> AS <result_var>
```

**Examples**:
```gasl
COMPARE authors_2020 WITH authors_2021 ON publication_count AS growth_analysis
COMPARE male_authors WITH female_authors ON h_index AS gender_gap_analysis
```

### Field Operations

#### ADD_FIELD
Add fields to data with automatic conflict resolution.

```gasl
ADD_FIELD <variable> field: <name> = <source_var> AS <result_var>
```

**Examples**:
```gasl
# Extract and add field
PROCESS authors WITH instruction: Extract author name AS names
ADD_FIELD authors field: author_name = names AS authors

# Add computed field
PROCESS papers WITH instruction: Calculate h-index AS h_indices
ADD_FIELD papers field: h_index = h_indices AS papers
```

**Conflict Resolution**:
```gasl
ADD_FIELD data field: name = first_names   # Adds "name"
ADD_FIELD data field: name = last_names    # Adds "name_1" (auto-resolved)
ADD_FIELD data field: name = full_names    # Adds "name_2"
```

#### RANK
Rank items by field value.

```gasl
RANK <variable> BY <field> [order asc|desc] AS <result_var>
```

**Examples**:
```gasl
RANK authors BY publication_count order desc AS top_authors
RANK papers BY citation_count order asc AS least_cited
```

### Object Creation

#### CREATE_NODES
Create new nodes in the graph.

```gasl
CREATE_NODES from <variable> [with type: <type>] AS <result_var>
```

**Examples**:
```gasl
CREATE_NODES from authors with type: PERSON AS new_author_nodes
CREATE_NODES from institutions with type: ORGANIZATION AS org_nodes
```

#### CREATE_EDGES
Create new edges/relationships.

```gasl
CREATE_EDGES from <variable> [with type: <type>] AS <result_var>
```

**Examples**:
```gasl
CREATE_EDGES from collaborations with type: COLLABORATED_WITH AS collaboration_edges
CREATE_EDGES from citations with type: CITED_BY AS citation_edges
```

#### CREATE_GROUPS
Create group nodes from aggregations.

```gasl
CREATE_GROUPS from <variable> [with type: <type>] AS <result_var>
```

**Examples**:
```gasl
CREATE_GROUPS from author_counts with type: AUTHOR_GROUP AS author_clusters
CREATE_GROUPS from topic_analysis with type: TOPIC AS topic_nodes
```

#### GENERATE
Generate new content using LLM.

```gasl
GENERATE <content_type> from <variable> [with <spec>] AS <result_var>
```

**Examples**:
```gasl
GENERATE report from analysis with format: markdown AS final_report
GENERATE summary from findings with length: 500_words AS executive_summary
```

### Control Flow

#### REQUIRE
Require conditions to be met (soft validation).

```gasl
REQUIRE <variable> <condition>
```

**Examples**:
```gasl
REQUIRE authors count > 0
REQUIRE papers has field: year
```

#### ASSERT
Assert conditions (hard validation, stops execution).

```gasl
ASSERT <variable> <condition>
```

**Examples**:
```gasl
ASSERT authors count > 0
ASSERT results has field: summary
```

#### ON
Conditional execution based on status.

```gasl
ON success|error|empty do <command>
```

**Examples**:
```gasl
ON empty do FIND nodes with entity_type=AUTHOR
ON error do SET debug_mode = true
```

#### TRY/CATCH/FINALLY
Error handling blocks.

```gasl
TRY <command>
CATCH <error_handler>
FINALLY <cleanup>
```

---

## Execution Model

### Initialization

```python
from gasl import GASLExecutor
from gasl.adapters import NetworkXAdapter
from gasl.llm import ArgoBridgeLLM

# Load graph
graph = load_graph_from_nano_graphrag(working_dir)

# Create adapter
adapter = NetworkXAdapter(graph)

# Create LLM client
llm = ArgoBridgeLLM()

# Create executor
executor = GASLExecutor(adapter, llm, state_file="state.json")
```

### Running Queries

**Method 1: Hypothesis-Driven Traversal (HDT)**
```python
result = executor.run_hypothesis_driven_traversal(
    query="Create histogram of author names",
    max_iterations=10
)
print(result["final_answer"])
```

**Method 2: Direct Command Execution**
```python
result = executor.execute_command("FIND nodes with entity_type=PERSON AS authors")
print(result)
```

### Execution Flow

```
1. User Query
   ↓
2. LLM generates hypothesis and plan (JSON)
   ↓
3. Parser converts plan to command list
   ↓
4. For each command:
   a. Parse command syntax
   b. Execute via handler
   c. Update state
   d. Track provenance
   ↓
5. LLM evaluates results
   ↓
6. If incomplete: goto step 2 (new iteration)
   If complete: generate final answer
   ↓
7. Return answer + final state
```

### Command Execution

```python
# Example: FIND command execution

1. Input: "FIND nodes with entity_type=PERSON AS authors"

2. Parser extracts:
   - object_type: "nodes"
   - filters: {"entity_type": "PERSON"}
   - result_var: "authors"

3. Handler (FindCommandHandler):
   - Calls adapter.find_nodes(filters)
   - Gets results from graph

4. StateManager:
   - Creates variable "authors" (type: LIST)
   - Stores results
   - Adds field metadata
   - Saves to state file

5. Output:
   {
     "status": "success",
     "result_count": 42,
     "variable": "authors"
   }
```

---

## State Management

### State File Structure

```json
{
  "version": "0.1",
  "created_at": "2024-01-01T10:00:00",
  "updated_at": "2024-01-01T10:15:00",
  "query": "Create histogram of author names",
  "config": {
    "max_iterations": 10,
    "llm_model": "gpt-4o"
  },
  "variables": {
    "authors": {
      "_meta": {
        "type": "LIST",
        "description": "PERSON entities from graph"
      },
      "items": [
        {"id": "1", "description": "John Smith", "entity_type": "PERSON"},
        {"id": "2", "description": "Jane Doe", "entity_type": "PERSON"}
      ],
      "fields": {
        "author_name": {
          "description": "Extracted author name",
          "source": "PROCESS command step 2",
          "created_at": "2024-01-01T10:05:00"
        }
      }
    },
    "histogram": {
      "_meta": {
        "type": "DICT",
        "description": "Author name frequency counts"
      },
      "John Smith": 5,
      "Jane Doe": 3
    }
  },
  "history": [
    {
      "step": 1,
      "command": "FIND nodes with entity_type=PERSON AS authors",
      "why": "Find all author entities in the graph",
      "summary": {"count": 42, "avg_degree": 3.2},
      "started_at": "2024-01-01T10:00:00",
      "finished_at": "2024-01-01T10:01:00"
    },
    {
      "step": 2,
      "command": "PROCESS authors WITH instruction: Extract author names",
      "why": "Extract clean author names from descriptions",
      "summary": {"processed": 42, "extracted": 40},
      "started_at": "2024-01-01T10:01:00",
      "finished_at": "2024-01-01T10:05:00"
    }
  ],
  "validation_hint": null,
  "strategy_insights": "Successfully extracted authors using PERSON entity type"
}
```

### Working with State

**Read State**:
```python
state = executor.state_manager.get_state()
authors = state["variables"]["authors"]["items"]
```

**Inspect Variables**:
```python
# List all variables
variables = executor.state_manager.list_variables()

# Get variable metadata
meta = executor.state_manager.get_variable_metadata("authors")
print(meta["type"])  # "LIST"
print(meta["description"])  # "PERSON entities from graph"

# Get field metadata
fields = executor.state_manager.get_field_metadata("authors")
print(fields["author_name"]["description"])
```

**Clear State**:
```python
executor.state_manager.clear_state()
```

---

## Usage Examples

### Example 1: Author Frequency Analysis

**Query**: "Create a histogram of how often author names appear"

**Generated Plan**:
```json
{
  "hypothesis": "Author names are in PERSON entity descriptions",
  "commands": [
    {
      "command": "FIND nodes with entity_type=PERSON AS authors",
      "why": "Locate all author entities"
    },
    {
      "command": "PROCESS authors with instruction: Extract author name from description AS names",
      "why": "Get clean author names"
    },
    {
      "command": "ADD_FIELD authors field: author_name = names",
      "why": "Store names as structured field"
    },
    {
      "command": "COUNT authors field author_name AS histogram",
      "why": "Count frequency of each author"
    }
  ]
}
```

**Execution**:
```bash
python gasl_main.py \
  --working-dir /path/to/papers \
  --query "Create a histogram of how often author names appear" \
  --max-iterations 3
```

**Result**:
```
Author Name Histogram:
- John Smith: 5 papers
- Jane Doe: 3 papers
- Bob Johnson: 2 papers
...
```

### Example 2: Multi-Dataset Analysis

**Query**: "Find all author names across both PERSON and EVENT entities, then create a unified histogram"

**Generated Plan**:
```json
{
  "hypothesis": "Authors may appear in different entity types",
  "commands": [
    {
      "command": "FIND nodes with entity_type=PERSON AS person_nodes",
      "why": "Find PERSON entities"
    },
    {
      "command": "FIND nodes with entity_type=EVENT AS event_nodes",
      "why": "Find EVENT entities"
    },
    {
      "command": "PROCESS person_nodes with instruction: Extract author names AS person_authors",
      "why": "Extract from PERSON nodes"
    },
    {
      "command": "PROCESS event_nodes with instruction: Extract author names AS event_authors",
      "why": "Extract from EVENT nodes"
    },
    {
      "command": "ADD_FIELD person_nodes field: author_name = person_authors",
      "why": "Add field to PERSON nodes"
    },
    {
      "command": "ADD_FIELD event_nodes field: author_name = event_authors",
      "why": "Add field to EVENT nodes"
    },
    {
      "command": "JOIN person_nodes with event_nodes on author_name AS combined",
      "why": "Merge datasets on author name"
    },
    {
      "command": "COUNT combined field author_name AS histogram",
      "why": "Create unified histogram"
    }
  ]
}
```

### Example 3: Collaboration Network Analysis

**Query**: "Find all collaboration pairs and count how many times each pair collaborated"

**Generated Plan**:
```json
{
  "hypothesis": "Collaborations are edges between PERSON nodes",
  "commands": [
    {
      "command": "FIND edges with relationship_name=COLLABORATION AS collabs",
      "why": "Find collaboration edges"
    },
    {
      "command": "PROCESS collabs with instruction: Create author pair string 'A & B' AS pairs",
      "why": "Create standardized pair identifiers"
    },
    {
      "command": "ADD_FIELD collabs field: pair = pairs",
      "why": "Add pair field"
    },
    {
      "command": "COUNT collabs field pair AS pair_counts",
      "why": "Count collaborations per pair"
    },
    {
      "command": "RANK pair_counts by count order desc AS top_pairs",
      "why": "Rank by collaboration frequency"
    }
  ]
}
```

---

## Advanced Features

### 1. Graph Versioning

Track all modifications to the graph:

```python
from gasl.graph_versioning import VersionedGraph, GraphVersionDebugger

# Wrap graph in versioning system
versioned_graph = VersionedGraph(graph, working_dir)

# Execute operations (versions created automatically)
executor.execute_command("ADD_FIELD authors field: name = names")

# Inspect versions
debugger = GraphVersionDebugger(versioned_graph)
debugger.show_versions()

# Output:
# v0: Initial graph (100 nodes, 250 edges)
# v1: ADD_FIELD author_name (42 nodes modified)
# v2: CREATE_NODES institutions (5 nodes added)

# Diff versions
debugger.diff_versions("v0", "v1")

# Rollback
versioned_graph.rollback_to_version("v0")
```

### 2. Provenance Tracking

Trace results back to source documents:

```python
# Execute with provenance
result = executor.execute_command("FIND nodes with entity_type=PERSON AS authors")

# Get provenance
provenance = executor.state_manager.get_provenance("authors")

for p in provenance:
    print(f"Source: {p.source_id}")
    print(f"Document: {p.doc_id}")
    print(f"Offset: {p.offset_start}-{p.offset_end}")
    print(f"Snippet: {p.snippet}")
```

### 3. Flexible Parsing

GASL supports multiple parsing strategies:

**Exact Matching**: Traditional parser
```python
parser = GASLParser()
ast = parser.parse("FIND nodes with entity_type=PERSON AS authors")
```

**Flexible Parsing**: LLM-assisted parsing
```python
parser = FlexibleGASLParser(llm_func)
ast = parser.parse("get me all the people")  # Natural language
# → Converts to: "FIND nodes with entity_type=PERSON AS people"
```

### 4. Micro-Actions

LLM-powered micro-operations for fine-grained control:

```python
from gasl.micro_actions import extract_field, filter_items, classify_items

# Extract fields from unstructured data
names = extract_field(
    items=[{"desc": "John Smith, PhD"}],
    instruction="Extract name without title",
    llm_func=llm
)
# → ["John Smith"]

# Filter with LLM reasoning
humans = filter_items(
    items=[{"name": "John Smith"}, {"name": "HeLa"}],
    condition="Keep only human authors, not cell lines",
    llm_func=llm
)
# → [{"name": "John Smith"}]

# Classify items
types = classify_items(
    items=[{"text": "..."}, ...],
    categories=["person", "organization", "location"],
    llm_func=llm
)
# → ["person", "organization", ...]
```

### 5. Custom Adapters

Create adapters for custom graph backends:

```python
from gasl.adapters import GraphAdapter

class CustomGraphAdapter(GraphAdapter):
    def __init__(self, my_graph):
        self.graph = my_graph

    def find_nodes(self, filters: Dict) -> List[Dict]:
        # Your custom node search
        return self.graph.query_nodes(filters)

    def find_edges(self, filters: Dict) -> List[Dict]:
        # Your custom edge search
        return self.graph.query_edges(filters)

    def add_node(self, node_id: str, properties: Dict) -> None:
        # Your custom node addition
        self.graph.create_node(node_id, properties)

# Use custom adapter
executor = GASLExecutor(CustomGraphAdapter(my_graph), llm, state_file)
```

---

## Best Practices

### 1. Query Design

**Good Queries**:
- ✅ Specific: "Create histogram of author names"
- ✅ Actionable: "Find all collaboration pairs"
- ✅ Clear scope: "Count papers per year from 2020-2023"

**Poor Queries**:
- ❌ Vague: "Tell me about the data"
- ❌ Ambiguous: "Find interesting patterns"
- ❌ Too broad: "Analyze everything"

### 2. Command Selection

**Use PROCESS for**:
- Text extraction ("Extract author name from description")
- Classification ("Classify as human/organization/location")
- Semantic understanding ("Identify main topic")
- Complex reasoning ("Determine if description indicates collaboration")

**Use FILTER for**:
- Numeric comparisons ("age > 30")
- Field existence checks ("has email")
- Simple conditions ("status = 'active'")

**Use COUNT for**:
- Frequency analysis
- Grouping and aggregation
- Statistical summaries

### 3. State Management

**Keep state clean**:
```python
# Declare variables upfront
executor.execute_command("DECLARE authors AS LIST")
executor.execute_command("DECLARE stats AS DICT")

# Use descriptive names
# Good: author_frequency_histogram
# Bad: data, temp, result

# Clear state between different analyses
executor.state_manager.clear_state()
```

### 4. Performance Optimization

**Reduce LLM calls**:
```python
# Bad: Process entire descriptions
PROCESS nodes with instruction: Extract name from full description

# Good: Process only relevant field
SELECT nodes FIELDS name_field AS names
PROCESS names with instruction: Clean and standardize
```

**Batch operations**:
```python
# Bad: Multiple small FINDs
FIND nodes with entity_type=PERSON AS persons
FIND nodes with entity_type=ORG AS orgs

# Good: Single FIND with OR
FIND nodes where entity_type=PERSON OR entity_type=ORG AS entities
```

### 5. Error Handling

**Use validation**:
```python
# Check preconditions
REQUIRE authors count > 0
ASSERT data has field: name

# Use TRY/CATCH for risky operations
TRY
  PROCESS authors with complex_extraction
CATCH
  PROCESS authors with simple_extraction
FINALLY
  GENERATE summary from authors
```

### 6. Debugging

**Enable verbose output**:
```bash
python gasl_main.py --query "..." --verbose
```

**Use DEBUG command**:
```gasl
FIND nodes with entity_type=PERSON AS authors
DEBUG authors  # Inspect intermediate results
PROCESS authors with instruction: Extract names AS names
DEBUG names  # Check extraction results
```

**Inspect state file**:
```python
import json
with open("gasl_state.json") as f:
    state = json.load(f)
    print(json.dumps(state["history"], indent=2))
```

---

## Integration with nano-graphrag

### Loading Existing Graphs

```python
from gasl_main import load_graph_from_nano_graphrag

# Load graph built with nano-graphrag
graph, backend = load_graph_from_nano_graphrag("/path/to/working_dir")

# Graph is automatically wrapped in VersionedGraph
# Ready to use with GASL
```

### Creating Graphs from Documents

```python
from gasl_main import create_graph_from_folder

# Build graph from text files
graph_func, working_dir = create_graph_from_folder("/path/to/documents")

# Graph is stored in working_dir/graphrag_cache/
# Can now use with GASL
```

### Query-Aware Processing

```python
from nano_graphrag.prompt_system import QueryAwarePromptSystem, set_prompt_system

# Set up query-aware prompts
ps = QueryAwarePromptSystem(llm_func=llm)
set_prompt_system(ps)

# Now graph construction will optimize for your query
# Entity types will be generated dynamically
```

---

## Troubleshooting

### Common Issues

**1. "Variable not found"**
- Make sure to DECLARE variables before using them
- Check spelling of variable names

**2. "No results from FIND"**
- Inspect graph: `DEBUG FIND nodes AS all_nodes`
- Check filter syntax
- Verify entity_type values in graph

**3. "LLM extraction inconsistent"**
- Make instructions more specific
- Add examples in instruction
- Use CLASSIFY instead of PROCESS for categories

**4. "State file corrupted"**
- Delete state file and restart
- Check file permissions
- Ensure working directory is writable

**5. "Graph modifications not persisting"**
- Ensure using VersionedGraph wrapper
- Check adapter has reference to versioned graph
- Verify GraphML file permissions

---

## Next Steps

- [Command Reference](#command-reference) - Complete command documentation (see above)
- [Architecture Guide](./ARCHITECTURE.md) - System architecture details
- [API Reference](./API_REFERENCE.md) - Python API documentation
- [Examples](../examples/) - More usage examples
