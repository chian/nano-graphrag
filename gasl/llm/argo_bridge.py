"""
Argo Bridge LLM wrapper for GASL system.
"""

import os
import asyncio
from typing import Any, Dict, Optional
from openai import AsyncOpenAI
from ..errors import LLMError


class ArgoBridgeLLM:
    """Wrapper around existing argo_bridge_llm function."""
    
    def __init__(self, model: str = None, temperature: float = 0.0, max_tokens: int = 4000):
        self.model = model or os.getenv("LLM_MODEL", "gpt41")
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Initialize OpenAI client
        self.client = AsyncOpenAI(
            api_key=os.getenv("LLM_API_KEY", "api+key"),
            base_url=os.getenv("LLM_ENDPOINT", "https://argo-bridge.cels.anl.gov/v1")
        )
    
    async def call_async(self, prompt: str) -> str:
        """Make async LLM call."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            raise LLMError(f"LLM call failed: {e}", "argo_bridge", self.model)
    
    def call(self, prompt: str) -> str:
        """Make synchronous LLM call."""
        try:
            # Run async call in event loop
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(self.call_async(prompt))
            print(f"DEBUG: LLM response length: {len(result) if result else 0}")
            print(f"DEBUG: LLM response content: {repr(result[:200]) if result else 'None'}")
            return result
        except RuntimeError:
            # No event loop running, create new one
            result = asyncio.run(self.call_async(prompt))
            print(f"DEBUG: LLM response length: {len(result) if result else 0}")
            print(f"DEBUG: LLM response content: {repr(result[:200]) if result else 'None'}")
            return result
    
    def create_plan_prompt(self, query: str, schema: Dict[str, Any], 
                          state: Dict[str, Any], history: list) -> str:
        """Create prompt for LLM to generate a plan."""
        prompt = f"""You are an AI agent that analyzes knowledge graphs to answer queries. 

Query: {query}

Available Graph Schema:
- Node Labels: {schema.get('node_labels', [])}
- Edge Types: {schema.get('edge_types', [])}
- Node Properties: {schema.get('node_properties', [])}
- Edge Properties: {schema.get('edge_properties', [])}

Current State Variables:
{self._format_state(state)}

IMPORTANT: Before creating new variables, check if existing variables can be reused or updated. 
- If a variable already exists with the same type, you can reuse it (it will be reset)
- If you need different data, consider updating existing variables with UPDATE commands
- Only create new variables if you need a fundamentally different data structure

Execution History:
{self._format_history(history)}

AVAILABLE GASL COMMANDS:

CORE COMMANDS:
- DECLARE <var> AS DICT|LIST|COUNTER [WITH_DESCRIPTION "desc"]
- FIND nodes|edges|paths with <criteria>
- PROCESS <var> with instruction: <task>
- CLASSIFY <var> with instruction: <classification_task>
- UPDATE <var> with <source> [operation: replace|filter|delete|merge|append] [where <condition>]
- COUNT [FIND nodes with <criteria>] [<var>] field <field_name> [where <condition>] [group by <group_field>] [unique] AS <result_var>

DEBUG COMMANDS:
- SHOW <var> [limit <n>] - Display variable contents
- INSPECT <var> - Analyze data structure and content

GRAPH NAVIGATION:
- GRAPHWALK from <var> follow <relationship> [depth <n>]
- GRAPHCONNECT <var1> to <var2> via <relationship>
- SUBGRAPH around <var> radius <n> [include <types>]
- GRAPHPATTERN find <pattern> in <var>

MULTI-VARIABLE OPERATIONS:
- JOIN <var1> with <var2> on <field> AS <result>
- MERGE <var1>,<var2>,... AS <result>
- COMPARE <var1> with <var2> on <field> AS <result>

DATA TRANSFORMATION:
- TRANSFORM <var> with instruction: <transformation>
- RESHAPE <var> from <format1> to <format2>
- AGGREGATE <var> by <field> with count|sum|avg|min|max
- PIVOT <var> on <pivot_field> by <value_field>

FIELD CALCULATIONS:
- CALCULATE <var> add field: <name> = <computation>
- SCORE <var> with criteria: <scoring_criteria>
- RANK <var> by <field> [order desc|asc]
- WEIGHT <var> with criteria: <weighting_criteria>

OBJECT CREATION:
- CREATE nodes|edges|summary from <var> [with <spec>]
- GENERATE <content_type> from <var> [with <spec>]

PATTERN ANALYSIS:
- CLUSTER <var> with criteria: <clustering_criteria>
- DETECT patterns in <var> with type: <pattern_type>
- GROUP <var> by <field> [with <aggregation>]
- ANALYZE <var> for <analysis_type>

CONTROL FLOW:
- SELECT <var> FIELDS <field1>,<field2>,... AS <result>
- SET <var> = <value>
- REQUIRE <var> <condition>
- ASSERT <var> <condition>
- ON success|error|empty do <action>

Generate a JSON plan object with the following structure:
{{
  "plan_id": "unique-plan-id",
  "why": "explanation of what this plan accomplishes",
  "commands": [
    "DECLARE variable_name AS DICT|LIST|COUNTER WITH_DESCRIPTION \"description\"",
    "FIND nodes with entity_type=PERSON",
    "FIND edges with relationship_name=COLLABORATION", 
    "FIND paths with source_filter entity_type=PERSON",
    "CLASSIFY variable_name with instruction: classify items into categories",
    "UPDATE variable_name with source_var operation: replace|filter|delete|merge|append",
    "UPDATE variable_name with source_var operation: filter where condition",
    "PROCESS variable_name with instruction: complex data processing",
    "TRANSFORM variable_name with instruction: data transformation",
    "AGGREGATE variable_name by field with count",
    "SCORE variable_name with criteria: scoring criteria",
    "RANK variable_name by field order desc",
    "JOIN var1 with var2 on field AS result",
    "GRAPHWALK from var follow relationship depth 2",
    "CLUSTER variable_name with criteria: clustering criteria",
    "GENERATE report from variable_name with format: markdown",
    "ANALYZE variable_name for analysis_type",
    "SELECT variable_name FIELDS field1,field2 AS new_variable",
    "SET variable_name = value",
    "REQUIRE variable_name condition",
    "ASSERT variable_name condition"
  ],
  "config": {{
    "stop_on_error": true|false,
    "continue_on_empty": true|false
  }}
}}

IMPORTANT GASL SYNTAX RULES:
- DECLARE: Use quotes around descriptions: WITH_DESCRIPTION \"description\"
- FIND: No AS clause, just criteria like: entity_type=PERSON or relationship_name=COLLABORATION
  FIND results are automatically stored as last_nodes_result in context
- CLASSIFY: Use for categorization tasks: CLASSIFY var with instruction: classify items into categories
- UPDATE: Use built-in operations: UPDATE var with source_var operation: replace|filter|delete|merge|append
- UPDATE: Use filter operation: UPDATE var with source_var operation: filter where condition
- PROCESS: Use for complex data processing beyond simple classification
- TRANSFORM: Use for data transformation tasks: TRANSFORM var with instruction: transformation task
- AGGREGATE: Use for grouping and counting: AGGREGATE var by field with count|sum|avg
- SCORE: Use for LLM-based scoring: SCORE var with criteria: scoring criteria
- RANK: Use for ranking items: RANK var by field order desc|asc
- GRAPHWALK: Use for graph traversal: GRAPHWALK from var follow relationship depth n
- CLUSTER: Use for clustering similar items: CLUSTER var with criteria: clustering criteria
- GENERATE: Use for creating reports: GENERATE report from var with format: markdown
- When you need to categorize items (e.g., human authors vs. cell types), use CLASSIFY
- When you need to filter/transform data, use UPDATE with appropriate operation
- When you need to aggregate data (e.g., count publications per author), use AGGREGATE
- When you need to score or rank items, use SCORE or RANK
- When you need to explore graph structure, use GRAPHWALK or SUBGRAPH
- When you need to create reports, use GENERATE
- Only use ONE FIND command per plan - store results and process them with other commands
- Commands end with semicolons or newlines

Use GASL commands to systematically analyze the graph and build up state to answer the query.
"""
        return prompt
    
    def create_completion_validator_prompt(self, query: str, results: Dict[str, Any]) -> str:
        """Create prompt to validate if query was successfully answered."""
        prompt = f"""You are a validator that determines if a query has been successfully answered.

Query: {query}

Results:
{self._format_results(results)}

Answer with ONLY "YES" or "NO":
- YES: if the results contain actual data that directly answers the query
- NO: if the results are empty, contain no meaningful data, or don't answer the query

Examples:
- Query: "Count cell types" + Results: {{"cell_type_counts": 0}} → NO
- Query: "Count cell types" + Results: {{"cell_type_counts": {{"T_cell": 5, "B_cell": 3}}}} → YES
- Query: "Find authors" + Results: {{"authors": []}} → NO
- Query: "Find authors" + Results: {{"authors": ["John", "Jane"]}} → YES

Answer:"""
        return prompt

    def create_analysis_prompt(self, query: str, results: Dict[str, Any]) -> str:
        """Create prompt for final analysis."""
        prompt = f"""Answer this query using ONLY the actual results provided. Do not add methodology, overview, or hypothetical examples. 
        Do not make anything up. If you do not know the answer say that the query was not answered. This is important! Otherwise the user will be falsely led to believe
        made up things and will potentially hurt people based on that knowledge who may be seeking treatment.

Query: {query}

Results:
{self._format_results(results)}

Answer:"""
        return prompt
    
    def create_strategy_adaptation_prompt(self, query: str, results: Dict[str, Any], iteration: int, schema: Dict[str, Any]) -> str:
        """Create prompt for strategy adaptation between iterations."""
        prompt = f"""You are analyzing the results of iteration {iteration} for the query: "{query}"

Current Results:
{self._format_results(results)}

Available Graph Schema:
- Node Labels: {schema.get('node_labels', [])}
- Edge Types: {schema.get('edge_types', [])}
- Node Properties: {schema.get('node_properties', [])}
- Edge Properties: {schema.get('edge_properties', [])}

Analysis Questions:
1. Did you find the expected data? If not, is it because you are filtering in a way that does not exist in the data?
2. Are there any patterns in the data that suggest a different approach?
3. Can you reuse or update existing variables instead of creating new ones?
4. What other node labels, edge types, or properties from the schema might help answer this query?
5. Instead of filtering, can you use the entities in the schema to answer the query without filtering?

Based on this analysis, you will generate a new plan for the next iteration. If the current approach isn't working, try a different strategy.

Key insights from this iteration:
- What data was found vs. what was expected?
- What filtering or search criteria worked or didn't work?
- What should be tried differently next time?
- Which existing variables can be reused or updated?
- What other schema elements (node labels, edge types, properties) could be explored?

AVAILABLE GASL COMMANDS FOR STRATEGY ADAPTATION:

CORE COMMANDS:
- DECLARE <var> AS DICT|LIST|COUNTER [WITH_DESCRIPTION "desc"]
- FIND nodes|edges|paths with <criteria>
- PROCESS <var> with instruction: <task>
- CLASSIFY <var> with instruction: <classification_task>
- UPDATE <var> with <source> [operation: replace|filter|delete|merge|append] [where <condition>]
- COUNT [FIND nodes with <criteria>] [<var>] field <field_name> [where <condition>] [group by <group_field>] [unique] AS <result_var>

DEBUG COMMANDS:
- SHOW <var> [limit <n>] - Display variable contents
- INSPECT <var> - Analyze data structure and content

GRAPH NAVIGATION:
- GRAPHWALK from <var> follow <relationship> [depth <n>]
- GRAPHCONNECT <var1> to <var2> via <relationship>
- SUBGRAPH around <var> radius <n> [include <types>]
- GRAPHPATTERN find <pattern> in <var>

MULTI-VARIABLE OPERATIONS:
- JOIN <var1> with <var2> on <field> AS <result>
- MERGE <var1>,<var2>,... AS <result>
- COMPARE <var1> with <var2> on <field> AS <result>

DATA TRANSFORMATION:
- TRANSFORM <var> with instruction: <transformation>
- RESHAPE <var> from <format1> to <format2>
- AGGREGATE <var> by <field> with count|sum|avg|min|max
- PIVOT <var> on <pivot_field> by <value_field>

FIELD CALCULATIONS:
- CALCULATE <var> add field: <name> = <computation>
- SCORE <var> with criteria: <scoring_criteria>
- RANK <var> by <field> [order desc|asc]
- WEIGHT <var> with criteria: <weighting_criteria>

OBJECT CREATION:
- CREATE nodes|edges|summary from <var> [with <spec>]
- GENERATE <content_type> from <var> [with <spec>]

PATTERN ANALYSIS:
- CLUSTER <var> with criteria: <clustering_criteria>
- DETECT patterns in <var> with type: <pattern_type>
- GROUP <var> by <field> [with <aggregation>]
- ANALYZE <var> for <analysis_type>

CONTROL FLOW:
- SELECT <var> FIELDS <field1>,<field2>,... AS <result>
- SET <var> = <value>
- REQUIRE <var> <condition>
- ASSERT <var> <condition>
- ON success|error|empty do <action>

**MANDATORY STRATEGY ENFORCEMENT:**
1. **YOU MUST INSPECT DATA FIRST** - Before making any assumptions, use SHOW or INSPECT to examine what data you actually have
2. **YOU MUST USE PROCESS** - If you need to extract information from data, you MUST use PROCESS command - no assumptions allowed
3. **YOU MUST FOLLOW ANALYSIS RECOMMENDATIONS** - If the analysis suggests a different approach, you MUST implement it exactly
4. **NO REPEATING FAILED STRATEGIES** - If an approach failed, you MUST try something completely different
5. **VALIDATE RESULTS** - Ensure your commands produce meaningful data, not empty results

Remember: 
- The goal is to systematically explore the graph to answer the query
- If one approach fails, try another
- Reuse existing variables when possible - DECLARE will reset them if same type
- Use UPDATE to modify existing variables with new data
- Look at the available schema to find alternative approaches
- Try different node labels, edge types, or properties that might be relevant
- Focus on entity_type and relationship_name properties
- Use PROCESS command for intelligent filtering based on content analysis
- Use TRANSFORM for data transformation tasks
- Use AGGREGATE for grouping and counting data
- Use SCORE/RANK for prioritizing items
- Use GRAPHWALK for exploring graph structure
- Use CLUSTER for finding similar items
- Use GENERATE for creating reports
- Let the LLM analyze names, descriptions, and properties to make smart decisions
- When you have raw data that needs intelligent filtering, use PROCESS instead of simple UPDATE
- PROCESS is especially useful when you need to distinguish between different types of entities (e.g., human authors vs. cell types)
"""
        return prompt
    
    def _format_state(self, state: Dict[str, Any]) -> str:
        """Format state for prompt."""
        if not state:
            return "No state variables defined yet."
        
        formatted = []
        for key, value in state.items():
            if isinstance(value, dict) and "_meta" in value:
                var_type = value["_meta"].get("type", "unknown")
                description = value["_meta"].get("description", "")
                if var_type == "LIST":
                    count = len(value.get("items", []))
                    formatted.append(f"- {key} ({var_type}): {count} items - {description}")
                elif var_type == "DICT":
                    keys = [k for k in value.keys() if k != "_meta"]
                    formatted.append(f"- {key} ({var_type}): {len(keys)} keys - {description}")
                elif var_type == "COUNTER":
                    count = value.get("value", 0)
                    formatted.append(f"- {key} ({var_type}): {count} - {description}")
            else:
                formatted.append(f"- {key}: {value}")
        
        return "\n".join(formatted)
    
    def _format_history(self, history: list) -> str:
        """Format history for prompt."""
        if not history:
            return "No execution history yet."
        
        formatted = []
        for entry in history[-5:]:  # Last 5 entries
            status = entry.get("status", "unknown")
            command = entry.get("command", "")
            count = entry.get("result_count", 0)
            formatted.append(f"- {status}: {command} (result count: {count})")
        
        return "\n".join(formatted)
    
    def _format_results(self, results: Dict[str, Any]) -> str:
        """Format results for prompt."""
        formatted = []
        for key, value in results.items():
            if isinstance(value, list):
                formatted.append(f"{key}: {len(value)} items")
                # Show first few items
                for i, item in enumerate(value[:3]):
                    formatted.append(f"  {i+1}. {item}")
                if len(value) > 3:
                    formatted.append(f"  ... and {len(value) - 3} more")
            else:
                formatted.append(f"{key}: {value}")
        
        return "\n".join(formatted)
