# GASL Commands Reference

This document provides a comprehensive reference for all Graph Analysis & State Language (GASL) commands available in the system.

## Core Commands

### DECLARE
**Purpose**: Define state variables dynamically
**Syntax**: `DECLARE <variable_name> AS DICT|LIST|COUNTER [WITH_DESCRIPTION "description"]`
**Examples**:
- `DECLARE authors AS LIST WITH_DESCRIPTION "List of author entities"`
- `DECLARE stats AS DICT WITH_DESCRIPTION "Statistical analysis results"`
- `DECLARE count AS COUNTER WITH_DESCRIPTION "Publication count"`

### FIND
**Purpose**: Search for nodes, edges, or paths in the graph
**Syntax**: `FIND nodes|edges|paths with <criteria>`
**Examples**:
- `FIND nodes with entity_type=PERSON`
- `FIND edges with relationship_name=COLLABORATION`
- `FIND paths with source_filter entity_type=PERSON`

### PROCESS
**Purpose**: Complex LLM-based data processing and filtering
**Syntax**: `PROCESS <variable> with <instruction>`
**Examples**:
- `PROCESS raw_authors with instruction: filter to only human authors`
- `PROCESS publications with instruction: extract publication years and categorize by decade`

### CLASSIFY
**Purpose**: LLM-based categorization of items
**Syntax**: `CLASSIFY <variable> with instruction: <classification_task>`
**Examples**:
- `CLASSIFY authors with instruction: classify into human authors vs cell types`
- `CLASSIFY papers with instruction: categorize by research field`

### UPDATE
**Purpose**: Update state variables with data transformations
**Syntax**: `UPDATE <variable> with <source_var> [operation: <operation>] [where <condition>]`
**Operations**: `replace`, `filter`, `delete`, `merge`, `append`
**Examples**:
- `UPDATE authors with raw_data operation: filter where entity_type=PERSON`
- `UPDATE stats with temp_data operation: merge`

### COUNT
**Purpose**: Count occurrences of field values in data
**Syntax**: `COUNT [FIND nodes with <criteria>] [<variable>] field <field_name> [where <condition>] [group by <group_field>] [unique] AS <result_var>`
**Examples**:
- `COUNT cell_types field id AS cell_type_counts`
- `COUNT FIND nodes with entity_type=PERSON field source_id AS publication_counts`
- `COUNT authors field publication_count group by institution AS institution_stats`
- `COUNT papers field year where year > 2020 unique AS recent_papers`

## Graph Navigation Commands

### GRAPHWALK
**Purpose**: Walk through graph following relationships
**Syntax**: `GRAPHWALK from <start_var> follow <relationship_pattern> [depth <number>]`
**Examples**:
- `GRAPHWALK from authors follow COLLABORATION depth 2`
- `GRAPHWALK from papers follow CITED_BY depth 1`

### GRAPHCONNECT
**Purpose**: Find connections between two sets of nodes
**Syntax**: `GRAPHCONNECT <var1> to <var2> via <relationship_type>`
**Examples**:
- `GRAPHCONNECT authors to papers via AUTHORED_BY`
- `GRAPHCONNECT institutions to authors via AFFILIATED_WITH`

### SUBGRAPH
**Purpose**: Extract subgraph around specific nodes
**Syntax**: `SUBGRAPH around <center_var> radius <number> [include <node_types>]`
**Examples**:
- `SUBGRAPH around key_authors radius 2 include PERSON,ORGANIZATION`
- `SUBGRAPH around papers radius 1`

### GRAPHPATTERN
**Purpose**: Find specific patterns in the graph
**Syntax**: `GRAPHPATTERN find <pattern_description> in <variable>`
**Examples**:
- `GRAPHPATTERN find collaboration triangles in authors`
- `GRAPHPATTERN find citation chains in papers`

## Multi-Variable Commands

### JOIN
**Purpose**: Join two variables on common fields
**Syntax**: `JOIN <var1> with <var2> on <join_field> AS <result_var>`
**Examples**:
- `JOIN authors with papers on author_id AS author_papers`
- `JOIN institutions with authors on institution_id AS institutional_authors`

### MERGE
**Purpose**: Merge multiple variables into one
**Syntax**: `MERGE <var1>,<var2>,... AS <result_var>`
**Examples**:
- `MERGE authors,coauthors AS all_people`
- `MERGE papers,reports AS all_publications`

### COMPARE
**Purpose**: Compare two variables and find differences/similarities
**Syntax**: `COMPARE <var1> with <var2> on <comparison_field> AS <result_var>`
**Examples**:
- `COMPARE authors_2020 with authors_2021 on publication_count AS year_comparison`
- `COMPARE male_authors with female_authors on collaboration_count AS gender_analysis`

## Data Transformation Commands

### TRANSFORM
**Purpose**: Transform data using LLM intelligence
**Syntax**: `TRANSFORM <variable> with <transformation_instruction>`
**Examples**:
- `TRANSFORM raw_text with instruction: extract structured data from unstructured text`
- `TRANSFORM names with instruction: standardize name formats`

### RESHAPE
**Purpose**: Change data structure format
**Syntax**: `RESHAPE <variable> from <from_format> to <to_format>`
**Formats**: `list`, `dict`, `flat`, `hierarchical`
**Examples**:
- `RESHAPE authors from list to dict`
- `RESHAPE papers from flat to hierarchical`

### AGGREGATE
**Purpose**: Group and aggregate data
**Syntax**: `AGGREGATE <variable> by <group_field> with <operation>`
**Operations**: `count`, `sum`, `avg`, `min`, `max`
**Examples**:
- `AGGREGATE papers by author_id with count`
- `AGGREGATE citations by year with sum`

### PIVOT
**Purpose**: Create pivot table from data
**Syntax**: `PIVOT <variable> on <pivot_field> by <value_field>`
**Examples**:
- `PIVOT publications on year by author_id`
- `PIVOT collaborations on institution by author_id`

## Field Calculation Commands

### CALCULATE
**Purpose**: Add calculated fields to data
**Syntax**: `CALCULATE <variable> add field: <field_name> = <computation>`
**Examples**:
- `CALCULATE authors add field: name_length = description_length`
- `CALCULATE papers add field: citation_density = count_citations`

### SCORE
**Purpose**: Score items using LLM evaluation
**Syntax**: `SCORE <variable> with <scoring_criteria>`
**Examples**:
- `SCORE authors with criteria: research impact and collaboration`
- `SCORE papers with criteria: novelty and methodology quality`

### RANK
**Purpose**: Rank items by a field
**Syntax**: `RANK <variable> by <field> [order desc|asc]`
**Examples**:
- `RANK authors by publication_count order desc`
- `RANK papers by citation_count order asc`

### WEIGHT
**Purpose**: Assign weights to items using LLM
**Syntax**: `WEIGHT <variable> with <weighting_criteria>`
**Examples**:
- `WEIGHT authors with criteria: importance in research community`
- `WEIGHT papers with criteria: relevance to query topic`

## Object Creation Commands

### CREATE
**Purpose**: Create new graph objects from data
**Syntax**: `CREATE nodes|edges|summary from <variable> [with <specification>]`
**Examples**:
- `CREATE nodes from authors with type: PERSON`
- `CREATE edges from collaborations with type: COLLABORATED_WITH`
- `CREATE summary from analysis_results with format: report`

### GENERATE
**Purpose**: Generate new content using LLM
**Syntax**: `GENERATE <content_type> from <variable> [with <specification>]`
**Examples**:
- `GENERATE report from analysis_data with format: markdown`
- `GENERATE summary from findings with length: 500_words`

## Pattern Analysis Commands

### CLUSTER
**Purpose**: Cluster similar items using LLM
**Syntax**: `CLUSTER <variable> with <clustering_criteria>`
**Examples**:
- `CLUSTER authors with criteria: research interests and collaboration patterns`
- `CLUSTER papers with criteria: topic similarity`

### DETECT
**Purpose**: Detect patterns in data
**Syntax**: `DETECT patterns in <variable> with <pattern_type>`
**Examples**:
- `DETECT patterns in collaborations with type: collaboration_networks`
- `DETECT patterns in citations with type: citation_chains`

### GROUP
**Purpose**: Group items by field values
**Syntax**: `GROUP <variable> by <field> [with <aggregation>]`
**Examples**:
- `GROUP authors by institution with count`
- `GROUP papers by year with sum citations`

### ANALYZE
**Purpose**: Perform analysis on data
**Syntax**: `ANALYZE <variable> for <analysis_type>`
**Examples**:
- `ANALYZE authors for collaboration_network_analysis`
- `ANALYZE papers for citation_impact_analysis`

## Control Flow Commands

### SELECT
**Purpose**: Select specific fields from data
**Syntax**: `SELECT <variable> FIELDS <field1>,<field2>,... AS <result_var>`
**Examples**:
- `SELECT authors FIELDS id,name,publication_count AS author_summary`
- `SELECT papers FIELDS title,year,citations AS paper_basics`

### SET
**Purpose**: Set variable values
**Syntax**: `SET <variable> = <value>`
**Examples**:
- `SET max_iterations = 5`
- `SET analysis_mode = detailed`

### REQUIRE
**Purpose**: Require conditions to be met
**Syntax**: `REQUIRE <variable> <condition>`
**Examples**:
- `REQUIRE authors count > 0`
- `REQUIRE papers has field: year`

### ASSERT
**Purpose**: Assert conditions (stops execution if false)
**Syntax**: `ASSERT <variable> <condition>`
**Examples**:
- `ASSERT authors count > 0`
- `ASSERT analysis_results has field: summary`

### ON
**Purpose**: Conditional execution based on status
**Syntax**: `ON success|error|empty do <action>`
**Examples**:
- `ON empty do FIND nodes with entity_type=PERSON`
- `ON error do SET debug_mode = true`

### TRY/CATCH/FINALLY
**Purpose**: Error handling
**Syntax**: 
- `TRY <action>`
- `CATCH <error_handling>`
- `FINALLY <cleanup>`

### CANCEL
**Purpose**: Cancel execution
**Syntax**: `CANCEL PLAN "<plan_id>"`

## Command Categories by Implementation Status

### Fully Implemented
- DECLARE
- FIND
- PROCESS
- CLASSIFY
- UPDATE
- TRANSFORM
- RESHAPE
- AGGREGATE
- PIVOT
- CALCULATE
- SCORE
- RANK
- WEIGHT
- SELECT
- SET

### Partially Implemented (Placeholders)
- ANALYZE
- REQUIRE
- ASSERT
- ON
- TRY/CATCH
- CANCEL

### New Categories (Fully Implemented)
- Graph Navigation: GRAPHWALK, GRAPHCONNECT, SUBGRAPH, GRAPHPATTERN
- Multi-Variable: JOIN, MERGE, COMPARE
- Object Creation: CREATE, GENERATE
- Pattern Analysis: CLUSTER, DETECT, GROUP

## Usage Patterns

### Basic Analysis Workflow
1. `DECLARE` variables for data storage
2. `FIND` relevant nodes/edges in graph
3. `PROCESS` or `CLASSIFY` data as needed
4. `UPDATE` state variables with processed data
5. `ANALYZE` or `GENERATE` final results

### Complex Analysis Workflow
1. `DECLARE` multiple variables for different data types
2. `FIND` various graph elements
3. `JOIN` or `MERGE` related data
4. `TRANSFORM` data using LLM intelligence
5. `AGGREGATE` or `GROUP` for statistical analysis
6. `SCORE` or `RANK` for prioritization
7. `GENERATE` comprehensive reports

### Graph Exploration Workflow
1. `GRAPHWALK` to explore graph structure
2. `SUBGRAPH` to focus on relevant areas
3. `GRAPHPATTERN` to find specific patterns
4. `DETECT` patterns in the data
5. `CLUSTER` similar elements
6. `ANALYZE` for insights
