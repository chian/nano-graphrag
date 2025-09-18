"""
Object Creation command handlers.
"""

from typing import Any, List, Dict
from .base import CommandHandler
from ..types import Command, ExecutionResult, Provenance


class ObjectCreateHandler(CommandHandler):
    """Handles object creation commands: CREATE, GENERATE."""
    
    def __init__(self, state_store, context_store, llm_func=None):
        super().__init__(state_store, context_store)
        self.llm_func = llm_func
    
    def can_handle(self, command: Command) -> bool:
        return command.command_type in ["CREATE", "GENERATE"]
    
    def execute(self, command: Command) -> ExecutionResult:
        """Execute object creation command."""
        try:
            if command.command_type == "CREATE":
                return self._execute_create(command)
            elif command.command_type == "GENERATE":
                return self._execute_generate(command)
            else:
                return self._create_result(
                    command=command,
                    status="error",
                    error_message=f"Unknown object creation command: {command.command_type}"
                )
        except Exception as e:
            return self._create_result(
                command=command,
                status="error",
                error_message=str(e)
            )
    
    def _execute_create(self, command: Command) -> ExecutionResult:
        """Execute CREATE command."""
        args = command.args
        object_type = args["object_type"]  # nodes, edges, summary
        from_variable = args["from_variable"]
        creation_rules = args["creation_rules"]
        
        print(f"DEBUG: CREATE - type: {object_type}, from: {from_variable}, rules: {creation_rules}")
        
        # Get source data
        source_data = self._get_variable_data(from_variable)
        if not source_data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {from_variable} not found or empty")
        
        # Create objects based on type
        if object_type == "nodes":
            created_objects = self._create_nodes(source_data, creation_rules)
        elif object_type == "edges":
            created_objects = self._create_edges(source_data, creation_rules)
        elif object_type == "summary":
            created_objects = self._create_summary(source_data, creation_rules)
        else:
            return self._create_result(command=command, status="error",
                                     error_message=f"Unknown object type: {object_type}")
        
        # Store created objects in context
        result_key = f"created_{object_type}"
        self.context_store.set(result_key, created_objects)
        
        print(f"DEBUG: CREATE - created {len(created_objects)} {object_type} objects")
        
        return self._create_result(
            command=command,
            status="success",
            data=created_objects,
            count=len(created_objects),
            provenance=[self._create_provenance("create", "create",
                                               object_type=object_type, from_variable=from_variable)]
        )
    
    def _execute_generate(self, command: Command) -> ExecutionResult:
        """Execute GENERATE command using LLM."""
        args = command.args
        content_type = args["content_type"]
        source_variable = args["source_variable"]
        specification = args["specification"]
        
        print(f"DEBUG: GENERATE - type: {content_type}, from: {source_variable}, spec: {specification}")
        
        # Get source data
        source_data = self._get_variable_data(source_variable)
        if not source_data:
            return self._create_result(command=command, status="error",
                                     error_message=f"Variable {source_variable} not found or empty")
        
        if not self.llm_func:
            return self._create_result(command=command, status="error",
                                     error_message="LLM function not available for GENERATE command")
        
        # Create prompt for LLM generation
        prompt = self._create_generate_prompt(source_data, content_type, specification)
        
        # Call LLM
        llm_response = self.llm_func.call(prompt)
        print(f"DEBUG: GENERATE - LLM Response:\n{llm_response}\n")
        
        # Parse LLM response
        try:
            import json
            generate_result = json.loads(llm_response)
            generated_objects = generate_result.get("generated_objects", [])
            
            # Store generated objects in context
            result_key = f"generated_{content_type}"
            self.context_store.set(result_key, generated_objects)
            
            print(f"DEBUG: GENERATE - generated {len(generated_objects)} {content_type} objects")
            
            return self._create_result(
                command=command,
                status="success",
                data=generated_objects,
                count=len(generated_objects),
                provenance=[self._create_provenance("generate", "generate",
                                                   content_type=content_type, source_variable=source_variable)]
            )
            
        except json.JSONDecodeError:
            return self._create_result(command=command, status="error",
                                     error_message="Failed to parse LLM generation response as JSON")
    
    def _create_nodes(self, source_data: List[Dict], creation_rules: str) -> List[Dict]:
        """Create node objects from source data."""
        created_nodes = []
        
        for i, item in enumerate(source_data):
            # Create basic node structure
            node = {
                "id": item.get("id", f"node_{i}"),
                "type": "node",
                "label": item.get("name", item.get("id", f"Node {i}")),
                "properties": {}
            }
            
            # Apply creation rules
            if "with metadata" in creation_rules.lower():
                node["properties"]["original_data"] = item
                node["properties"]["entity_type"] = item.get("entity_type", "UNKNOWN")
                node["properties"]["description"] = item.get("description", "")
            
            if "research areas" in creation_rules.lower():
                # Extract research areas from description
                description = item.get("description", "").lower()
                research_areas = []
                if "asthma" in description:
                    research_areas.append("asthma")
                if "influenza" in description:
                    research_areas.append("influenza")
                if "allergy" in description:
                    research_areas.append("allergy")
                node["properties"]["research_areas"] = research_areas
            
            created_nodes.append(node)
        
        return created_nodes
    
    def _create_edges(self, source_data: List[Dict], creation_rules: str) -> List[Dict]:
        """Create edge objects from source data."""
        created_edges = []
        
        # Simple edge creation based on rules
        if "collaboration edges" in creation_rules.lower():
            # Create collaboration edges between items
            for i, item1 in enumerate(source_data):
                for j, item2 in enumerate(source_data[i+1:], i+1):
                    # Check if items should be connected
                    if self._should_create_edge(item1, item2, creation_rules):
                        edge = {
                            "id": f"edge_{i}_{j}",
                            "type": "edge",
                            "source": item1.get("id", f"node_{i}"),
                            "target": item2.get("id", f"node_{j}"),
                            "relationship": "collaboration",
                            "properties": {}
                        }
                        
                        # Add weight if specified
                        if "with weights" in creation_rules.lower():
                            edge["properties"]["weight"] = self._calculate_edge_weight(item1, item2)
                        
                        created_edges.append(edge)
        
        return created_edges
    
    def _create_summary(self, source_data: List[Dict], creation_rules: str) -> List[Dict]:
        """Create summary objects from source data."""
        summaries = []
        
        # Create basic summary
        summary = {
            "id": "summary_1",
            "type": "summary",
            "total_items": len(source_data),
            "summary_type": "basic",
            "properties": {}
        }
        
        # Group by entity type
        entity_counts = {}
        for item in source_data:
            entity_type = item.get("entity_type", "UNKNOWN")
            entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
        
        summary["properties"]["entity_type_counts"] = entity_counts
        
        # Add research areas if specified
        if "research clusters" in creation_rules.lower():
            research_areas = set()
            for item in source_data:
                description = item.get("description", "").lower()
                if "asthma" in description:
                    research_areas.add("asthma")
                if "influenza" in description:
                    research_areas.add("influenza")
                if "allergy" in description:
                    research_areas.add("allergy")
            summary["properties"]["research_areas"] = list(research_areas)
        
        summaries.append(summary)
        return summaries
    
    def _should_create_edge(self, item1: Dict, item2: Dict, rules: str) -> bool:
        """Determine if an edge should be created between two items."""
        # Simple heuristic: create edge if items share research areas
        desc1 = item1.get("description", "").lower()
        desc2 = item2.get("description", "").lower()
        
        # Check for shared keywords
        keywords = ["asthma", "influenza", "allergy", "il-4", "blockade"]
        shared_keywords = 0
        for keyword in keywords:
            if keyword in desc1 and keyword in desc2:
                shared_keywords += 1
        
        return shared_keywords >= 2  # Require at least 2 shared keywords
    
    def _calculate_edge_weight(self, item1: Dict, item2: Dict) -> float:
        """Calculate weight for an edge between two items."""
        # Simple weight calculation based on shared content
        desc1 = item1.get("description", "").lower()
        desc2 = item2.get("description", "").lower()
        
        # Count shared words (simple approach)
        words1 = set(desc1.split())
        words2 = set(desc2.split())
        shared_words = len(words1.intersection(words2))
        total_words = len(words1.union(words2))
        
        if total_words == 0:
            return 0.1
        
        # Jaccard similarity as weight
        weight = shared_words / total_words
        return round(weight, 2)
    
    def _create_generate_prompt(self, data: Any, content_type: str, specification: str) -> str:
        """Create prompt for LLM object generation."""
        prompt = f"""Generate {content_type} from the provided data according to these specifications: {specification}

Source data:
{self._format_data_for_llm(data)}

Instructions:
1. Create {content_type} that follows the specifications
2. Each object should have appropriate structure and properties
3. Return your results as a JSON object with this structure:
{{
  "generated_objects": [
    // Array of generated {content_type} objects
  ],
  "generation_summary": {{
    "total_generated": 0,
    "content_type": "{content_type}",
    "specifications_applied": "{specification}"
  }}
}}

Make the generated objects useful and well-structured.
"""
        return prompt
    
    def _format_data_for_llm(self, data: Any) -> str:
        """Format data for LLM consumption."""
        if not isinstance(data, list):
            return str(data)
        
        # Limit to first 10 items to avoid token limits
        sample_data = data[:10]
        formatted = []
        
        for i, item in enumerate(sample_data):
            formatted.append(f"Item {i+1}: {item}")
        
        if len(data) > 10:
            formatted.append(f"... and {len(data) - 10} more items")
        
        return "\n".join(formatted)
    
    def _get_variable_data(self, variable_name: str) -> List[Dict]:
        """Get data from state or context variable."""
        # Try context first
        if self.context_store.has(variable_name):
            data = self.context_store.get(variable_name)
            return data if isinstance(data, list) else [data]
        
        # Try state
        if self.state_store.has_variable(variable_name):
            var_data = self.state_store.get_variable(variable_name)
            if isinstance(var_data, dict) and "items" in var_data:
                return var_data["items"]
            else:
                return var_data if isinstance(var_data, list) else [var_data]
        
        return []
