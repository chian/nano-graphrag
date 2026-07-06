"""
Analytical Retriever for nano-graphrag

A flexible retriever that uses LLM-driven query decomposition to systematically answer
complex analytical queries by breaking them down into structured graph operations.
Works with both NetworkX and Neo4j backends.
"""

from typing import Dict, List, Any, Optional, Union
import json
import asyncio
from dataclasses import dataclass
from enum import Enum
import networkx as nx

from nano_graphrag._utils import logger
from nano_graphrag._storage import NetworkXStorage, Neo4jStorage
# LLM functions will be passed as parameters


@dataclass
class QueryStep:
    """Represents a single step in a systematic query execution."""
    step_number: int
    description: str
    query_type: str  # 'cypher', 'networkx', 'hybrid'
    query: str
    expected_output_type: str
    depends_on: List[int] = None


class OutputType(Enum):
    """Types of expected outputs from query steps."""
    ENTITY_LIST = "entity_list"
    RELATIONSHIP_ANALYSIS = "relationship_analysis"
    COAUTHORSHIP_NETWORK = "coauthorship_network"
    AGGREGATION = "aggregation"
    PATTERN_DISCOVERY = "pattern_discovery"
    TEXT_EXTRACTION = "text_extraction"


class AnalyticalRetriever:
    """
    A flexible retriever that systematically answers complex analytical queries by:
    1. Using LLM to decompose queries into structured steps
    2. Executing graph queries to retrieve comprehensive data
    3. Processing results based on query intent
    4. Generating final answers using retrieved data
    
    Works with both NetworkX and Neo4j backends.
    """

    def __init__(
        self,
        graph_storage: Union[NetworkXStorage, Neo4jStorage],
        llm_func=None,
        system_prompt: Optional[str] = None,
    ):
        """Initialize the analytical retriever."""
        self.graph_storage = graph_storage
        self.llm_func = llm_func or best_model_func
        self.system_prompt = system_prompt
        self.is_neo4j = isinstance(graph_storage, Neo4jStorage)

    async def get_context(self, query: str) -> Dict[str, Any]:
        """Systematically retrieve context by decomposing and executing the query."""
        try:
            # Get graph schema for LLM context
            graph_schema = await self._get_graph_schema()
            
            # Decompose query into systematic steps
            steps = await self._decompose_query(query, graph_schema)
            
            # Execute steps and collect results
            results = await self._execute_steps(steps)
            
            return {
                "original_query": query,
                "steps": results,
                "execution_summary": self._create_execution_summary(results)
            }
            
        except Exception as e:
            logger.error(f"Error in analytical retrieval: {e}")
            return {
                "original_query": query,
                "error": str(e),
                "steps": {},
                "execution_summary": {"status": "failed", "error": str(e)}
            }

    async def get_completion(self, query: str, context: Optional[Dict[str, Any]] = None) -> List[str]:
        """Generate completion using systematically retrieved context."""
        if context is None:
            context = await self.get_context(query)
        
        if "error" in context:
            return [f"Error processing query: {context['error']}"]
        
        # Generate final answer using LLM
        final_answer = await self._generate_final_answer(query, context)
        return [final_answer]

    async def _get_graph_schema(self) -> Dict[str, Any]:
        """Retrieve the current graph schema for LLM context."""
        try:
            if self.is_neo4j:
                return await self._get_neo4j_schema()
            else:
                return await self._get_networkx_schema()
        except Exception as e:
            logger.warning(f"Could not retrieve graph schema: {e}")
            return {"node_types": [], "relationship_types": [], "total_nodes": 0, "total_relationships": 0}

    async def _get_neo4j_schema(self) -> Dict[str, Any]:
        """Get schema from Neo4j database."""
        async with self.graph_storage.async_driver.session() as session:
            # Get node labels and properties
            node_query = f"""
            MATCH (n:`{self.graph_storage.namespace}`)
            UNWIND keys(n) AS prop
            RETURN DISTINCT labels(n) AS node_labels, collect(DISTINCT prop) AS properties
            ORDER BY node_labels
            """
            
            # Get relationship types
            rel_query = f"""
            MATCH ()-[r]->()
            WHERE r.namespace = '{self.graph_storage.namespace}'
            RETURN DISTINCT r.relationship_name AS relationship_type
            """
            
            node_result = await session.run(node_query)
            rel_result = await session.run(rel_query)
            
            node_schema = [record for record in await node_result.data()]
            rel_schema = [record for record in await rel_result.data()]
            
            return {
                "node_types": node_schema,
                "relationship_types": rel_schema,
                "total_nodes": len(node_schema),
                "total_relationships": len(rel_schema)
            }

    async def _get_networkx_schema(self) -> Dict[str, Any]:
        """Get schema from NetworkX graph."""
        graph = self.graph_storage._graph
        
        # Get node types and properties
        node_types = {}
        for node, data in graph.nodes(data=True):
            node_type = data.get('entity_type', 'unknown')
            if node_type not in node_types:
                node_types[node_type] = set()
            node_types[node_type].update(data.keys())
        
        # Get relationship types
        rel_types = set()
        for source, target, data in graph.edges(data=True):
            rel_type = data.get('relationship_name', 'unknown')
            rel_types.add(rel_type)
        
        return {
            "node_types": [{"node_labels": [k], "properties": list(v)} for k, v in node_types.items()],
            "relationship_types": [{"relationship_type": rt} for rt in rel_types],
            "total_nodes": graph.number_of_nodes(),
            "total_relationships": graph.number_of_edges()
        }

    async def _decompose_query(self, query: str, graph_schema: Dict[str, Any]) -> List[QueryStep]:
        """Use LLM to decompose a query into systematic execution steps."""
        
        backend_type = "Neo4j" if self.is_neo4j else "NetworkX"
        
        decomposition_prompt = f"""
        You are an expert at analyzing complex queries and breaking them down into systematic graph database operations.

        USER QUERY: "{query}"

        BACKEND: {backend_type}
        AVAILABLE GRAPH SCHEMA:
        {json.dumps(graph_schema, indent=2)}

        IMPORTANT DATABASE CONSTRAINTS:
        - This is a {backend_type} database with a knowledge graph schema
        - The graph contains {graph_schema.get('total_nodes', 0)} nodes and {graph_schema.get('total_relationships', 0)} relationships
        - Node types found in the data: PERSON, GEO, ORGANIZATION, EVENT, UNKNOWN
        - For Neo4j: Use Cypher queries with namespace filtering
        - For NetworkX: Use Python NetworkX operations
        - Focus on finding the correct entity types for your query
        
        CRITICAL ENTITY TYPE MAPPING:
        - AUTHORS: Look for entity_type='PERSON' (NOT 'Entity')
        - PROTEINS/CYTOKINES: Look for entity_type='EVENT' or 'ORGANIZATION' 
        - LOCATIONS: Look for entity_type='GEO'
        - INSTITUTIONS: Look for entity_type='ORGANIZATION'
        - PROCESSES: Look for entity_type='EVENT'
        
        FOR AUTHOR QUERIES, use this specific approach:
        - Query for nodes with entity_type='PERSON' (NOT 'Entity')
        - Authors are people with names like "firstname lastname"
        - Authors have descriptions mentioning "author", "researcher", "study"
        - For NetworkX: Use simple query strings like "find nodes with entity_type=PERSON"
        - For Neo4j: Use "MATCH (n) WHERE n.entity_type = 'PERSON' RETURN n"
        
        FOR CO-AUTHORSHIP QUERIES, look for indirect connections:
        - Authors might be connected through shared papers, institutions, or research topics
        - Look for paths: AUTHOR -> PAPER/INSTITUTION/TOPIC -> AUTHOR
        - Query for edges where both endpoints are PERSON nodes (direct co-authorship)
        - Query for paths through intermediate entities (indirect co-authorship)
        - For NetworkX: Use "find paths between PERSON nodes through intermediate entities"
        
        FOR PROTEIN QUERIES, use this approach:
        - Query for nodes with entity_type='EVENT' or 'ORGANIZATION'
        - Look for names containing 'IL-', 'interleukin', 'cytokine', 'protein'
        - For NetworkX: Use simple query strings like "find nodes with entity_type=EVENT"
        - For Neo4j: Use "MATCH (n) WHERE n.entity_type = 'EVENT' AND n.name CONTAINS 'IL-' RETURN n"
        
        {backend_type.upper()} SYNTAX EXAMPLES:
        {self._get_syntax_examples()}

        Your task is to break this query down into a series of systematic steps that will retrieve all necessary data.

        For each step, provide:
        1. A clear description of what this step does
        2. A valid query (Cypher for Neo4j, NetworkX for NetworkX)
        3. What type of output this step produces
        4. Which previous steps (if any) this step depends on

        Focus on queries that leverage the graph structure - relationships, entity connections, and graph patterns.

        Return your analysis as a JSON array of steps with this exact format:
        [
            {{
                "step_number": 1,
                "description": "Clear description of what this step does",
                "query_type": "{backend_type.lower()}",
                "query": "MATCH (n) RETURN n LIMIT 10",
                "expected_output_type": "entity_list",
                "depends_on": []
            }}
        ]

        Make sure all queries are syntactically correct and will execute successfully.
        """

        try:
            response = await self.llm_func(
                prompt=decomposition_prompt,
                system_prompt="You are an expert database query planner. Always return valid JSON in the exact format requested.",
                history_messages=[]
            )
            
            # Parse the JSON response
            try:
                steps_data = json.loads(response)
                if not isinstance(steps_data, list):
                    raise ValueError("Response is not a list")
                
                steps = []
                for step_data in steps_data:
                    step = QueryStep(
                        step_number=step_data["step_number"],
                        description=step_data["description"],
                        query_type=step_data["query_type"],
                        query=step_data["query"],
                        expected_output_type=step_data["expected_output_type"],
                        depends_on=step_data.get("depends_on", [])
                    )
                    steps.append(step)
                
                return steps
                
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"Error parsing LLM response: {e}")
                return self._create_fallback_steps(query)
            
        except Exception as e:
            logger.error(f"Error decomposing query: {e}")
            return self._create_fallback_steps(query)
    
    def _get_syntax_examples(self) -> str:
        """Get syntax examples based on the backend type."""
        if self.is_neo4j:
            return """
            - Find entities: "MATCH (n:`{namespace}`) WHERE n.entity_type = 'Entity' RETURN n"
            - Find document chunks: "MATCH (n:`{namespace}`) WHERE n.entity_type = 'DocumentChunk' RETURN n"
            - Find relationships: "MATCH ()-[r]->() WHERE r.namespace = '{namespace}' RETURN r"
            - Find co-authors: "MATCH (a:`{namespace}`)-[r]->(b:`{namespace}`) WHERE a.entity_type = 'Entity' AND b.entity_type = 'Entity' RETURN a, b, r"
            """
        else:
            return """
            - Find authors: "find nodes with entity_type=PERSON"
            - Find proteins: "find nodes with entity_type=EVENT"
            - Find organizations: "find nodes with entity_type=ORGANIZATION"
            - Find locations: "find nodes with entity_type=GEO"
            - Find relationships: "find edges"
            - Find co-authors: "find edges between PERSON nodes"
            """

    def _create_fallback_steps(self, query: str) -> List[QueryStep]:
        """Create fallback steps when LLM decomposition fails."""
        if self.is_neo4j:
            query_str = f"MATCH (n:`{self.graph_storage.namespace}`) RETURN n LIMIT 50"
        else:
            query_str = "graph.nodes(data=True)"
        
        return [QueryStep(
            step_number=1,
            description=f"Basic search for: {query}",
            query_type="neo4j" if self.is_neo4j else "networkx",
            query=query_str,
            expected_output_type="text_extraction"
        )]

    async def _execute_steps(self, steps: List[QueryStep]) -> Dict[str, Any]:
        """Execute the decomposed query steps in order."""
        results = {}
        step_outputs = {}
        
        for step in steps:
            try:
                # Check dependencies
                if step.depends_on:
                    for dep_step in step.depends_on:
                        if f"step_{dep_step}" not in step_outputs:
                            logger.warning(f"Step {step.step_number} depends on step {dep_step} which hasn't completed")
                            continue
                
                # Execute the query based on type
                if step.query_type == "cypher" or (self.is_neo4j and step.query_type == "neo4j"):
                    raw_result = await self._execute_cypher_query(step.query)
                elif step.query_type == "networkx" or (not self.is_neo4j and step.query_type == "networkx"):
                    raw_result = await self._execute_networkx_query(step.query)
                else:
                    # Hybrid approach - try both
                    if self.is_neo4j:
                        raw_result = await self._execute_cypher_query(step.query)
                    else:
                        raw_result = await self._execute_networkx_query(step.query)
                
                # Process the result based on expected output type
                processed_result = await self._process_step_result(step, raw_result, step_outputs)
                
                step_outputs[step.step_number] = processed_result
                results[f"step_{step.step_number}"] = {
                    "description": step.description,
                    "result": processed_result,
                    "raw_count": len(raw_result) if isinstance(raw_result, list) else 1,
                    "status": "success"
                }
                
            except Exception as e:
                logger.error(f"Error executing step {step.step_number}: {e}")
                results[f"step_{step.step_number}"] = {
                    "description": step.description,
                    "error": str(e),
                    "result": None,
                    "status": "failed"
                }
        
        return results

    async def _execute_cypher_query(self, query: str) -> List[Dict]:
        """Execute a Cypher query on Neo4j."""
        async with self.graph_storage.async_driver.session() as session:
            result = await session.run(query)
            return [record for record in await result.data()]

    async def _execute_networkx_query(self, query: str) -> List[Dict]:
        """Execute a NetworkX query (simplified Python operations)."""
        graph = self.graph_storage._graph
        
        # Debug: print the actual query being executed
        print(f"DEBUG: Executing NetworkX query: {query}")
        print(f"DEBUG: Contains 'entity_type': {'entity_type' in query}")
        print(f"DEBUG: Contains 'PERSON': {'PERSON' in query}")
        
        # Handle entity type queries dynamically
        if "entity_type" in query or "find nodes with entity_type" in query:
            # Dynamically discover all entity types in the graph
            all_entity_types = set()
            for node, data in graph.nodes(data=True):
                entity_type = data.get('entity_type', '').strip('"')
                if entity_type:
                    all_entity_types.add(entity_type)
            
            # Extract requested entity type from query
            requested_type = None
            for entity_type in all_entity_types:
                if entity_type.upper() in query.upper():
                    requested_type = entity_type
                    break
            
            # If no specific type found, return all nodes
            if not requested_type:
                nodes = []
                for node, data in graph.nodes(data=True):
                    nodes.append({"node": node, **data})
                print(f"DEBUG: Found {len(nodes)} total nodes (no specific type requested)")
                return nodes
            
            # Find nodes of the requested type
            nodes = []
            for node, data in graph.nodes(data=True):
                entity_type = data.get('entity_type', '').strip('"')
                if entity_type == requested_type:
                    nodes.append({"node": node, **data})
                # Debug: show first few entity types
                if len(nodes) < 3:
                    print(f"DEBUG: Node {node} has entity_type: '{entity_type}' (type: {type(entity_type)})")
            print(f"DEBUG: Found {len(nodes)} {requested_type} nodes")
            return nodes
        
        elif "edges" in query:
            # Find edges
            edges = []
            for source, target, data in graph.edges(data=True):
                edges.append({"source": source, "target": target, **data})
            print(f"DEBUG: Found {len(edges)} edges")
            return edges
        
        elif "paths" in query or "path" in query:
            # Find paths between nodes of specified types
            import networkx as nx
            import re
            
            # Dynamically discover all entity types in the graph
            all_entity_types = set()
            for node, data in graph.nodes(data=True):
                entity_type = data.get('entity_type', '').strip('"')
                if entity_type:
                    all_entity_types.add(entity_type)
            
            # Extract node types from query using regex
            found_types = [t for t in all_entity_types if t.upper() in query.upper()]
            
            # If no specific types found, use all types
            if not found_types:
                found_types = list(all_entity_types)
            
            # Get all nodes of the specified types
            source_nodes = []
            target_nodes = []
            
            for node, data in graph.nodes(data=True):
                entity_type = data.get('entity_type', '').strip('"')
                if entity_type in found_types:
                    source_nodes.append(node)
                    target_nodes.append(node)
            
            paths = []
            # Find all simple paths between nodes (max length 3 to avoid too many paths)
            for i, source in enumerate(source_nodes[:50]):  # Limit for performance
                for j, target in enumerate(target_nodes[:50]):  # Limit for performance
                    if source != target:  # Avoid self-loops
                        try:
                            # Find all simple paths of length 2-3
                            for path in nx.all_simple_paths(graph, source, target, cutoff=3):
                                if len(path) >= 2:  # At least 2 nodes
                                    paths.append({
                                        "source": source,
                                        "target": target,
                                        "path": path,
                                        "path_length": len(path) - 1,
                                        "intermediate_nodes": path[1:-1] if len(path) > 2 else []
                                    })
                        except nx.NetworkXNoPath:
                            continue
            
            print(f"DEBUG: Found {len(paths)} paths between nodes of types: {found_types}")
            return paths
        
        elif "edges between" in query.lower() or "connections between" in query.lower():
            # Find direct edges between nodes of specified types
            import re
            
            # Dynamically discover all entity types in the graph
            all_entity_types = set()
            for node, data in graph.nodes(data=True):
                entity_type = data.get('entity_type', '').strip('"')
                if entity_type:
                    all_entity_types.add(entity_type)
            
            # Extract node types from query using regex
            found_types = [t for t in all_entity_types if t.upper() in query.upper()]
            
            # If no specific types found, use all types
            if not found_types:
                found_types = list(all_entity_types)
            
            connections = []
            for source, target, data in graph.edges(data=True):
                source_data = graph.nodes.get(source, {})
                target_data = graph.nodes.get(target, {})
                
                source_type = source_data.get('entity_type', '').strip('"')
                target_type = target_data.get('entity_type', '').strip('"')
                
                if source_type in found_types and target_type in found_types:
                    connections.append({
                        "source": source,
                        "target": target,
                        "source_type": source_type,
                        "target_type": target_type,
                        "relationship": data.get('relationship_name', 'unknown'),
                        **data
                    })
            
            print(f"DEBUG: Found {len(connections)} direct connections between nodes of types: {found_types}")
            return connections
        
        else:
            # Default: return all nodes
            nodes = []
            for node, data in graph.nodes(data=True):
                nodes.append({"node": node, **data})
            print(f"DEBUG: Found {len(nodes)} total nodes")
            return nodes

    async def _process_step_result(self, step: QueryStep, raw_result: List[Dict], 
                                 step_outputs: Dict[int, Any]) -> Any:
        """Process step results based on the step's expected output type."""
        
        if step.expected_output_type == "entity_list":
            return self._process_entity_list(raw_result)
        elif step.expected_output_type == "relationship_analysis":
            return self._process_relationship_analysis(raw_result)
        elif step.expected_output_type == "coauthorship_network":
            return self._process_coauthorship_network(raw_result)
        elif step.expected_output_type == "aggregation":
            return self._process_aggregation(raw_result)
        elif step.expected_output_type == "pattern_discovery":
            return self._process_pattern_discovery(raw_result)
        else:
            return raw_result

    def _process_entity_list(self, raw_result: List[Dict]) -> Dict[str, Any]:
        """Process entity list results."""
        return {
            "entities": raw_result,
            "count": len(raw_result),
            "processing_type": "entity_list"
        }

    def _process_relationship_analysis(self, raw_result: List[Dict]) -> Dict[str, Any]:
        """Process relationship analysis results."""
        # Group by relationship type
        rel_types = {}
        for item in raw_result:
            rel_type = item.get('relationship_name', 'unknown')
            if rel_type not in rel_types:
                rel_types[rel_type] = []
            rel_types[rel_type].append(item)
        
        return {
            "relationships": raw_result,
            "relationship_types": rel_types,
            "total_relationships": len(raw_result),
            "processing_type": "relationship_analysis"
        }

    def _process_coauthorship_network(self, raw_result: List[Dict]) -> Dict[str, Any]:
        """Process co-authorship network results."""
        # Extract author nodes and their relationships
        authors = set()
        coauthorships = []
        
        for item in raw_result:
            if 'node' in item and item.get('entity_type') == 'Entity':
                # Check if this looks like an author
                name = item.get('node', '')
                description = item.get('description', '')
                if self._is_author(name, description):
                    authors.add(name)
            elif 'source' in item and 'target' in item:
                # This is a relationship
                coauthorships.append(item)
        
        return {
            "authors": list(authors),
            "coauthorships": coauthorships,
            "author_count": len(authors),
            "coauthorship_count": len(coauthorships),
            "processing_type": "coauthorship_network"
        }

    def _is_author(self, name: str, description: str) -> bool:
        """Determine if a node represents an author."""
        # Simple heuristics for author identification
        author_keywords = ['author', 'researcher', 'affiliated with', 'professor', 'dr.', 'phd']
        
        # Check description for author keywords
        description_lower = description.lower()
        if any(keyword in description_lower for keyword in author_keywords):
            return True
        
        # Check if name looks like a person's name (has spaces, proper case)
        if ' ' in name and name[0].isupper() and len(name.split()) >= 2:
            return True
        
        return False

    def _process_aggregation(self, raw_result: List[Dict]) -> Dict[str, Any]:
        """Process aggregation results."""
        # Extract counts and frequencies
        counts = {}
        for item in raw_result:
            for key, value in item.items():
                if isinstance(value, (int, float)) and 'count' in key.lower():
                    counts[key] = counts.get(key, 0) + value
        
        return {
            "aggregated_data": raw_result,
            "counts": counts,
            "total_items": len(raw_result),
            "processing_type": "aggregation"
        }

    def _process_pattern_discovery(self, raw_result: List[Dict]) -> Dict[str, Any]:
        """Process pattern discovery results."""
        # Find common patterns
        patterns = {}
        for item in raw_result:
            pattern_key = str(sorted(item.items()))
            if pattern_key not in patterns:
                patterns[pattern_key] = 0
            patterns[pattern_key] += 1
        
        return {
            "patterns": raw_result,
            "pattern_frequencies": patterns,
            "total_patterns": len(raw_result),
            "processing_type": "pattern_discovery"
        }

    async def _generate_final_answer(self, query: str, context: Dict[str, Any]) -> str:
        """Generate the final answer using LLM and retrieved data."""
        
        # Prepare context for LLM
        context_text = self._format_context_for_llm(context)
        
        # Use the standard template format
        final_prompt = f"The question is: `{query}`\nAnd here is the context: `{context_text}`"

        try:
            return await self.llm_func(
                prompt=final_prompt,
                system_prompt=self.system_prompt or "You are an expert at analyzing graph data and providing comprehensive answers.",
                history_messages=[]
            )
        except Exception as e:
            logger.error(f"Error generating final answer: {e}")
            return f"Error generating answer: {e}"

    def _format_context_for_llm(self, context: Dict[str, Any]) -> str:
        """Format the systematically retrieved context for LLM processing."""
        context_text = f"Query: {context['original_query']}\n\n"
        
        for step_name, step_data in context['steps'].items():
            if step_data.get('status') == 'success':
                context_text += f"Step {step_name}: {step_data['description']}\n"
                
                # Safely format the result data
                result = step_data.get('result', {})
                if isinstance(result, dict):
                    # Extract key information from the result
                    if 'count' in result:
                        context_text += f"Count: {result['count']}\n"
                    if 'entities' in result:
                        entities = result['entities']
                        entity_names = []
                        for entity in entities:
                            if isinstance(entity, dict):
                                name = entity.get('node', entity.get('name', 'unnamed'))
                                if name and name != 'unnamed':
                                    entity_names.append(name)
                        if entity_names:
                            context_text += f"All entities ({len(entity_names)}): {', '.join(entity_names)}\n"
                        else:
                            context_text += f"Found {len(result['entities'])} entities (names not available)\n"
                    elif 'authors' in result:
                        context_text += f"Authors found: {', '.join(result['authors'][:10])}\n"
                        context_text += f"Total authors: {result['author_count']}\n"
                        context_text += f"Co-authorship relationships: {result['coauthorship_count']}\n"
                    elif isinstance(result, list) and result:
                        # Handle list results
                        if result and isinstance(result[0], dict) and 'path' in result[0]:
                            # Handle path results
                            context_text += f"Found {len(result)} paths between nodes:\n"
                            for i, path_item in enumerate(result[:20]):  # Show first 20 paths
                                source = path_item.get('source', 'unknown')
                                target = path_item.get('target', 'unknown')
                                path_length = path_item.get('path_length', 0)
                                intermediates = path_item.get('intermediate_nodes', [])
                                context_text += f"  Path {i+1}: {source} -> {target} (length: {path_length})\n"
                                if intermediates:
                                    context_text += f"    Via: {', '.join(intermediates)}\n"
                        else:
                            # Handle other list results
                            sample_items = result[:10]  # Show first 10 items
                            context_text += f"Results: {len(result)} items found\n"
                            for i, item in enumerate(sample_items):
                                if isinstance(item, dict) and 'node' in item:
                                    context_text += f"  - {item['node']}\n"
                                else:
                                    context_text += f"  - Item {i+1}\n"
                    else:
                        context_text += f"Results: {str(result)[:200]}...\n"
                else:
                    context_text += f"Results: {str(result)[:200]}...\n"
                context_text += "\n"
            else:
                context_text += f"Step {step_name}: {step_data['description']} (FAILED: {step_data.get('error', 'Unknown error')})\n\n"
        
        return context_text

    def _create_execution_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Create a summary of the execution results."""
        successful_steps = sum(1 for step in results.values() if step.get('status') == 'success')
        total_steps = len(results)
        
        return {
            "total_steps": total_steps,
            "successful_steps": successful_steps,
            "failed_steps": total_steps - successful_steps,
            "success_rate": successful_steps / total_steps if total_steps > 0 else 0
        }


# Example usage function
async def analyze_coauthorship(working_dir: str, query: str = "Find all authors and their co-authorship relationships"):
    """
    Example function to analyze co-authorship using the analytical retriever.
    """
    from nano_graphrag import GraphRAG
    from nano_graphrag._storage import NetworkXStorage, Neo4jStorage
    
    # Initialize GraphRAG (this will load the existing knowledge graph)
    rag = GraphRAG(working_dir=working_dir)
    
    # Get the graph storage instance
    graph_storage = rag.chunk_entity_relation_graph
    
    # Create analytical retriever
    analytical_retriever = AnalyticalRetriever(
        graph_storage=graph_storage,
        llm_func=rag.best_model_func
    )
    
    # Get context and completion
    context = await analytical_retriever.get_context(query)
    completion = await analytical_retriever.get_completion(query, context)
    
    return {
        "query": query,
        "context": context,
        "completion": completion
    }


if __name__ == "__main__":
    # Example usage
    import asyncio
    
    async def main():
        working_dir = "/Users/chia/Documents/ANL_Grants/ARPA-Connie/graphrag/dustmites_example"
        result = await analyze_coauthorship(working_dir)
        print("Query:", result["query"])
        print("Completion:", result["completion"])
    
    asyncio.run(main())
